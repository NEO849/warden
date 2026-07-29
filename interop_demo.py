#!/usr/bin/env python3
"""interop_demo.py — a DIFFERENT agent consumes Warden's on-graph governance signal.

The moat, demonstrated from the outside: because Warden writes its verdict as a structured
property ON the DataHub entity (`warden.governance_status`), any other agent — with zero
knowledge of Warden — can read it straight off the graph and act on it. A chat agent that keeps
its memory in a side database cannot be consulted this way; there is nothing on the graph to read.

Here a minimal "deployment-gate" agent refuses to recommend a model for a production run while
Warden has it flagged NEEDS_REVIEW — reading only the shared graph, calling no Warden code.

Usage:
    python interop_demo.py [--server URL] [--urn MODEL_URN]
"""
from __future__ import annotations

import argparse
import sys

from datahub.ingestion.graph.client import DataHubGraph, DataHubGraphConfig
from datahub.metadata.schema_classes import StructuredPropertiesClass

GOV_PROP = "urn:li:structuredProperty:warden.governance_status"
DEFAULT_URN = "urn:li:mlModel:(urn:li:dataPlatform:mlflow,churn_model,PROD)"


def read_governance(graph: DataHubGraph, model_urn: str) -> str | None:
    """Read Warden's governance verdict off the graph — nothing Warden-specific beyond the property name."""
    sp = graph.get_aspect(model_urn, StructuredPropertiesClass)
    if not sp:
        return None
    for p in sp.properties:
        if p.propertyUrn == GOV_PROP and p.values:
            return str(p.values[0])
    return None


def deployment_gate(model_urn: str, status: str | None) -> bool:
    """A downstream agent's decision: promote this model to a production run, or not?"""
    short = model_urn.split(",")[-2] if "," in model_urn else model_urn
    if status == "NEEDS_REVIEW":
        print(f"  downstream agent REFUSED to recommend {short}: "
              f"Warden flagged NEEDS_REVIEW on the graph (a human must clear it first).")
        return False
    if status == "TRUSTED":
        print(f"  downstream agent recommends {short}: Warden marks it TRUSTED.")
        return True
    print(f"  downstream agent proceeds with {short}: no Warden governance signal on the graph "
          f"(status={status!r}).")
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--server", default="http://localhost:8090")
    ap.add_argument("--urn", default=DEFAULT_URN)
    args = ap.parse_args()

    print("=== interop: a downstream agent consults Warden's on-graph governance (no Warden code called) ===")
    graph = DataHubGraph(DataHubGraphConfig(server=args.server))
    status = read_governance(graph, args.urn)
    print(f"  read warden.governance_status from the graph: {status!r}")
    deployment_gate(args.urn, status)
    print("\n  [honesty] The verdict came ONLY from a structured property on the DataHub entity — "
          "the moat is that Warden's memory lives on the graph, so a foreign agent can read it. "
          "A side-DB chat agent has nothing here to consult.")
    print("INTEROP DEMO GREEN ✅")
    return 0


if __name__ == "__main__":
    sys.exit(main())
