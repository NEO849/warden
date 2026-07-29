#!/usr/bin/env python3
"""VERIFY step 2b — re-fire the wake trigger with a fresh tag value (the previous tag
value is already present, so re-emitting the identical GlobalTags aspect would be a
no-op diff and might not generate a new TAG ADD event)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"))

from datahub.emitter.mcp import MetadataChangeProposalWrapper as MCP
from datahub.ingestion.graph.client import DataHubGraph, DataHubGraphConfig
from datahub.metadata.schema_classes import GlobalTagsClass, TagAssociationClass

g = DataHubGraph(DataHubGraphConfig(
    server=os.getenv("DATAHUB_GMS_URL", "http://localhost:8090"),
    token=os.getenv("DATAHUB_GMS_TOKEN") or None,
))
WAKE_MODEL = "urn:li:mlModel:(urn:li:dataPlatform:mlflow,warden_wake_verify_model,PROD)"
g.emit(MCP(entityUrn=WAKE_MODEL, aspect=GlobalTagsClass(tags=[TagAssociationClass(tag="urn:li:tag:warden_wake_trigger_2")])))
print("re-fired wake trigger (tag swap) on", WAKE_MODEL)
