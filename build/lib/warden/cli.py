#!/usr/bin/env python3
"""
warden/cli.py — `warden` console-script entry point.

Thin argparse wrapper around the already-existing agent/provisioning code — no new core logic.
Connects to GMS the same way every other entrypoint in this repo does (run_agent.py,
warden/mcp_server.py): DataHubGraph(DataHubGraphConfig(server=DATAHUB_GMS_URL, token=
DATAHUB_GMS_TOKEN)), DATAHUB_GMS_URL defaulting to http://localhost:8090.

Subcommands:
  warden provision [--force]      idempotently define the warden.* structured properties on GMS
                                  (warden/provision.py) — makes the agent reproducible against a
                                  fresh DataHub instance instead of relying on properties this
                                  VPS's GMS already happens to have registered.
  warden assess <model_urn>       run WardenAgent.check_model_inputs(model_urn) + govern() and
                                  print the drift verdict as JSON — the same read/detect/govern
                                  logic warden/mcp_server.py's assess_model_drift tool exposes over
                                  MCP, here exposed as a plain CLI call for scripting/CI/demo use.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv

from datahub.ingestion.graph.client import DataHubGraph, DataHubGraphConfig

from warden.agent import WardenAgent
from warden.provision import provision as provision_properties


def _make_graph() -> DataHubGraph:
    return DataHubGraph(DataHubGraphConfig(
        server=os.getenv("DATAHUB_GMS_URL", "http://localhost:8090"),
        token=os.getenv("DATAHUB_GMS_TOKEN") or None,
    ))


def _cmd_provision(args: argparse.Namespace) -> int:
    graph = _make_graph()
    result = provision_properties(graph, force=args.force)
    print(json.dumps(result, indent=2))
    print(f"\n{len(result['created'])} created, {len(result['skipped'])} already defined (skipped) "
          f"of {len(result['qualified_names'])} warden.* structured properties.", file=sys.stderr)
    return 0


def _cmd_assess(args: argparse.Namespace) -> int:
    graph = _make_graph()
    agent = WardenAgent(graph)
    changed, remembered, now, belief, drift_info = agent.check_model_inputs(args.model_urn)
    verdict = WardenAgent.govern(belief)
    print(json.dumps({
        "model_urn": args.model_urn,
        "verdict": verdict,
        "confidence": round(belief.confidence, 3),
        "changed": changed,
        "remembered_sources": remembered,
        "current_sources": now,
        "measured_drift": drift_info,
        "provenance": belief.provenance,
    }, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="warden",
        description="Warden — compounding-memory governance agent for DataHub. "
                    "Connects via DATAHUB_GMS_URL (default http://localhost:8090).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_provision = sub.add_parser(
        "provision",
        help="idempotently define the warden.* structured properties on GMS",
    )
    p_provision.add_argument(
        "--force", action="store_true",
        help="re-emit definitions even if they already exist (default: skip existing)",
    )
    p_provision.set_defaults(func=_cmd_provision)

    p_assess = sub.add_parser(
        "assess",
        help="check an mlModel's inputs for drift and print the governance verdict",
    )
    p_assess.add_argument(
        "model_urn",
        help="DataHub mlModel URN, e.g. "
             "'urn:li:mlModel:(urn:li:dataPlatform:mlflow,churn_model,PROD)'",
    )
    p_assess.set_defaults(func=_cmd_assess)

    return parser


def main(argv=None) -> int:
    load_dotenv()
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
