---
name: datahub-agent-memory
description: |
  Use this skill when an agent needs durable, per-asset state on the DataHub graph across
  repeated visits — a confidence score that survives between runs, a provenance trail of what
  evidence was seen, and a confidence-gated governance signal (trusted vs. needs-review) instead
  of a print statement nobody sees. Triggers on: "give this agent memory", "persist confidence on
  an asset", "track belief over time for this dataset/model", "flag this asset for review when
  confidence drops", "resumable agent state in DataHub", "confidence-gated auto-trust", "agent
  observes and remembers".
user-invocable: true
min-cli-version: 1.4.0
allowed-tools: Bash(datahub *), Bash(python *belief.py*), Bash(python *agent_memory.py*)
---

# DataHub Agent Memory

You are an expert in giving DataHub agents **durable, per-asset memory**: a resumable confidence
belief that survives between runs, and a confidence-gated governance policy that turns that belief
into a real, visible graph action instead of a log line. Your role is to help the user wire this
pattern into their own agent — observing evidence, persisting belief, and gating governance writes
by how much the agent actually knows.

---

## The gap this fills

Search/enrich/quality skills in this plugin act on an asset once, in one run. An agent that
**revisits the same assets repeatedly** (a lineage watcher, a data-quality bot, an enrichment
agent re-run on a schedule) needs somewhere durable to put what it learned last time — otherwise
every run starts from scratch, re-derives the same conclusions, and has no principled way to know
when to trust its own prior work versus flag something for a human.

This skill provides that missing piece: a small, pure-stdlib belief model
(`scripts/belief.py`) plus its persistence and governance actuation on the DataHub graph
(`scripts/agent_memory.py`), using ordinary structured properties and tags — no custom entity
types, no DataHub Cloud features required.

---

## Requirements

```bash
pip install acryl-datahub
```

A reachable DataHub GMS (`datahub docker quickstart` for local dev). Server resolution: `--server`
flag, then `DATAHUB_GMS_URL` env var, then `http://localhost:8090`. Optional auth via
`DATAHUB_GMS_TOKEN`.

---

## The workflow

**1. Observe** — some event fires: a scheduled scan, a detected schema/lineage delta, a user
query, a data-quality check result. Decide what evidence this represents: a `source` (e.g.
`lineage`, `schema`, `usage`, `human`), whether it `corroborates` or contradicts the agent's
current belief, its provenance `hops` from the asset, and a `quality` in `0..1`.

**2. Load prior belief** — resume the exact posterior from last time instead of starting at a
neutral prior. `agent_memory.py write` does this internally via `load_belief()`; call `read`
first if you just want to inspect what's there:

```bash
python scripts/agent_memory.py read --urn '<ENTITY_URN>' --json
```

**3. Update with evidence & 4. Persist** — fold the new evidence into the belief and write it back
in one step:

```bash
python scripts/agent_memory.py write --urn '<ENTITY_URN>' \
  --source lineage --hops 0 --quality 0.9 \
  --summary "orders table, lineage confirmed" --event-id obs_2026_07_28
```

Add `--contradicts` for evidence that undermines rather than supports the current belief. Run
`write` once per piece of evidence — the belief accumulates across calls (see
`references/confidence-model.md` for the log-odds math).

**5. Confidence-gated governance write** — turn the belief into a visible verdict:

```bash
python scripts/agent_memory.py govern --urn '<ENTITY_URN>' --json
```

This sets `agent.status` to `TRUSTED` or `NEEDS_REVIEW`, and adds/removes the
`agent-needs-review` tag depending on whether the low confidence is from a genuine contradiction
or just not-yet-enough evidence. See `references/governance-gating.md` for the exact policy table.
It never touches the asset's own description or other owner-authored metadata — only its own
`agent.*` properties and tag.

**6. Read-back verify** — never assume a write landed; confirm it:

```bash
python scripts/agent_memory.py read --urn '<ENTITY_URN>' --json
```

**First-time setup**, once per DataHub instance (idempotent, safe to re-run):

```bash
python scripts/agent_memory.py define
```

---

## Worked example (end-to-end)

```bash
URN='urn:li:dataset:(urn:li:dataPlatform:hive,orders,PROD)'

python scripts/agent_memory.py define

python scripts/agent_memory.py write --urn "$URN" --source usage --hops 1 --quality 0.4 \
  --summary "orders table, first pass" --event-id obs_1
# -> confidence still low (weak, distant evidence)

python scripts/agent_memory.py govern --urn "$URN" --json
# -> verdict "open-proposal": agent.status=NEEDS_REVIEW, agent-needs-review tag added

python scripts/agent_memory.py write --urn "$URN" --source human --hops 0 --quality 1.0 \
  --event-id obs_2
python scripts/agent_memory.py write --urn "$URN" --source lineage --hops 0 --quality 1.0 \
  --event-id obs_3
python scripts/agent_memory.py write --urn "$URN" --source schema --hops 0 --quality 1.0 \
  --event-id obs_4
# -> enough independent corroborating evidence accumulated (confidence AND mass both clear)

python scripts/agent_memory.py govern --urn "$URN" --json
# -> verdict "auto-write": agent.status=TRUSTED, tag removed

python scripts/agent_memory.py read --urn "$URN" --json
# -> read-back confirms agent.confidence, agent.status, agent.provenance all landed
```

Run `python scripts/belief.py` on its own (no DataHub needed) to see the belief model's math in
isolation — a narrated worked example of the full arc: prior → corroborating evidence → staleness
decay → contradiction → human override.

---

## Reference Documents

| Document                                      | Covers                                                                                 |
| --------------------------------------------- | -------------------------------------------------------------------------------------- |
| `references/confidence-model.md`              | The log-odds belief math: weights, decay, Cromwell's rule, evidence-mass gating        |
| `references/structured-property-writeback.md` | Define → write → read-back pattern for typed metadata, and the full-replace merge trap |
| `references/governance-gating.md`             | The three-band verdict policy and exactly what gets written for each                   |

---

## Not this skill

| If the user wants to...                               | Use this instead   |
| ----------------------------------------------------- | ------------------ |
| A one-off metadata update (a tag, description, owner) | `/datahub-enrich`  |
| To search or discover entities                        | `/datahub-search`  |
| To trace existing lineage (not detect drift in it)    | `/datahub-lineage` |
| A generic data-quality report                         | `/datahub-quality` |

---

## Design notes worth preserving if you extend this

- **Merge-safety is not optional.** `structuredProperties` is a full-replace aspect — every writer
  in `agent_memory.py` reads the current property set before writing any subset, so a belief-only
  write never erases a governance status and vice versa. Any extension that adds its own `agent.*`
  property must follow the same read-before-write discipline.
- **The governance verdict is a pure function of the belief** (`govern_verdict(belief)`) — no
  hidden state. This makes it trivial to unit-test and to reason about ("why did this get flagged?"
  is always answerable from `agent.confidence` and `agent.mass` alone).
- **Never write owner-authored metadata.** Governance actuation only ever touches its own `agent.*`
  properties and its own tag urn. If you extend this to also update the description or ownership,
  that is a different, higher-trust operation and should not live in the same gated write.
