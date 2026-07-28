#!/usr/bin/env python3
"""
agent_memory.py — durable per-asset belief + confidence-gated governance for DataHub agents.

Any agent that revisits the same assets across many runs (an enrichment agent, a lineage watcher,
a data-quality bot) needs somewhere to put what it learned last time: a confidence score, why it
believes that, and whether a human still needs to look at it. This script gives that state a home
ON the DataHub graph, as `agent.*` structured properties, instead of scratch state that resets
every run.

Two pieces work together:

1. Belief persistence (define / write / read) -- the log-odds belief from `belief.py`
   (`Belief.log_odds`, `Belief.mass`, `Belief.provenance`) is stored as structured properties on
   the target entity, so the NEXT run can resume the exact posterior instead of starting from a
   neutral prior every time. `structuredProperties` is a full-replace aspect in DataHub, so every
   write here reads the CURRENT set first and re-includes whatever it isn't touching -- a
   belief-only `write` never clobbers a governance status set by a previous `govern` call, and
   `govern` never clobbers the belief fields.

2. Confidence-gated governance (govern) -- turns the belief's confidence into a real, visible
   graph action instead of a print statement: high confidence -> `agent.status=TRUSTED`; low
   confidence -> `agent.status=NEEDS_REVIEW` plus the `agent-needs-review` tag. This NEVER touches
   the entity's own editable description or any other owner-authored metadata -- only its own
   `agent.*` structured properties and its own tag.

Requires: acryl-datahub (`pip install acryl-datahub`) and a reachable DataHub GMS.

Usage:
    python agent_memory.py define  [--server URL]
    python agent_memory.py write   --urn URN --source SRC --hops N --quality Q
                                    [--contradicts] [--summary TEXT] [--event-id ID] [--server URL]
    python agent_memory.py read    --urn URN [--server URL] [--json]
    python agent_memory.py govern  --urn URN [--server URL] [--json]

Examples:
    # One-time setup: define the agent.* structured properties + the needs-review tag
    python agent_memory.py define

    # Record one piece of evidence (a direct lineage confirmation) for an asset
    python agent_memory.py write --urn 'urn:li:dataset:(urn:li:dataPlatform:hive,orders,PROD)' \\
        --source lineage --hops 0 --quality 0.9 --summary "orders table, lineage confirmed"

    # Record a contradicting piece of evidence (e.g. a detected schema change)
    python agent_memory.py write --urn 'urn:li:dataset:(urn:li:dataPlatform:hive,orders,PROD)' \\
        --source schema --hops 0 --quality 1.0 --contradicts --event-id schema_delta_2026_07_28

    # Read back everything currently on the graph
    python agent_memory.py read --urn 'urn:li:dataset:(urn:li:dataPlatform:hive,orders,PROD)'

    # Confidence-gated governance write (TRUSTED / NEEDS_REVIEW + tag), read the verdict back
    python agent_memory.py govern --urn 'urn:li:dataset:(urn:li:dataPlatform:hive,orders,PROD)'

Server resolution order: --server flag, then DATAHUB_GMS_URL env var, then http://localhost:8090.
Auth token (optional): DATAHUB_GMS_TOKEN env var.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

# Make the sibling belief.py importable regardless of the caller's working directory.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from belief import Belief
from datahub.api.entities.structuredproperties.structuredproperties import (
    StructuredProperties,
)
from datahub.emitter.mcp import MetadataChangeProposalWrapper as MCP
from datahub.ingestion.graph.client import DataHubGraph, DataHubGraphConfig
from datahub.metadata.schema_classes import (
    GlobalTagsClass,
    StructuredPropertiesClass,
    StructuredPropertyValueAssignmentClass,
    TagAssociationClass,
    TagPropertiesClass,
)

AGENT_VERSION = "datahub-agent-memory-skill-0.1"

# The generic `agent.*` structured-property namespace this skill defines and writes to. Rename
# the prefix if your org already has a metadata namespace convention -- nothing else depends on
# the literal string "agent".
PROPS = {
    "agent.summary": "string",
    "agent.confidence": "number",
    "agent.logodds": "number",
    "agent.mass": "number",
    "agent.provenance": "string",  # JSON-encoded list, see Belief.provenance
    "agent.lastEvent": "string",
    "agent.agentVersion": "string",
    "agent.status": "string",  # TRUSTED | NEEDS_REVIEW -- see actuate_governance()
}

# Which entity types may carry these properties. Extend for your own asset types (dataJob,
# dashboard, chart, ...) -- structured property definitions are additive and idempotent to redefine.
ENTITY_TYPES = ["dataset", "mlModel", "mlFeature"]

# The OSS-native "needs a human" signal: a visible, queryable tag, not a print statement nobody
# sees. There is no ActionRequest/Proposal entity in OSS DataHub (that class of object is
# Cloud-only) -- a tag plus this script's own `agent.status` property is the honest OSS equivalent.
NEEDS_REVIEW_TAG_URN = "urn:li:tag:agent-needs-review"


def _property_urn(qualified_name: str) -> str:
    return f"urn:li:structuredProperty:{qualified_name}"


def _connect(server: str | None) -> DataHubGraph:
    server = server or os.getenv("DATAHUB_GMS_URL", "http://localhost:8090")
    token = os.getenv("DATAHUB_GMS_TOKEN") or None
    return DataHubGraph(DataHubGraphConfig(server=server, token=token))


# --- one-time setup: define the agent.* structured properties + the needs-review tag -----------


def define_properties(graph: DataHubGraph) -> None:
    """Idempotent. Structured property definitions are additive -- safe to call on every run."""
    for qualified_name, value_type in PROPS.items():
        sp = StructuredProperties(
            id=qualified_name,
            qualified_name=qualified_name,
            display_name=qualified_name,
            type=value_type,
            cardinality="SINGLE",
            entity_types=ENTITY_TYPES,
        )
        for mcp in sp.generate_mcps():
            graph.emit(mcp)


def define_needs_review_tag(graph: DataHubGraph) -> None:
    """Idempotent, cosmetic-only: gives the tag entity a human-readable name/description in the
    DataHub UI. Not required for the tag ASSOCIATION in actuate_governance() to work."""
    graph.emit(
        MCP(
            entityUrn=NEEDS_REVIEW_TAG_URN,
            aspect=TagPropertiesClass(
                name="Agent: Needs Review",
                description=(
                    "An agent's confidence in this asset's current belief fell below the "
                    "governance threshold after contradicting evidence. A human should review "
                    "before the asset is trusted again."
                ),
            ),
        )
    )


def cmd_define(graph: DataHubGraph, _args: argparse.Namespace) -> dict:
    define_properties(graph)
    define_needs_review_tag(graph)
    return {"defined_properties": list(PROPS), "defined_tag": NEEDS_REVIEW_TAG_URN}


# --- belief persistence: load / write / read back, merge-safe on the sibling fields -------------


def _read_values(graph: DataHubGraph, urn: str) -> dict:
    """Raw qualified-name -> value map of whatever agent.* structured properties currently sit on
    `urn`. `structuredProperties` is a full-replace aspect on DataHub -- read the current set
    before writing any subset of it, or the write silently erases the rest."""
    sp = graph.get_aspect(urn, StructuredPropertiesClass)
    values: dict = {}
    if sp:
        for p in sp.properties:
            qualified_name = p.propertyUrn.split(":")[-1]
            values[qualified_name] = p.values[0] if p.values else None
    return values


def load_belief(graph: DataHubGraph, urn: str) -> tuple[Belief, str | None]:
    """Resume the Belief exactly where a previous run left it, plus its prior summary text."""
    values = _read_values(graph, urn)
    belief = Belief(
        log_odds=float(values.get("agent.logodds") or 0.0),
        mass=float(values.get("agent.mass") or 0.0),
        provenance=json.loads(values["agent.provenance"])
        if values.get("agent.provenance")
        else [],
    )
    return belief, values.get("agent.summary")


def save_belief(
    graph: DataHubGraph, urn: str, summary: str, belief: Belief, event_id: str
) -> None:
    """Persist the belief fields. Merge-safe on `agent.status`: if a prior `govern` call already
    set that field, this belief-only write re-reads and re-includes it instead of erasing it."""
    existing = _read_values(graph, urn)
    props = [
        StructuredPropertyValueAssignmentClass(
            propertyUrn=_property_urn("agent.summary"), values=[summary]
        ),
        StructuredPropertyValueAssignmentClass(
            propertyUrn=_property_urn("agent.confidence"),
            values=[round(belief.confidence, 3)],
        ),
        StructuredPropertyValueAssignmentClass(
            propertyUrn=_property_urn("agent.logodds"),
            values=[round(belief.log_odds, 4)],
        ),
        StructuredPropertyValueAssignmentClass(
            propertyUrn=_property_urn("agent.mass"), values=[round(belief.mass, 4)]
        ),
        StructuredPropertyValueAssignmentClass(
            propertyUrn=_property_urn("agent.provenance"),
            values=[json.dumps(belief.provenance)],
        ),
        StructuredPropertyValueAssignmentClass(
            propertyUrn=_property_urn("agent.lastEvent"), values=[event_id]
        ),
        StructuredPropertyValueAssignmentClass(
            propertyUrn=_property_urn("agent.agentVersion"), values=[AGENT_VERSION]
        ),
    ]
    if existing.get("agent.status") is not None:
        props.append(
            StructuredPropertyValueAssignmentClass(
                propertyUrn=_property_urn("agent.status"),
                values=[existing["agent.status"]],
            )
        )
    graph.emit(MCP(entityUrn=urn, aspect=StructuredPropertiesClass(properties=props)))


def cmd_write(graph: DataHubGraph, args: argparse.Namespace) -> dict:
    belief, prior_summary = load_belief(graph, args.urn)
    weight = belief.update(
        source=args.source,
        corroborates=not args.contradicts,
        hops=args.hops,
        quality=args.quality,
        event_id=args.event_id,
    )
    summary = (
        args.summary if args.summary is not None else (prior_summary or "observed")
    )
    save_belief(graph, args.urn, summary, belief, args.event_id)
    return {
        "urn": args.urn,
        "applied_weight": round(weight, 3),
        "confidence": round(belief.confidence, 3),
        "mass": round(belief.mass, 4),
        "summary": summary,
    }


def cmd_read(graph: DataHubGraph, args: argparse.Namespace) -> dict:
    values = _read_values(graph, args.urn)
    return {
        "urn": args.urn,
        "properties": {k: v for k, v in values.items() if k in PROPS},
    }


# --- governance: confidence-gated verdict + its actuation on the graph --------------------------


def govern_verdict(belief: Belief) -> str:
    """Single source of truth for the governance verdict, from the belief alone."""
    if belief.actionable_high:
        return "auto-write"
    if belief.needs_proposal():
        return "open-proposal"
    return "needs-review"


def set_status(graph: DataHubGraph, urn: str, status: str) -> None:
    """Merge-safe write of ONLY agent.status -- preserves whatever belief fields (summary,
    confidence, logodds, mass, provenance, lastEvent, agentVersion) already sit on `urn`."""
    values = _read_values(graph, urn)
    values["agent.status"] = status
    props = [
        StructuredPropertyValueAssignmentClass(
            propertyUrn=_property_urn(qn), values=[v]
        )
        for qn, v in values.items()
        if v is not None and qn in PROPS
    ]
    graph.emit(MCP(entityUrn=urn, aspect=StructuredPropertiesClass(properties=props)))


def actuate_governance(graph: DataHubGraph, urn: str, belief: Belief) -> dict:
    """Confidence-gated, OSS-native governance signal -- replaces a print statement with a real
    write the DataHub UI shows immediately.

    Verdict -> action (govern_verdict() is the single source of truth for the verdict itself):
      open-proposal (confidence < TAU_PROPOSAL, belief.needs_proposal()):
          agent.status=NEEDS_REVIEW, tag ADDED if not already present.
      needs-review (mid-band, neither threshold hit):
          agent.status=NEEDS_REVIEW, tag left as-is -- not contradicted enough to demand review,
          just not confident enough to auto-write.
      auto-write (belief.actionable_high):
          agent.status=TRUSTED, tag REMOVED if present.

    HARD INVARIANT: this function never writes the entity's own description or any other
    editable/owner-authored metadata. It only ever writes this skill's own `agent.*` structured
    properties and its own tag.
    """
    verdict = govern_verdict(belief)
    status = "TRUSTED" if verdict == "auto-write" else "NEEDS_REVIEW"
    want_tag = verdict == "open-proposal"

    set_status(graph, urn, status)

    current = graph.get_aspect(urn, GlobalTagsClass)
    tags = list(current.tags) if current and current.tags else []
    has_tag = any(t.tag == NEEDS_REVIEW_TAG_URN for t in tags)

    if want_tag and not has_tag:
        define_needs_review_tag(
            graph
        )  # idempotent: label the tag entity before referencing it
        tags.append(TagAssociationClass(tag=NEEDS_REVIEW_TAG_URN))
        graph.emit(MCP(entityUrn=urn, aspect=GlobalTagsClass(tags=tags)))
        tag_action = "added"
    elif not want_tag and has_tag:
        tags = [t for t in tags if t.tag != NEEDS_REVIEW_TAG_URN]
        graph.emit(MCP(entityUrn=urn, aspect=GlobalTagsClass(tags=tags)))
        tag_action = "removed"
    else:
        tag_action = "unchanged"

    return {
        "verdict": verdict,
        "agent_status": status,
        "tag": NEEDS_REVIEW_TAG_URN if (want_tag or has_tag) else None,
        "tag_action": tag_action,
    }


def cmd_govern(graph: DataHubGraph, args: argparse.Namespace) -> dict:
    belief, _ = load_belief(graph, args.urn)
    result = actuate_governance(graph, args.urn, belief)
    result["urn"] = args.urn
    result["confidence"] = round(belief.confidence, 3)
    result["mass"] = round(belief.mass, 4)
    return result


# --- CLI -----------------------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    # Shared flags, available both before AND after the subcommand (argparse does not otherwise
    # propagate a parent parser's optionals past a positional subcommand token).
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--server", help="DataHub GMS URL (default: $DATAHUB_GMS_URL or localhost:8090)"
    )
    common.add_argument("--json", action="store_true", help="Print the result as JSON")

    parser = argparse.ArgumentParser(
        description="Durable per-asset belief + confidence-gated governance for DataHub agents.",
        parents=[common],
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser(
        "define",
        parents=[common],
        help="Define the agent.* structured properties + needs-review tag",
    )

    write_parser = sub.add_parser(
        "write",
        parents=[common],
        help="Fold one piece of evidence into an asset's belief",
    )
    write_parser.add_argument("--urn", required=True, help="Target entity URN")
    write_parser.add_argument(
        "--source",
        required=True,
        help="Evidence source, e.g. lineage/schema/usage/human",
    )
    write_parser.add_argument(
        "--hops", type=int, required=True, help="Provenance distance (0 = direct)"
    )
    write_parser.add_argument(
        "--quality", type=float, required=True, help="Evidence quality, 0..1"
    )
    write_parser.add_argument(
        "--contradicts",
        action="store_true",
        help="Evidence contradicts (default: corroborates) the belief",
    )
    write_parser.add_argument(
        "--summary", help="Updated summary text (default: keep the prior one)"
    )
    write_parser.add_argument(
        "--event-id",
        default="write",
        help="Identifier recorded in the provenance trail",
    )

    read_parser = sub.add_parser(
        "read",
        parents=[common],
        help="Read back the agent.* properties currently on an asset",
    )
    read_parser.add_argument("--urn", required=True, help="Target entity URN")

    govern_parser = sub.add_parser(
        "govern",
        parents=[common],
        help="Confidence-gated governance write (status + tag)",
    )
    govern_parser.add_argument("--urn", required=True, help="Target entity URN")

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    graph = _connect(args.server)
    dispatch = {
        "define": cmd_define,
        "write": cmd_write,
        "read": cmd_read,
        "govern": cmd_govern,
    }
    result = dispatch[args.command](graph, args)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        for key, value in result.items():
            print(f"{key}: {value}")


if __name__ == "__main__":
    main()
