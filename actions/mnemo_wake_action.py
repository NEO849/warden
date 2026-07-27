#!/usr/bin/env python3
"""
Event-driven wake for Mnemo — the real (non-polling) trigger.

A custom DataHub Actions Action that listens on `EntityChangeEvent_v1` (the Actions
Framework's high-level, cleanly-deserializable "platform event", delivered on the
`PlatformEvent_v1` Kafka topic — NOT `MetadataChangeLog_*` / MCL). On a qualifying
category (schema/tag/owner/glossary/documentation/lifecycle change), it wakes
`MnemoAgent.check_model_inputs()` for each watched ML model instead of waiting for
the next poll cycle.

ROOT CAUSE of the original spike failure (2026-07-24, see ../spike/action.log):
the Kafka source's `schema_registry_url` defaulted to `http://localhost:8081`, which
does not exist in this quickstart — the schema registry is embedded inside GMS at
`http://<gms-host>:8080/schema-registry/api/` (env `SCHEMA_REGISTRY_TYPE=INTERNAL`).
Every poll() therefore raised `ValueDeserializationError: Connection refused` before
a single message — of ANY topic, MCL or PE — could ever be decoded. The log line
"all MCL messages will be dropped before avrogen deserialization" that the original
audit flagged as the culprit is a RED HERRING: it is the (working-as-designed)
MCL pre-deserialization optimization described in kafka_event_source.py's own
docstring, which explicitly does not affect EntityChangeEvent/PlatformEvent delivery.
Fix: point `schema_registry_url` at the GMS-embedded registry (see
mnemo_wake_config.yaml). Verified empirically by reading PlatformEvent_v1 directly
with confluent-kafka + AvroDeserializer before wiring the Actions pipeline.

Also empirically confirmed (see spike/_scan_pe_topic.py output):
  - category=TAG fires for GlobalTags changes on an EXISTING mlModel entity.
  - category=TECHNICAL_SCHEMA fires for SchemaMetadata changes on a dataset.
  - category=LIFECYCLE/CREATE fires when a brand-new entity is first created.
  - A tag/property write that ALSO creates the entity's first aspect (i.e. the
    entity did not exist before) does NOT reliably fire the corresponding
    TAG/OWNER/etc. category — only LIFECYCLE/CREATE. Wake triggers must target
    entities that already exist in the graph.
"""
import json
import logging
import os
import sys
from typing import Any, List, Optional

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from datahub.ingestion.graph.client import DataHubGraph, DataHubGraphConfig
from datahub_actions.action.action import Action
from datahub_actions.event.event_envelope import EventEnvelope
from datahub_actions.event.event_registry import ENTITY_CHANGE_EVENT_V1_TYPE
from datahub_actions.pipeline.pipeline_context import PipelineContext

from mnemo.agent import MnemoAgent

logger = logging.getLogger("mnemo.wake")
logging.basicConfig(level=logging.INFO)

# EntityChangeEvent categories that should wake the memory loop.
# SOURCE-VERIFIED (empirically, via spike/_scan_pe_topic.py) for TAG (mlModel),
# TECHNICAL_SCHEMA (dataset), LIFECYCLE (create). OWNER/GLOSSARY_TERM/DOCUMENTATION
# are the documented sibling categories of the same generator hook family — included
# on the same basis as the original spike's WAKE_ON set, not independently re-verified.
WAKE_ON = {"TECHNICAL_SCHEMA", "DOCUMENTATION", "GLOSSARY_TERM", "TAG", "OWNER", "LIFECYCLE"}


def _parse_watch_models(raw: Any) -> List[str]:
    """Accepts a YAML list, or a "|"-delimited string (NOT comma-delimited: DataHub
    URNs themselves contain commas as key-field separators, e.g.
    urn:li:mlModel:(urn:li:dataPlatform:mlflow,churn_model,PROD) — splitting on "," is
    a real bug we hit and fixed during live verification, see EVENT_WAKE_STATUS.md)."""
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(u).strip() for u in raw if str(u).strip()]
    if isinstance(raw, str):
        return [u.strip() for u in raw.split("|") if u.strip()]
    return []


class MnemoWakeAction(Action):
    """Wakes MnemoAgent.check_model_inputs() for each watched model URN whenever a
    qualifying EntityChangeEvent_v1 arrives — the event-driven counterpart to the
    polling loop in mnemo/agent.py. Polling remains the shipped default; this is an
    additional, opt-in wake path (run as its own `datahub actions -c ...` process)."""

    @classmethod
    def create(cls, config_dict: dict, ctx: PipelineContext) -> "Action":
        watch_models = _parse_watch_models(config_dict.get("watch_models"))
        if not watch_models:
            logger.warning(
                "MnemoWakeAction: no watch_models configured — the action will run "
                "but will never call check_model_inputs. Set action.config.watch_models "
                "in the pipeline YAML (list or comma-separated string of model URNs)."
            )

        # Prefer the graph client the Pipeline already built (ctx.graph wraps the
        # AcrylDataHubGraph, whose .graph is the plain DataHubGraph MnemoAgent expects).
        if ctx.graph is not None:
            graph = ctx.graph.graph
        else:
            graph = DataHubGraph(DataHubGraphConfig(
                server=config_dict.get("server") or os.getenv("DATAHUB_GMS_URL", "http://localhost:8090"),
                token=os.getenv("DATAHUB_GMS_TOKEN") or None,
            ))

        return cls(graph, watch_models)

    def __init__(self, graph: DataHubGraph, watch_models: List[str]) -> None:
        self.agent = MnemoAgent(graph)
        self.watch_models = watch_models

    def act(self, event: EventEnvelope) -> None:
        if event.event_type != ENTITY_CHANGE_EVENT_V1_TYPE:
            return
        e = event.event  # EntityChangeEvent: .entityUrn .entityType .category .operation .modifier
        category = getattr(e, "category", None)
        if category not in WAKE_ON:
            return

        logger.info(
            "MNEMO WAKE ▶ event=%s/%s entityType=%s urn=%s (watching %d model(s))",
            category, getattr(e, "operation", None), getattr(e, "entityType", None),
            getattr(e, "entityUrn", None), len(self.watch_models),
        )

        for model_urn in self.watch_models:
            try:
                changed, remembered, now, belief, drift_info = self.agent.check_model_inputs(model_urn)
            except Exception:
                logger.exception("MNEMO WAKE: check_model_inputs failed for %s", model_urn)
                continue

            governance = self.agent.govern(belief)
            drift_note = (
                f" drift_psi={drift_info['psi']:.3f} field={drift_info['field']}"
                if drift_info else ""
            )
            if changed:
                logger.warning(
                    "MNEMO WAKE RESULT ⚠ model=%s changed=%s remembered=%s now=%s "
                    "confidence=%.3f governance=%s%s (triggered by %s on %s)",
                    model_urn, changed, remembered, now, belief.confidence, governance,
                    drift_note, category, getattr(e, "entityUrn", None),
                )
            else:
                logger.info(
                    "MNEMO WAKE RESULT model=%s changed=%s confidence=%.3f governance=%s",
                    model_urn, changed, belief.confidence, governance,
                )

    def close(self) -> None:
        pass
