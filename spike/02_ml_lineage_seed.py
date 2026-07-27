#!/usr/bin/env python3
"""
PROOF C (verified 2026-07-24, DataHub v1.5 / CLI 1.6) — build ML lineage via SDK.
Creates dataset → feature → model lineage, which is the substrate our Production ML Agents
track reasons over (upstream change → model risk). Extend this into the real ML sample setup.

Run:  python spike/02_ml_lineage_seed.py
"""
import os

from dotenv import load_dotenv

from datahub.emitter.mcp import MetadataChangeProposalWrapper as MCP
from datahub.emitter.mce_builder import make_dataset_urn
from datahub.ingestion.graph.client import DataHubGraph, DataHubGraphConfig
from datahub.metadata.schema_classes import (
    MLFeaturePropertiesClass,
    MLFeatureTablePropertiesClass,
    MLModelPropertiesClass,
)

load_dotenv()
g = DataHubGraph(DataHubGraphConfig(
    server=os.getenv("DATAHUB_GMS_URL", "http://localhost:8090"),
    token=os.getenv("DATAHUB_GMS_TOKEN") or None,
))

DS = make_dataset_urn("hive", "fct_users_created", "PROD")
FEAT = "urn:li:mlFeature:(user_features,days_since_signup)"
FT = "urn:li:mlFeatureTable:(urn:li:dataPlatform:feast,user_features)"
MODEL = "urn:li:mlModel:(urn:li:dataPlatform:mlflow,churn_model,PROD)"


def seed() -> None:
    # feature sourced FROM dataset  → training-data lineage
    g.emit(MCP(entityUrn=FEAT, aspect=MLFeaturePropertiesClass(
        description="days since signup", sources=[DS])))
    # feature table groups the feature
    g.emit(MCP(entityUrn=FT, aspect=MLFeatureTablePropertiesClass(
        description="user features", mlFeatures=[FEAT])))
    # model uses the feature        → feature → model lineage
    g.emit(MCP(entityUrn=MODEL, aspect=MLModelPropertiesClass(
        description="churn model", mlFeatures=[FEAT])))
    print("[seed] dataset → feature → model lineage created")


def verify() -> None:
    fp = g.get_aspect(FEAT, MLFeaturePropertiesClass)
    mp = g.get_aspect(MODEL, MLModelPropertiesClass)
    print(f"[verify] feature.sources = {getattr(fp, 'sources', None)}")
    print(f"[verify] model.mlFeatures = {getattr(mp, 'mlFeatures', None)}")
    ok = fp and mp and fp.sources and DS in fp.sources
    print("PROOF C", "GREEN ✅" if ok else "RED ❌")


if __name__ == "__main__":
    seed()
    verify()
