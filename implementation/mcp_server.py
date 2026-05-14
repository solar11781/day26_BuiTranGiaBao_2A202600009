"""FastMCP server for Lab 26: search, insert, aggregate, and schema resources."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from db import DatabaseAdapter, ValidationError, build_adapter
from init_db import create_database
from dotenv import load_dotenv

load_dotenv()


SERVER_NAME = "SQLite Lab MCP Server"
SERVER_VERSION = "1.0.0"


def _build_auth_provider():
    """Return a FastMCP auth provider when LAB26_AUTH_TOKEN is configured."""

    token = os.getenv("LAB26_AUTH_TOKEN")
    if not token:
        return None
    try:
        from fastmcp.server.auth.providers.jwt import StaticTokenVerifier
    except ImportError as exc:
        raise RuntimeError("HTTP auth requires FastMCP auth extras: pip install 'fastmcp[auth]>=2.18'") from exc

    return StaticTokenVerifier(
        tokens={
            token: {
                "client_id": "lab26-local-client",
                "scopes": ["read:data", "write:data"],
            }
        },
        required_scopes=["read:data"],
    )


def _ensure_database_exists() -> None:
    """Create the default database if it is missing."""

    backend = os.getenv("DB_BACKEND", "sqlite").strip().lower()
    if backend == "sqlite":
        db_path = Path(os.getenv("LAB26_DB_PATH") or Path(__file__).resolve().parent / "lab26.sqlite3")
        if not db_path.exists():
            create_database("sqlite")


def _to_tool_error(exc: ValidationError) -> ValueError:
    return ValueError(f"Validation error: {exc}")


_ensure_database_exists()
adapter: DatabaseAdapter = build_adapter()

mcp = FastMCP(
    name=SERVER_NAME,
    version=SERVER_VERSION,
    instructions=(
        "Use this server to safely inspect and modify the Lab 26 course database. "
        "Available tools are exactly search, insert, and aggregate. "
        "Use schema://database or schema://table/{table_name} for read-only schema context."
    ),
    auth=_build_auth_provider(),
    strict_input_validation=True,
    list_page_size=50,
)


@mcp.tool(name="search", annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": False})
def search(
    table: str,
    filters: dict[str, Any] | list[dict[str, Any]] | None = None,
    columns: list[str] | None = None,
    limit: int = 20,
    offset: int = 0,
    order_by: str | None = None,
    descending: bool = False,
) -> dict[str, Any]:
    """Search a table with validated filters, ordering, and pagination.

    Filter examples:
    - {"cohort": "A1"}
    - {"score": {"op": "gte", "value": 90}}
    - [{"column": "cohort", "op": "in", "value": ["A1", "B2"]}]
    Supported operators: eq, ne, gt, gte, lt, lte, like, in, is_null, not_null.
    """

    try:
        return adapter.search(
            table=table,
            columns=columns,
            filters=filters,
            limit=limit,
            offset=offset,
            order_by=order_by,
            descending=descending,
        )
    except ValidationError as exc:
        raise _to_tool_error(exc) from exc


@mcp.tool(name="insert", annotations={"readOnlyHint": False, "idempotentHint": False, "openWorldHint": False})
def insert(table: str, values: dict[str, Any]) -> dict[str, Any]:
    """Insert one row into a validated table and return the inserted payload.

    Example: {"table": "students", "values": {"name": "New Student", "email": "new@example.edu", "cohort": "A1", "score": 87.5}}
    """

    try:
        return adapter.insert(table=table, values=values)
    except ValidationError as exc:
        raise _to_tool_error(exc) from exc


@mcp.tool(name="aggregate", annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": False})
def aggregate(
    table: str,
    metric: str,
    column: str | None = None,
    filters: dict[str, Any] | list[dict[str, Any]] | None = None,
    group_by: str | None = None,
) -> dict[str, Any]:
    """Compute count, avg, sum, min, or max with optional filters and grouping.

    Use column=null or column="*" only with metric="count". Other metrics require a real column name.
    """

    try:
        return adapter.aggregate(table=table, metric=metric, column=column, filters=filters, group_by=group_by)
    except ValidationError as exc:
        raise _to_tool_error(exc) from exc


@mcp.resource("schema://database", mime_type="application/json")
def database_schema() -> str:
    """Return JSON describing every table, column, foreign key, and supported query option."""

    return json.dumps(adapter.get_database_schema(), indent=2, sort_keys=True)


@mcp.resource("schema://table/{table_name}", mime_type="application/json")
def table_schema(table_name: str) -> str:
    """Return JSON describing one table schema."""

    try:
        return json.dumps(adapter.get_table_schema(table_name), indent=2, sort_keys=True)
    except ValidationError as exc:
        raise ValueError(f"Validation error: {exc}") from exc


@mcp.custom_route("/health", methods=["GET"])
async def health_check(request: Request) -> JSONResponse:
    """HTTP health endpoint for the optional Streamable HTTP transport."""

    return JSONResponse(
        {
            "status": "ok",
            "server": SERVER_NAME,
            "version": SERVER_VERSION,
            "backend": adapter.backend_name,
            "tables": adapter.list_tables(),
            "auth_enabled": bool(os.getenv("LAB26_AUTH_TOKEN")),
        }
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Lab 26 FastMCP database server.")
    parser.add_argument("--transport", choices=["stdio", "http"], default=os.getenv("LAB26_MCP_TRANSPORT", "stdio"))
    parser.add_argument("--host", default=os.getenv("LAB26_MCP_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("LAB26_MCP_PORT", "8000")))
    args = parser.parse_args()

    if args.transport == "stdio":
        mcp.run()
    else:
        mcp.run(transport="http", host=args.host, port=args.port)


if __name__ == "__main__":
    main()
