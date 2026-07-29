#!/usr/bin/env python3
"""
PROOF B — DataHub custom Action that fires on schema/documentation change events.
Spike: only LOGS. Later, act() wakes the Warden agent → reconcile memory → re-score → write back.

✅ SOURCE-VERIFIED against datahub-actions (action.py, event_registry.py,
   tag_propagation_action.py, EntityChangeEvent.pdl). See scratchpad/audit_source.md.

Run:
    datahub actions -c warden_action_config.yaml
Then edit a sample dataset's description/schema in the UI → watch this print.
"""
import logging

from datahub_actions.action.action import Action
from datahub_actions.event.event_envelope import EventEnvelope
from datahub_actions.event.event_registry import EntityChangeEvent
from datahub_actions.pipeline.pipeline_context import PipelineContext

logger = logging.getLogger("warden")
logging.basicConfig(level=logging.INFO)

# EntityChangeEvent categories that should wake the memory loop.
WAKE_ON = {"TECHNICAL_SCHEMA", "DOCUMENTATION", "GLOSSARY_TERM", "TAG", "OWNER"}


class WardenAction(Action):
    @classmethod
    def create(cls, config_dict: dict, ctx: PipelineContext) -> "Action":
        return cls()

    def act(self, event: EventEnvelope) -> None:
        if event.event_type != "EntityChangeEvent_v1":
            return
        e: EntityChangeEvent = event.event  # .entityUrn .category .operation .modifier .parameters
        if e.category in WAKE_ON:
            logger.info("WARDEN WAKE ▶ %s | %s/%s | %s",
                        e.entityUrn, e.category, e.operation, e.modifier)
            # DAY 7+: load prior warden.memory → reconcile with new graph → Bayesian re-score → write.

    def close(self) -> None:
        pass
