# Agent Write-Back: Typed Metadata via Structured Properties

Agents that enrich DataHub increasingly need to write **typed, machine-readable** metadata back onto
assets — a confidence score, a provenance trail, a computed state — rather than only free-text
descriptions. Structured properties are the right primitive for this, because the value is typed
(NUMBER / STRING / DATE / URN) and queryable, so the next agent or person can consume it programmatically.

This reference covers the full round-trip an agent needs: **define the property → write a value →
read it back to verify**. The first step is easy to miss: you cannot upsert a value to a structured
property that has not been defined yet.

## 1. Define the property (do this first)

A structured property must exist before any value can be set on an entity. Define it once, either via
the CLI or GraphQL.

**CLI** (`datahub properties upsert -f property.yaml`):

```yaml
# property.yaml
- id: confidence
  qualified_name: my_org.confidence
  display_name: Confidence
  type: number # string | number | date | urn | rich_text
  cardinality: SINGLE # or MULTIPLE
  entity_types:
    - dataset # which entity types may carry this property
  description: Agent's confidence in this asset's derived metadata, 0-1.
```

```bash
datahub properties upsert -f property.yaml
```

**GraphQL** (`createStructuredProperty`):

```bash
datahub graphql --query 'mutation {
  createStructuredProperty(input: {
    id: "my_org.confidence",
    qualifiedName: "my_org.confidence",
    displayName: "Confidence",
    valueType: "urn:li:dataType:datahub.number",
    cardinality: SINGLE,
    entityTypes: ["urn:li:entityType:datahub.dataset"]
  }) { urn }
}' --format json
```

Defining a structured property uses the built-in `structuredProperty` entity — it does **not** require
rebuilding or redeploying DataHub.

## 2. Write the value (the agent's write-back)

Once the property exists, set values on an asset with `upsertStructuredProperties` (see the
[mutation reference](./mutation-reference.md#structured-properties)):

```bash
datahub graphql --query 'mutation {
  upsertStructuredProperties(input: {
    assetUrn: "<ENTITY_URN>",
    structuredPropertyInputs: [{
      structuredPropertyUrn: "urn:li:structuredProperty:my_org.confidence",
      values: ["0.9"]
    }]
  })
}' --format json
```

## 3. Read it back (verify the write)

An autonomous agent should confirm its own write by reading the value back:

```bash
datahub graphql --query 'query {
  dataset(urn: "<ENTITY_URN>") {
    structuredProperties {
      properties {
        structuredProperty { urn }
        values {
          ... on StringValue { stringValue }
          ... on NumberValue { numberValue }
        }
      }
    }
  }
}' --format json
```

## Worked example — an agent recording confidence + provenance + summary

An enrichment agent that assesses an asset can persist three typed signals so the next run (or the next
agent) inherits them: a `confidence` (NUMBER), a `provenance` trail (STRING, MULTIPLE), and a `summary`
(STRING). Define all three once (as in step 1, with `cardinality: MULTIPLE` for `provenance`), then on
each run write the current values:

```bash
datahub graphql --query 'mutation {
  upsertStructuredProperties(input: {
    assetUrn: "<ENTITY_URN>",
    structuredPropertyInputs: [
      { structuredPropertyUrn: "urn:li:structuredProperty:my_org.confidence", values: ["0.9"] },
      { structuredPropertyUrn: "urn:li:structuredProperty:my_org.summary",    values: ["User-creation fact table; grounds signup analytics."] },
      { structuredPropertyUrn: "urn:li:structuredProperty:my_org.provenance", values: ["event=lineage_add", "event=schema_confirm"] }
    ]
  })
}' --format json
```

Because the values are typed and queryable, a downstream agent can filter or reason over them (e.g.
"re-review assets where `my_org.confidence` < 0.7") instead of parsing free text — turning one-shot
enrichment into durable, compounding context on the graph.
