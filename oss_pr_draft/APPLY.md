# OSS PR draft — low-risk `docs:` package (from `OSS_PR_PLAN.md`)

This is the **docs-only** contribution to `datahub-project/datahub-skills` recommended in
`OSS_PR_PLAN.md`: it extends the existing `datahub-enrich` skill's structured-properties reference
with the missing "define the property before you can write to it" step, plus a short reusable
reference for the agent write-back pattern (define → write → read-back) that Warden itself relies on.
Generic wording throughout — no Warden branding in the content.

**Nothing here has been sent anywhere.** No fork, no branch, no push, no PR opened. Everything below
is a plan for the user to execute with their own GitHub identity, per the repo's outward-facing-action
convention.

## Files in this folder

- `PR_TITLE.txt` — the PR title (Conventional-Commits-enforced by this repo's CI; `docs:` prefix ==
  no version bump == lowest-risk category).
- `PR_BODY.md` — the PR description, for `gh pr create --body-file` (never pasted inline in a shell
  command — avoids backtick/`$` injection into a live shell).
- `doc_content/agent-structured-properties.md` — the complete content of the **new** reference file
  this PR adds, ready to copy in as-is.
- `doc_content/PATCH_mutation-reference.md` — the exact insertion block for the **existing**
  `references/mutation-reference.md`, with precise placement instructions (this PR only inserts,
  never removes/reorders existing content).
- `doc_content/PATCH_SKILL.md` — the one-row addition to `SKILL.md`'s reference-documents table.

## Note: a second, more ambitious PR package also exists

`/root/hackathons/datahub-agent/oss_pr/` contains a separate, already-further-along package: a full
new `feat:` skill (`datahub-agent-memory`) rather than a docs patch to an existing skill — higher
judge signal, higher merge-risk/review-time, already locally verified (ruff/markdownlint/prettier
clean, live-tested against a local GMS). This folder (`oss_pr_draft/`) is the smaller, safer sibling
described in `OSS_PR_PLAN.md`; pick whichever fits the time budget before 2026-08-10 — they are not
mutually exclusive, but only one is likely worth the review-latency risk this close to deadline.

## 5-step open-it checklist (unchanged from `OSS_PR_PLAN.md`)

1. **Fork & branch**

   ```bash
   gh repo fork datahub-project/datahub-skills --clone
   cd datahub-skills
   git checkout -b docs/structured-property-agent-writeback
   ```

2. **Apply the three edits** (all under `skills/datahub-enrich/`):
   - Copy `doc_content/agent-structured-properties.md` in as
     `references/agent-structured-properties.md` (new file, verbatim).
   - Apply `doc_content/PATCH_mutation-reference.md`'s insertion block into
     `references/mutation-reference.md` at the documented location.
   - Apply `doc_content/PATCH_SKILL.md`'s one-row addition to `SKILL.md`'s reference table.
   - Keep wording generic — no "Warden" anywhere in the applied content (already true above).

3. **Lint locally (must pass CI)**

   ```bash
   pip install pre-commit && pre-commit install
   pre-commit run --all-files      # prettier + markdownlint-cli2 + ruff
   ```

   Fix anything the hooks rewrite, then re-stage.

4. **Commit & push** (PR title == squash commit message; Conventional Commits enforced on PR title)

   ```bash
   git add skills/datahub-enrich
   git commit -m "$(cat PR_TITLE.txt)"
   git push -u origin docs/structured-property-agent-writeback
   ```

5. **Open the PR**

   ```bash
   gh pr create --repo datahub-project/datahub-skills \
     --title "$(cat PR_TITLE.txt)" \
     --body-file PR_BODY.md
   ```

   Confirm the `Lint PR Title` and lint checks go green. Link the PR URL in the hackathon submission
   as the OSS-bonus artifact.

Do NOT hand-edit `plugin.json`, `marketplace.json`, or `CHANGELOG.md` — Release Please owns those,
and a `docs:` change needs none of them.
