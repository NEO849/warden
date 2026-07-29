# Patch — skills/datahub-enrich/SKILL.md

In the "## Reference Documents" table (currently ~line 206–214 in the live repo — verify against
current `main`), ADD one row after the "Mutation reference" row.

Existing rows for context:

| Mutation reference    | `references/mutation-reference.md`        | GraphQL mutations per operation  |
| ---------------------- | ------------------------------------------- | ----------------------------------- |
| Bulk operations guide | `references/bulk-operations-reference.md` | Batch patterns and safety limits |

ADD this row (align the markdown columns to match the table's existing formatting):

| Agent write-back (typed) | `references/agent-structured-properties.md` | Define → write → read-back structured properties |

No YAML frontmatter change. This is the only edit to `SKILL.md`.
