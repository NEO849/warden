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

from datahub.metadata.schema_classes import MLFeaturePropertiesClass, MLModelPropertiesClass

from confidence_model import Belief
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

    def check_model_inputs(self, model_urn):
        """Return (changed, remembered, now, belief_after). If changed, folds it in as contradicting
        evidence → confidence drops → governance can route it to a Proposal."""
        belief, summary_json = self.memory.load(model_urn)
        try:
            remembered = json.loads(summary_json).get("input_sources", []) if summary_json else []
        except Exception:
            remembered = []
        now = self.model_input_sources(model_urn)
        changed = set(now) != set(remembered)
        if changed:
            belief.update("schema", corroborates=False, hops=0, quality=1.0, event_id="input_delta")
            self.memory.save(model_urn, json.dumps({"desc": "input source changed", "input_sources": now}),
                             belief, "input_delta")
        return changed, remembered, now, belief

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
