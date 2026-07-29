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
from datahub.ingestion.graph.openapi import RelationshipDirection
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

# --- G2: reverse-lineage auto-watch --------------------------------------------------------
# Relationship names EMPIRICALLY CONFIRMED against a live GMS via
# GET /openapi/relationships/v1/?urn=...&direction=...&relationshipTypes=... (not assumed from
# the PDL source, which isn't shipped in the installed package):
#   Dataset  <--DerivedFrom-- MLFeature      (MLFeatureProperties.sources points AT the dataset)
#   MLFeature <--Consumes--   MLModel        (MLModelProperties.mlFeatures points AT the feature)
# i.e. querying INCOMING relationships FROM the dataset/feature URN walks the edge backwards —
# exactly the "which model depends on this" direction mnemo/reader.py's forward walk doesn't give.
_DATASET_TO_FEATURE_REL = "DerivedFrom"
_FEATURE_TO_MODEL_REL = "Consumes"
_MAX_REVERSE_LINEAGE_MODELS = 25


def _reverse_lineage_models(graph: DataHubGraph, dataset_urn: str,
                            max_models: int = _MAX_REVERSE_LINEAGE_MODELS) -> List[str]:
    """Dataset -> (reverse) MLFeature -> (reverse) MLModel: which model(s) autonomously found to
    depend on `dataset_urn` via a feature, using GMS's live relationships API — the autonomy move,
    letting the wake find its own targets instead of relying purely on the static watch_models
    config. De-duplicated, capped at `max_models`. Best-effort and NEVER raises: any failure
    (relationship API hiccup, SDK surface change, empty result) returns [] and the caller (act(),
    below) falls back to the static watch_models list — this is purely additive, never a hard
    dependency for the wake to keep functioning."""
    try:
        feature_urns = [
            r.urn for r in graph.get_related_entities(
                dataset_urn, relationship_types=[_DATASET_TO_FEATURE_REL],
                direction=RelationshipDirection.INCOMING,
            )
            if r.urn.startswith("urn:li:mlFeature:")
        ]
        models: List[str] = []
        seen = set()
        for feat_urn in feature_urns:
            for r in graph.get_related_entities(
                feat_urn, relationship_types=[_FEATURE_TO_MODEL_REL],
                direction=RelationshipDirection.INCOMING,
            ):
                if r.urn.startswith("urn:li:mlModel:") and r.urn not in seen:
                    seen.add(r.urn)
                    models.append(r.urn)
                    if len(models) >= max_models:
                        return models
        return models
    except Exception:
        logger.exception("MNEMO WAKE: reverse-lineage resolution failed for dataset %s", dataset_urn)
        return []


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

        entity_type = getattr(e, "entityType", None)
        entity_urn = getattr(e, "entityUrn", None)

        # G2: if the event landed on a DATASET, try to autonomously resolve which mlModel(s)
        # depend on it (reverse lineage) instead of only re-checking the static watch_models
        # config. Static list is the guaranteed fallback whenever the dynamic resolution comes
        # back empty (no dependents, API hiccup, or a non-dataset event) — see _reverse_lineage_
        # models's docstring.
        resolved_dynamically = False
        if entity_type == "dataset" and entity_urn:
            dynamic_models = _reverse_lineage_models(self.agent.g, entity_urn)
            if dynamic_models:
                target_models, resolved_dynamically = dynamic_models, True
            else:
                target_models = self.watch_models
        else:
            target_models = self.watch_models

        resolution_source = "reverse-lineage" if resolved_dynamically else "static-watchlist"
        # NOTE: logger.info here is routinely swallowed by the `datahub actions` CLI's own
        # logging config (verified empirically: even the original code's per-event INFO line
        # never once appears in wake_service.err.log across thousands of lines — only WARNING+
        # from this logger ever surfaces). So the resolution source is ALSO folded into the
        # WARNING result line below (via=...), which is always visible, rather than relying on
        # this line alone. AND (below, check_model_inputs(..., via=resolution_source)) into the
        # "schema" provenance entry itself — a DURABLE on-graph witness (mnemo.provenance) that
        # survives a wake_service.err.log rotation/reset, not just a log line.
        logger.info(
            "MNEMO WAKE ▶ event=%s/%s entityType=%s urn=%s (watching %d model(s), resolved via %s)",
            category, getattr(e, "operation", None), entity_type, entity_urn,
            len(target_models), resolution_source,
        )

        for model_urn in target_models:
            try:
                changed, remembered, now, belief, drift_info = self.agent.check_model_inputs(
                    model_urn, via=resolution_source)
            except Exception:
                logger.exception("MNEMO WAKE: check_model_inputs failed for %s", model_urn)
                continue

            drift_note = (
                f" drift_psi={drift_info['psi']:.3f} field={drift_info['field']}"
                if drift_info else ""
            )

            if not changed:
                logger.info(
                    "MNEMO WAKE RESULT model=%s changed=%s confidence=%.3f governance=%s",
                    model_urn, changed, belief.confidence, self.agent.govern(belief),
                )
                continue

            # G1 (load-bearing fix): ACTUATE the governance verdict — was log-only before. This
            # is what makes the write real: mnemo.governance_status + the mnemo-needs-review tag
            # + the mnemo.finding context-document all land on the graph (see
            # mnemo/agent.py::actuate_governance), which is what console/app.py and
            # interop_demo.py actually read.
            ctx: dict = {}
            if drift_info is not None:
                # _measured_drift already pins down the exact swapped pair + measured PSI.
                ctx = {"old_source": drift_info.get("old_source"),
                       "new_source": drift_info.get("new_source"),
                       "psi": drift_info.get("psi")}
            else:
                removed = set(remembered) - set(now)
                added = set(now) - set(remembered)
                if len(removed) == 1 and len(added) == 1:
                    ctx = {"old_source": next(iter(removed)), "new_source": next(iter(added))}

            try:
                result = self.agent.actuate_governance(model_urn, belief, context=ctx)
            except Exception:
                logger.exception("MNEMO WAKE: actuate_governance failed for %s", model_urn)
                continue

            logger.warning(
                "MNEMO WAKE RESULT ⚠ model=%s changed=%s remembered=%s now=%s confidence=%.3f "
                "governance=%s tag=%s(%s) finding=%r%s (triggered by %s on %s, via=%s)",
                model_urn, changed, remembered, now, belief.confidence,
                result["governance_status"], result["tag"], result["tag_action"], result["finding"],
                drift_note, category, entity_urn, resolution_source,
            )

    def close(self) -> None:
        pass
