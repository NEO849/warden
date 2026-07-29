"""console/app.py — Mnemo Trust Console: a read-only window onto the live DataHub graph.

WHAT THIS IS: the perception lever. It reads ONLY the mnemo.* structured properties and the
mnemo-needs-review GlobalTag that MnemoAgent (mnemo/agent.py, a different block — not touched or
imported here) already writes to a live DataHub GMS, and renders them as a "trust console" — the
5-second proof that a compounding-memory governance agent is running against real graph data right
now, not a slideshow.

WHAT THIS IS NOT: it is not part of the agent. It never computes a belief, never emits an MCP
(MetadataChangeProposal), never calls anything that writes to GMS. It is a pure read + render tier
bolted on top of a system that was already live before this file existed.

SECURITY (non-negotiable, do not soften):
  - This module never binds a socket itself in-process except via the __main__ convenience runner
    below, which is hardcoded to host="127.0.0.1" — not read from any environment variable, so
    there is no way to override it into 0.0.0.0 by accident. The documented/recommended way to run
    this (see console/README.md) is `uvicorn console.app:app --host 127.0.0.1 --port 8808`, i.e.
    the operator types 127.0.0.1 explicitly too.
  - Every route in this file is a GET. There is no POST/PUT/PATCH/DELETE anywhere below, and no
    code path ever imports MetadataChangeProposalWrapper or calls `graph.emit(...)`. The only SDK
    surface used is the read side: DataHubGraph.get_aspect / get_urns_by_filter, plus a read-only
    GMS OpenAPI v3 GET (for the aspect's audit timestamp — see get_audit_time_ms below).
  - DATAHUB_GMS_TOKEN (if set) is used ONLY as an outbound Authorization header from this server
    process to GMS; it is never included in, derived into, or logged alongside any HTTP response
    this app sends to a browser. ANTHROPIC_API_KEY is not read by this module at all.
  - GMS (:8090) and the DataHub UI (:9002) are never proxied, iframed, or re-exposed by any route
    here — the console only ever returns the small, already-public mnemo.* fields as JSON/HTML.
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from urllib.parse import quote

import requests
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from datahub.ingestion.graph.client import DataHubGraph, DataHubGraphConfig
from datahub.metadata.schema_classes import (
    GlobalTagsClass,
    MLFeaturePropertiesClass,
    MLModelPropertiesClass,
    StructuredPropertiesClass,
)

# --- config (env-driven, per the brief; no host override lever exists — see module docstring) ---
GMS_URL = os.getenv("DATAHUB_GMS_URL", "http://localhost:8090")
GMS_TOKEN = os.getenv("DATAHUB_GMS_TOKEN") or None
CONSOLE_PORT = int(os.getenv("MNEMO_CONSOLE_PORT", "8808"))
HEARTBEAT_AWAKE_WINDOW_S = int(os.getenv("MNEMO_HEARTBEAT_AWAKE_WINDOW_S", "3600"))

STATIC_DIR = Path(__file__).parent / "static"
REPO_ROOT = Path(__file__).parent.parent
WAKE_LOG_PATH = REPO_ROOT / "actions" / "verify_run_SUCCESS.log"

# The needs-review human-gate tag mnemo/agent.py actually writes (mnemo/agent.py::
# NEEDS_REVIEW_TAG_URN). Duplicated here as a plain string constant (not imported) so this
# console has zero import-time coupling to the mnemo/* package — it never needs mnemo/agent.py
# to be import-safe or side-effect-free for the console to start.
NEEDS_REVIEW_TAG_URN = "urn:li:tag:mnemo-needs-review"

# Governance-verdict thresholds, mirrored (read-only, for DISPLAY classification only) from
# confidence_model.py's Belief: TAU_PROPOSAL / N_MIN / the 0.85 auto-write cut. The authoritative
# governance decision is whatever MnemoAgent.actuate_governance() already wrote into
# mnemo.governance_status — this function only exists to show the finer-grained 3-way verdict
# (auto-write / open-proposal / needs-review) the UI wants, from the same public numbers.
TAU_PROPOSAL = 0.70
ACTIONABLE_HIGH_CONF = 0.85
ACTIONABLE_HIGH_MASS = 3.0

_session = requests.Session()
if GMS_TOKEN:
    _session.headers.update({"Authorization": f"Bearer {GMS_TOKEN}"})

app = FastAPI(title="Mnemo Trust Console", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def _graph() -> DataHubGraph:
    # Fresh client per process (module-level singleton, lazy) — mirrors mnemo/mcp_server.py's
    # _get_agent() lazy-singleton pattern so `import console.app` never requires a live GMS.
    global _graph_singleton
    try:
        return _graph_singleton
    except NameError:
        _graph_singleton = DataHubGraph(DataHubGraphConfig(server=GMS_URL, token=GMS_TOKEN))
        return _graph_singleton


def _entity_type_segment(urn: str) -> str:
    """'urn:li:mlModel:(...)' -> 'mlmodel' — the lowercase path segment the GMS OpenAPI v3
    entity API expects. split(':', 3) is deliberate: URNs nest further colons inside the
    parenthesized key (e.g. urn:li:dataPlatform:mlflow), so a plain split(':') would grab the
    wrong token; limiting to 3 splits stops right after the entity-type field."""
    parts = urn.split(":", 3)
    return parts[2].lower() if len(parts) > 2 else ""


def get_audit_time_ms(urn: str) -> int | None:
    """Best-effort: the epoch-ms audit timestamp of this entity's LAST structuredProperties write
    — i.e. the last time Mnemo touched this asset ("last wake" for that specific model/dataset).
    Read-only GET against GMS's OpenAPI v3 entity API (`?systemMetadata=true`), which is the only
    place the acryl-datahub SDK's typed get_aspect() does not surface an audit stamp. Returns None
    on any failure (entity never observed, GMS hiccup, etc.) — callers must handle None."""
    seg = _entity_type_segment(urn)
    if not seg:
        return None
    url = f"{GMS_URL}/openapi/v3/entity/{seg}/{quote(urn, safe='')}/structuredproperties"
    try:
        r = _session.get(url, params={"systemMetadata": "true"}, timeout=5)
        if r.status_code != 200:
            return None
        data = r.json()
        return (data.get("auditStamp") or {}).get("time")
    except Exception:
        return None


def _read_structured_props(g: DataHubGraph, urn: str) -> dict:
    """qualified-name -> value map of whatever mnemo.* structured properties sit on `urn` right
    now. Same shape as mnemo/memory.py::MnemoMemory._read_values, reimplemented independently here
    (not imported) so the console has no load-bearing dependency on that other block's file."""
    sp = g.get_aspect(urn, StructuredPropertiesClass)
    vals: dict = {}
    if sp:
        for p in sp.properties:
            qn = p.propertyUrn.split(":")[-1]
            vals[qn] = p.values[0] if p.values else None
    return vals


def _model_input_sources_now(g: DataHubGraph, model_urn: str) -> list[str]:
    """Live current input sources for an mlModel, read straight off the graph — independently
    reimplements mnemo/agent.py::MnemoAgent.model_input_sources's read-only query (mlModel ->
    mlFeatures -> each feature's `sources`) so this console never imports mnemo/agent.py. Used to
    compute "current" for the remembered-vs-current drift comparison in /api/model/{urn}."""
    mp = g.get_aspect(model_urn, MLModelPropertiesClass)
    srcs: list[str] = []
    for feat in (mp.mlFeatures if mp and mp.mlFeatures else []):
        fp = g.get_aspect(feat, MLFeaturePropertiesClass)
        srcs += (fp.sources if fp and fp.sources else [])
    return sorted(set(srcs))


def _model_lineage_now(g: DataHubGraph, model_urn: str) -> list[dict]:
    """Live model->feature->sources path, read straight off the graph. Reuses the exact same
    read-only traversal as _model_input_sources_now (mlModel -> mlFeatures -> feature.sources)
    but keeps the per-feature grouping instead of flattening to a single source set, so the
    console can draw the reverse-lineage spine (source dataset -> feature -> model)."""
    mp = g.get_aspect(model_urn, MLModelPropertiesClass)
    lineage: list[dict] = []
    for feat in (mp.mlFeatures if mp and mp.mlFeatures else []):
        fp = g.get_aspect(feat, MLFeaturePropertiesClass)
        srcs = sorted(set(fp.sources)) if fp and fp.sources else []
        lineage.append({"feature": feat, "sources": srcs})
    return lineage


def compute_verdict(confidence: float | None, mass: float | None) -> str | None:
    """Display-only recompute of MnemoAgent.govern()'s 3-way verdict from the two public numbers
    (mnemo.confidence, mnemo.mass) already on the graph. Order matters and mirrors govern()
    exactly: auto-write is checked first (both the confidence AND mass gate must hold), then the
    proposal threshold, else the mid-band."""
    if confidence is None:
        return None
    m = mass or 0.0
    if confidence > ACTIONABLE_HIGH_CONF and m >= ACTIONABLE_HIGH_MASS:
        return "auto-write"
    if confidence < TAU_PROPOSAL:
        return "open-proposal"
    return "needs-review"


def _parse_json_field(raw) -> object:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


def _model_summary(g: DataHubGraph, urn: str) -> dict | None:
    """Lightweight per-model row for GET /api/models. Returns None if this entity has never been
    observed by Mnemo (no mnemo.confidence set yet) so untouched demo entities don't clutter the
    console."""
    vals = _read_structured_props(g, urn)
    confidence = vals.get("mnemo.confidence")
    if confidence is None:
        return None
    mass = vals.get("mnemo.mass")
    audit_ms = get_audit_time_ms(urn)
    return {
        "urn": urn,
        "model_name": urn.split(",")[-2] if "," in urn else urn,
        "confidence": confidence,
        "verdict": compute_verdict(confidence, mass),
        "governance_status": vals.get("mnemo.governance_status"),
        "last_wake_ts": audit_ms,
        "last_wake_seconds_ago": (int(time.time() - audit_ms / 1000) if audit_ms else None),
    }


@app.get("/api/models")
def api_models():
    """List of every mlModel entity Mnemo has ever observed (mnemo.confidence set), newest write
    first. Read-only: get_urns_by_filter + get_aspect(StructuredPropertiesClass), no writes."""
    g = _graph()
    try:
        urns = list(g.get_urns_by_filter(entity_types=["mlModel"]))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"GMS unreachable: {type(e).__name__}") from e

    rows = [row for u in urns if (row := _model_summary(g, u)) is not None]
    rows.sort(key=lambda r: r["last_wake_ts"] or 0, reverse=True)
    return {"models": rows, "watching_count": len(rows)}


@app.get("/api/model/{urn:path}")
def api_model(urn: str):
    """Full read-only snapshot for one URN: confidence, verdict, remembered-vs-current input
    sources (the drift signal itself), governance_status, the full provenance chain (Belief's
    evidence log — what the confidence timeseries panel plots), and the last-wake timestamp."""
    g = _graph()
    vals = _read_structured_props(g, urn)
    if not vals:
        raise HTTPException(status_code=404, detail="No mnemo.* properties on this URN yet")

    confidence = vals.get("mnemo.confidence")
    mass = vals.get("mnemo.mass")
    summary = _parse_json_field(vals.get("mnemo.summary")) or {}
    remembered_sources = summary.get("input_sources", []) if isinstance(summary, dict) else []
    provenance = _parse_json_field(vals.get("mnemo.provenance")) or []

    current_sources: list[str] = []
    lineage: list[dict] = []
    if _entity_type_segment(urn) == "mlmodel":
        try:
            current_sources = _model_input_sources_now(g, urn)
        except Exception:
            current_sources = []
        try:
            lineage = _model_lineage_now(g, urn)
        except Exception:
            lineage = []

    tags_aspect = g.get_aspect(urn, GlobalTagsClass)
    tag_list = [t.tag for t in tags_aspect.tags] if tags_aspect and tags_aspect.tags else []

    audit_ms = get_audit_time_ms(urn)

    return {
        "urn": urn,
        "confidence": confidence,
        "mass": mass,
        "verdict": compute_verdict(confidence, mass),
        "governance_status": vals.get("mnemo.governance_status"),
        "needs_review_tag": NEEDS_REVIEW_TAG_URN in tag_list,
        "tags": tag_list,
        "last_event": vals.get("mnemo.lastEvent"),
        "agent_version": vals.get("mnemo.agentVersion"),
        "summary": summary,
        "remembered_sources": remembered_sources,
        "current_sources": current_sources,
        "sources_drifted": bool(current_sources) and set(current_sources) != set(remembered_sources),
        "provenance": provenance,
        "lineage": lineage,
        "last_wake_ts": audit_ms,
        "last_wake_seconds_ago": (int(time.time() - audit_ms / 1000) if audit_ms else None),
    }


_WAKE_LOG_TS_RE = re.compile(r"^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+\]")


def _tail_wake_log_seconds_ago() -> int | None:
    """Fallback heartbeat source when no model carries a live audit timestamp yet: read-only tail
    of actions/verify_run_SUCCESS.log for the last log4j-style timestamp. Never writes to the log,
    never used if the live-graph path (audit timestamps on watched models) already has an answer."""
    try:
        text = WAKE_LOG_PATH.read_text(errors="ignore")
    except OSError:
        return None
    last_ts = None
    for line in text.splitlines():
        m = _WAKE_LOG_TS_RE.match(line)
        if m:
            last_ts = m.group(1)
    if not last_ts:
        return None
    try:
        parsed = time.strptime(last_ts, "%Y-%m-%d %H:%M:%S")
        epoch = time.mktime(parsed)
        return max(0, int(time.time() - epoch))
    except ValueError:
        return None


@app.get("/api/heartbeat")
def api_heartbeat():
    """{awake, last_event_seconds_ago, watching_count} — the 5-second-wow ticker's data source.
    Primary signal: the freshest audit timestamp across every mlModel Mnemo currently watches
    (a genuinely live number — it moves the instant MnemoAgent writes again). Fallback: tail the
    wake-consumer's own log for its last logged event, per the brief, used only if no watched
    model has an audit timestamp at all (e.g. a completely fresh GMS)."""
    g = _graph()
    try:
        urns = list(g.get_urns_by_filter(entity_types=["mlModel"]))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"GMS unreachable: {type(e).__name__}") from e

    rows = [row for u in urns if (row := _model_summary(g, u)) is not None]
    watching_count = len(rows)

    ages = [r["last_wake_seconds_ago"] for r in rows if r["last_wake_seconds_ago"] is not None]
    if ages:
        last_event_seconds_ago = min(ages)
        source = "graph-audit-timestamp"
    else:
        last_event_seconds_ago = _tail_wake_log_seconds_ago()
        source = "wake-log-tail"

    awake = last_event_seconds_ago is not None and last_event_seconds_ago < HEARTBEAT_AWAKE_WINDOW_S

    return {
        "awake": awake,
        "last_event_seconds_ago": last_event_seconds_ago,
        "watching_count": watching_count,
        "source": source,
    }


@app.get("/", response_class=HTMLResponse)
def index():
    return (STATIC_DIR / "index.html").read_text()


if __name__ == "__main__":
    import uvicorn

    # Hardcoded 127.0.0.1 — see module docstring: this is not an env-configurable lever.
    uvicorn.run(app, host="127.0.0.1", port=CONSOLE_PORT)
