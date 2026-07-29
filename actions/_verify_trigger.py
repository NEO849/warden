#!/usr/bin/env python3
"""VERIFY step 2/3 — the "silent upstream re-point" (same story as run_ml_drift_demo.py
BEAT 2), then the Kafka-visible wake trigger (TAG change on the model, the category
empirically confirmed to fire EntityChangeEvent_v1 for an EXISTING mlModel). All on the
isolated warden_wake_verify_* namespace only."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"))

from datahub.emitter.mcp import MetadataChangeProposalWrapper as MCP
from datahub.emitter.mce_builder import make_dataset_urn
from datahub.ingestion.graph.client import DataHubGraph, DataHubGraphConfig
from datahub.metadata.schema_classes import GlobalTagsClass, MLFeaturePropertiesClass, TagAssociationClass

g = DataHubGraph(DataHubGraphConfig(
    server=os.getenv("DATAHUB_GMS_URL", "http://localhost:8090"),
    token=os.getenv("DATAHUB_GMS_TOKEN") or None,
))

WAKE_DS2 = make_dataset_urn("hive", "warden_wake_verify_source_v2", "PROD")
WAKE_FEAT = "urn:li:mlFeature:(warden_wake_verify,test_feature)"
WAKE_MODEL = "urn:li:mlModel:(urn:li:dataPlatform:mlflow,warden_wake_verify_model,PROD)"

print("silent re-point: feature source -> warden_wake_verify_source_v2 (same name/desc)")
g.emit(MCP(entityUrn=WAKE_FEAT, aspect=MLFeaturePropertiesClass(description="wake-test feature", sources=[WAKE_DS2])))

print("Kafka-visible wake trigger: TAG add on WAKE_MODEL")
g.emit(MCP(entityUrn=WAKE_MODEL, aspect=GlobalTagsClass(tags=[TagAssociationClass(tag="urn:li:tag:warden_wake_trigger")])))
print("done — watch actions/verify_run.log for 'WARDEN WAKE'")
