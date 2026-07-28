# Superseded

These three files were the original docs-only PR plan (a small addition to the existing
`datahub-enrich` skill's reference docs). They are kept here for history only — **the actual PR
this repo now ships is a new skill**, `skill/datahub-agent-memory/`, which supersedes this plan:

- The define → write → read-back pattern in `agent-structured-properties.md` is generalized and
  expanded in `skill/datahub-agent-memory/references/structured-property-writeback.md`.
- `INSERT_mutation-reference.md` and `INSERT_SKILL.md` (patches against the existing
  `datahub-enrich` skill) are not applied — the new skill is a self-contained addition under
  `skills/datahub-agent-memory/` instead, requiring no edits to any existing skill's files.

Use `oss_pr/PR_BODY.md` and `oss_pr/APPLY.md` at the repo root of `oss_pr/` for the current,
active PR plan.
