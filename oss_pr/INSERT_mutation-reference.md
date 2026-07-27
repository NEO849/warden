# Edit 1 — skills/datahub-enrich/references/mutation-reference.md

INSERT the block below immediately AFTER the line `## Structured Properties` (currently line 270)
and BEFORE the existing ```bash fenced block that starts with `# Upsert structured property values`.

--------------------------------------------------------------------------------------------------
Define a structured property before setting values on it — you cannot upsert a value to a property
that does not exist. Define it once (CLI or GraphQL), then upsert values per asset. See
[Agent write-back with structured properties](./agent-structured-properties.md) for the full
define → write → read-back round-trip.

```bash
# Define a structured property (once) — GraphQL
datahub graphql --query 'mutation {
  createStructuredProperty(input: {
    id: "<PROP>",
    qualifiedName: "<PROP>",
    displayName: "<Display Name>",
    valueType: "urn:li:dataType:datahub.number",
    cardinality: SINGLE,
    entityTypes: ["urn:li:entityType:datahub.dataset"]
  }) { urn }
}' --format json

# Or define via CLI from a YAML spec
datahub properties upsert -f property.yaml
```

--------------------------------------------------------------------------------------------------

(The existing `# Upsert structured property values on an entity` and `# Remove ...` examples stay
unchanged directly below this new block.)
