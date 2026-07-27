# OSS PR — ready-to-apply package

Everything for the datahub-skills bonus PR is prepared here. You do the git/GitHub steps (outward-facing
— your GitHub identity). No Mnemo branding in any of the content (generic, upstream-useful).

## Files in this folder
- `agent-structured-properties.md` — the NEW reference file (drop into `skills/datahub-enrich/references/`)
- `INSERT_mutation-reference.md` — the block to insert into the existing `mutation-reference.md` (exact location inside)
- `INSERT_SKILL.md` — the one table row to add to `SKILL.md`
- `PR_BODY.md` — the PR description (use with `--body-file`, avoids shell backtick/`$` issues)

## ⚠️ Verify before opening (protects the PR from a bounce)
- The **CLI path** `datahub properties upsert -f property.yaml` is verified (our spike used the equivalent SDK path successfully).
- The **GraphQL `createStructuredProperty`** input field names (`valueType`, `entityTypes`, `cardinality`) are written from the DataHub docs but **were not run live** — test both commands against a local DataHub (`datahub docker quickstart`, GMS :8090) before you open the PR. Adjust field names if your version differs.

## 5-step open-it checklist
1. **Fork & branch**
   ```
   gh repo fork datahub-project/datahub-skills --clone
   cd datahub-skills
   git checkout -b docs/structured-property-agent-writeback
   ```
2. **Apply the 3 edits**
   - Copy `agent-structured-properties.md` → `skills/datahub-enrich/references/agent-structured-properties.md`
   - Open `skills/datahub-enrich/references/mutation-reference.md`, insert the block per `INSERT_mutation-reference.md` (after `## Structured Properties`, line ~270)
   - Open `skills/datahub-enrich/SKILL.md`, add the table row per `INSERT_SKILL.md`
3. **Lint locally (must pass CI)**
   ```
   pip install pre-commit && pre-commit install
   pre-commit run --all-files      # prettier + markdownlint-cli2 + ruff; fix anything it rewrites
   ```
4. **Commit & push** (PR title == squash message; Conventional Commits enforced)
   ```
   git add -A
   git commit -m "docs: document defining structured properties + agent write-back pattern in datahub-enrich"
   git push -u origin docs/structured-property-agent-writeback
   ```
5. **Open the PR**
   ```
   gh pr create --repo datahub-project/datahub-skills \
     --title "docs: document defining structured properties + agent write-back pattern in datahub-enrich" \
     --body-file oss_pr/PR_BODY.md
   ```
   Confirm the `Lint PR Title` + lint checks go green. Link the PR URL in the Devpost submission as the OSS-bonus artifact.

Do NOT hand-edit `plugin.json`, `marketplace.json`, `CHANGELOG.md`, or tags — Release Please owns those (a docs PR needs none of them).
