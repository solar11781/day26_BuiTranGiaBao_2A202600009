"""Repeatable FastMCP verification script for Lab 26.

This uses FastMCP's in-memory client transport so it can verify the MCP surface
without starting a subprocess or opening a network port.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastmcp import Client
from fastmcp.exceptions import ToolError

from init_db import create_database
from mcp_server import mcp


def _json(data: Any) -> str:
    return json.dumps(data, indent=2, sort_keys=True, default=str)


def _extract_resource_text(result: Any) -> str:
    if isinstance(result, str):
        return result
    if isinstance(result, list) and result:
        first = result[0]
        return getattr(first, "text", str(first))
    return str(result)


async def main() -> None:
    create_database("sqlite")

    async with Client(mcp) as client:
        tools = await client.list_tools()
        tool_names = sorted(tool.name for tool in tools)
        print("Tools discovered:", tool_names)
        assert tool_names == ["aggregate", "insert", "search"]

        resources = await client.list_resources()
        resource_uris = sorted(str(resource.uri) for resource in resources)
        print("Resources discovered:", resource_uris)
        assert "schema://database" in resource_uris

        templates = await client.list_resource_templates()
        template_uris = sorted(str(getattr(template, "uriTemplate", getattr(template, "uri_template", ""))) for template in templates)
        print("Resource templates discovered:", template_uris)
        assert "schema://table/{table_name}" in template_uris

        schema_result = await client.read_resource("schema://database")
        print("Database schema preview:", _extract_resource_text(schema_result)[:240].replace("\n", " "), "...")

        students_result = await client.read_resource("schema://table/students")
        print("Students schema preview:", _extract_resource_text(students_result)[:240].replace("\n", " "), "...")

        search_result = await client.call_tool(
            "search",
            {
                "table": "students",
                "filters": {"cohort": "A1"},
                "columns": ["id", "name", "cohort", "score"],
                "order_by": "score",
                "descending": True,
                "limit": 5,
            },
        )
        print("Valid search result:", _json(search_result.data))
        assert search_result.data["count"] == 2

        insert_result = await client.call_tool(
            "insert",
            {
                "table": "students",
                "values": {
                    "name": "Dorothy Vaughan",
                    "email": "dorothy@example.edu",
                    "cohort": "A1",
                    "score": 89.0,
                },
            },
        )
        print("Valid insert result:", _json(insert_result.data))
        assert insert_result.data["inserted"]["email"] == "dorothy@example.edu"

        aggregate_result = await client.call_tool(
            "aggregate",
            {"table": "students", "metric": "avg", "column": "score", "group_by": "cohort"},
        )
        print("Valid aggregate result:", _json(aggregate_result.data))
        assert aggregate_result.data["rows"]

        try:
            await client.call_tool("search", {"table": "missing_table"})
        except ToolError as exc:
            print("Expected invalid request error:", exc)
        else:
            raise AssertionError("Expected missing table search to fail")

    print("All Lab 26 MCP checks passed.")


if __name__ == "__main__":
    asyncio.run(main())
