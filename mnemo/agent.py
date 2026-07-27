"""
MnemoAgent — the coherent agent that unifies the pieces the demo scripts exercised separately:

    observe(asset, evidence)      → reconcile the asset's belief with new evidence (compounding memory)
    check_model_inputs(model)     → detect a silent upstream source-delta vs remembered inputs (drift)
    reflect(model)                → lineage-wide insight grounded in accumulated memories (crown)
    govern(belief)                → auto-write / needs-review / open-proposal, by confidence + mass

One object, one belief model, one governance policy — so the project reads as an agent, not scripts.
Read layer via DataHubReader; memory persisted on the graph via MnemoMemory; confidence via Belief.
"""
import json

from datahub.metadata.schema_classes import (
    DatasetProfileClass,
    MLFeaturePropertiesClass,
    MLModelPropertiesClass,
)

from confidence_model import Belief
from mnemo import drift
from mnemo.memory import MnemoMemory
from mnemo.reader import DataHubReader
from mnemo.reflection import reflect, define_reflection_property


class MnemoAgent:
    def __init__(self, graph, llm=None):
        self.g = graph
        self.reader = DataHubReader(graph)
        self.memory = MnemoMemory(graph)
        self.llm = llm

    # --- one-time setup: ensure the mnemo.* structured properties exist (no GMS rebuild) ---
    def setup(self):
        self.memory.define_properties()
        define_reflection_property(self.g)

    # --- compounding memory: fold new evidence into an asset's persisted belief ---
    def observe(self, urn, evidence, summary=None, event_id="obs"):
        """evidence = list of dicts for Belief.update(source, corroborates, hops, quality, event_id)."""
        belief, prior_summary = self.memory.load(urn)
        for ev in evidence:
            belief.update(**ev)
        payload = summary if summary is not None else (prior_summary or json.dumps({"desc": "observed"}))
        self.memory.save(urn, payload, belief, event_id)
        return belief

    # --- drift detection: current model input sources vs the remembered set ---
    def model_input_sources(self, model_urn):
        mp = self.g.get_aspect(model_urn, MLModelPropertiesClass)
        srcs = []
        for feat in (mp.mlFeatures if mp and mp.mlFeatures else []):
            fp = self.g.get_aspect(feat, MLFeaturePropertiesClass)
            srcs += (fp.sources if fp and fp.sources else [])
        return sorted(set(srcs))

    def remember_inputs(self, model_urn, desc="inputs healthy"):
        """Establish/refresh the model's memory of its current input source-set."""
        belief, _ = self.memory.load(model_urn)
        sources = self.model_input_sources(model_urn)
        self.memory.save(model_urn, json.dumps({"desc": desc, "input_sources": sources}),
                         belief, "remember_inputs")
        return sources

    def _measured_drift(self, remembered, now):
        """Block 1 (measured drift): if the source-set delta is a clean 1-for-1 swap AND DataHub
        holds a DatasetProfileClass (field histogram) for BOTH the old and the new source, compute
        PSI over a matching field and return {"field", "psi", "old_source", "new_source"}.

        PROFILE GATE — the superset guarantee: any other case (0 or >1 sources removed/added, a
        missing profile on either side, or no field the two profiles can be compared on) returns
        None and check_model_inputs falls back to exactly today's structural-only behavior. This
        method never blocks or weakens the structural term — it only ever ADDS a second, independent
        piece of evidence on top of it.

        Field matching: prefer an identical fieldPath name (multi-field profiles). If neither profile
        has a name in common but EACH has exactly one histogram-bearing field, fall back to comparing
        those two positionally — the common real-world case this whole feature targets, where a
        source swap renames the column (e.g. signup_ts -> ingest_ts) along with the table.
        """
        removed = set(remembered) - set(now)
        added = set(now) - set(remembered)
        if len(removed) != 1 or len(added) != 1:
            return None
        old_urn, new_urn = next(iter(removed)), next(iter(added))
        old_profile = self.g.get_latest_timeseries_value(old_urn, DatasetProfileClass, filter_criteria_map={})
        new_profile = self.g.get_latest_timeseries_value(new_urn, DatasetProfileClass, filter_criteria_map={})
        if not old_profile or not new_profile or not old_profile.fieldProfiles or not new_profile.fieldProfiles:
            return None
        old_fields = {fp.fieldPath: fp for fp in old_profile.fieldProfiles if fp.histogram}
        new_fields = {fp.fieldPath: fp for fp in new_profile.fieldProfiles if fp.histogram}
        if not old_fields or not new_fields:
            return None
        shared = sorted(set(old_fields) & set(new_fields))
        if shared:
            pairs = [(f, old_fields[f], new_fields[f]) for f in shared]
        elif len(old_fields) == 1 and len(new_fields) == 1:
            (old_name, old_fp), = old_fields.items()
            (new_name, new_fp), = new_fields.items()
            pairs = [(f"{old_name}->{new_name}", old_fp, new_fp)]
        else:
            return None
        # aggregate = worst-case (max) PSI across matched fields — one materially drifted field is
        # enough to raise the flag, mirroring how a single silently-changed column caused the
        # original drift.
        best_field, best_psi = None, -1.0
        for field_label, old_fp, new_fp in pairs:
            p = drift.psi(old_fp.histogram.heights, new_fp.histogram.heights)
            if p > best_psi:
                best_field, best_psi = field_label, p
        return {"field": best_field, "psi": best_psi, "old_source": old_urn, "new_source": new_urn}

    def check_model_inputs(self, model_urn):
        """Return (changed, remembered, now, belief_after, drift_info). If changed, folds the
        structural source-delta in as contradicting evidence → confidence drops → governance can
        route it to a Proposal. ADDITIVE (Block 1): when a profile pair exists for the swapped
        sources, a second, independent drift_stat evidence term is folded in too, scored from a real
        PSI over the field histograms — see _measured_drift for the profile gate. drift_info is None
        whenever no profile pair was found (today's behavior, unchanged); otherwise it carries the
        measured PSI for the caller/demo/UI.
        """
        belief, summary_json = self.memory.load(model_urn)
        try:
            remembered = json.loads(summary_json).get("input_sources", []) if summary_json else []
        except Exception:
            remembered = []
        now = self.model_input_sources(model_urn)
        changed = set(now) != set(remembered)
        drift_info = None
        if changed:
            belief.update("schema", corroborates=False, hops=0, quality=1.0, event_id="input_delta")
            drift_info = self._measured_drift(remembered, now)
            if drift_info is not None:
                belief.update("drift_stat", corroborates=False, hops=0,
                              quality=drift.psi_to_quality(drift_info["psi"]), event_id="input_delta")
            self.memory.save(model_urn, json.dumps({"desc": "input source changed", "input_sources": now}),
                             belief, "input_delta")
        return changed, remembered, now, belief, drift_info

    # --- crown: lineage-wide reflection ---
    def reflect(self, model_urn, event=None):
        return reflect(self.g, self.memory, model_urn, event=event, llm=self.llm)

    # --- governance policy (single source of truth) ---
    @staticmethod
    def govern(belief):
        if belief.actionable_high:
            return "auto-write"
        if belief.needs_proposal():
            return "open-proposal"
        return "needs-review"
