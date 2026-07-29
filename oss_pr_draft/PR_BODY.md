## What

The `datahub-enrich` skill's structured-properties reference documents how to **set values**
(`upsertStructuredProperties`) but never how to **define** a structured property in the first
place. You cannot upsert a value to a property that doesn't exist yet. This PR adds the missing
definition step, plus a short reference for the reusable "agent write-back" pattern: define a
typed property once, write a value to it programmatically, then read it back to verify the write.

## Changes

- `references/mutation-reference.md` — extends the existing `## Structured Properties` section
  with a new "Define a structured property (do this first)" block, placed above the existing
  value-upsert examples. Covers both paths: the GraphQL mutation `createStructuredProperty` and
  the CLI `datahub properties upsert -f property.yaml`. Links to the new reference below.
- `references/agent-structured-properties.md` (new) — a short, generic reference for an agent
  that writes typed metadata back onto an asset: define the property → write the value → read it
  back to confirm. Worked example: an agent recording a `confidence` (NUMBER), a `provenance`
  trail (STRING, multi-value), and a `summary` (STRING) on a dataset.
- `SKILL.md` — one pointer row in the reference-documents table linking to the new reference.
  No frontmatter change.

Docs-only diff, three files, no code and no tests. Passes `prettier` + `markdownlint-cli2` + `ruff`
with no repo-specific config changes needed.

## Why

`datahub-skills` is explicitly "LLM Agent skills for working with DataHub." Agents that enrich the
graph increasingly need to write typed, machine-readable metadata — a score, a provenance trail, a
computed state — rather than only free-text descriptions, because a typed value is queryable by the
next agent or person. Structured properties are the right primitive for this, but the
define-before-write step wasn't documented anywhere in the skill, and it's the step a first-time
reader is most likely to miss (the existing examples silently assume the property already exists).
`datahub-enrich`'s `SKILL.md` already declares `allowed-tools: Bash(datahub *)`, so both commands
this PR documents are already in-scope for the skill — this only documents what the skill can
already run.

No new skill, no manifest or version-file changes (`plugin.json` / `marketplace.json` /
`CHANGELOG.md` untouched — Release Please owns those and this change needs none of them).
