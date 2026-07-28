# OSS PR — ready-to-apply package

Everything for the datahub-skills bonus PR is prepared here. You do the git/GitHub steps (outward-facing
— your GitHub identity). No branding from this hackathon project appears in any of the content — it's
a generic, upstream-useful skill.

## Files in this folder

- `skill/datahub-agent-memory/` — the complete new skill directory, ready to copy in as-is:
  - `SKILL.md`, `README.md`
  - `references/confidence-model.md`, `references/structured-property-writeback.md`,
    `references/governance-gating.md`
  - `scripts/belief.py`, `scripts/agent_memory.py` (both ruff-clean, both live-tested against a
    local DataHub GMS)
  - `evaluations/*.json` (3 files)
- `PR_BODY.md` — the PR description (use with `--body-file`, avoids shell backtick/`$` issues)
- `_superseded_docs_only/` — the earlier docs-only plan (a small addition to the existing
  `datahub-enrich` skill's references) that this new-skill PR replaces. Kept for history only —
  see `_superseded_docs_only/NOTE.md`. Nothing in there needs to be applied.

## Already verified locally (before you open the PR)

- `python scripts/belief.py` runs standalone, no dependencies, produces the worked-example trace.
- `python scripts/agent_memory.py define / write / read / govern` were run end-to-end against a
  local DataHub GMS (`datahub docker quickstart`, v1.5.0.6) using a dedicated test URN
  (`urn:li:dataset:(urn:li:dataPlatform:hive,agent_memory_skill_demo,PROD)`) — confirmed the full
  lifecycle: low-confidence write → `govern` sets `NEEDS_REVIEW` + adds the `agent-needs-review`
  tag → more corroborating evidence written → `govern` sets `TRUSTED` + removes the tag → read-back
  shows every `agent.*` property landed and prior belief fields were preserved across writes.
- `ruff check` and `ruff format --check` pass clean on both scripts (ruff 0.16, no project-specific
  config needed — matches this repo having no `pyproject.toml`/`ruff.toml` of its own).
- `markdownlint-cli2` (pinned to the repo's `v0.21.0`, using its exact `.markdownlint-cli2.yaml`
  rule set) and `prettier` (using the repo's `.prettierrc.yaml`) both pass clean on all 5 Markdown
  files in the new skill.

You should still re-run these yourself once the files are in place inside the real repo checkout
(step 3 below) — that's what CI actually gates on.

## 5-step open-it checklist

1. **Fork & branch**

   ```bash
   gh repo fork datahub-project/datahub-skills --clone
   cd datahub-skills
   git checkout -b feat/agent-memory-skill
   ```

2. **Copy the new skill in** (a straight directory copy, nothing to merge/patch):

   ```bash
   cp -r <this-repo>/oss_pr/skill/datahub-agent-memory skills/datahub-agent-memory
   ```

   No edits to any existing file. No `plugin.json`, `marketplace.json`, or `CHANGELOG.md` changes —
   skills are auto-discovered by directory.

3. **Lint locally (must pass CI)**

   ```bash
   pip install pre-commit && pre-commit install
   pre-commit run --all-files      # prettier + markdownlint-cli2 + ruff (check + format)
   ```

   Fix anything it rewrites, then re-stage.

4. **Commit & push** (PR title == squash commit message; Conventional Commits enforced)

   ```bash
   git add skills/datahub-agent-memory
   git commit -m "feat: add datahub-agent-memory skill"
   git push -u origin feat/agent-memory-skill
   ```

5. **Open the PR**

   ```bash
   gh pr create --repo datahub-project/datahub-skills \
     --title "feat: add datahub-agent-memory skill" \
     --body-file oss_pr/PR_BODY.md
   ```

   Confirm the `Lint PR Title` + `Lint` checks go green. Link the PR URL in the Devpost submission
   as the OSS-bonus artifact.

Do NOT hand-edit `plugin.json`, `marketplace.json`, `CHANGELOG.md`, or tags — Release Please owns
those, and a new-skill PR needs none of them (auto-discovery by directory).
