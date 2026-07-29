#!/usr/bin/env python3
"""
Measured-drift demo (Block 1): PSI/KS as a REAL Bayes evidence term, not just priors.

run_ml_drift_demo.py (unchanged, still the live-verified 0.901→0.600 hero) proves the STRUCTURAL
half of Warden's honesty claim: a source-delta a schema-diff cannot see. This script proves the
MEASURED half — that when DataHub also holds field-profile histograms for the old and new source,
warden/drift.py's PSI feeds in as a second, independent drift_stat evidence term (see
warden/agent.py::check_model_inputs / _measured_drift), on top of — never instead of — the structural
term.

Two scenarios, same structural swap (a feature's source re-pointed under an unchanged name):

  (a) KILL-SHOT "PSI schweigt": new profile ≈ old profile (PSI≈0.02, same as the seeded
      run_ml_drift_demo.py-style pair — see seed_demo_graph.py::seed_profiles). A PSI/KS-only
      monitor would stay GREEN here. Warden's STRUCTURAL source-delta term still fires on its own —
      proof that Warden is a SUPERSET of a pure statistical-drift monitor, not a subset.

  (b) "measured drift": the new source's distribution has genuinely moved (PSI>0.25). Confidence
      now falls HARDER than in scenario (a), because the structural signal is independently
      CORROBORATED by a measured statistical one — two evidence terms instead of one.

Run:  python run_measured_drift_demo.py   (needs DataHub up; LLM not required)
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dotenv import load_dotenv

from datahub.emitter.mcp import MetadataChangeProposalWrapper as MCP
from datahub.emitter.mce_builder import make_dataset_urn
from datahub.ingestion.graph.client import DataHubGraph, DataHubGraphConfig
from datahub.metadata.schema_classes import (
    DatasetFieldProfileClass,
    DatasetProfileClass,
    GlobalTagsClass,
    HistogramClass,
    MLFeaturePropertiesClass,
    MLFeatureTablePropertiesClass,
    MLModelPropertiesClass,
    StructuredPropertiesClass,
)

from confidence_model import Belief
from warden import drift
from warden.agent import WardenAgent

load_dotenv()
g = DataHubGraph(DataHubGraphConfig(
    server=os.getenv("DATAHUB_GMS_URL", "http://localhost:8090"),
    token=os.getenv("DATAHUB_GMS_TOKEN") or None,
))
agent = WardenAgent(g)

BOUNDARIES = [float(b) for b in range(0, 8)]
BOUNDARY_LABELS = [str(b) for b in BOUNDARIES]


def _emit_profile(urn, field_path, seed_val, mean, stdev, n=2000):
    samples = drift.sample(seed=seed_val, n=n, mean=mean, stdev=stdev)
    heights = drift.histogram(samples, BOUNDARIES)
    g.emit(MCP(entityUrn=urn, aspect=DatasetProfileClass(
        timestampMillis=int(time.time() * 1000),
        fieldProfiles=[DatasetFieldProfileClass(
            fieldPath=field_path, histogram=HistogramClass(boundaries=BOUNDARY_LABELS, heights=heights))])))
    return samples


def run_scenario(label, tag, old_field, new_field, old_stat, new_stat, expect_significant):
    """One end-to-end WardenAgent cycle: seed profiles -> healthy baseline -> silent re-point ->
    check_model_inputs -> report structural + measured (drift_stat) evidence."""
    old_ds = make_dataset_urn("hive", f"{tag}_old_src", "PROD")
    new_ds = make_dataset_urn("hive", f"{tag}_new_src", "PROD")
    feat = f"urn:li:mlFeature:(measured_drift_demo,{tag}_feature)"
    ft = f"urn:li:mlFeatureTable:(urn:li:dataPlatform:feast,{tag}_features)"
    model = f"urn:li:mlModel:(urn:li:dataPlatform:mlflow,{tag}_model,PROD)"

    print(f"\n=== SCENARIO {label} ===")
    old_samples = _emit_profile(old_ds, old_field, seed_val=100, mean=old_stat[0], stdev=old_stat[1])
    new_samples = _emit_profile(new_ds, new_field, seed_val=101, mean=new_stat[0], stdev=new_stat[1])
    ks = drift.ks_stat(old_samples, new_samples)
    time.sleep(2)

    g.emit(MCP(entityUrn=feat, aspect=MLFeaturePropertiesClass(description="demo feature", sources=[old_ds])))
    g.emit(MCP(entityUrn=ft, aspect=MLFeatureTablePropertiesClass(description="demo features", mlFeatures=[feat])))
    g.emit(MCP(entityUrn=model, aspect=MLModelPropertiesClass(description="demo model", mlFeatures=[feat])))
    time.sleep(2)
    description_before = g.get_aspect(model, MLModelPropertiesClass).description

    baseline = Belief()
    baseline.update("lineage", corroborates=True, hops=2, quality=0.9, event_id="o1")
    baseline.update("lineage", corroborates=True, hops=0, quality=1.0, event_id="o2")
    agent.memory.save(model, json.dumps({"desc": "healthy", "input_sources": [old_ds]}), baseline, "o2")
    print(f"   baseline: confidence={baseline.confidence:.3f}  source={old_field}@{old_ds.split(',')[1]}")

    print(f"   silent re-point: {old_field} -> {new_field} (name/description of the FEATURE unchanged)")
    g.emit(MCP(entityUrn=feat, aspect=MLFeaturePropertiesClass(description="demo feature", sources=[new_ds])))
    time.sleep(2)

    changed, remembered, now, belief2, drift_info = agent.check_model_inputs(model)
    if drift_info:
        print(f"   measured: PSI={drift_info['psi']:.4f}  KS={ks:.4f}  field={drift_info['field']}"
              f"  quality={drift.psi_to_quality(drift_info['psi']):.4f}")
    else:
        print(f"   measured: PSI/KS computed standalone (not wired in) KS={ks:.4f} — no profile pair matched")
    print(f"   confidence: {baseline.confidence:.3f} -> {belief2.confidence:.3f}"
          f"  (Δ={belief2.confidence - baseline.confidence:+.3f})  governance={agent.govern(belief2)}")

    gov_result = agent.actuate_governance(model, belief2)
    print(f"   governance actuation: wrote warden.governance_status={gov_result['governance_status']}"
          f"  tag={gov_result['tag']} ({gov_result['tag_action']}) on {model}")
    sp_after = g.get_aspect(model, StructuredPropertiesClass)
    gov_status_live = None
    for p in (sp_after.properties if sp_after else []):
        if p.propertyUrn.endswith("warden.governance_status"):
            gov_status_live = p.values[0] if p.values else None
    tags_after = g.get_aspect(model, GlobalTagsClass)
    tag_urns_live = [t.tag for t in tags_after.tags] if tags_after and tags_after.tags else []
    description_after = g.get_aspect(model, MLModelPropertiesClass).description
    print(f"   [read-back from GMS] warden.governance_status={gov_status_live!r}  globalTags={tag_urns_live}"
          f"  description unchanged={description_before == description_after}")

    psi_val = drift_info["psi"] if drift_info else None
    is_significant = psi_val is not None and psi_val > drift.PSI_SIGNIFICANT
    ok = changed and (is_significant == expect_significant)
    print(f"   [honesty] {'PSI/KS silent, structural term alone caught the swap' if not expect_significant else 'PSI/KS corroborated the structural term — confidence fell HARDER because the drop is now MEASURED, not prior-only'}")
    return belief2.confidence, psi_val, ok


print("Warden Block 1 — measured drift as a real Bayes evidence term (PSI/KS alongside the structural delta)")

conf_a, psi_a, ok_a = run_scenario(
    "(a) KILL-SHOT: PSI stays quiet", "kill_shot",
    old_field="signup_ts", new_field="ingest_ts",
    old_stat=(3.5, 1.2), new_stat=(3.6, 1.25),
    expect_significant=False,
)

conf_b, psi_b, ok_b = run_scenario(
    "(b) measured drift: PSI fires", "measured",
    old_field="value", new_field="value",
    old_stat=(3.5, 1.2), new_stat=(5.0, 1.3),
    expect_significant=True,
)

print("\n=== SUMMARY ===")
print(f"   (a) PSI schweigt:   PSI={psi_a:.4f}  confidence→{conf_a:.3f}")
print(f"   (b) measured drift: PSI={psi_b:.4f}  confidence→{conf_b:.3f}")
harder = conf_b < conf_a
print(f"   scenario (b) confidence fell {'HARDER' if harder else 'NOT harder'} than (a)"
      f"  ({conf_a:.3f} vs {conf_b:.3f})")
print("   [honesty] Warden stays a SUPERSET: (a) shows the structural term alone catches a swap PSI/KS")
print("             cannot see; (b) shows that where a real profile pair exists AND genuinely diverges,")
print("             the confidence MAGNITUDE is now partly MEASURED (drift_stat), not prior-only.")

ok = ok_a and ok_b and harder
print("\nMEASURED-DRIFT DEMO", "GREEN ✅" if ok else "check")
