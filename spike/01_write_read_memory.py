#!/usr/bin/env python3
"""
PROOF A — define a Mnemo structured property, write it onto a sample dataset, read it back.
If this round-trips, the custom-PDL-aspect GMS rebuild is OFF the critical path forever.

✅ Signatures below are SOURCE-VERIFIED against datahub metadata-ingestion examples
   (structured_property_create_basic.py, dataset_add_structured_properties_patch.py,
   structured_property_query.py). See scratchpad/audit_source.md.

Run:
    python 01_write_read_memory.py
"""
import os

from dotenv import load_dotenv

import time

from datahub.api.entities.structuredproperties.structuredproperties import StructuredProperties
from datahub.emitter.mce_builder import make_dataset_urn
from datahub.emitter.mcp import MetadataChangeProposalWrapper
from datahub.ingestion.graph.client import DataHubGraph, DataHubGraphConfig
from datahub.metadata.schema_classes import (
    StructuredPropertiesClass,
    StructuredPropertyValueAssignmentClass,
)

load_dotenv()

g = DataHubGraph(
    DataHubGraphConfig(
        server=os.getenv("DATAHUB_GMS_URL", "http://localhost:8080"),
        token=os.getenv("DATAHUB_GMS_TOKEN"),
    )
)

# A sample dataset from `datahub docker ingest-sample-data` (confirm via UI search).
TARGET = make_dataset_urn(platform="hive", name="fct_users_created", env="PROD")


def define_properties() -> None:
    """Emit MCPs against the built-in `structuredProperty` entity — NO GMS rebuild."""
    defs = [
        StructuredProperties(id="mnemo.summary", qualified_name="mnemo.summary",
                             display_name="Mnemo Summary", type="string",
                             cardinality="SINGLE", entity_types=["dataset"]),
        StructuredProperties(id="mnemo.confidence", qualified_name="mnemo.confidence",
                             display_name="Mnemo Confidence", type="number",
                             cardinality="SINGLE", entity_types=["dataset"]),
    ]
    for prop in defs:
        for mcp in prop.generate_mcps():
            g.emit(mcp)
    print("[define] mnemo.summary + mnemo.confidence defined")


def write_memory() -> None:
    # VERIFIED on DataHub v1.5/CLI 1.6 (2026-07-24): direct-aspect emit works;
    # DatasetPatchBuilder.add_structured_property threw 500 "no mapping" — use this instead.
    time.sleep(3)  # let the property definition index before attaching values
    aspect = StructuredPropertiesClass(properties=[
        StructuredPropertyValueAssignmentClass(
            propertyUrn="urn:li:structuredProperty:mnemo.summary",
            values=["User-creation fact table. Grounds signup analytics."]),
        StructuredPropertyValueAssignmentClass(
            propertyUrn="urn:li:structuredProperty:mnemo.confidence", values=[0.6]),
    ])
    g.emit(MetadataChangeProposalWrapper(entityUrn=TARGET, aspect=aspect))
    print(f"[write] memory (confidence 0.6) written onto {TARGET}")


def read_memory() -> None:
    sp = g.get_aspect(TARGET, StructuredPropertiesClass)
    props = sp.properties if sp else []
    print("[read] structured properties on entity:")
    for p in props:
        print(f"    {p.propertyUrn} = {p.values}")
    ok = any("mnemo.confidence" in p.propertyUrn for p in props)
    print(f"\nPROOF A {'GREEN ✅' if ok else 'RED ❌ — check ENABLE_STRUCTURED_PROPERTIES / PAT'}")


if __name__ == "__main__":
    define_properties()
    write_memory()
    read_memory()
