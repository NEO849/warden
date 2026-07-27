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
    DatasetLineageTypeClass,
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

load_dotenv()
g = DataHubGraph(DataHubGraphConfig(
    server=os.getenv("DATAHUB_GMS_URL", "http://localhost:8090"),
    token=os.getenv("DATAHUB_GMS_TOKEN") or None,
))

RAW = make_dataset_urn("hive", "raw_signups", "PROD")
FCT = make_dataset_urn("hive", "fct_users_created", "PROD")
NOW = int(time.time() * 1000)


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
        lastModified=AuditStampClass(time=NOW, actor="urn:li:corpuser:mnemo"))))
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


if __name__ == "__main__":
    seed_datasets()
    seed_ml()
    print("Demo graph seeded. Chain: raw_signups → fct_users_created → features → churn_model")
