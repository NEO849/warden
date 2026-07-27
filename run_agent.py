#!/usr/bin/env python3
"""
One coherent agent, one cycle: MnemoAgent observes a model, remembers its inputs, and when an upstream
source is silently re-pointed it detects the delta, re-scores, governs (opens a Proposal), and reflects.
This is the demo scripts' logic unified behind a single object.

Run:  python run_agent.py    (needs DataHub up; LLM optional via Ollama)
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
    DatasetLineageTypeClass, MLFeaturePropertiesClass, MLFeatureTablePropertiesClass,
    MLModelPropertiesClass, UpstreamClass, UpstreamLineageClass,
)

from mnemo.agent import MnemoAgent

load_dotenv()
g = DataHubGraph(DataHubGraphConfig(server=os.getenv("DATAHUB_GMS_URL", "http://localhost:8090"),
                                    token=os.getenv("DATAHUB_GMS_TOKEN") or None))
agent = MnemoAgent(g)  # llm=make_reflection_llm() to use Ollama for the reflection text

FCT = make_dataset_urn("hive", "fct_users_created", "PROD")
FCT2 = make_dataset_urn("hive", "fct_users_created_v2", "PROD")
FEAT = "urn:li:mlFeature:(user_features,days_since_signup)"
FT = "urn:li:mlFeatureTable:(urn:li:dataPlatform:feast,user_features)"
MODEL = "urn:li:mlModel:(urn:li:dataPlatform:mlflow,churn_model,PROD)"


def seed(source):
    g.emit(MCP(entityUrn=FEAT, aspect=MLFeaturePropertiesClass(description="days since signup", sources=[source])))
    g.emit(MCP(entityUrn=FT, aspect=MLFeatureTablePropertiesClass(description="user features", mlFeatures=[FEAT])))
    g.emit(MCP(entityUrn=MODEL, aspect=MLModelPropertiesClass(description="predicts 30-day churn", mlFeatures=[FEAT])))


print("1. setup + seed (feature sourced from fct_users_created)")
agent.setup(); time.sleep(3)
seed(FCT); time.sleep(1)

print("2. establish healthy model memory (fresh baseline for a reproducible demo)")
from confidence_model import Belief
baseline = Belief()
baseline.update("lineage", corroborates=True, hops=2, quality=0.9, event_id="o1")
baseline.update("lineage", corroborates=True, hops=0, quality=1.0, event_id="o2")
agent.memory.save(MODEL, json.dumps({"desc": "healthy", "input_sources": [FCT]}), baseline, "o2")
srcs = [FCT]
belief, _ = agent.memory.load(MODEL)
print(f"   confidence={belief.confidence:.3f} · governance={agent.govern(belief)} · remembered={srcs}")

print("3. silent upstream re-point (same name/description)")
seed(FCT2); time.sleep(1)

print("4. agent.check_model_inputs → detect delta, re-score, govern")
changed, remembered, now, belief2 = agent.check_model_inputs(MODEL)
print(f"   changed={changed} · confidence→{belief2.confidence:.3f} · governance={agent.govern(belief2)}")

print("5. give the new source an upstream chain + observe it (so reflection has grounding)")
RAW_A = make_dataset_urn("hive", "raw_events_a", "PROD")
RAW_B = make_dataset_urn("hive", "raw_events_b", "PROD")
g.emit(MCP(entityUrn=FCT2, aspect=UpstreamLineageClass(
    upstreams=[UpstreamClass(dataset=RAW_A, type=DatasetLineageTypeClass.TRANSFORMED)])))
g.emit(MCP(entityUrn=RAW_A, aspect=UpstreamLineageClass(
    upstreams=[UpstreamClass(dataset=RAW_B, type=DatasetLineageTypeClass.TRANSFORMED)])))
time.sleep(1)
for u, c, note in [(FCT2, 0.9, "ingest-time user facts"), (RAW_A, 0.85, "enriched events"),
                   (RAW_B, 0.8, "raw event stream")]:
    b = agent.observe(u, [{"source": "lineage", "corroborates": True, "hops": 0, "quality": c,
                           "event_id": "seed"}], summary=note, event_id="seed")
time.sleep(1)

print("6. agent.reflect → lineage-wide insight grounded in accumulated memories")
rec = agent.reflect(MODEL, event="input_delta")
print("   reflection:", json.dumps(rec)[:240])

ok = changed and belief2.confidence < 0.7 and agent.govern(belief2) == "open-proposal"
print("\nAGENT CYCLE", "GREEN ✅ (observe→remember→detect→re-score→govern→reflect, one object)" if ok else "check")
