# OSS Contribution Plan — DataHub Hackathon Bonus (Criterion-1 depth proof)

> Goal: the single **most-mergeable** open-source contribution to DataHub, doable by a solo
> builder and **review-ready before 2026-08-10**, that is clearly *ours-but-upstreamable*.
> Every claim below is grounded in the live repo layout (audited 2026-07-24).

---

## Decision — RECOMMENDED contribution

**A small `docs:` PR to `datahub-project/datahub-skills`** that closes a real, objective gap in
the **`datahub-enrich`** skill's structured-properties documentation, and adds the
**"agent memory + confidence via structured properties"** write-back pattern as a reusable reference.

This is the exact pattern Warden is built on (define a typed property like `warden.confidence` /
`warden.provenance` → write it programmatically as an agent → read it back), generalized so it is
upstream-useful for any agent, not Warden-specific.

### The objective gap (why a reviewer can't say "no")
`skills/datahub-enrich/references/mutation-reference.md` §"Structured Properties" documents only
`upsertStructuredProperties` and `removeStructuredProperties` — i.e. how to **set values** on a
property. It never documents how to **define/create** the property itself. You cannot upsert a value
to a structured property that does not exist. The missing step is:
- GraphQL mutation **`createStructuredProperty`** (verified real — DataHub docs), and
- CLI **`datahub properties upsert -f <yaml>`** (verified real — DataHub docs).

The `datahub-enrich` SKILL.md already declares `allowed-tools: Bash(datahub *)`, so both commands
are already in-scope for the skill — the PR only documents what the skill can already run.

### Why this over the alternatives
| Option | Merge-before-08-10 odds | Judge signal | Verdict |
|---|---|---|---|
| **This docs PR (create-step + agent write-back reference)** | **High** | High (it *is* our moat, upstreamed) | ✅ **RECOMMEND** |
| New full `datahub-memory` skill | Low — 16–35 KB SKILL.md + tests + marketplace reg, scope negotiation with maintainers | Highest | Stretch only (see below) |
| Abstract RFC "agent memory via structured properties" | Low — skills repo is not the RFC venue; RFCs live in `datahub-project/datahub` and take months | Medium | ❌ Too slow |
| Implement missing `datahub-audit` skill (open issue #24) | Low — large new skill | Medium | ❌ Too big |

---

## Repo facts (audited live, 2026-07-24)
- **Repo:** `github.com/datahub-project/datahub-skills` — Apache-2.0, 34★, 29 forks, pushed 2026-07-23, `has_issues`, `default_branch: main`. Mission (repo description): *"LLM Agent skills for working with DataHub, search, enrich, quality, build connectors."*
- **Skill layout** (verified from `datahub-enrich`): each skill = a dir under `skills/` containing `SKILL.md` (YAML frontmatter: `name`, `description`, `user-invocable`, `min-cli-version`, `allowed-tools`), a short `README.md`, and optional `references/` + `templates/` dirs.
- **Contribution rules** (`CONTRIBUTING.md`): pre-commit hooks = `prettier` + `markdownlint-cli2` + `ruff` + basic file checks; **Conventional Commits enforced on PR title by CI** (`Lint PR Title`). `docs:` = no release; `feat:` = minor bump. Release Please owns versioning — **do NOT hand-edit `plugin.json`, `marketplace.json`, `CHANGELOG.md`, or tags.**
- **Precedent for this exact shape:** merged PRs **#46** (`docs: remove ... from code examples`), **#27** (`docs: add Document / Knowledge-Base Sources archetype`), **#2** (`docs:`) — small reference/markdown edits merge routinely.
- **A new reference file needs NO manifest changes** — `marketplace.json`/`plugin.json` register *plugins/skills*, not reference files. (A whole new *skill* would need more; a reference does not.)

---

## Exact files to touch (3, all under `skills/datahub-enrich/`)
1. **`references/mutation-reference.md`** — extend the existing `## Structured Properties` section:
   add a "Define a structured property (do this first)" block with `createStructuredProperty`
   (GraphQL) and `datahub properties upsert -f property.yaml` (CLI), above the existing value-upsert
   examples. Add a one-line link to the new reference (#2).
2. **`references/agent-structured-properties.md`** — **NEW** (~60–90 lines). The reusable pattern:
   *define typed property → write value programmatically (agent) → read back*. Worked example uses
   an agent writing a `confidence` (NUMBER) + `provenance` (STRING, multi-value) + `summary` property
   back onto a dataset — generic wording, no Warden branding. Include the round-trip read
   (`datahub graphql` query of `structuredProperties`) so an agent can verify its own write.
3. **`SKILL.md`** — one pointer line in the structured-properties row / references list pointing to
   `references/agent-structured-properties.md`. No frontmatter change.

No code, no tests required (docs-only). Markdown-only diff → passes prettier/markdownlint/ruff cleanly.

---

## PR title (CI-enforced Conventional Commits)
```
docs: document defining structured properties + agent write-back pattern in datahub-enrich
```
(`docs:` = no version bump → zero release-mechanics risk, the safest prefix.)

## PR description draft
```
## What

The datahub-enrich structured-properties reference documents how to *set values*
(upsertStructuredProperties) but never how to *define* a structured property. You can't
upsert a value to a property that doesn't exist yet. This adds the missing definition step
and a short reference for the programmatic agent write-back pattern.

## Changes
- references/mutation-reference.md — add "Define a structured property" (createStructuredProperty
  GraphQL + `datahub properties upsert -f` CLI) ahead of the existing value-upsert examples.
- references/agent-structured-properties.md (new) — the reusable pattern for an agent that writes
  typed metadata back onto an asset: define property -> write value -> read back to verify.
  Worked example: an agent recording a confidence score + provenance + summary on a dataset.
- SKILL.md — one pointer line to the new reference.

## Why

datahub-skills is explicitly "LLM Agent skills for working with DataHub." Agents that enrich the
graph increasingly need to write *typed, machine-readable* metadata (scores, provenance, state)
rather than free-text descriptions — structured properties are the right primitive, and the
define-then-write round-trip wasn't documented. This makes that a first-class, copy-pasteable path.

Docs-only. No new skill, no manifest/version changes. `datahub-enrich` already declares
`allowed-tools: Bash(datahub *)`, so both commands are in-scope for the skill.
```

---

## 5-step open-it checklist
1. **Fork & branch:** `gh repo fork datahub-project/datahub-skills --clone`; `git checkout -b docs/structured-property-agent-writeback`.
2. **Set up hooks & edit:** `pip install pre-commit && pre-commit install`; make the 3 edits above (new reference + mutation-reference block + SKILL.md pointer line). Keep example wording generic (no "Warden").
3. **Lint locally (must pass CI):** `pre-commit run --all-files` (prettier + markdownlint-cli2 + ruff); fix any formatting the hooks rewrite.
4. **Commit & push:** commit with the `docs:` title above (PR title == squash message); `git push -u origin docs/structured-property-agent-writeback`.
5. **Open PR:** `gh pr create --repo datahub-project/datahub-skills` using the title + body-file above (put the body in a temp file to avoid backtick/`$` shell issues); confirm the `Lint PR Title` and lint checks go green; respond to review. Link the PR in the hackathon submission as the OSS-bonus artifact.

## Stretch (only if the docs PR merges fast, ≥1 week of buffer)
Open a follow-up `feat:` PR proposing a dedicated **`datahub-memory`** skill (agent memory pattern
as a first-class skill). Higher judge signal, but 16–35 KB SKILL.md + a `tests/test-*.sh` + possibly
maintainer scope discussion — do NOT put this on the critical path before 08-10.

## Sources
- `github.com/datahub-project/datahub-skills` — repo metadata, `skills/` tree, `skills/datahub-enrich/{SKILL.md,README.md,references/mutation-reference.md}`, `CONTRIBUTING.md`, `.claude-plugin/{plugin.json,marketplace.json}`, open issues (#24), merged PRs (#2, #27, #46) — audited via GitHub API 2026-07-24.
- DataHub docs — Structured Properties tutorial: confirms `createStructuredProperty` (GraphQL), `upsertStructuredProperties` (values), and `datahub properties upsert -f <yaml>` (CLI). https://docs.datahub.com/docs/api/tutorials/structured-properties
- `/root/hackathons/datahub-agent/ARCHITECTURE.md` §6 (OSS ranking) + §4 (source-verified structured-property write path).
