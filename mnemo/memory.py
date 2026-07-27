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
    # governance actuation (mnemo/agent.py::actuate_governance) — the real, OSS-native "human gate"
    # signal: NEEDS_REVIEW | TRUSTED. Same define/emit pattern as the belief fields above.
    "mnemo.governance_status": "string",
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

    def _read_values(self, urn: str) -> dict:
        """Raw qualified-name -> value map of whatever mnemo.* structured properties currently sit
        on `urn`. Shared by load() and every merge-safe writer below, since structuredProperties is
        a full-replace aspect on DataHub — you must read the current set before writing any subset
        of it, or you silently erase the rest."""
        sp = self.g.get_aspect(urn, StructuredPropertiesClass)
        vals = {}
        if sp:
            for p in sp.properties:
                qn = p.propertyUrn.split(":")[-1]
                vals[qn] = p.values[0] if p.values else None
        return vals

    def load(self, urn: str):
        """Return (Belief resumed from the graph, prior summary or None)."""
        vals = self._read_values(urn)
        belief = Belief(
            log_odds=float(vals.get("mnemo.logodds") or 0.0),
            mass=float(vals.get("mnemo.mass") or 0.0),
            provenance=json.loads(vals["mnemo.provenance"]) if vals.get("mnemo.provenance") else [],
        )
        return belief, vals.get("mnemo.summary")

    def save(self, urn: str, summary: str, belief: Belief, last_event: str) -> None:
        """Persist the belief. Merge-safe on mnemo.governance_status: if a governance actuation
        already set that field (see set_governance_status/actuate_governance), a later belief-only
        save() here does not silently erase it — it re-reads and re-includes whatever governance
        status currently sits on the entity."""
        existing = self._read_values(urn)
        props = [
            StructuredPropertyValueAssignmentClass(propertyUrn=_u("mnemo.summary"), values=[summary]),
            StructuredPropertyValueAssignmentClass(propertyUrn=_u("mnemo.confidence"), values=[round(belief.confidence, 3)]),
            StructuredPropertyValueAssignmentClass(propertyUrn=_u("mnemo.logodds"), values=[round(belief.log_odds, 4)]),
            StructuredPropertyValueAssignmentClass(propertyUrn=_u("mnemo.mass"), values=[round(belief.mass, 4)]),
            StructuredPropertyValueAssignmentClass(propertyUrn=_u("mnemo.provenance"), values=[json.dumps(belief.provenance)]),
            StructuredPropertyValueAssignmentClass(propertyUrn=_u("mnemo.lastEvent"), values=[last_event]),
            StructuredPropertyValueAssignmentClass(propertyUrn=_u("mnemo.agentVersion"), values=[AGENT_VERSION]),
        ]
        if existing.get("mnemo.governance_status") is not None:
            props.append(StructuredPropertyValueAssignmentClass(
                propertyUrn=_u("mnemo.governance_status"), values=[existing["mnemo.governance_status"]]))
        self.g.emit(MCP(entityUrn=urn, aspect=StructuredPropertiesClass(properties=props)))

    def set_governance_status(self, urn: str, status: str) -> None:
        """Merge-safe write of ONLY mnemo.governance_status — preserves whatever belief fields
        (summary/confidence/logodds/mass/provenance/lastEvent/agentVersion) already sit on `urn`.
        Called by mnemo/agent.py::actuate_governance; never touches editable model metadata."""
        vals = self._read_values(urn)
        vals["mnemo.governance_status"] = status
        props = []
        for qn, v in vals.items():
            if v is None or qn not in PROPS:
                continue
            props.append(StructuredPropertyValueAssignmentClass(propertyUrn=_u(qn), values=[v]))
        self.g.emit(MCP(entityUrn=urn, aspect=StructuredPropertiesClass(properties=props)))
