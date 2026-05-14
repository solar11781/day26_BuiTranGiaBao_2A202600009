"""Database adapters for the Lab 26 FastMCP database server.

The public surface is intentionally small: every adapter exposes the same
search, insert, aggregate, and schema methods used by the MCP tools/resources.
SQL identifiers are always validated against the live schema before they are
quoted into SQL, while all user values are passed as query parameters.
"""

from __future__ import annotations

import abc
import os
import re
import sqlite3
from pathlib import Path
from typing import Any, Iterable, Literal


JsonDict = dict[str, Any]
FilterInput = dict[str, Any] | list[dict[str, Any]] | None


class ValidationError(Exception):
    """Raised when a request cannot be safely executed."""


class DatabaseAdapter(abc.ABC):
    """Shared interface for database backends used by the MCP server."""

    supported_operators = {"eq", "ne", "gt", "gte", "lt", "lte", "like", "in", "is_null", "not_null"}
    aggregate_metrics = {"count", "avg", "sum", "min", "max"}
    identifier_pattern = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
    max_limit = 100

    placeholder = "?"

    @abc.abstractmethod
    def list_tables(self) -> list[str]:
        """Return user-defined table names."""

    @abc.abstractmethod
    def get_table_schema(self, table: str) -> JsonDict:
        """Return a normalized schema snapshot for one table."""

    @abc.abstractmethod
    def get_database_schema(self) -> JsonDict:
        """Return a normalized schema snapshot for the full database."""

    @abc.abstractmethod
    def search(
        self,
        table: str,
        columns: list[str] | None = None,
        filters: FilterInput = None,
        limit: int = 20,
        offset: int = 0,
        order_by: str | None = None,
        descending: bool = False,
    ) -> JsonDict:
        """Search a validated table using safe filters, ordering, and pagination."""

    @abc.abstractmethod
    def insert(self, table: str, values: JsonDict) -> JsonDict:
        """Insert a row into a validated table and return the inserted payload."""

    @abc.abstractmethod
    def aggregate(
        self,
        table: str,
        metric: str,
        column: str | None = None,
        filters: FilterInput = None,
        group_by: str | None = None,
    ) -> JsonDict:
        """Run a validated aggregate query."""

    def _ensure_identifier_shape(self, identifier: str, kind: str) -> None:
        if not isinstance(identifier, str) or not self.identifier_pattern.match(identifier):
            raise ValidationError(f"Invalid {kind} name: {identifier!r}")

    def _quote_identifier(self, identifier: str) -> str:
        self._ensure_identifier_shape(identifier, "identifier")
        return '"' + identifier.replace('"', '""') + '"'

    def _validate_table(self, table: str) -> None:
        self._ensure_identifier_shape(table, "table")
        available = set(self.list_tables())
        if table not in available:
            raise ValidationError(f"Unknown table {table!r}. Available tables: {sorted(available)}")

    def _column_names(self, table: str) -> list[str]:
        schema = self.get_table_schema(table)
        return [column["name"] for column in schema["columns"]]

    def _validate_columns(self, table: str, columns: Iterable[str], *, allow_star: bool = False) -> list[str]:
        available = set(self._column_names(table))
        validated: list[str] = []
        for column in columns:
            if column == "*" and allow_star:
                validated.append(column)
                continue
            self._ensure_identifier_shape(column, "column")
            if column not in available:
                raise ValidationError(f"Unknown column {column!r} for table {table!r}. Available columns: {sorted(available)}")
            validated.append(column)
        return validated

    def _normalize_pagination(self, limit: int, offset: int) -> tuple[int, int]:
        try:
            normalized_limit = int(limit)
            normalized_offset = int(offset)
        except (TypeError, ValueError) as exc:
            raise ValidationError("limit and offset must be integers") from exc
        if normalized_limit < 1:
            raise ValidationError("limit must be at least 1")
        if normalized_limit > self.max_limit:
            raise ValidationError(f"limit must be at most {self.max_limit}")
        if normalized_offset < 0:
            raise ValidationError("offset must be 0 or greater")
        return normalized_limit, normalized_offset

    def _normalize_filters(self, filters: FilterInput) -> list[JsonDict]:
        if filters is None or filters == {} or filters == []:
            return []

        normalized: list[JsonDict] = []
        if isinstance(filters, dict):
            for column, condition in filters.items():
                if isinstance(condition, dict) and ("op" in condition or "operator" in condition):
                    op = condition.get("op", condition.get("operator"))
                    value = condition.get("value")
                    normalized.append({"column": column, "op": op, "value": value})
                else:
                    normalized.append({"column": column, "op": "eq", "value": condition})
            return normalized

        if isinstance(filters, list):
            for condition in filters:
                if not isinstance(condition, dict):
                    raise ValidationError("Each filter must be an object")
                column = condition.get("column")
                op = condition.get("op", condition.get("operator", "eq"))
                value = condition.get("value")
                normalized.append({"column": column, "op": op, "value": value})
            return normalized

        raise ValidationError("filters must be an object, a list of objects, or null")

    def _build_where_clause(self, table: str, filters: FilterInput, *, placeholder: str | None = None) -> tuple[str, list[Any]]:
        params: list[Any] = []
        clauses: list[str] = []
        ph = placeholder or self.placeholder

        for item in self._normalize_filters(filters):
            column = item.get("column")
            op = str(item.get("op", "eq")).lower()
            value = item.get("value")

            if not isinstance(column, str):
                raise ValidationError("Every filter must include a string column")
            self._validate_columns(table, [column])
            if op not in self.supported_operators:
                raise ValidationError(f"Unsupported filter operator {op!r}. Supported operators: {sorted(self.supported_operators)}")

            quoted_column = self._quote_identifier(column)
            if op == "eq":
                clauses.append(f"{quoted_column} = {ph}")
                params.append(value)
            elif op == "ne":
                clauses.append(f"{quoted_column} <> {ph}")
                params.append(value)
            elif op == "gt":
                clauses.append(f"{quoted_column} > {ph}")
                params.append(value)
            elif op == "gte":
                clauses.append(f"{quoted_column} >= {ph}")
                params.append(value)
            elif op == "lt":
                clauses.append(f"{quoted_column} < {ph}")
                params.append(value)
            elif op == "lte":
                clauses.append(f"{quoted_column} <= {ph}")
                params.append(value)
            elif op == "like":
                if not isinstance(value, str):
                    raise ValidationError("The 'like' operator requires a string value")
                clauses.append(f"{quoted_column} LIKE {ph}")
                params.append(value)
            elif op == "in":
                if not isinstance(value, list) or not value:
                    raise ValidationError("The 'in' operator requires a non-empty list value")
                placeholders = ", ".join([ph] * len(value))
                clauses.append(f"{quoted_column} IN ({placeholders})")
                params.extend(value)
            elif op == "is_null":
                clauses.append(f"{quoted_column} IS NULL")
            elif op == "not_null":
                clauses.append(f"{quoted_column} IS NOT NULL")

        if not clauses:
            return "", []
        return " WHERE " + " AND ".join(clauses), params

    def _primary_key_columns(self, table: str) -> list[str]:
        schema = self.get_table_schema(table)
        return [column["name"] for column in schema["columns"] if column.get("primary_key")]

    def _format_schema(self, tables: list[str]) -> JsonDict:
        return {
            "backend": self.backend_name,
            "tables": {table: self.get_table_schema(table) for table in tables},
            "filter_operators": sorted(self.supported_operators),
            "aggregate_metrics": sorted(self.aggregate_metrics),
            "pagination": {"default_limit": 20, "max_limit": self.max_limit},
        }

    @property
    @abc.abstractmethod
    def backend_name(self) -> str:
        """Short backend label used in tool responses."""


class SQLiteAdapter(DatabaseAdapter):
    """SQLite implementation of the Lab 26 database adapter."""

    placeholder = "?"

    def __init__(self, database_path: str | Path):
        self.database_path = Path(database_path)

    @property
    def backend_name(self) -> str:
        return "sqlite"

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.database_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def list_tables(self) -> list[str]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
                ORDER BY name
                """
            ).fetchall()
        return [row["name"] for row in rows]

    def get_table_schema(self, table: str) -> JsonDict:
        self._validate_table(table)
        quoted_table = self._quote_identifier(table)
        with self.connect() as conn:
            column_rows = conn.execute(f"PRAGMA table_info({quoted_table})").fetchall()
            fk_rows = conn.execute(f"PRAGMA foreign_key_list({quoted_table})").fetchall()

        columns = [
            {
                "name": row["name"],
                "type": row["type"],
                "nullable": not bool(row["notnull"]),
                "default": row["dflt_value"],
                "primary_key": bool(row["pk"]),
                "primary_key_order": int(row["pk"]),
            }
            for row in column_rows
        ]
        foreign_keys = [
            {
                "column": row["from"],
                "references_table": row["table"],
                "references_column": row["to"],
                "on_update": row["on_update"],
                "on_delete": row["on_delete"],
            }
            for row in fk_rows
        ]
        return {"name": table, "columns": columns, "foreign_keys": foreign_keys}

    def get_database_schema(self) -> JsonDict:
        return self._format_schema(self.list_tables())

    def search(
        self,
        table: str,
        columns: list[str] | None = None,
        filters: FilterInput = None,
        limit: int = 20,
        offset: int = 0,
        order_by: str | None = None,
        descending: bool = False,
    ) -> JsonDict:
        self._validate_table(table)
        limit, offset = self._normalize_pagination(limit, offset)
        selected_columns = self._column_names(table) if columns is None else self._validate_columns(table, columns)
        if not selected_columns:
            raise ValidationError("columns must not be empty")

        where_clause, params = self._build_where_clause(table, filters)
        order_clause = ""
        if order_by:
            self._validate_columns(table, [order_by])
            direction = "DESC" if descending else "ASC"
            order_clause = f" ORDER BY {self._quote_identifier(order_by)} {direction}"

        column_sql = ", ".join(self._quote_identifier(column) for column in selected_columns)
        sql = f"SELECT {column_sql} FROM {self._quote_identifier(table)}{where_clause}{order_clause} LIMIT ? OFFSET ?"
        query_params = [*params, limit + 1, offset]

        with self.connect() as conn:
            rows = [dict(row) for row in conn.execute(sql, query_params).fetchall()]

        has_more = len(rows) > limit
        visible_rows = rows[:limit]
        return {
            "table": table,
            "backend": self.backend_name,
            "columns": selected_columns,
            "filters": self._normalize_filters(filters),
            "rows": visible_rows,
            "count": len(visible_rows),
            "limit": limit,
            "offset": offset,
            "has_more": has_more,
            "next_offset": offset + limit if has_more else None,
            "order_by": order_by,
            "descending": bool(descending),
        }

    def insert(self, table: str, values: JsonDict) -> JsonDict:
        self._validate_table(table)
        if not isinstance(values, dict) or not values:
            raise ValidationError("values must be a non-empty object")
        self._validate_columns(table, values.keys())

        columns = list(values.keys())
        column_sql = ", ".join(self._quote_identifier(column) for column in columns)
        placeholders = ", ".join(["?"] * len(columns))
        sql = f"INSERT INTO {self._quote_identifier(table)} ({column_sql}) VALUES ({placeholders})"

        with self.connect() as conn:
            cursor = conn.execute(sql, [values[column] for column in columns])
            conn.commit()
            lastrowid = cursor.lastrowid

            inserted = dict(values)
            pk_columns = self._primary_key_columns(table)
            if len(pk_columns) == 1 and pk_columns[0] not in inserted and lastrowid is not None:
                inserted[pk_columns[0]] = lastrowid
                row = conn.execute(
                    f"SELECT * FROM {self._quote_identifier(table)} WHERE {self._quote_identifier(pk_columns[0])} = ?",
                    [lastrowid],
                ).fetchone()
                if row is not None:
                    inserted = dict(row)

        return {"table": table, "backend": self.backend_name, "inserted": inserted}

    def aggregate(
        self,
        table: str,
        metric: str,
        column: str | None = None,
        filters: FilterInput = None,
        group_by: str | None = None,
    ) -> JsonDict:
        self._validate_table(table)
        metric = str(metric).lower()
        if metric not in self.aggregate_metrics:
            raise ValidationError(f"Unsupported aggregate metric {metric!r}. Supported metrics: {sorted(self.aggregate_metrics)}")

        if metric == "count":
            target = "*" if column in (None, "*") else self._quote_identifier(self._validate_columns(table, [column])[0])
        else:
            if not column:
                raise ValidationError(f"Aggregate metric {metric!r} requires a column")
            target = self._quote_identifier(self._validate_columns(table, [column])[0])

        group_select = ""
        group_clause = ""
        if group_by:
            self._validate_columns(table, [group_by])
            group_select = f"{self._quote_identifier(group_by)} AS group_value, "
            group_clause = f" GROUP BY {self._quote_identifier(group_by)} ORDER BY {self._quote_identifier(group_by)} ASC"

        where_clause, params = self._build_where_clause(table, filters)
        value_alias = f"{metric}_value"
        sql = (
            f"SELECT {group_select}{metric.upper()}({target}) AS {self._quote_identifier(value_alias)} "
            f"FROM {self._quote_identifier(table)}{where_clause}{group_clause}"
        )

        with self.connect() as conn:
            rows = [dict(row) for row in conn.execute(sql, params).fetchall()]

        return {
            "table": table,
            "backend": self.backend_name,
            "metric": metric,
            "column": column or "*",
            "group_by": group_by,
            "filters": self._normalize_filters(filters),
            "rows": rows,
        }


class PostgreSQLAdapter(DatabaseAdapter):
    """PostgreSQL implementation using psycopg 3.

    This adapter is optional for the lab. Install `psycopg[binary]` and set
    DB_BACKEND=postgres plus DATABASE_URL to enable it.
    """

    placeholder = "%s"

    def __init__(self, database_url: str):
        if not database_url:
            raise ValidationError("DATABASE_URL is required when DB_BACKEND=postgres")
        self.database_url = database_url

    @property
    def backend_name(self) -> str:
        return "postgres"

    def connect(self):
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise RuntimeError("PostgreSQL support requires: pip install 'psycopg[binary]>=3.2'") from exc
        return psycopg.connect(self.database_url, row_factory=dict_row)

    def list_tables(self) -> list[str]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT table_name AS name
                FROM information_schema.tables
                WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
                ORDER BY table_name
                """
            ).fetchall()
        return [row["name"] for row in rows]

    def get_table_schema(self, table: str) -> JsonDict:
        self._validate_table(table)
        with self.connect() as conn:
            columns = conn.execute(
                """
                SELECT
                    c.column_name AS name,
                    c.data_type AS type,
                    CASE WHEN c.is_nullable = 'YES' THEN TRUE ELSE FALSE END AS nullable,
                    c.column_default AS default,
                    CASE WHEN pk.column_name IS NULL THEN FALSE ELSE TRUE END AS primary_key,
                    COALESCE(pk.ordinal_position, 0) AS primary_key_order
                FROM information_schema.columns c
                LEFT JOIN (
                    SELECT ku.table_name, ku.column_name, ku.ordinal_position
                    FROM information_schema.table_constraints tc
                    JOIN information_schema.key_column_usage ku
                      ON tc.constraint_name = ku.constraint_name
                     AND tc.table_schema = ku.table_schema
                    WHERE tc.constraint_type = 'PRIMARY KEY' AND tc.table_schema = 'public'
                ) pk ON pk.table_name = c.table_name AND pk.column_name = c.column_name
                WHERE c.table_schema = 'public' AND c.table_name = %s
                ORDER BY c.ordinal_position
                """,
                [table],
            ).fetchall()
            foreign_keys = conn.execute(
                """
                SELECT
                    kcu.column_name AS column,
                    ccu.table_name AS references_table,
                    ccu.column_name AS references_column,
                    rc.update_rule AS on_update,
                    rc.delete_rule AS on_delete
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                  ON tc.constraint_name = kcu.constraint_name
                 AND tc.table_schema = kcu.table_schema
                JOIN information_schema.constraint_column_usage ccu
                  ON ccu.constraint_name = tc.constraint_name
                 AND ccu.table_schema = tc.table_schema
                JOIN information_schema.referential_constraints rc
                  ON rc.constraint_name = tc.constraint_name
                 AND rc.constraint_schema = tc.table_schema
                WHERE tc.constraint_type = 'FOREIGN KEY'
                  AND tc.table_schema = 'public'
                  AND tc.table_name = %s
                ORDER BY kcu.ordinal_position
                """,
                [table],
            ).fetchall()
        return {"name": table, "columns": columns, "foreign_keys": foreign_keys}

    def get_database_schema(self) -> JsonDict:
        return self._format_schema(self.list_tables())

    def search(
        self,
        table: str,
        columns: list[str] | None = None,
        filters: FilterInput = None,
        limit: int = 20,
        offset: int = 0,
        order_by: str | None = None,
        descending: bool = False,
    ) -> JsonDict:
        self._validate_table(table)
        limit, offset = self._normalize_pagination(limit, offset)
        selected_columns = self._column_names(table) if columns is None else self._validate_columns(table, columns)
        if not selected_columns:
            raise ValidationError("columns must not be empty")
        where_clause, params = self._build_where_clause(table, filters, placeholder="%s")

        order_clause = ""
        if order_by:
            self._validate_columns(table, [order_by])
            direction = "DESC" if descending else "ASC"
            order_clause = f" ORDER BY {self._quote_identifier(order_by)} {direction}"

        column_sql = ", ".join(self._quote_identifier(column) for column in selected_columns)
        sql = f"SELECT {column_sql} FROM {self._quote_identifier(table)}{where_clause}{order_clause} LIMIT %s OFFSET %s"
        query_params = [*params, limit + 1, offset]
        with self.connect() as conn:
            rows = conn.execute(sql, query_params).fetchall()

        has_more = len(rows) > limit
        visible_rows = [dict(row) for row in rows[:limit]]
        return {
            "table": table,
            "backend": self.backend_name,
            "columns": selected_columns,
            "filters": self._normalize_filters(filters),
            "rows": visible_rows,
            "count": len(visible_rows),
            "limit": limit,
            "offset": offset,
            "has_more": has_more,
            "next_offset": offset + limit if has_more else None,
            "order_by": order_by,
            "descending": bool(descending),
        }

    def insert(self, table: str, values: JsonDict) -> JsonDict:
        self._validate_table(table)
        if not isinstance(values, dict) or not values:
            raise ValidationError("values must be a non-empty object")
        self._validate_columns(table, values.keys())

        columns = list(values.keys())
        column_sql = ", ".join(self._quote_identifier(column) for column in columns)
        placeholders = ", ".join(["%s"] * len(columns))
        sql = f"INSERT INTO {self._quote_identifier(table)} ({column_sql}) VALUES ({placeholders}) RETURNING *"
        with self.connect() as conn:
            inserted = dict(conn.execute(sql, [values[column] for column in columns]).fetchone())
            conn.commit()
        return {"table": table, "backend": self.backend_name, "inserted": inserted}

    def aggregate(
        self,
        table: str,
        metric: str,
        column: str | None = None,
        filters: FilterInput = None,
        group_by: str | None = None,
    ) -> JsonDict:
        self._validate_table(table)
        metric = str(metric).lower()
        if metric not in self.aggregate_metrics:
            raise ValidationError(f"Unsupported aggregate metric {metric!r}. Supported metrics: {sorted(self.aggregate_metrics)}")
        if metric == "count":
            target = "*" if column in (None, "*") else self._quote_identifier(self._validate_columns(table, [column])[0])
        else:
            if not column:
                raise ValidationError(f"Aggregate metric {metric!r} requires a column")
            target = self._quote_identifier(self._validate_columns(table, [column])[0])

        group_select = ""
        group_clause = ""
        if group_by:
            self._validate_columns(table, [group_by])
            group_select = f"{self._quote_identifier(group_by)} AS group_value, "
            group_clause = f" GROUP BY {self._quote_identifier(group_by)} ORDER BY {self._quote_identifier(group_by)} ASC"

        where_clause, params = self._build_where_clause(table, filters, placeholder="%s")
        value_alias = f"{metric}_value"
        sql = (
            f"SELECT {group_select}{metric.upper()}({target}) AS {self._quote_identifier(value_alias)} "
            f"FROM {self._quote_identifier(table)}{where_clause}{group_clause}"
        )
        with self.connect() as conn:
            rows = [dict(row) for row in conn.execute(sql, params).fetchall()]
        return {
            "table": table,
            "backend": self.backend_name,
            "metric": metric,
            "column": column or "*",
            "group_by": group_by,
            "filters": self._normalize_filters(filters),
            "rows": rows,
        }


def build_adapter() -> DatabaseAdapter:
    """Create the adapter selected by environment variables.

    Environment variables:
    - DB_BACKEND=sqlite|postgres, default sqlite
    - LAB26_DB_PATH=/path/to/sqlite.db for SQLite
    - DATABASE_URL=postgresql://... for PostgreSQL
    """

    backend = os.getenv("DB_BACKEND", "sqlite").strip().lower()
    if backend == "sqlite":
        db_path = os.getenv("LAB26_DB_PATH")
        if db_path is None:
            db_path = str(Path(__file__).resolve().parent / "lab26.sqlite3")
        return SQLiteAdapter(db_path)
    if backend in {"postgres", "postgresql"}:
        return PostgreSQLAdapter(os.getenv("DATABASE_URL", ""))
    raise ValidationError("DB_BACKEND must be 'sqlite' or 'postgres'")
