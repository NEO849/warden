"""Read layer — pull an asset's context from DataHub (schema, upstream lineage, owners, prior memory).

Two read paths:
  - DEFAULT (always on): the direct `acryl-datahub` SDK graph client (get_aspect/...) — get_context()
    below. This is what mnemo/agent.py's drift detection actually relies on; unchanged, live-verified.
  - OPTIONAL (off by default): the OFFICIAL DataHub MCP server (github.com/acryldata/mcp-server-
    datahub), consumed as an MCP client over stdio, self-hosted on demand via `uvx`. Enable with
    MNEMO_USE_MCP_READER=1. This is the "consume the DataHub MCP server" angle, additive to Mnemo
    exposing ITSELF as an MCP tool (see mnemo/mcp_server.py). get_upstreams() below is the only
    place it plugs in, and even there it falls back to the SDK path on any failure — nothing in
    mnemo/agent.py's check_model_inputs()/model_input_sources() calls this; the drift-detection
    invariant path is untouched. Each MCP call spawns `uvx mcp-server-datahub` fresh (~10-15s,
    dominated by importing the full datahub SDK inside that subprocess) — fine for an optional/
    demo path, deliberately not swapped in as the hot path.
"""
import asyncio
import json
import os

from datahub.metadata.schema_classes import (
    OwnershipClass,
    SchemaMetadataClass,
    StructuredPropertiesClass,
    UpstreamLineageClass,
)

USE_MCP_READER = os.getenv("MNEMO_USE_MCP_READER", "0") == "1"


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

    # --- optional MCP-backed read path (2a) ---
    @staticmethod
    async def _get_upstreams_via_mcp_async(urn: str, max_hops: int) -> list:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        params = StdioServerParameters(
            command="uvx",
            args=["--from", "mcp-server-datahub", "mcp-server-datahub"],
            env={**os.environ, "DATAHUB_GMS_URL": os.getenv("DATAHUB_GMS_URL", "http://localhost:8090")},
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                res = await session.call_tool(
                    "get_lineage", {"urn": urn, "upstream": True, "max_hops": max_hops}
                )
                if res.isError:
                    raise RuntimeError(f"mcp-server-datahub get_lineage failed for {urn}")
                text = "".join(b.text for b in res.content if b.type == "text")
                data = json.loads(text)
                results = (data.get("upstreams") or {}).get("searchResults") or []
                return [r["entity"]["urn"] for r in results if r.get("entity", {}).get("urn")]

    def get_upstreams_via_mcp(self, urn: str, max_hops: int = 1) -> list:
        """Fetch upstream lineage for `urn` via the OFFICIAL DataHub MCP server, self-hosted
        on-demand via `uvx` (github.com/acryldata/mcp-server-datahub). Returns a list of upstream
        entity URNs (datasets/mlFeatures/etc). Raises on failure — callers should catch (see
        get_upstreams(), which does exactly that and falls back to the SDK path). Requires `uvx`
        on PATH; DATAHUB_GMS_URL is passed through to the spawned server."""
        return asyncio.run(self._get_upstreams_via_mcp_async(urn, max_hops))

    def get_upstreams(self, urn: str, max_hops: int = 1) -> list:
        """Upstream URNs for `urn`. Uses the MCP-backed reader when MNEMO_USE_MCP_READER=1 and
        that call succeeds; otherwise (the default, and on any MCP failure) falls back to the
        direct SDK path via UpstreamLineageClass — the always-on, live-verified default. The MCP
        path is purely additive here; nothing load-bearing depends on it."""
        if USE_MCP_READER:
            try:
                return self.get_upstreams_via_mcp(urn, max_hops=max_hops)
            except Exception as e:
                print(f"   [reader] MCP reader failed ({type(e).__name__}: {str(e)[:80]}) → SDK fallback")
        up = self.g.get_aspect(urn, UpstreamLineageClass)
        return [u.dataset for u in up.upstreams] if up else []
