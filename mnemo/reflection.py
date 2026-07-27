"""
Lineage-wide reflection (the crown feature).

Synthesizes a higher-level INSIGHT that lives on NO single asset, grounded in the agent's own
accumulated per-asset memories along the model's lineage, written back onto the MODEL entity with
its own confidence + evidence chain. Insight-confidence reuses the same log-odds algebra as
confidence_model: each source memory's posterior becomes evidence, discounted by GAMMA**hops.

Spec: scratchpad/spec_reflection.md. LLM synthesis is pluggable (deterministic stub when no key),
so the traversal / confidence-pool / write-back / guards are all testable without an API key.
"""
import hashlib
import json
import math
import time

from datahub.emitter.mcp import MetadataChangeProposalWrapper as MCP
from datahub.metadata.schema_classes import (
    MLFeaturePropertiesClass,
    MLModelPropertiesClass,
    StructuredPropertiesClass,
    StructuredPropertyValueAssignmentClass,
    UpstreamLineageClass,
)

from confidence_model import C_MAX, C_MIN, DW_MAX, GAMMA, N_MIN, _sigmoid

MAX_DEPTH = 6
K_MIN = 3               # need at least this many upstream memories to reflect
# Rejects reflections whose POOLED evidence is weak even when K_MIN assets exist — i.e. all cited
# memories are low-confidence and/or deep in lineage (each hop halves weight). NOT tuned-to-pass:
# K_MIN=3 is the primary gate; this is the secondary "is the pooled evidence substantial" check.
# TODO: derive from a target false-reflection rate rather than a hand-set constant.
MIN_REFLECT_MASS = 0.5
AGENT_VERSION = "mnemo-0.1"
REFLECTION_PROP = "urn:li:structuredProperty:mnemo.reflection"


def define_reflection_property(g) -> None:
    """Define mnemo.reflection on the model entity (no GMS rebuild — verified path)."""
    from datahub.api.entities.structuredproperties.structuredproperties import StructuredProperties
    sp = StructuredProperties(id="mnemo.reflection", qualified_name="mnemo.reflection",
                             display_name="Mnemo Reflection", type="string",
                             cardinality="SINGLE", entity_types=["mlModel", "dataset"])
    for mcp in sp.generate_mcps():
        g.emit(mcp)


def _logit(c: float) -> float:
    c = min(max(c, 1e-6), 1 - 1e-6)
    return math.log(c / (1 - c))


def _clamp(x, lo, hi):
    return max(lo, min(hi, x))


def collect_upstream_memories(g, memory, model_urn: str) -> list:
    """Walk model → features → source datasets → upstream datasets, gather mnemo memories."""
    out, visited = [], set()

    def visit(urn, hops):
        if urn in visited or hops > MAX_DEPTH:
            return
        visited.add(urn)
        belief, summary = memory.load(urn)
        if summary is not None or belief.mass > 0:
            out.append({"urn": urn, "hops": hops, "confidence": belief.confidence,
                        "mass": belief.mass, "summary": summary})
        # recurse dataset upstreams
        up = g.get_aspect(urn, UpstreamLineageClass)
        for u in (up.upstreams if up else []):
            visit(u.dataset, hops + 1)

    mp = g.get_aspect(model_urn, MLModelPropertiesClass)
    for feat in (mp.mlFeatures if mp and mp.mlFeatures else []):
        fp = g.get_aspect(feat, MLFeaturePropertiesClass)
        for ds in (fp.sources if fp and fp.sources else []):
            visit(ds, 1)  # direct model inputs = 1 hop (through the feature)
    return out


def pool_confidence(cited: list) -> tuple:
    """Proximity-weighted log-odds pool over cited memories (same algebra as Belief)."""
    ell = mass = 0.0
    for m in cited:
        sign = 1.0 if m.get("supported", True) else -1.0
        w = _clamp(sign * (GAMMA ** m["hops"]) * _logit(m["confidence"]), -DW_MAX, DW_MAX)
        ell += w
        mass += (GAMMA ** m["hops"]) * m["confidence"]
    return _clamp(_sigmoid(ell), C_MIN, C_MAX), mass, ell


def _stub_synthesis(memories: list, event) -> list:
    """Deterministic insight when no LLM key is set — cites the collected memories.
    A memory whose confidence is low OR whose summary flags a change is treated as contradicting
    (drives the drift-warning behavior)."""
    cited = []
    for m in memories:
        supported = m["confidence"] >= 0.55 and "drift" not in (m["summary"] or "").lower()
        cited.append({**m, "supported": supported})
    statement = ("Model inputs are corroborated across lineage."
                 if all(c["supported"] for c in cited)
                 else "Upstream change threatens this model's inputs — drift/leakage risk.")
    return [{"statement": statement, "evidence_urns": [c["urn"] for c in cited],
             "generated_from_events": [str(event)] if event else [], "cited": cited}]


def reflect(g, memory, model_urn: str, event=None, llm=None) -> dict | None:
    memories = collect_upstream_memories(g, memory, model_urn)
    if len(memories) < K_MIN:
        return {"skipped": f"only {len(memories)} upstream memories (< K_MIN={K_MIN})"}

    insights = (llm(memories, event) if llm else _stub_synthesis(memories, event))
    valid_urns = {m["urn"] for m in memories}
    results = []
    for ins in insights:
        cited = ins.get("cited") or [m for m in memories if m["urn"] in set(ins["evidence_urns"])]
        # Guard 1: citation validity — need ≥2 distinct valid URNs
        good = [c for c in cited if c["urn"] in valid_urns]
        if len({c["urn"] for c in good}) < 2:
            continue
        c_ins, mass_ins, _ = pool_confidence(good)
        # Guard 2: min mass (calibrated to the discounted reflection scale)
        if mass_ins < MIN_REFLECT_MASS:
            continue
        # Guard 3 + 5: gov gate / contradiction escalation
        contradiction_near = any((not c.get("supported", True)) and c["hops"] <= 1 for c in good)
        if c_ins > 0.85 and mass_ins >= N_MIN and not contradiction_near:
            gate = "auto-write"
        elif c_ins >= 0.7 and not contradiction_near:
            gate = "needs_review"
        else:
            gate = "needs_proposal"
        results.append({"statement": ins["statement"], "confidence": round(c_ins, 3),
                        "mass": round(mass_ins, 3), "evidence_urns": [c["urn"] for c in good],
                        "generated_from_events": ins.get("generated_from_events", []),
                        "gate": gate})

    if not results:
        return {"skipped": "no insight survived guards"}

    fingerprint = hashlib.sha1(
        json.dumps(sorted((m["urn"], round(m["confidence"], 2)) for m in memories)).encode()
    ).hexdigest()[:12]
    record = {"insights": results, "graph_fingerprint": fingerprint,
              "agentVersion": AGENT_VERSION, "timestamp": int(time.time())}

    # Guard 4: no re-reflect if fingerprint unchanged
    existing = g.get_aspect(model_urn, StructuredPropertiesClass)
    if existing:
        for p in existing.properties:
            if p.propertyUrn == REFLECTION_PROP and p.values:
                try:
                    if json.loads(p.values[0]).get("graph_fingerprint") == fingerprint:
                        return {"skipped": "graph unchanged (same fingerprint)", "record": record}
                except Exception:
                    pass

    # write-back onto the MODEL (verified direct-emit, not patch builder)
    aspect = StructuredPropertiesClass(properties=[
        StructuredPropertyValueAssignmentClass(propertyUrn=REFLECTION_PROP, values=[json.dumps(record)])
    ])
    g.emit(MCP(entityUrn=model_urn, aspect=aspect))
    return record
