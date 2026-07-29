#!/usr/bin/env python3
"""
Seed a realistic mini data+ML graph so the drift/target-leakage demo has real lineage to reason over:

    raw_signups (raw)  →  fct_users_created (schema, owned)  →  [features]  →  churn_model

Run:  python seed_demo_graph.py
"""
import os
import time

from dotenv import load_dotenv

from datahub.emitter.mcp import MetadataChangeProposalWrapper as MCP
from datahub.emitter.mce_builder import make_dataset_urn
from datahub.ingestion.graph.client import DataHubGraph, DataHubGraphConfig
from datahub.metadata.schema_classes import (
    AuditStampClass,
    DatasetFieldProfileClass,
    DatasetLineageTypeClass,
    DatasetProfileClass,
    HistogramClass,
    MLFeaturePropertiesClass,
    MLFeatureTablePropertiesClass,
    MLModelPropertiesClass,
    NumberTypeClass,
    OtherSchemaClass,
    OwnerClass,
    OwnershipClass,
    OwnershipTypeClass,
    SchemaFieldClass,
    SchemaFieldDataTypeClass,
    SchemaMetadataClass,
    StringTypeClass,
    UpstreamClass,
    UpstreamLineageClass,
)

from warden import drift

load_dotenv()
g = DataHubGraph(DataHubGraphConfig(
    server=os.getenv("DATAHUB_GMS_URL", "http://localhost:8090"),
    token=os.getenv("DATAHUB_GMS_TOKEN") or None,
))

RAW = make_dataset_urn("hive", "raw_signups", "PROD")
FCT = make_dataset_urn("hive", "fct_users_created", "PROD")
FCT2 = make_dataset_urn("hive", "fct_users_created_v2", "PROD")
NOW = int(time.time() * 1000)
PROFILE_BOUNDARIES = [str(b) for b in range(0, 8)]  # 8 labels -> 7 bins, seconds-since-midnight-ish buckets


def _field(path, native, t):
    return SchemaFieldClass(fieldPath=path, type=SchemaFieldDataTypeClass(type=t()),
                            nativeDataType=native)


def seed_datasets():
    # upstream raw table (minimal)
    g.emit(MCP(entityUrn=RAW, aspect=SchemaMetadataClass(
        schemaName="raw_signups", platform="urn:li:dataPlatform:hive", version=0, hash="",
        platformSchema=OtherSchemaClass(rawSchema=""),
        fields=[_field("event_json", "string", StringTypeClass)])))

    # fact table with a real schema (the columns features are built from)
    fields = [
        _field("user_id", "bigint", NumberTypeClass),
        _field("email", "string", StringTypeClass),
        _field("created_at", "timestamp", StringTypeClass),
        _field("signup_source", "string", StringTypeClass),
        _field("country", "string", StringTypeClass),
        _field("plan_tier", "string", StringTypeClass),
    ]
    g.emit(MCP(entityUrn=FCT, aspect=SchemaMetadataClass(
        schemaName="fct_users_created", platform="urn:li:dataPlatform:hive", version=0, hash="",
        platformSchema=OtherSchemaClass(rawSchema=""), fields=fields)))

    # lineage raw → fct
    g.emit(MCP(entityUrn=FCT, aspect=UpstreamLineageClass(
        upstreams=[UpstreamClass(dataset=RAW, type=DatasetLineageTypeClass.TRANSFORMED)])))

    # ownership
    g.emit(MCP(entityUrn=FCT, aspect=OwnershipClass(
        owners=[OwnerClass(owner="urn:li:corpuser:data_eng", type=OwnershipTypeClass.DATAOWNER)],
        lastModified=AuditStampClass(time=NOW, actor="urn:li:corpuser:warden"))))
    print("[seed] raw_signups → fct_users_created (schema + lineage + owner)")


def seed_ml():
    feats = {
        "days_since_signup": "num",
        "signup_source_encoded": "cat",
    }
    feat_urns = []
    for name in feats:
        u = f"urn:li:mlFeature:(user_features,{name})"
        feat_urns.append(u)
        g.emit(MCP(entityUrn=u, aspect=MLFeaturePropertiesClass(
            description=f"{name} (derived from fct_users_created)", sources=[FCT])))
    ft = "urn:li:mlFeatureTable:(urn:li:dataPlatform:feast,user_features)"
    g.emit(MCP(entityUrn=ft, aspect=MLFeatureTablePropertiesClass(
        description="user features", mlFeatures=feat_urns)))
    mdl = "urn:li:mlModel:(urn:li:dataPlatform:mlflow,churn_model,PROD)"
    g.emit(MCP(entityUrn=mdl, aspect=MLModelPropertiesClass(
        description="predicts 30-day churn", mlFeatures=feat_urns)))
    print(f"[seed] {len(feat_urns)} features → user_features → churn_model")


def seed_profiles():
    """Block 1 (measured drift): give the OLD source (fct_users_created.signup_ts) and the NEW
    source (fct_users_created_v2.ingest_ts) a real DatasetProfileClass field histogram, seeded so
    drift.py can compute a real PSI over them via warden.agent's profile-gated drift_stat term.

    Fixed seed, near-identical shape on purpose: this mirrors the run_ml_drift_demo.py hero case,
    where the column is renamed but the underlying distribution barely moves (PSI stays near the
    "stable" band) — the exact case where a PSI/KS-only monitor would stay green, and only Warden's
    STRUCTURAL source-delta term catches the silent re-point.
    """
    old_samples = drift.sample(seed=42, n=2000, mean=3.5, stdev=1.2)
    new_samples = drift.sample(seed=43, n=2000, mean=3.6, stdev=1.25)
    boundaries = [float(b) for b in PROFILE_BOUNDARIES]
    old_heights = drift.histogram(old_samples, boundaries)
    new_heights = drift.histogram(new_samples, boundaries)

    g.emit(MCP(entityUrn=FCT, aspect=DatasetProfileClass(
        timestampMillis=NOW,
        fieldProfiles=[DatasetFieldProfileClass(
            fieldPath="signup_ts",
            histogram=HistogramClass(boundaries=PROFILE_BOUNDARIES, heights=old_heights))])))
    g.emit(MCP(entityUrn=FCT2, aspect=DatasetProfileClass(
        timestampMillis=NOW,
        fieldProfiles=[DatasetFieldProfileClass(
            fieldPath="ingest_ts",
            histogram=HistogramClass(boundaries=PROFILE_BOUNDARIES, heights=new_heights))])))
    measured_psi = drift.psi(old_heights, new_heights)
    print(f"[seed] field profiles: fct_users_created.signup_ts vs fct_users_created_v2.ingest_ts "
          f"(measured PSI={measured_psi:.4f}, seed=42/43)")


if __name__ == "__main__":
    seed_datasets()
    seed_ml()
    seed_profiles()
    print("Demo graph seeded. Chain: raw_signups → fct_users_created → features → churn_model")
