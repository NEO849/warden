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
    # Block C — outcome loop (mnemo/agent.py::actuate_governance / resolve_review, calibration.py):
    # mnemo.decision_features is the calibration feature vector x, FROZEN at flag time (the moment
    # actuate_governance raises NEEDS_REVIEW) as JSON {"sources": [...], "x": [...]}; mnemo.outcome
    # is the human-resolution label y (1.0 confirmed / 0.0 rejected) written later by
    # resolve_review(). Kept as two separate properties (not folded into mnemo.provenance) so a
    # calibration fit can read (x, y) pairs directly without re-parsing the whole provenance log.
    "mnemo.decision_features": "string",
    "mnemo.outcome": "number",
    # Block D — context-document write-back (mnemo/agent.py::actuate_governance): a human-readable,
    # one-line finding synced onto the model whenever governance opens a review. Its own property —
    # never the model's own MLModelPropertiesClass.description (see the HARD INVARIANT in
    # actuate_governance's docstring).
    "mnemo.finding": "string",
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

    def _merge_write(self, urn: str, updates: dict) -> None:
        """Merge-safe write of an arbitrary subset of mnemo.* PROPS: reads whatever currently sits
        on `urn`, overlays `updates` on top, and re-emits the FULL known set. structuredProperties
        is a full-replace aspect on DataHub, so every writer below (save/set_governance_status/
        set_decision_features/set_outcome/set_finding) goes through this one place — none of them
        can silently erase a sibling field some other writer already set."""
        vals = self._read_values(urn)
        vals.update(updates)
        props = []
        for qn, v in vals.items():
            if v is None or qn not in PROPS:
                continue
            props.append(StructuredPropertyValueAssignmentClass(propertyUrn=_u(qn), values=[v]))
        self.g.emit(MCP(entityUrn=urn, aspect=StructuredPropertiesClass(properties=props)))

    def save(self, urn: str, summary: str, belief: Belief, last_event: str,
              extra: dict | None = None) -> None:
        """Persist the belief. Merge-safe on every OTHER mnemo.* field (governance_status,
        decision_features, outcome, finding, ...): a belief-only save() here never silently erases
        whatever a governance actuation / outcome-loop write already set on this entity — see
        _merge_write.

        `extra` (optional) folds additional mnemo.* fields into this SAME read-modify-write round
        trip (e.g. resolve_review passes {"mnemo.outcome": ...} here) rather than issuing a second,
        separate emit right after — one round trip per logical event, not two, so a second write's
        read can never race the first write's not-yet-visible result on the same entity."""
        updates = {
            "mnemo.summary": summary,
            "mnemo.confidence": round(belief.confidence, 3),
            "mnemo.logodds": round(belief.log_odds, 4),
            "mnemo.mass": round(belief.mass, 4),
            "mnemo.provenance": json.dumps(belief.provenance),
            "mnemo.lastEvent": last_event,
            "mnemo.agentVersion": AGENT_VERSION,
        }
        if extra:
            updates.update(extra)
        self._merge_write(urn, updates)

    def set_governance_status(self, urn: str, status: str) -> None:
        """Merge-safe write of ONLY mnemo.governance_status — preserves whatever belief fields
        (summary/confidence/logodds/mass/provenance/lastEvent/agentVersion) already sit on `urn`.
        Standalone convenience method; mnemo/agent.py::actuate_governance itself goes through the
        single combined actuate_write() below instead (see its docstring for why)."""
        self._merge_write(urn, {"mnemo.governance_status": status})

    @staticmethod
    def _decision_features_payload(sources: list, x) -> str:
        return json.dumps({"sources": list(sources), "x": [round(float(v), 4) for v in x]})

    def set_decision_features(self, urn: str, sources: list, x) -> None:
        """Block C: merge-safe write of the calibration feature vector x, frozen at flag time by
        mnemo/agent.py::actuate_governance. Stored as JSON {"sources": [...], "x": [...]} so it is
        self-describing (robust to FEATURE_SOURCES ever changing order) — calibration.py's
        fit_map/fit_temperature read the "x" array; "sources" is provenance for a human/report.
        Standalone convenience method; actuate_governance itself uses actuate_write() (below) to
        fold this into the SAME round trip as the governance_status/finding writes."""
        self._merge_write(urn, {"mnemo.decision_features": self._decision_features_payload(sources, x)})

    def read_decision_features(self, urn: str):
        """Return the {"sources": [...], "x": [...]} dict frozen by set_decision_features, or None
        if this entity has never had a review flagged."""
        raw = self._read_values(urn).get("mnemo.decision_features")
        return json.loads(raw) if raw else None

    def set_outcome(self, urn: str, confirmed: bool) -> None:
        """Block C outcome-loop label y for calibration.py. Standalone convenience method;
        mnemo/agent.py::resolve_review instead passes `extra={"mnemo.outcome": ...}` to save() so
        the belief-update and the outcome label land in the SAME round trip."""
        self._merge_write(urn, {"mnemo.outcome": 1.0 if confirmed else 0.0})

    def set_finding(self, urn: str, finding: str) -> None:
        """Block D: merge-safe write of the human-readable context-document finding. Its own
        property — never MLModelPropertiesClass.description (see the HARD INVARIANT documented on
        mnemo/agent.py::actuate_governance). Standalone convenience method; actuate_governance
        itself uses actuate_write() (below) to fold this into the same round trip as the other
        governance writes."""
        self._merge_write(urn, {"mnemo.finding": finding})

    def actuate_write(self, urn: str, status: str, decision_features=None,
                       finding: str | None = None) -> None:
        """The ONE read-modify-write round trip mnemo/agent.py::actuate_governance actually issues
        for a given call: governance_status always, plus decision_features/finding when a review is
        opening. Combining what would otherwise be up to three separate _merge_write calls (each its
        own get_aspect + emit) into one matters beyond tidiness: three back-to-back read-modify-write
        cycles against the SAME entity's structuredProperties aspect open a real race window if any
        one of those reads doesn't yet observe an earlier one's write (a transient full-suite flake
        during Block C/D verification traced to exactly this: extra sequential round trips added by
        the new decision_features/finding writes). One combined round trip removes the window
        entirely rather than just making it statistically unlikely.

        `decision_features`, if given, is (sources, x) — see set_decision_features. `finding`, if
        given, is the pre-formatted string — see set_finding / mnemo/agent.py::_format_finding.
        """
        updates = {"mnemo.governance_status": status}
        if decision_features is not None:
            sources, x = decision_features
            updates["mnemo.decision_features"] = self._decision_features_payload(sources, x)
        if finding is not None:
            updates["mnemo.finding"] = finding
        self._merge_write(urn, updates)
