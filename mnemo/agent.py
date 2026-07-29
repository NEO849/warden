"""
MnemoAgent — the coherent agent that unifies the pieces the demo scripts exercised separately:

    observe(asset, evidence)      → reconcile the asset's belief with new evidence (compounding memory)
    check_model_inputs(model)     → detect a silent upstream source-delta vs remembered inputs (drift)
    reflect(model)                → lineage-wide insight grounded in accumulated memories (crown)
    govern(belief)                → auto-write / needs-review / open-proposal, by confidence + mass

One object, one belief model, one governance policy — so the project reads as an agent, not scripts.
Read layer via DataHubReader; memory persisted on the graph via MnemoMemory; confidence via Belief.
"""
import datetime as _dt
import json
import re

from datahub.emitter.mcp import MetadataChangeProposalWrapper as MCP
from datahub.metadata.schema_classes import (
    DatasetProfileClass,
    GlobalTagsClass,
    MLFeaturePropertiesClass,
    MLModelPropertiesClass,
    TagAssociationClass,
    TagPropertiesClass,
)

from calibration import FEATURE_SOURCES, freeze_features
from confidence_model import Belief
from mnemo import drift
from mnemo.memory import MnemoMemory
from mnemo.reader import DataHubReader
from mnemo.reflection import reflect, define_reflection_property

# The real, OSS-native "human gate" tag Mnemo puts on a model it doesn't trust yet. There is no
# ActionRequest/Proposal entity in OSS DataHub (that class of object is Cloud-only) — a tag +
# Mnemo's own structured property is the honest OSS equivalent: a visible, queryable review flag
# on the graph instead of a print statement nobody can see or act on.
NEEDS_REVIEW_TAG_URN = "urn:li:tag:mnemo-needs-review"


def _short_urn(urn: str) -> str:
    """Best-effort short label for a comma-delimited DataHub URN, e.g.
    'urn:li:dataset:(urn:li:dataPlatform:hive,fct_users_created,PROD)' -> 'fct_users_created'.
    Falls back to the raw urn if the pattern doesn't match (never raises)."""
    m = re.search(r",([^,()]+),", urn)
    return m.group(1) if m else urn


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
        self._define_needs_review_tag()

    def _define_needs_review_tag(self):
        """Idempotent, cosmetic-only: gives the tag entity a human-readable name/description in the
        DataHub UI. Not required for the tag ASSOCIATION in actuate_governance() to work."""
        self.g.emit(MCP(entityUrn=NEEDS_REVIEW_TAG_URN, aspect=TagPropertiesClass(
            name="Mnemo: Needs Review",
            description="Mnemo's confidence in this model's current inputs fell below the "
                        "governance threshold (τ=0.70) after contradicting evidence (e.g. a "
                        "silent upstream source re-point). A human should review before the model's "
                        "lineage is trusted again.",
        )))

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

    def check_model_inputs(self, model_urn, via: str | None = None):
        """Return (changed, remembered, now, belief_after, drift_info). If changed, folds the
        structural source-delta in as contradicting evidence → confidence drops → governance can
        route it to a Proposal. ADDITIVE (Block 1): when a profile pair exists for the swapped
        sources, a second, independent drift_stat evidence term is folded in too, scored from a real
        PSI over the field histograms — see _measured_drift for the profile gate. drift_info is None
        whenever no profile pair was found (today's behavior, unchanged); otherwise it carries the
        measured PSI for the caller/demo/UI.

        `via` (optional): how the CALLER resolved `model_urn` as a wake target — e.g.
        actions/mnemo_wake_action.py passes "reverse-lineage" when G2's _reverse_lineage_models
        found it, or "static-watchlist" when it fell back to the configured watch list. Folded onto
        the contradicting "schema" evidence entry (Belief.update's `via`) so the resolution source
        is DURABLE on the graph (mnemo.provenance, written by memory.save below) — on-graph proof a
        Kafka log reset cannot erase, instead of only a log line. Callers that don't know/care about
        their own resolution path (demos, direct calls) simply omit it — no behavior change.
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
            belief.update("schema", corroborates=False, hops=0, quality=1.0, event_id="input_delta",
                          via=via)
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

    # --- governance ACTUATION: turn the govern() verdict into a real, visible graph action ---
    def actuate_governance(self, model_urn: str, belief: Belief, context: dict | None = None) -> dict:
        """Confidence-gated, OSS-native governance signal — replaces a mere print statement with a
        real write the DataHub UI shows immediately.

        There is no ActionRequest/Proposal entity in the OSS DataHub SDK — real Proposals are a
        Cloud-only feature. The honest OSS-native "human gate" this method actually emits is now
        FOUR things, all owned entirely by Mnemo:
          (a) `mnemo.governance_status` structured property on the model  (NEEDS_REVIEW | TRUSTED)
          (b) the GlobalTag `mnemo-needs-review` on the model, present only while NEEDS_REVIEW is
              the result of a genuine contradiction (govern() == "open-proposal")
          (c) [Block C] `mnemo.decision_features` — the calibration feature vector x, FROZEN
              *right now* from belief.provenance, whenever a review opens (status==NEEDS_REVIEW).
              This is deliberately the earliest possible freeze point ("flag time"), strictly
              before any human resolution can exist — see resolve_review()'s LEAKAGE-GUARD, which
              depends on that ordering.
          (d) [Block D] `mnemo.finding` — a human-readable one-line context-document write-back,
              also whenever a review opens: "Mnemo · <date>: source re-pointed X→Y; PSI=…;
              confidence 0.90→0.60; NEEDS-REVIEW". `context` (optional) supplies the drift
              specifics (old_source/new_source/psi — see check_model_inputs's drift_info) for the
              richer message; without it the finding still reports the confidence transition and
              verdict, both always available from belief itself.

        Verdict -> action (govern(belief) is the single source of truth for the verdict itself):
          open-proposal (confidence < 0.70, belief.needs_proposal()):
              governance_status=NEEDS_REVIEW, tag ADDED if not already present, (c)+(d) written.
          needs-review (mid-band, neither threshold hit):
              governance_status=NEEDS_REVIEW, tag left as-is — not contradicted enough to demand
              review, just not confident enough to auto-write. (c)+(d) written (same NEEDS_REVIEW
              status as open-proposal — a human review is equally warranted either way).
          auto-write (belief.actionable_high):
              governance_status=TRUSTED, tag REMOVED if present. (c)/(d) NOT written — nothing to
              flag, so nothing to freeze a decision on.

        HARD INVARIANT — this method NEVER writes MLModelPropertiesClass.description, or any other
        editable/owner-authored metadata on the model. It only ever writes Mnemo's OWN mnemo.*
        structured properties and its OWN tag. That is the literal mechanism behind "never silently
        trusts/rewrites the model's metadata": read MLModelPropertiesClass.description before and
        after any call to this method and it must come back byte-identical.

        Returns what was actually emitted (for demo/readback), e.g.:
          {"verdict": "open-proposal", "governance_status": "NEEDS_REVIEW",
           "tag": "urn:li:tag:mnemo-needs-review", "tag_action": "added",
           "finding": "Mnemo · 2026-07-28: confidence 0.90→0.60; NEEDS-REVIEW"}
        """
        verdict = self.govern(belief)
        status = "TRUSTED" if verdict == "auto-write" else "NEEDS_REVIEW"
        want_tag = verdict == "open-proposal"

        decision_features = None
        finding = None
        if status == "NEEDS_REVIEW":
            # Block C: freeze x AT FLAG TIME (this call, right now) — before this call returns,
            # nothing has touched belief with a human update, so freeze_features() (which itself
            # unconditionally drops any 'human' source) cannot possibly see one. That ordering IS
            # the leakage guard; resolve_review() later only ever READS this frozen snapshot back.
            x = freeze_features(belief.provenance)
            decision_features = (FEATURE_SOURCES, x)
            # Block D: confidence-gated context-document write-back.
            finding = self._format_finding(belief, context)

        # ONE combined read-modify-write for governance_status + decision_features + finding — see
        # MnemoMemory.actuate_write's docstring for why this must not be three separate round trips.
        self.memory.actuate_write(model_urn, status, decision_features=decision_features, finding=finding)

        current = self.g.get_aspect(model_urn, GlobalTagsClass)
        tags = list(current.tags) if current and current.tags else []
        has_tag = any(t.tag == NEEDS_REVIEW_TAG_URN for t in tags)

        if want_tag and not has_tag:
            self._define_needs_review_tag()  # idempotent: label the tag entity before referencing it
            tags.append(TagAssociationClass(tag=NEEDS_REVIEW_TAG_URN))
            self.g.emit(MCP(entityUrn=model_urn, aspect=GlobalTagsClass(tags=tags)))
            tag_action = "added"
        elif not want_tag and has_tag:
            tags = [t for t in tags if t.tag != NEEDS_REVIEW_TAG_URN]
            self.g.emit(MCP(entityUrn=model_urn, aspect=GlobalTagsClass(tags=tags)))
            tag_action = "removed"
        else:
            tag_action = "unchanged"

        return {
            "verdict": verdict,
            "governance_status": status,
            "tag": NEEDS_REVIEW_TAG_URN if (want_tag or has_tag) else None,
            "tag_action": tag_action,
            "finding": finding,
        }

    def _format_finding(self, belief: Belief, context: dict | None) -> str:
        """Block D: human-readable one-liner for the mnemo.finding context-document write-back —
        'Mnemo · <date>: source re-pointed X→Y; PSI=…; confidence 0.90→0.60; NEEDS-REVIEW'.
        `context` (optional) supplies the drift specifics {"old_source", "new_source", "psi"} when
        the caller has them (see check_model_inputs's drift_info); without it, the message still
        reports the confidence transition (always available from belief.provenance) and verdict."""
        ctx = context or {}
        parts = [f"Mnemo · {_dt.date.today().isoformat()}:"]
        old_s, new_s = ctx.get("old_source"), ctx.get("new_source")
        if old_s and new_s:
            parts.append(f"source re-pointed {_short_urn(old_s)}→{_short_urn(new_s)};")
        if ctx.get("psi") is not None:
            parts.append(f"PSI={ctx['psi']:.3f};")
        prov = belief.provenance
        if len(prov) >= 2:
            parts.append(f"confidence {prov[-2]['c_after']:.2f}→{prov[-1]['c_after']:.2f};")
        else:
            parts.append(f"confidence →{belief.confidence:.2f};")
        parts.append("NEEDS-REVIEW")
        return " ".join(parts)

    # --- outcome loop (Block C): close the review a human just resolved -------------------------
    def resolve_review(self, urn: str, confirmed: bool, event_id: str = "resolve_review") -> dict:
        """A human resolves an OPEN review (one actuate_governance previously flagged NEEDS_REVIEW
        on) as confirmed=True (the contradiction was real) or confirmed=False (false alarm).

        Writes the outcome-loop LABEL y for calibration.py:
          mnemo.outcome = 1.0 if confirmed else 0.0

        paired with the FEATURE vector x = mnemo.decision_features that actuate_governance already
        froze AT FLAG TIME — this method only ever READS that snapshot back, it never recomputes x
        from the (by-now human-updated) belief. That is the LEAKAGE-GUARD, made structural rather
        than a convention: x was captured before any human evidence existed, so it cannot contain
        the label it is later fit against — see calibration.freeze_features()'s own defense-in-depth
        drop of any 'human' source too.

        Then folds the human decision into the belief itself as genuine 'human' evidence
        (undiscounted, d=0 — confidence_model.py's rho=1.0 rule for source=='human'), so the NEXT
        observe()/check_model_inputs() resumes from the human-corrected posterior instead of the
        pre-review one — the review loop closes and the memory keeps compounding forward, exactly
        like any other evidence update.
        """
        belief, summary_json = self.memory.load(urn)
        decision_features = self.memory.read_decision_features(urn)  # frozen at flag time, above
        belief.update("human", corroborates=confirmed, hops=0, quality=1.0, event_id=event_id)
        payload = summary_json or json.dumps({"desc": "resolve_review"})
        # ONE combined round trip for the belief save + the outcome label — same rationale as
        # actuate_governance's actuate_write (see its docstring): no separate save() then
        # set_outcome() pair that could race each other's not-yet-visible write on this entity.
        self.memory.save(urn, payload, belief, event_id,
                          extra={"mnemo.outcome": 1.0 if confirmed else 0.0})
        return {
            "outcome": 1.0 if confirmed else 0.0,
            "decision_features": decision_features,
            "confidence_after": belief.confidence,
        }
