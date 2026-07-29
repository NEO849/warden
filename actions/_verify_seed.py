#!/usr/bin/env python3
"""VERIFY step 1/3 — seed an ISOLATED test lineage (warden_wake_verify namespace, never
touches the shared demo entities fct_users_created/churn_model) and establish Warden's
baseline memory of the model's healthy input set, exactly like run_agent.py beat 1-2."""
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"))

from datahub.emitter.mcp import MetadataChangeProposalWrapper as MCP
from datahub.emitter.mce_builder import make_dataset_urn
from datahub.ingestion.graph.client import DataHubGraph, DataHubGraphConfig
from datahub.metadata.schema_classes import (
    MLFeaturePropertiesClass, MLFeatureTablePropertiesClass, MLModelPropertiesClass,
)

from confidence_model import Belief
from warden.agent import WardenAgent

g = DataHubGraph(DataHubGraphConfig(
    server=os.getenv("DATAHUB_GMS_URL", "http://localhost:8090"),
    token=os.getenv("DATAHUB_GMS_TOKEN") or None,
))
agent = WardenAgent(g)

WAKE_DS = make_dataset_urn("hive", "warden_wake_verify_source", "PROD")
WAKE_FEAT = "urn:li:mlFeature:(warden_wake_verify,test_feature)"
WAKE_FT = "urn:li:mlFeatureTable:(urn:li:dataPlatform:feast,warden_wake_verify)"
WAKE_MODEL = "urn:li:mlModel:(urn:li:dataPlatform:mlflow,warden_wake_verify_model,PROD)"

print("1. seed isolated lineage: dataset -> feature -> model")
agent.setup()
g.emit(MCP(entityUrn=WAKE_FEAT, aspect=MLFeaturePropertiesClass(description="wake-test feature", sources=[WAKE_DS])))
g.emit(MCP(entityUrn=WAKE_FT, aspect=MLFeatureTablePropertiesClass(description="wake-test table", mlFeatures=[WAKE_FEAT])))
g.emit(MCP(entityUrn=WAKE_MODEL, aspect=MLModelPropertiesClass(description="wake-test model", mlFeatures=[WAKE_FEAT])))
time.sleep(2)

print("2. establish healthy baseline memory (remembered input = WAKE_DS)")
baseline = Belief()
baseline.update("lineage", corroborates=True, hops=2, quality=0.9, event_id="verify_seed1")
baseline.update("lineage", corroborates=True, hops=0, quality=1.0, event_id="verify_seed2")
agent.memory.save(WAKE_MODEL, json.dumps({"desc": "healthy (wake-test baseline)", "input_sources": [WAKE_DS]}),
                   baseline, "verify_seed2")
belief, _ = agent.memory.load(WAKE_MODEL)
print(f"   WAKE_MODEL={WAKE_MODEL}")
print(f"   confidence={belief.confidence:.3f} governance={agent.govern(belief)} remembered=[{WAKE_DS}]")
print("SEED DONE")
