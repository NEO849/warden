# Event-driven wake — status: LIVE-VERIFIED ✅

Block 7 deliverable. Polling (`mnemo/agent.py` + `run_ml_drift_demo.py`) remains the
shipped default and is **unchanged**. Event-driven wake is an additional, opt-in
capability: run `datahub actions -c actions/mnemo_wake_config.yaml` as its own process
alongside the shipped demo.

## Root cause of the original spike failure

The spike (`spike/mnemo_action_config.yaml`, `spike/action.log`) logged:

```
KafkaEventSource [mnemo]: pre-deserialization filter active — all MCL messages will be
dropped before avrogen deserialization (MetadataChangeLogEvent_v1 is not present in the
EventTypeFilter)
```

The earlier audit read this as "the Kafka source drops our events." **That log line is
a red herring.** Reading `kafka_event_source.py` (installed package,
`datahub_actions/plugin/source/kafka/kafka_event_source.py:120-138`) shows it is a
documented, working-as-designed optimization that skips the expensive avrogen
`MetadataChangeLogClass.from_obj()` conversion for **MCL** messages only — its own
docstring states explicitly: *"EntityChangeEvent (ECE) events ... pre-deserialization
filtering of ECE events is not supported and ECE delivery is never affected by this
flag."* Our config already listened on the `pe` route (`PlatformEvent_v1`, carrying
`EntityChangeEvent_v1`) with an `EntityChangeEvent_v1` category filter — architecturally
correct from day one.

**The actual break:** `schema_registry_url` defaulted to `http://localhost:8081`, which
does not exist in this quickstart. `docker inspect` on `datahub-datahub-gms-quickstart-1`
shows `SCHEMA_REGISTRY_TYPE=INTERNAL` / `KAFKA_SCHEMAREGISTRY_URL=http://datahub-gms:8080/schema-registry/api/`
— the schema registry is embedded **inside GMS**, reachable from the host at
`http://localhost:8090/schema-registry/api/` (8090 is GMS's mapped port). With the wrong
URL, `confluent_kafka`'s `AvroDeserializer` throws `ValueDeserializationError: Connection
refused` on the **first** `consumer.poll()` of **any** topic — MCL or PE — before a
single message is ever decoded. That's why the spike never printed a wake, regardless of
category filter correctness.

Fix: point `schema_registry_url` at the GMS-embedded registry
(`actions/mnemo_wake_config.yaml`).

## Empirical category verification (before wiring the pipeline)

Read `PlatformEvent_v1` directly with `confluent_kafka` + `AvroDeserializer`
(`spike/_scan_pe_topic.py`, kept as a reusable diagnostic) to confirm, independent of the
Actions framework, which categories GMS actually emits:

| category | entity type | fires? |
|---|---|---|
| `TECHNICAL_SCHEMA` | dataset | ✅ (SchemaMetadata changes) |
| `TAG` | mlModel | ✅ (GlobalTags add/remove — **on an already-existing entity**) |
| `LIFECYCLE` / `CREATE` | dataset | ✅ (first-ever aspect write) |

**Important negative finding:** a tag/property write that is *also* the entity's
first-ever aspect (i.e. the entity didn't exist before) fires `LIFECYCLE/CREATE` only,
**not** the `TAG` category — the category-specific hook appears to require a prior
version to diff against. Wake triggers must target entities that already exist in the
graph. This cost one failed round-trip during verification (see below) and is now
documented in `actions/mnemo_wake_action.py`'s docstring.

## What was built

- `actions/mnemo_wake_action.py` — `MnemoWakeAction`, a DataHub Actions `Action`. On a
  qualifying `EntityChangeEvent_v1` (`TAG`/`TECHNICAL_SCHEMA`/`DOCUMENTATION`/
  `GLOSSARY_TERM`/`OWNER`/`LIFECYCLE`), calls `MnemoAgent.check_model_inputs(model_urn)`
  for each configured watched model and logs the result (changed / confidence /
  governance / measured drift). Reuses the Pipeline's own `DataHubGraph` client
  (`ctx.graph.graph`) — no separate connection.
- `actions/mnemo_wake_config.yaml` — Kafka source with the corrected
  `schema_registry_url`, `pe`-only topic route (no `mcl` route — we don't need MCL at
  all here), the category filter, and `watch_models` (defaults to the shipped demo's
  `churn_model`, overridable via `MNEMO_WATCH_MODELS` env var, `|`-delimited — **not**
  comma-delimited, see bug below).
- `spike/_scan_pe_topic.py` — kept as a standalone, reusable Kafka-level diagnostic
  (bypasses the Actions framework entirely) for future "is GMS even emitting the event I
  expect" questions.
- `actions/_verify_seed.py`, `_verify_trigger.py`, `_verify_trigger2.py` — the isolated
  live-verification scripts described below (safe to re-run; touch only the
  `mnemo_wake_verify_*` namespace).

## A real bug found and fixed during verification

`MnemoWakeAction`'s config initially split the `watch_models` string on `,`. DataHub URNs
themselves contain commas as key-field separators
(`urn:li:mlModel:(urn:li:dataPlatform:mlflow,churn_model,PROD)`), so splitting on `,`
truncated the URN at the first comma and every `check_model_inputs()` call 500'd against
a malformed GMS URL. Fixed by switching the string-form delimiter to `|`. This is exactly
the kind of failure that only surfaces under a live, real-URN test — flagging it in case
similar comma-splitting exists elsewhere in the codebase.

## LIVE VERIFY — proof

1. Seeded an **isolated** lineage (`mnemo_wake_verify_*` namespace — never touches the
   shared demo entities `fct_users_created`/`churn_model` that another parallel block is
   using for demo capture) and established Mnemo's baseline memory
   (`actions/_verify_seed.py`): confidence `0.901`, remembered input =
   `mnemo_wake_verify_source`.
2. Started the Actions consumer as its **own process** (not the DataHub stack):
   `MNEMO_WATCH_MODELS="urn:li:mlModel:(urn:li:dataPlatform:mlflow,mnemo_wake_verify_model,PROD)" datahub actions -c actions/mnemo_wake_config.yaml`
3. Silently re-pointed the feature's source (`mnemo_wake_verify_source` →
   `_source_v2`, same name/description — the exact "harmless-looking" drift the
   ML-track demo is built around) **and** fired the Kafka-visible trigger: added a tag
   to the model (`actions/_verify_trigger.py` / `_verify_trigger2.py`).
4. The running consumer, with **zero polling**, logged (verbatim,
   `actions/verify_run_SUCCESS.log`):

```
[2026-07-27 18:03:54,831] WARNING  {mnemo.wake:135} - MNEMO WAKE RESULT ⚠ model=urn:li:mlModel:(urn:li:dataPlatform:mlflow,mnemo_wake_verify_model,PROD) changed=True remembered=['urn:li:dataset:(urn:li:dataPlatform:hive,mnemo_wake_verify_source,PROD)'] now=['urn:li:dataset:(urn:li:dataPlatform:hive,mnemo_wake_verify_source_v2,PROD)'] confidence=0.600 governance=open-proposal (triggered by TAG on urn:li:mlModel:(urn:li:dataPlatform:mlflow,mnemo_wake_verify_model,PROD))
```

Confidence dropped `0.901 → 0.600` (the same magnitude as the shipped polling demo),
`governance=open-proposal` — the event **woke** the exact same detection/re-scoring/
governance logic `run_agent.py` exercises via manual polling, but triggered purely by a
Kafka `EntityChangeEvent_v1`, ~30s end-to-end from tag-write to logged result.

## Guardrails held

- **No stack restart.** Only `datahub actions -c ...` was started/stopped as an
  independent process (PIDs, never `docker restart`/`quickstart --stop`); `docker ps`
  shows all DataHub containers with unchanged "Up 3 days" uptime throughout.
- **Shared demo entities untouched** for the actual wake proof — all seed/trigger
  activity is scoped to the `mnemo_wake_verify_*` namespace. (One accidental early tag
  write landed on the shared `churn_model` during root-cause diagnosis before the
  isolated namespace was adopted; it was reverted immediately —
  `git status`/`git diff` on `mnemo/`, `run_ml_drift_demo.py`, `run_agent.py`,
  `demo_e2e.py`, `examples/`, `eval/` show no modifications from this block.)
- `run_ml_drift_demo.py`, `mnemo/agent.py`: **not modified** — polling remains the
  shipped default, event-wake is additive and opt-in.

## Known rough edges (honest, not hidden)

- The consumer logged one `MAXPOLL ... leaving group` warning during the first
  (buggy-config) run; harmless for a demo-scale run but would need
  `max.poll.interval.ms` tuning for a long-lived production deployment doing heavier
  per-event work.
- `watch_models` is a static list in the pipeline config, not a live query — a real
  deployment would resolve "which models depend on this changed dataset" via a reverse
  lineage lookup rather than a hardcoded watch-list. Out of scope for the time-box.
- Category coverage beyond `TAG`/`TECHNICAL_SCHEMA`/`LIFECYCLE` (`DOCUMENTATION`,
  `GLOSSARY_TERM`, `OWNER`) is carried over from the original spike's assumption and
  documented as such — not independently re-verified against a live event in this pass.
