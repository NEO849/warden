#!/usr/bin/env python3
"""
ML-track HERO demo: silent upstream semantic re-point caught by memory.

A feature's SOURCE table is swapped (fct_users_created → fct_users_created_v2) while its NAME and
DESCRIPTION stay identical. A schema-diff tool sees nothing. Warden remembers the prior source-set,
sees the delta, feeds it as CONTRADICTING evidence → the model's confidence drops below the
governance threshold → it opens a DataHub Proposal instead of silently trusting the model.

Run:  python run_ml_drift_demo.py   (needs DataHub up; LLM not required)
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
    GlobalTagsClass,
    MLFeaturePropertiesClass,
    MLFeatureTablePropertiesClass,
    MLModelPropertiesClass,
    NumberTypeClass,
    OtherSchemaClass,
    SchemaFieldClass,
    SchemaFieldDataTypeClass,
    SchemaMetadataClass,
    StringTypeClass,
    StructuredPropertiesClass,
)

from confidence_model import Belief
from warden.agent import WardenAgent
from warden.memory import WardenMemory

load_dotenv()
g = DataHubGraph(DataHubGraphConfig(
    server=os.getenv("DATAHUB_GMS_URL", "http://localhost:8090"),
    token=os.getenv("DATAHUB_GMS_TOKEN") or None,
))
mem = WardenMemory(g)
agent = WardenAgent(g)

FCT = make_dataset_urn("hive", "fct_users_created", "PROD")
FCT2 = make_dataset_urn("hive", "fct_users_created_v2", "PROD")
FEAT = "urn:li:mlFeature:(user_features,days_since_signup)"
FT = "urn:li:mlFeatureTable:(urn:li:dataPlatform:feast,user_features)"
MODEL = "urn:li:mlModel:(urn:li:dataPlatform:mlflow,churn_model,PROD)"


def _schema(name, fields):
    return SchemaMetadataClass(
        schemaName=name, platform="urn:li:dataPlatform:hive", version=0, hash="",
        platformSchema=OtherSchemaClass(rawSchema=""),
        fields=[SchemaFieldClass(fieldPath=f, type=SchemaFieldDataTypeClass(type=t()), nativeDataType=n)
                for f, n, t in fields])


def model_input_sources():
    mp = g.get_aspect(MODEL, MLModelPropertiesClass)
    srcs = []
    for feat in (mp.mlFeatures if mp and mp.mlFeatures else []):
        fp = g.get_aspect(feat, MLFeaturePropertiesClass)
        srcs += (fp.sources if fp and fp.sources else [])
    return sorted(set(srcs))


print("=== BEAT 1: seed graph + establish healthy model memory ===")
mem.define_properties()
time.sleep(3)
g.emit(MCP(entityUrn=FCT, aspect=_schema("fct_users_created",
      [("user_id", "bigint", NumberTypeClass), ("signup_ts", "timestamp", StringTypeClass)])))
g.emit(MCP(entityUrn=FEAT, aspect=MLFeaturePropertiesClass(description="days since signup", sources=[FCT])))
g.emit(MCP(entityUrn=FT, aspect=MLFeatureTablePropertiesClass(description="user features", mlFeatures=[FEAT])))
g.emit(MCP(entityUrn=MODEL, aspect=MLModelPropertiesClass(description="predicts 30-day churn", mlFeatures=[FEAT])))
time.sleep(1)

b = Belief()
b.update("lineage", corroborates=True, hops=2, quality=0.9, event_id="init1")
b.update("lineage", corroborates=True, hops=0, quality=1.0, event_id="init2")
remembered = model_input_sources()
mem.save(MODEL, json.dumps({"desc": "inputs healthy: days_since_signup ← fct_users_created",
                            "input_sources": remembered}), b, "init2")
print(f"   model memory established: confidence {b.confidence:.3f}, remembered sources {remembered}")
description_before = g.get_aspect(MODEL, MLModelPropertiesClass).description

print("\n=== BEAT 2: harmful change lands, looks harmless ===")
g.emit(MCP(entityUrn=FCT2, aspect=_schema("fct_users_created_v2",
      [("user_id", "bigint", NumberTypeClass), ("ingest_ts", "timestamp", StringTypeClass)])))
# re-point the feature's source — SAME name, SAME description
g.emit(MCP(entityUrn=FEAT, aspect=MLFeaturePropertiesClass(description="days since signup", sources=[FCT2])))
print("   feature 'days_since_signup' silently re-pointed fct_users_created → fct_users_created_v2")
print("   (name unchanged, description unchanged — a schema-diff sees nothing)")
time.sleep(1)

print("\n=== BEAT 3-4: Warden wakes, compares to memory, re-scores, governs ===")
b2, summary_json = mem.load(MODEL)
remembered = json.loads(summary_json)["input_sources"]
now = model_input_sources()
changed = set(now) != set(remembered)
print(f"   remembered: {remembered}")
print(f"   now:        {now}")
print(f"   source delta detected: {changed}")
if changed:
    b2.update("schema", corroborates=False, hops=0, quality=1.0, event_id="drift")
    mem.save(MODEL, json.dumps({"desc": "DRIFT: feature source re-pointed under a stable name",
                                "input_sources": now}), b2, "drift")
    print(f"   confidence {b.confidence:.3f} → {b2.confidence:.3f}")
    if b2.needs_proposal():
        result = agent.actuate_governance(MODEL, b2)
        print(f"   ⚠️  confidence {b2.confidence:.3f} < 0.70 → verdict={result['verdict']} "
              f"(OSS has no ActionRequest/Proposal entity — that's Cloud-only; this is the honest "
              f"OSS-native human gate instead)")
        print(f"   wrote warden.governance_status={result['governance_status']} + tag "
              f"{result['tag']} ({result['tag_action']}) on {MODEL}")
        print("   (a human-visible review gate — the model's own description is never touched)")
        # live read-back from the graph — proof this is a real write, not a print
        sp_after = g.get_aspect(MODEL, StructuredPropertiesClass)
        gov_status_live = None
        for p in (sp_after.properties if sp_after else []):
            if p.propertyUrn.endswith("warden.governance_status"):
                gov_status_live = p.values[0] if p.values else None
        tags_after = g.get_aspect(MODEL, GlobalTagsClass)
        tag_urns_live = [t.tag for t in tags_after.tags] if tags_after and tags_after.tags else []
        print(f"   [read-back from GMS] warden.governance_status={gov_status_live!r}  "
              f"globalTags={tag_urns_live}")
        description_after = g.get_aspect(MODEL, MLModelPropertiesClass).description
        print(f"   [description untouched] before={description_before!r} after={description_after!r} "
              f"unchanged={description_before == description_after}")
    print("\n=== BEAT 5: payoff ===")
    print("   Caught before the next training run baked the drift into prod —")
    print("   because Warden REMEMBERED the prior source. A one-shot tool cannot see a")
    print("   delta under an unchanged schema.")
    ok = b2.confidence < 0.7 and changed
    print("\nML-DRIFT DEMO", "GREEN ✅" if ok else "check")
    print("   [honesty] REAL = the source-delta detection (live lineage vs remembered source, which a "
          "schema-diff\n             cannot see). The confidence MAGNITUDE (→0.60) is set by the Bayesian "
          "priors\n             (contradicting schema evidence), not a measured drift score.")
