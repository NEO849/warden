#!/usr/bin/env python3
"""
mnemo/mcp_server.py — exposes Mnemo itself as an MCP tool (FastMCP, `mcp` Python SDK).

Satisfies the hackathon's "must use DataHub-OSS + >=1 of {DataHub MCP Server, Agent Context
Kit, DataHub Skills, Analytics Agent}" requirement via the DataHub-MCP-Server angle: Mnemo
becomes an MCP tool that any MCP client (Claude Desktop, an orchestrating agent, another MCP
host) can call to get a drift verdict for an ML model — grounded in DataHub's live lineage
graph plus Mnemo's own persisted belief memory (mnemo.* structured properties on the entity).

One tool: assess_model_drift(model_urn) -> {verdict, confidence, evidence, memory_recall}
Thin wrapper — no new logic here, just adapting MnemoAgent to the MCP tool-call contract.
The SDK-backed default read/write path (mnemo/agent.py, mnemo/reader.py, mnemo/memory.py) is
completely unchanged by this file.

Run standalone (stdio transport):        python mnemo/mcp_server.py
Inspect/dev with the MCP Inspector:      mcp dev mnemo/mcp_server.py
Call it from a stdio client:             see test_mcp_client.py (project root)
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from datahub.ingestion.graph.client import DataHubGraph, DataHubGraphConfig

from mnemo.agent import MnemoAgent

load_dotenv()

mcp = FastMCP("mnemo")

_graph = None
_agent = None


def _get_agent() -> MnemoAgent:
    """Lazy singleton — one DataHubGraph connection per server process, built on first tool call
    (not at import time), so `mcp dev`/module import never requires a live GMS to succeed."""
    global _graph, _agent
    if _agent is None:
        _graph = DataHubGraph(DataHubGraphConfig(
            server=os.getenv("DATAHUB_GMS_URL", "http://localhost:8090"),
            token=os.getenv("DATAHUB_GMS_TOKEN") or None,
        ))
        _agent = MnemoAgent(_graph)
    return _agent


@mcp.tool()
def assess_model_drift(model_urn: str) -> dict:
    """Assess whether an ML model's input sources have silently drifted since Mnemo last
    remembered them, using DataHub's live lineage graph plus Mnemo's persisted belief memory.

    Catches a class of change a plain schema-diff cannot see: a feature silently re-pointed to a
    new upstream source table under an UNCHANGED name/description (e.g. fct_users_created ->
    fct_users_created_v2). Mnemo remembers the prior source-set as a structured property on the
    entity; a delta is folded in as contradicting Bayesian evidence, dropping confidence and
    (below threshold) routing to a DataHub Proposal instead of silent auto-trust.

    Args:
        model_urn: DataHub URN of the mlModel entity, e.g.
            "urn:li:mlModel:(urn:li:dataPlatform:mlflow,churn_model,PROD)"

    Returns:
        dict with keys:
          verdict: "auto-write" | "open-proposal" | "needs-review" (MnemoAgent.govern(belief))
          confidence: float in [0.02, 0.98] — Belief.confidence, the Bayesian posterior
          evidence: {
            "changed": bool, "remembered_sources": [...], "current_sources": [...],
            "provenance": [...] (Belief's evidence log), "measured_drift": {...} | None (PSI, if
            DataHub holds field-histogram profiles for both old/new source — see mnemo/drift.py),
            "reflection": {...} | None (best-effort lineage-wide insight via MnemoAgent.reflect;
            None if too few upstream memories exist or nothing new survived its guards)
          }
          memory_recall: {"prior_summary": {...} | None} — what MnemoMemory.load() held for this
            URN's mnemo.summary BEFORE this call's own re-score (genuine prior recall, not the
            post-check state)
    """
    agent = _get_agent()

    # Snapshot the PRIOR recall before check_model_inputs() re-scores/persists — .load() is
    # read-only, so this doesn't disturb anything; it just lets us report what was actually
    # remembered walking in, distinct from the post-check state below.
    _, prior_summary_json = agent.memory.load(model_urn)
    try:
        prior_summary = json.loads(prior_summary_json) if prior_summary_json else None
    except (json.JSONDecodeError, TypeError):
        prior_summary = prior_summary_json

    changed, remembered, now, belief, drift_info = agent.check_model_inputs(model_urn)
    verdict = MnemoAgent.govern(belief)

    reflection = None
    try:
        rec = agent.reflect(model_urn, event="mcp_assess_model_drift")
        if rec and not rec.get("skipped"):
            reflection = rec
    except Exception as e:  # reflect is best-effort here — never break the drift verdict on it
        reflection = {"error": f"{type(e).__name__}: {str(e)[:120]}"}

    return {
        "verdict": verdict,
        "confidence": round(belief.confidence, 3),
        "evidence": {
            "changed": changed,
            "remembered_sources": remembered,
            "current_sources": now,
            "provenance": belief.provenance,
            "measured_drift": drift_info,
            "reflection": reflection,
        },
        "memory_recall": {
            "prior_summary": prior_summary,
        },
    }


if __name__ == "__main__":
    mcp.run()
