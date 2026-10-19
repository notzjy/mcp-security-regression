from __future__ import annotations

import json
import os
import sys
from contextlib import asynccontextmanager
from datetime import timedelta

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from .storage import Store


def server_arguments(store: Store, role: str, campaign_id: str | None = None) -> list[str]:
    args = ["-m", "guardbench.mcp_server", "--db", str(store.path), "--role", role]
    if campaign_id:
        args += ["--campaign", campaign_id]
    return args


@asynccontextmanager
async def evaluation_client(store: Store, campaign_id: str | None = None):
    # Only controller servers receive explicitly configured target credentials.
    env = {"PYTHONUNBUFFERED": "1"}
    for target in store.list("target"):
        name = target.get("auth_env")
        if name and os.getenv(name):
            env[name] = os.environ[name]
    params = StdioServerParameters(command=sys.executable, args=server_arguments(store, "controller", campaign_id), env=env)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write, read_timeout_seconds=timedelta(seconds=900)) as session:
            await session.initialize()
            yield session


async def call(session: ClientSession, tool: str, **arguments) -> dict:
    result = await session.call_tool(tool, arguments=arguments)
    if result.isError:
        message = " ".join(getattr(c, "text", "") for c in result.content)
        raise ValueError(f"MCP tool {tool} failed: {message}")
    if result.structuredContent is not None:
        return result.structuredContent
    for item in result.content:
        if getattr(item, "type", "") == "text":
            return json.loads(item.text)
    raise ValueError(f"MCP tool {tool} returned no JSON")
