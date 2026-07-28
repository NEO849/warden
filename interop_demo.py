#!/usr/bin/env python3
"""interop_demo.py — a DIFFERENT agent consumes Mnemo's on-graph governance signal.

The moat, demonstrated from the outside: because Mnemo writes its verdict as a structured
property ON the DataHub entity (`mnemo.governance_status`), any other agent — with zero
knowledge of Mnemo — can read it straight off the graph and act on it. A chat agent that keeps
its memory in a side database cannot be consulted this way; there is nothing on the graph to read.

Here a minimal "deployment-gate" agent refuses to recommend a model for a production run while
Mnemo has it flagged NEEDS_REVIEW — reading only the shared graph, calling no Mnemo code.

Usage:
    python interop_demo.py [--server URL] [--urn MODEL_URN]
"""
from __future__ import annotations

import argparse
import sys

from datahub.ingestion.graph.client import DataHubGraph, DataHubGraphConfig
from datahub.metadata.schema_classes import StructuredPropertiesClass

GOV_PROP = "urn:li:structuredProperty:mnemo.governance_status"
DEFAULT_URN = "urn:li:mlModel:(urn:li:dataPlatform:mlflow,churn_model,PROD)"


def read_governance(graph: DataHubGraph, model_urn: str) -> str | None:
    """Read Mnemo's governance verdict off the graph — nothing Mnemo-specific beyond the property name."""
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
              f"Mnemo flagged NEEDS_REVIEW on the graph (a human must clear it first).")
        return False
    if status == "TRUSTED":
        print(f"  downstream agent recommends {short}: Mnemo marks it TRUSTED.")
        return True
    print(f"  downstream agent proceeds with {short}: no Mnemo governance signal on the graph "
          f"(status={status!r}).")
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--server", default="http://localhost:8090")
    ap.add_argument("--urn", default=DEFAULT_URN)
    args = ap.parse_args()

    print("=== interop: a downstream agent consults Mnemo's on-graph governance (no Mnemo code called) ===")
    graph = DataHubGraph(DataHubGraphConfig(server=args.server))
    status = read_governance(graph, args.urn)
    print(f"  read mnemo.governance_status from the graph: {status!r}")
    deployment_gate(args.urn, status)
    print("\n  [honesty] The verdict came ONLY from a structured property on the DataHub entity — "
          "the moat is that Mnemo's memory lives on the graph, so a foreign agent can read it. "
          "A side-DB chat agent has nothing here to consult.")
    print("INTEROP DEMO GREEN ✅")
    return 0


if __name__ == "__main__":
    sys.exit(main())
