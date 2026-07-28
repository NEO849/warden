## What

Adds a new `datahub-agent-memory` skill: durable, per-asset agent state on the DataHub graph, plus
a confidence-gated governance write.

## Changes

- `skills/datahub-agent-memory/SKILL.md` — the workflow: observe → load prior belief → update with
  evidence → persist → confidence-gated governance write → read-back verify.
- `skills/datahub-agent-memory/README.md` — what it does + usage examples.
- `skills/datahub-agent-memory/scripts/belief.py` — pure-stdlib log-odds (Bayesian
  weight-of-evidence) confidence model: bounded accumulation, Cromwell's-rule clamp,
  evidence-mass gating, exponential staleness decay. Runs standalone with a narrated worked
  example (`python belief.py` or `python belief.py --json`), no DataHub or network needed.
- `skills/datahub-agent-memory/scripts/agent_memory.py` — persists that belief on a DataHub
  entity as `agent.*` structured properties (merge-safe against DataHub's full-replace
  `structuredProperties` aspect) and actuates a confidence-gated governance write: high confidence
  → `agent.status=TRUSTED`; low confidence → `agent.status=NEEDS_REVIEW` plus an
  `agent-needs-review` tag — without ever touching the entity's own editable description or other
  owner-authored metadata. CLI: `define` / `write` / `read` / `govern`.
- `skills/datahub-agent-memory/references/confidence-model.md` — the log-odds math and its
  parameters.
- `skills/datahub-agent-memory/references/structured-property-writeback.md` — the
  define → write → read-back pattern for typed metadata, and the full-replace merge trap to avoid.
- `skills/datahub-agent-memory/references/governance-gating.md` — the three-band verdict policy
  (auto-write / open-proposal / needs-review) and exactly what gets written for each.
- `skills/datahub-agent-memory/evaluations/*.json` — three evaluations covering durable
  persistence, confidence-gated review flagging, and resuming belief across runs.

## Why

`datahub-skills` currently covers search, enrich, quality, lineage, connectors, and setup — all
single-run interactions with the catalog. There is no skill for an agent that **revisits the same
assets repeatedly** (a lineage watcher, a scheduled data-quality bot, a periodic enrichment agent)
and needs somewhere durable to put what it learned last time, so it doesn't re-derive the same
conclusions from scratch on every run and has a principled way to decide when to trust its own
prior work versus flag something for a human.

This fills that gap with ordinary DataHub primitives already available in OSS — structured
properties and tags — no custom entity types, no DataHub Cloud features. The confidence model
(`belief.py`) is dependency-free and independently testable; the persistence/governance layer
(`agent_memory.py`) is a thin, explicit layer on top using the `acryl-datahub` SDK, matching the
pattern other skills in this repo already use for programmatic DataHub access.

This is a new, self-contained skill directory. It does not modify any existing skill, and it does
not touch `plugin.json`, `marketplace.json`, or `CHANGELOG.md` — the plugin auto-discovers skills
by directory.
