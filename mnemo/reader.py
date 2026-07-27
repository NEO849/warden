"""Read layer — pull an asset's context from DataHub (schema, upstream lineage, owners, prior memory)."""
from datahub.metadata.schema_classes import (
    OwnershipClass,
    SchemaMetadataClass,
    StructuredPropertiesClass,
    UpstreamLineageClass,
)


class DataHubReader:
    def __init__(self, graph):
        self.g = graph

    def get_context(self, urn: str) -> dict:
        schema = self.g.get_aspect(urn, SchemaMetadataClass)
        fields = [f.fieldPath for f in schema.fields] if schema else []

        up = self.g.get_aspect(urn, UpstreamLineageClass)
        upstreams = [u.dataset for u in up.upstreams] if up else []

        own = self.g.get_aspect(urn, OwnershipClass)
        owners = [o.owner for o in own.owners] if own else []

        sp = self.g.get_aspect(urn, StructuredPropertiesClass)
        memory = {}
        if sp:
            for p in sp.properties:
                qn = p.propertyUrn.split(":")[-1]
                memory[qn] = p.values[0] if p.values else None

        return {"urn": urn, "fields": fields, "upstreams": upstreams,
                "owners": owners, "memory": memory}
