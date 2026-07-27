#!/usr/bin/env python3
"""
test_mcp_client.py — stdio MCP client that spawns mnemo/mcp_server.py as a subprocess and calls
its assess_model_drift tool against the LIVE DataHub instance, exactly as an MCP host (Claude
Desktop, another agent) would. Proves the MCP wrapper actually works end-to-end, not just that
it imports.

Model URN matches the one seeded by run_ml_drift_demo.py / run_agent.py (see mnemo constants
there): urn:li:mlModel:(urn:li:dataPlatform:mlflow,churn_model,PROD)

Run:  python test_mcp_client.py    (needs DataHub up; spawns its own mnemo/mcp_server.py)
"""
import asyncio
import json
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

MODEL_URN = "urn:li:mlModel:(urn:li:dataPlatform:mlflow,churn_model,PROD)"
SERVER_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mnemo", "mcp_server.py")


async def main():
    params = StdioServerParameters(
        command=sys.executable,
        args=[SERVER_SCRIPT],
        env=os.environ.copy(),  # carries DATAHUB_GMS_URL / DATAHUB_GMS_TOKEN from .env/shell
    )
    print(f"=== spawning MCP server: {sys.executable} {SERVER_SCRIPT} ===")
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = await session.list_tools()
            print(f"=== tools exposed: {[t.name for t in tools.tools]} ===\n")

            print(f"=== calling assess_model_drift(model_urn={MODEL_URN!r}) ===")
            result = await session.call_tool("assess_model_drift", {"model_urn": MODEL_URN})

            for block in result.content:
                if block.type == "text":
                    payload = json.loads(block.text)
                    print(json.dumps(payload, indent=2, default=str))

            print("\nMCP CLIENT TEST", "FAIL (tool reported error)" if result.isError else "GREEN")


if __name__ == "__main__":
    asyncio.run(main())
