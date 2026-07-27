## What

The datahub-enrich structured-properties reference documents how to set values
(upsertStructuredProperties) but never how to define a structured property. You cannot upsert a
value to a property that does not exist yet. This adds the missing definition step and a short
reference for the programmatic agent write-back pattern.

## Changes

- references/mutation-reference.md — add a "Define a structured property" block
  (createStructuredProperty GraphQL and datahub properties upsert -f CLI) ahead of the existing
  value-upsert examples.
- references/agent-structured-properties.md (new) — the reusable pattern for an agent that writes
  typed metadata back onto an asset: define property, write value, read back to verify. Worked
  example: an agent recording a confidence score, provenance, and summary on a dataset.
- SKILL.md — one pointer row to the new reference in the Reference Documents table.

## Why

datahub-skills is explicitly "LLM Agent skills for working with DataHub." Agents that enrich the
graph increasingly need to write typed, machine-readable metadata (scores, provenance, state)
rather than free-text descriptions — structured properties are the right primitive, and the
define-then-write round-trip was not documented. This makes that a first-class, copy-pasteable path.

Docs-only. No new skill, no manifest or version changes. datahub-enrich already declares
allowed-tools Bash(datahub *), so both commands are in-scope for the skill.
