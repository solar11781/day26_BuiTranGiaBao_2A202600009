"""Automated tests for the Lab 26 FastMCP server and database adapter."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError


@pytest.fixture()
def isolated_server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db_path = tmp_path / "lab26-test.sqlite3"
    monkeypatch.setenv("DB_BACKEND", "sqlite")
    monkeypatch.setenv("LAB26_DB_PATH", str(db_path))

    from init_db import create_sqlite_database

    create_sqlite_database(db_path)

    import importlib
    import mcp_server

    importlib.reload(mcp_server)
    return mcp_server.mcp


@pytest.fixture()
async def client(isolated_server):
    async with Client(isolated_server) as test_client:
        yield test_client


async def test_tools_are_discoverable(client: Client):
    tools = await client.list_tools()
    assert sorted(tool.name for tool in tools) == ["aggregate", "insert", "search"]


async def test_schema_resources_are_discoverable(client: Client):
    resources = await client.list_resources()
    assert "schema://database" in {str(resource.uri) for resource in resources}

    templates = await client.list_resource_templates()
    assert "schema://table/{table_name}" in {str(getattr(template, "uriTemplate", getattr(template, "uri_template", ""))) for template in templates}

    table_schema = await client.read_resource("schema://table/students")
    assert table_schema


async def test_search_filters_ordering_and_pagination(client: Client):
    result = await client.call_tool(
        "search",
        {
            "table": "students",
            "filters": {"cohort": "A1"},
            "columns": ["id", "name", "cohort", "score"],
            "limit": 1,
            "order_by": "score",
            "descending": True,
        },
    )
    assert result.data["count"] == 1
    assert result.data["has_more"] is True
    assert result.data["rows"][0]["name"] == "John Smith"


async def test_insert_returns_inserted_payload(client: Client):
    result = await client.call_tool(
        "insert",
        {
            "table": "students",
            "values": {
                "name": "Mary Jackson",
                "email": "mary@example.edu",
                "cohort": "B2",
                "score": 90.5,
            },
        },
    )
    assert result.data["inserted"]["id"]
    assert result.data["inserted"]["email"] == "mary@example.edu"


async def test_aggregate_supports_grouped_avg(client: Client):
    result = await client.call_tool(
        "aggregate",
        {"table": "students", "metric": "avg", "column": "score", "group_by": "cohort"},
    )
    rows = result.data["rows"]
    assert any(row["group_value"] == "A1" for row in rows)


async def test_invalid_table_is_rejected(client: Client):
    with pytest.raises(ToolError):
        await client.call_tool("search", {"table": "students; DROP TABLE students;"})


async def test_invalid_column_is_rejected(client: Client):
    with pytest.raises(ToolError):
        await client.call_tool("search", {"table": "students", "columns": ["password"]})


async def test_invalid_operator_is_rejected(client: Client):
    with pytest.raises(ToolError):
        await client.call_tool(
            "search",
            {"table": "students", "filters": [{"column": "score", "op": "between", "value": [80, 90]}]},
        )


async def test_empty_insert_is_rejected(client: Client):
    with pytest.raises(ToolError):
        await client.call_tool("insert", {"table": "students", "values": {}})
