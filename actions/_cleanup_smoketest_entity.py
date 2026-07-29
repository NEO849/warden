#!/usr/bin/env python3
"""Cleanup: soft-delete the stray throwaway dataset entity created during root-cause
diagnosis (spike/_smoke_emit2.py). Isolated namespace, never referenced by shared demo
entities — removed for catalog tidiness only."""
import os
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"))

from datahub.emitter.mce_builder import make_dataset_urn
from datahub.ingestion.graph.client import DataHubGraph, DataHubGraphConfig

g = DataHubGraph(DataHubGraphConfig(
    server=os.getenv("DATAHUB_GMS_URL", "http://localhost:8090"),
    token=os.getenv("DATAHUB_GMS_TOKEN") or None,
))
urn = make_dataset_urn("hive", "warden_wake_smoketest", "PROD")
g.soft_delete_entity(urn)
print("soft-deleted", urn)
