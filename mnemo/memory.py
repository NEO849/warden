"""Memory layer — persist a compounding belief ON the graph as structured properties.

The Belief's log-odds + mass are stored too, so the NEXT event can resume the exact posterior and
re-score it. That resumable belief-state is what makes the memory compound instead of reset.
"""
import json

from datahub.api.entities.structuredproperties.structuredproperties import StructuredProperties
from datahub.emitter.mcp import MetadataChangeProposalWrapper as MCP
from datahub.metadata.schema_classes import (
    StructuredPropertiesClass,
    StructuredPropertyValueAssignmentClass,
)

from confidence_model import Belief

AGENT_VERSION = "mnemo-0.1"
PROPS = {
    "mnemo.summary": "string", "mnemo.confidence": "number", "mnemo.logodds": "number",
    "mnemo.mass": "number", "mnemo.provenance": "string", "mnemo.lastEvent": "string",
    "mnemo.agentVersion": "string",
}


def _u(qn: str) -> str:
    return f"urn:li:structuredProperty:{qn}"


class MnemoMemory:
    def __init__(self, graph):
        self.g = graph

    def define_properties(self) -> None:
        for qn, typ in PROPS.items():
            sp = StructuredProperties(id=qn, qualified_name=qn, display_name=qn,
                                     type=typ, cardinality="SINGLE", entity_types=["dataset", "mlModel", "mlFeature"])
            for mcp in sp.generate_mcps():
                self.g.emit(mcp)

    def load(self, urn: str):
        """Return (Belief resumed from the graph, prior summary or None)."""
        sp = self.g.get_aspect(urn, StructuredPropertiesClass)
        vals = {}
        if sp:
            for p in sp.properties:
                qn = p.propertyUrn.split(":")[-1]
                vals[qn] = p.values[0] if p.values else None
        belief = Belief(
            log_odds=float(vals.get("mnemo.logodds") or 0.0),
            mass=float(vals.get("mnemo.mass") or 0.0),
            provenance=json.loads(vals["mnemo.provenance"]) if vals.get("mnemo.provenance") else [],
        )
        return belief, vals.get("mnemo.summary")

    def save(self, urn: str, summary: str, belief: Belief, last_event: str) -> None:
        aspect = StructuredPropertiesClass(properties=[
            StructuredPropertyValueAssignmentClass(propertyUrn=_u("mnemo.summary"), values=[summary]),
            StructuredPropertyValueAssignmentClass(propertyUrn=_u("mnemo.confidence"), values=[round(belief.confidence, 3)]),
            StructuredPropertyValueAssignmentClass(propertyUrn=_u("mnemo.logodds"), values=[round(belief.log_odds, 4)]),
            StructuredPropertyValueAssignmentClass(propertyUrn=_u("mnemo.mass"), values=[round(belief.mass, 4)]),
            StructuredPropertyValueAssignmentClass(propertyUrn=_u("mnemo.provenance"), values=[json.dumps(belief.provenance)]),
            StructuredPropertyValueAssignmentClass(propertyUrn=_u("mnemo.lastEvent"), values=[last_event]),
            StructuredPropertyValueAssignmentClass(propertyUrn=_u("mnemo.agentVersion"), values=[AGENT_VERSION]),
        ])
        self.g.emit(MCP(entityUrn=urn, aspect=aspect))
