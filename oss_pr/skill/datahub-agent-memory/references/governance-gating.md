# Confidence-Gated Governance: Auto-Trust vs. Needs-Review

Implemented in `scripts/agent_memory.py` (`govern_verdict()` and `actuate_governance()`). This
reference explains the policy and why it writes what it writes.

## The problem it solves

An agent that persists a confidence score is only half-useful if nothing acts on that score. The
other half is a **governance policy**: a rule that turns "confidence dropped to 0.33" into a
visible action a human (or another system) can actually see and respond to — not a line in a log
file nobody reads.

There is no `ActionRequest` / "Proposal" entity in OSS DataHub — that class of reviewable-change
object is a DataHub Cloud feature. `actuate_governance()` uses the honest OSS-native equivalent:
**a structured property plus a tag**, both owned entirely by the agent, both visible immediately
in the DataHub UI.

## The verdict: three bands

`govern_verdict(belief)` is the single source of truth for the verdict, computed purely from the
belief (see `references/confidence-model.md` for `actionable_high` / `needs_proposal`):

| Verdict         | Condition                                                       | Meaning                                                                                  |
| --------------- | --------------------------------------------------------------- | ---------------------------------------------------------------------------------------- |
| `auto-write`    | `belief.actionable_high` (confidence > 0.85 **and** mass ≥ 3.0) | Confident enough, backed by enough independent evidence, to trust without a human.       |
| `open-proposal` | `belief.needs_proposal()` (confidence < 0.7)                    | A contradiction pulled confidence low enough that a human should look.                   |
| `needs-review`  | neither of the above (mid-band)                                 | Not contradicted enough to demand review, but not confident enough to auto-trust either. |

## The actuation: what actually gets written

`actuate_governance(graph, urn, belief)` turns the verdict into two graph writes:

1. **`agent.status`** structured property — set to `TRUSTED` for `auto-write`, `NEEDS_REVIEW`
   for the other two verdicts. This is a plain, queryable field: `agent.status = NEEDS_REVIEW`
   across the catalog is a one-line query for "what needs my attention right now."
2. **The `agent-needs-review` tag** — added when the verdict is specifically `open-proposal`
   (a genuine contradiction, not just insufficient evidence yet), removed once the verdict is no
   longer `open-proposal`. The tag is the loud, catalog-browsable signal; `agent.status` is the
   queryable one. They intentionally diverge in the `needs-review` band: status says
   `NEEDS_REVIEW` (not yet trustworthy) but the tag is _not_ added (nothing is actually
   contradicted — there's just not enough evidence yet to auto-trust).

```text
verdict         agent.status     tag (agent-needs-review)
-----------     -------------    -------------------------
open-proposal   NEEDS_REVIEW     added (if not already present)
needs-review    NEEDS_REVIEW     left as-is / removed if present
auto-write      TRUSTED          removed (if present)
```

## The hard invariant: never touch owner-authored metadata

`actuate_governance()` only ever emits two aspects, both entirely its own:

- `StructuredPropertiesClass` — but only the `agent.*` properties (merge-safe, see
  `references/structured-property-writeback.md` for the full-replace trap this avoids).
- `GlobalTagsClass` — but only adding/removing its own `agent-needs-review` tag urn; every other
  tag already on the entity is preserved (`tags = list(current.tags) ...` before mutating).

It **never** writes `datasetProperties.description`, ownership, or any other field a human curator
or upstream ingestion source owns. This is deliberate: a governance layer that silently rewrites
an asset's description alongside its own bookkeeping is not a governance layer, it's a metadata
squatter. Verify this yourself — read an entity's description before and after calling `govern`
and it should come back byte-identical.

## Why gate on evidence mass, not just confidence

A single very high-quality corroborating signal (e.g. one `human` confirmation, weight 4.0) can
push `confidence` above 0.85 on its own. Requiring `mass >= N_MIN` as well means `auto-write`
additionally needs several independent pieces of evidence to have accumulated — not one lucky
signal. See the live demonstration in this skill's test run: after one `human` confirmation
confidence was already 0.98, but `govern` still returned `needs-review` (not `auto-write`) until a
second and third independent piece of evidence pushed `mass` past the threshold. This is the
concrete mechanism behind "confidence-gated", not just "confidence-triggered."

## Workflow this skill's `SKILL.md` follows

1. **Observe** — an agent event fires (a scheduled scan, a lineage change, a user query).
2. **Load prior belief** — `load_belief(graph, urn)` resumes `log_odds` / `mass` / `provenance`
   from `agent.*` structured properties already on the entity (neutral prior if none exist yet).
3. **Update with evidence** — `Belief.update(...)` folds in what was just observed.
4. **Persist** — `save_belief(...)` writes the new belief back, merge-safe on `agent.status`.
5. **Confidence-gated governance write** — `actuate_governance(...)` computes the verdict and
   writes `agent.status` + the tag.
6. **Read-back verify** — confirm the write actually landed before trusting it happened
   (`agent_memory.py read`).

See `SKILL.md` for the full command sequence.
