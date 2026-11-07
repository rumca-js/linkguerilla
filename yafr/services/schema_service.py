"""
Database Schema Introspection and Column Modification Service for YAFR.

Provides dynamic introspection of database tables, column definitions, types,
and defaults using SQLAlchemy, as well as safe SQLite table reconstruction
to alter column default constraints and backfill existing NULL records.
"""

import logging
import re
from typing import Any, Dict, List, Optional
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from yafr.db.session import get_engine, get_session

logger = logging.getLogger(__name__)


class SchemaService:
    """
    Service for inspecting database tables/columns and altering column defaults.
    """

    @classmethod
    def get_tables(
        cls,
        engine: Optional[Engine] = None,
        metadata_lookup: Optional[List[Dict[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Dynamically returns all tables present in the database with their row counts.
        """
        eng = engine or get_engine()
        inspector = inspect(eng)
        table_names = sorted(inspector.get_table_names())

        lookup_by_name = {m["table_name"]: m for m in (metadata_lookup or [])}

        tables_data = []
        with eng.connect() as conn:
            for name in table_names:
                try:
                    count = (
                        conn.execute(text(f"SELECT COUNT(*) FROM {name}")).scalar() or 0
                    )
                except Exception as err:
                    logger.warning("Could not count rows for table %s: %s", name, err)
                    count = 0

                meta = lookup_by_name.get(name, {})
                tables_data.append(
                    {
                        "name": name,
                        "row_count": count,
                        "label": meta.get("label", name.capitalize()),
                        "description": meta.get("description", ""),
                        "icon": meta.get("icon", "bi-table"),
                    }
                )

        return tables_data

    @classmethod
    def get_table_columns(
        cls, table_name: str, engine: Optional[Engine] = None
    ) -> List[Dict[str, Any]]:
        """
        Dynamically inspects and returns all columns of a specified table.
        """
        eng = engine or get_engine()
        inspector = inspect(eng)
        existing_tables = inspector.get_table_names()

        if table_name not in existing_tables:
            raise ValueError(f"Table '{table_name}' does not exist in database.")

        raw_columns = inspector.get_columns(table_name)
        columns_data = []

        for col in raw_columns:
            columns_data.append(
                {
                    "name": col["name"],
                    "type": str(col["type"]),
                    "nullable": bool(col.get("nullable", True)),
                    "default": (
                        str(col["default"]) if col.get("default") is not None else None
                    ),
                    "primary_key": bool(col.get("primary_key", False)),
                }
            )

        return columns_data

    @classmethod
    def alter_column_default(
        cls,
        table_name: str,
        column_name: str,
        default_value: Any,
        backfill_existing: bool = True,
        engine: Optional[Engine] = None,
    ) -> Dict[str, Any]:
        """
        Modifies a column's default value constraint and optionally backfills existing NULL rows.
        Uses SQLite safe table recreation to apply the constraint.
        """
        eng = engine or get_engine()
        inspector = inspect(eng)
        existing_tables = inspector.get_table_names()

        if table_name not in existing_tables:
            raise ValueError(f"Table '{table_name}' does not exist.")

        col_defs = inspector.get_columns(table_name)
        matching_col = next(
            (c for c in col_defs if c["name"].lower() == column_name.lower()), None
        )
        if matching_col is None:
            raise ValueError(
                f"Column '{column_name}' does not exist in table '{table_name}'."
            )

        canonical_col_name = matching_col["name"]
        val_str = str(default_value).strip() if default_value is not None else "NULL"

        # Format SQL literal and typed representation for backfill
        sql_default_literal, typed_value = cls._format_default_literal(val_str)

        # 1. Rebuild SQLite Table with updated DEFAULT definition
        cls._rebuild_sqlite_table_with_new_default(
            eng, table_name, canonical_col_name, sql_default_literal
        )

        # 2. Backfill existing NULL records if requested
        backfilled_count = 0
        if backfill_existing and sql_default_literal != "NULL":
            with eng.begin() as conn:
                stmt = text(
                    f"UPDATE {table_name} SET {canonical_col_name} = :val WHERE {canonical_col_name} IS NULL"
                )
                res = conn.execute(stmt, {"val": typed_value})
                backfilled_count = res.rowcount or 0

        logger.info(
            "Altered column '%s' on table '%s': new default=%s, backfilled=%d",
            canonical_col_name,
            table_name,
            sql_default_literal,
            backfilled_count,
        )

        return {
            "success": True,
            "table": table_name,
            "column": canonical_col_name,
            "default_value": val_str,
            "default_literal": sql_default_literal,
            "backfilled_count": backfilled_count,
            "message": f"Default value for column '{canonical_col_name}' in table '{table_name}' updated successfully.",
        }

    @classmethod
    def _format_default_literal(cls, val_str: str) -> tuple[str, Any]:
        """
        Converts user input string into SQL literal and Python object for parameter binding.
        """
        upper = val_str.upper()
        if upper in ("NULL", "CURRENT_TIMESTAMP", "CURRENT_DATE", "CURRENT_TIME"):
            return upper, None
        if upper == "TRUE":
            return "1", True
        if upper == "FALSE":
            return "0", False

        # Attempt integer parsing
        try:
            int_val = int(val_str)
            return str(int_val), int_val
        except ValueError:
            pass

        # Attempt float parsing
        try:
            float_val = float(val_str)
            return str(float_val), float_val
        except ValueError:
            pass

        # Text literal: escape single quotes
        escaped = val_str.replace("'", "''")
        return f"'{escaped}'", val_str

    @classmethod
    def _rebuild_sqlite_table_with_new_default(
        cls, eng: Engine, table_name: str, column_name: str, default_literal: str
    ) -> None:
        """
        Performs atomic SQLite table recreation to alter column DEFAULT constraint.
        """
        raw_conn = eng.raw_connection()
        try:
            cur = raw_conn.cursor()
            cur.execute("PRAGMA foreign_keys=OFF;")

            # Get current table DDL
            cur.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
                (table_name,),
            )
            row = cur.fetchone()
            if not row or not row[0]:
                raise ValueError(
                    f"Could not retrieve CREATE TABLE DDL for '{table_name}'."
                )
            original_ddl = row[0]

            # Get secondary indexes
            cur.execute(
                "SELECT sql FROM sqlite_master WHERE type='index' AND tbl_name=? AND sql IS NOT NULL",
                (table_name,),
            )
            index_sqls = [r[0] for r in cur.fetchall()]

            # Update DDL with new default
            new_ddl = cls._update_ddl_column_default(
                original_ddl, column_name, default_literal
            )

            tmp_table = f"_yafr_tmp_{table_name}"
            tmp_ddl = re.sub(
                r"\bCREATE\s+TABLE\s+(\"?\w+\"?)",
                f"CREATE TABLE {tmp_table}",
                new_ddl,
                count=1,
                flags=re.IGNORECASE,
            )

            # Recreate table and copy data
            cur.execute(f"DROP TABLE IF EXISTS {tmp_table};")
            cur.execute(tmp_ddl)
            cur.execute(f"INSERT INTO {tmp_table} SELECT * FROM {table_name};")
            cur.execute(f"DROP TABLE {table_name};")
            cur.execute(f"ALTER TABLE {tmp_table} RENAME TO {table_name};")

            for isql in index_sqls:
                try:
                    cur.execute(isql)
                except Exception as idx_err:
                    logger.warning("Could not recreate index: %s (%s)", isql, idx_err)

            cur.execute("PRAGMA foreign_keys=ON;")
            raw_conn.commit()
        finally:
            raw_conn.close()

    @classmethod
    def _update_ddl_column_default(
        cls, ddl: str, column_name: str, default_literal: str
    ) -> str:
        """
        Parses CREATE TABLE DDL and updates the DEFAULT constraint for a column.
        """
        start_idx = ddl.find("(")
        end_idx = ddl.rfind(")")
        if start_idx == -1 or end_idx == -1:
            raise ValueError("Malformed CREATE TABLE statement.")

        prefix = ddl[: start_idx + 1]
        suffix = ddl[end_idx:]
        inner = ddl[start_idx + 1 : end_idx]

        parts = []
        current = []
        depth = 0
        in_single = False
        in_double = False

        for ch in inner:
            if ch == "'" and not in_double:
                in_single = not in_single
            elif ch == '"' and not in_single:
                in_double = not in_double
            elif not in_single and not in_double:
                if ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1
                elif ch == "," and depth == 0:
                    parts.append("".join(current).strip())
                    current = []
                    continue
            current.append(ch)

        if current:
            parts.append("".join(current).strip())

        found = False
        new_parts = []
        for part in parts:
            first_token = part.split(None, 1)[0].strip("\"'`[]")
            if first_token.lower() == column_name.lower():
                found = True
                cleaned = re.sub(
                    r"\s+DEFAULT\s+('[^']*'|\"[^\"]*\"|\S+)",
                    "",
                    part,
                    flags=re.IGNORECASE,
                )
                if default_literal != "NULL":
                    new_parts.append(f"{cleaned} DEFAULT {default_literal}")
                else:
                    new_parts.append(cleaned)
            else:
                new_parts.append(part)

        if not found:
            raise ValueError(
                f"Column '{column_name}' definition was not found in CREATE TABLE DDL."
            )

        return f"{prefix}\n\t" + ",\n\t".join(new_parts) + f"\n{suffix}"
