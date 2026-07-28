# Agent Write-Back: Typed Metadata via Structured Properties

Agents that revisit the same assets need somewhere to put **typed, machine-readable** state —
a confidence score, a provenance trail, a computed status — rather than only free-text
descriptions. Structured properties are the right primitive for this: the value is typed
(NUMBER / STRING / DATE / URN) and queryable, so the next agent (or person) can filter and reason
over it programmatically instead of parsing prose.

This reference covers the full round-trip: **define the property → write a value → read it back
to verify**. The first step is easy to miss — you cannot upsert a value to a structured property
that has not been defined yet.

## 1. Define the property (do this first)

A structured property must exist before any value can be set on an entity. Define it once, either
via the CLI, GraphQL, or the Python SDK.

**CLI** (`datahub properties upsert -f property.yaml`):

```yaml
# property.yaml
- id: agent.confidence
  qualified_name: agent.confidence
  display_name: Agent Confidence
  type: number # string | number | date | urn | rich_text
  cardinality: SINGLE # or MULTIPLE
  entity_types:
    - dataset # which entity types may carry this property
  description: An agent's posterior confidence in this asset's current belief, 0-1.
```

```bash
datahub properties upsert -f property.yaml
```

**GraphQL** (`createStructuredProperty`):

```bash
datahub graphql --query 'mutation {
  createStructuredProperty(input: {
    id: "agent.confidence",
    qualifiedName: "agent.confidence",
    displayName: "Agent Confidence",
    valueType: "urn:li:dataType:datahub.number",
    cardinality: SINGLE,
    entityTypes: ["urn:li:entityType:datahub.dataset"]
  }) { urn }
}' --format json
```

**Python SDK** (what `scripts/agent_memory.py` does — see `define_properties()`):

```python
from datahub.api.entities.structuredproperties.structuredproperties import StructuredProperties

sp = StructuredProperties(
    id="agent.confidence",
    qualified_name="agent.confidence",
    display_name="agent.confidence",
    type="number",
    cardinality="SINGLE",
    entity_types=["dataset", "mlModel", "mlFeature"],
)
for mcp in sp.generate_mcps():
    graph.emit(mcp)
```

Defining a structured property uses the built-in `structuredProperty` entity — it does **not**
require rebuilding or redeploying DataHub, and defining it again later is a no-op (safe to call on
every run).

## 2. Write the value (the agent's write-back)

Once the property exists, set values on an asset with `upsertStructuredProperties` (GraphQL) or by
emitting a `StructuredPropertiesClass` aspect (SDK — this is the path `scripts/agent_memory.py`
uses in `save_belief()`):

```bash
datahub graphql --query 'mutation {
  upsertStructuredProperties(input: {
    assetUrn: "<ENTITY_URN>",
    structuredPropertyInputs: [{
      structuredPropertyUrn: "urn:li:structuredProperty:agent.confidence",
      values: ["0.9"]
    }]
  })
}' --format json
```

### The full-replace trap

`structuredProperties` is a **full-replace aspect** in DataHub: whatever list of
`StructuredPropertyValueAssignmentClass` you emit becomes the _entire_ set of structured
properties on that entity — it does not merge with what's already there. If your agent writes only
`agent.confidence` and a governance step had previously set `agent.status`, a naive write silently
erases `agent.status`.

The fix is always the same shape: **read the current set, then write the union.**
`scripts/agent_memory.py::_read_values()` does this read; every writer (`save_belief()`,
`set_status()`) re-includes whatever sibling fields it isn't explicitly changing. This is the
difference between a durable, compounding write-back and one that quietly resets itself on every
other call.

## 3. Read it back (verify the write)

An autonomous agent should confirm its own write by reading the value back — never assume a write
succeeded silently.

**GraphQL:**

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

**Python SDK** (what `agent_memory.py read` does):

```python
from datahub.metadata.schema_classes import StructuredPropertiesClass

aspect = graph.get_aspect("<ENTITY_URN>", StructuredPropertiesClass)
for p in aspect.properties:
    qualified_name = p.propertyUrn.split(":")[-1]
    print(qualified_name, "=", p.values[0] if p.values else None)
```

## Worked example — an agent recording confidence + provenance + status

`scripts/agent_memory.py` defines a small `agent.*` namespace (rename the prefix for your own org's
convention — nothing else depends on the literal string "agent"):

| Property             | Type   | Meaning                                                                                  |
| -------------------- | ------ | ---------------------------------------------------------------------------------------- |
| `agent.summary`      | string | Human-readable summary of what the agent currently believes                              |
| `agent.confidence`   | number | Posterior confidence, 0..1 (see `references/confidence-model.md`)                        |
| `agent.logodds`      | number | Raw log-odds behind the confidence — lets the next run resume the exact posterior        |
| `agent.mass`         | number | Accumulated evidence mass (independent-evidence gate, see confidence-model.md)           |
| `agent.provenance`   | string | JSON-encoded list of every update applied, for audit/replay                              |
| `agent.lastEvent`    | string | Identifier of the most recent update                                                     |
| `agent.agentVersion` | string | Which agent version wrote this                                                           |
| `agent.status`       | string | `TRUSTED` \| `NEEDS_REVIEW` — governance verdict (see `references/governance-gating.md`) |

Because `agent.logodds` and `agent.mass` are typed and queryable (not buried in prose), the _next_
run of the same agent — or a different agent entirely — can resume the exact posterior instead of
starting over, and a downstream consumer can filter for `agent.confidence < 0.7` without parsing
free text. That is what turns a one-shot enrichment into durable, compounding context on the graph.

See `references/confidence-model.md` for how the confidence number itself is computed, and
`references/governance-gating.md` for how `agent.status` and its companion tag get set.
