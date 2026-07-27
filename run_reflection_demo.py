#!/usr/bin/env python3
"""
Crown feature test: lineage-wide reflection. Build a 3-deep upstream chain, give each asset a memory,
then reflect on the model — Mnemo synthesizes an insight that lives on NO single asset, grounded in
its own accumulated memories, with a pooled confidence + evidence chain, written onto the model.

Run:  python run_reflection_demo.py   (needs DataHub up; LLM optional — uses deterministic stub)
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
    DatasetLineageTypeClass, MLFeaturePropertiesClass, MLModelPropertiesClass,
    StructuredPropertiesClass, UpstreamClass, UpstreamLineageClass,
)

from confidence_model import Belief
from mnemo.memory import MnemoMemory
from mnemo.reflection import reflect, define_reflection_property, REFLECTION_PROP
from mnemo.llm import make_reflection_llm

load_dotenv()
g = DataHubGraph(DataHubGraphConfig(server=os.getenv("DATAHUB_GMS_URL", "http://localhost:8090"),
                                    token=os.getenv("DATAHUB_GMS_TOKEN") or None))
mem = MnemoMemory(g)

dsA = make_dataset_urn("hive", "refl_dsA", "PROD")
dsB = make_dataset_urn("hive", "refl_dsB", "PROD")
dsC = make_dataset_urn("hive", "refl_dsC", "PROD")
FEAT = "urn:li:mlFeature:(refl_features,f1)"
MODEL = "urn:li:mlModel:(urn:li:dataPlatform:mlflow,refl_model,PROD)"


def seed_memory(urn, conf, note):
    b = Belief()
    # push belief to ~conf with corroborating evidence
    while b.confidence < conf:
        b.update("lineage", corroborates=True, hops=0, quality=0.8, event_id="seed")
    mem.save(urn, note, b, "seed")


print("=== seed 3-deep chain + memories ===")
mem.define_properties(); define_reflection_property(g); time.sleep(3)
g.emit(MCP(entityUrn=dsA, aspect=UpstreamLineageClass(upstreams=[UpstreamClass(dataset=dsB, type=DatasetLineageTypeClass.TRANSFORMED)])))
g.emit(MCP(entityUrn=dsB, aspect=UpstreamLineageClass(upstreams=[UpstreamClass(dataset=dsC, type=DatasetLineageTypeClass.TRANSFORMED)])))
g.emit(MCP(entityUrn=FEAT, aspect=MLFeaturePropertiesClass(description="f1", sources=[dsA])))
g.emit(MCP(entityUrn=MODEL, aspect=MLModelPropertiesClass(description="reflection test model", mlFeatures=[FEAT])))
time.sleep(1)
seed_memory(dsA, 0.9, "dsA: clean signup facts")
seed_memory(dsB, 0.85, "dsB: enriched events")
seed_memory(dsC, 0.8, "dsC: raw ingest")
time.sleep(1)

print("=== reflect on the model (real LLM synthesis via local Ollama — ~1-3 min on CPU; pass llm=None for an instant deterministic stub) ===")
rec = reflect(g, mem, MODEL, llm=make_reflection_llm())
print(json.dumps(rec, indent=2)[:900])

print("\n=== read the reflection back FROM the model on the graph ===")
sp = g.get_aspect(MODEL, StructuredPropertiesClass)
found = None
for p in (sp.properties if sp else []):
    if p.propertyUrn == REFLECTION_PROP and p.values:
        found = json.loads(p.values[0])
if found:
    ins = found["insights"][0]
    print(f"   INSIGHT: {ins['statement']}")
    print(f"   confidence {ins['confidence']} | gate {ins['gate']} | cites {len(ins['evidence_urns'])} assets")
    print("\nREFLECTION", "GREEN ✅ (graph-level insight grounded in ≥2 remembered assets, on the graph)"
          if len(ins['evidence_urns']) >= 2 else "check")
    print("   [honesty] REAL = traversal + proximity-weighted confidence pooling + guards + write-back.\n"
          "             The insight TEXT is synthesized by a local Ollama model (no API key); on any Ollama\n"
          "             error it falls back to a deterministic stub — the pipeline never depends on the LLM.")
else:
    print("   no reflection written:", rec)
