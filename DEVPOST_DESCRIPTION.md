# Devpost Submission — Mnemo

*(Drop straight into the Devpost project description fields. Lead sentence is intentionally first —
Devpost and judges skim the opening line.)*

## Tagline

Compounding, governed memory for the data graph — Mnemo catches silent ML model drift under an
unchanged schema by remembering what a model's inputs used to be.

## Inspiration

Data catalogs and metadata chat agents can tell you what your graph looks like *right now* — but they
have no memory of what it looked like before, so they can't tell you *what changed*. The failure mode we
kept coming back to: a feature's upstream source table gets silently swapped for a near-identical one
(same field names, same description, different population) and every schema-diff, doc-linter, and
chat-with-your-metadata agent sees nothing wrong. That's exactly how target leakage and quiet model decay
get baked into production between two unremarkable-looking commits. A memory that persists per-asset,
**on the graph itself**, and gets compared against new evidence every time it's revisited, is the only
way to catch that class of drift.

## What it does

Mnemo is a memory agent for DataHub that:

1. **Remembers** each asset's prior belief — as typed structured properties written directly onto the
   entity (`mnemo.confidence`, `mnemo.logodds`, `mnemo.mass`, `mnemo.provenance`, `mnemo.summary`) —
   no side database, no GMS schema rebuild.
2. **Detects drift a schema-diff can't see**: it compares its remembered set of a model's upstream
   *source URNs* against the live lineage graph. In our demo, a feature's source is silently re-pointed
   from `fct_users_created` to `fct_users_created_v2` — name and description unchanged — and Mnemo
   catches the source-set delta anyway.
3. **Updates belief with a principled Bayesian model** (`confidence_model.py`, pure stdlib): evidence
   accumulates in log-odds space, discounted by lineage distance, capped against flapping, and never
   claims absolute certainty (Cromwell's rule). When the swapped sources carry distribution profiles, a
   **measured PSI/KS drift score** (`mnemo/drift.py`) is folded in as its own evidence term — so the
   confidence *magnitude* is measured, not prior-only; when the profiles are quiet, the structural
   source-delta term still fires, so Mnemo stays a **superset** of a PSI/KS drift monitor, never weaker.
4. **Gates on governance, not vibes**: when confidence drops below threshold after a contradiction, Mnemo
   opens a **DataHub Proposal** — a human approval gate — instead of silently trusting (or silently
   re-writing) the model's metadata.
5. **Reflects across lineage** (crown feature): periodically walks a model's full upstream chain,
   pools its own previously-written per-asset memories into a single graph-level insight that lives on
   **no single asset**, and writes it back onto the model with its own confidence and an evidence-URN
   citation list — guarded against weak evidence, nearby contradictions, and redundant re-writes.
6. **Synthesizes insight text with a local LLM** (Ollama, no API key/card needed), falling back to a
   deterministic stub on any LLM error so the traversal/pooling/guard/write-back pipeline is fully
   testable independent of any LLM.

## How it's different from a chat/analytics agent

The reference-style `analytics-agent` pattern (request/response chat, conversation history in a local DB,
free-text description write-back) **remembers the conversation, not the asset** — its session history lives
in a local DB, but it keeps no per-asset memory on the graph and therefore has nothing to diff a new event against. A same-name, same-description source swap is
structurally invisible to it. Mnemo's memory persists on the entity, survives across runs, and is
compared against every new piece of evidence — that's the mechanism the reference pattern cannot
replicate without becoming a different kind of system.

## How we built it

- `confidence_model.py` — Bayesian log-odds belief model, pure stdlib, runs standalone.
- `mnemo/memory.py` / `mnemo/reader.py` — persist/resume belief as DataHub structured properties;
  read schema/lineage/owners via the DataHub Python SDK graph client.
- `mnemo/reflection.py` — lineage traversal (up to 6 hops), proximity-weighted confidence pooling,
  four guard conditions, write-back onto the `MLModel` entity.
- `mnemo/llm.py` — local Ollama hook for reflection-insight text, with stub fallback.
- `run_ml_drift_demo.py` / `run_reflection_demo.py` — end-to-end, live-against-DataHub demo scripts
  that print an explicit `[honesty]` line distinguishing verified mechanism from placeholder text.
- Stack: Python 3.11, `acryl-datahub` SDK, DataHub local Docker quickstart, local Ollama.

## Challenges we ran into

- The Actions-framework event hook (`EntityChangeEvent_v1`) at first never reached our custom action. We
  traced it to a wrong `schema_registry_url` default (this quickstart embeds the registry *inside* GMS,
  not on :8081) — not the event-type filter we'd first suspected. After fixing it, **event-driven wake is
  now live-verified**: a real Kafka TAG event woke the detection, confidence 0.901→0.600, ~30s end-to-end,
  zero polling (`EVENT_WAKE_STATUS.md`). Polling remains the shipped default; event-wake is opt-in with a
  static watch-list.
- Structured-property write-back needed the direct `StructuredPropertiesClass` emit path rather than the
  patch-builder helper to round-trip cleanly against our quickstart image.
- Getting insight synthesis working without requiring judges to provision an API key — solved with a
  local-Ollama hook and a deterministic-stub fallback so the core logic is testable either way.

## Accomplishments that we're proud of

- A confidence model that is actually principled (log-odds Bayesian update, discounted by lineage
  distance, Cromwell's-rule-bounded) rather than a hand-waved 0–1 score.
- Live-verified drift detection: a source-set delta invisible to schema-diffing, caught by comparing
  live lineage against a resumed belief, with confidence crossing a governance threshold on camera.
- Lineage-wide reflection that pools multiple independently-written per-asset memories into one
  graph-level, evidence-cited insight — with real guard conditions, not just a prompt.

## What we learned

Honesty about what's built vs. planned is itself a submission-quality signal, not a liability — the repo
states plainly (in `ARCHITECTURE.md` and the README status table) exactly which pieces are live-verified
and which are work-in-progress (event-driven wake is currently a polling fallback), rather than narrating
aspirational behavior as shipped.

## What's next

- Resolve watched models dynamically via reverse lineage (the event-driven path currently uses a static
  watch-list) and broaden the empirically-verified `EntityChangeEvent` categories beyond TAG/schema/lifecycle.
- Upstream a DataHub Skill / RFC proposing "agent memory + confidence via structured properties."

## Built with

python, datahub-sdk, datahub-actions-framework, ollama, docker, bayesian-inference, structured-properties

## Try it out

Setup and exact run commands (DataHub quickstart, `.env`, `python run_ml_drift_demo.py`,
`python run_reflection_demo.py`) are in the repo [`README.md`](README.md).

## License

Apache-2.0.
