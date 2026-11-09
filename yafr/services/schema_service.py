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
        nullable: Optional[bool] = None,
        backfill_existing: bool = True,
        engine: Optional[Engine] = None,
    ) -> Dict[str, Any]:
        """
        Modifies a column's default value constraint and nullability (NOT NULL),
        optionally backfilling existing NULL rows.
        Uses SQLite safe table recreation to apply the constraints.
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

        # 1. Backfill existing NULL records if requested or if column is becoming NOT NULL
        backfilled_count = 0
        if (backfill_existing or nullable is False) and sql_default_literal != "NULL":
            with eng.begin() as conn:
                stmt = text(
                    f"UPDATE {table_name} SET {canonical_col_name} = :val WHERE {canonical_col_name} IS NULL"
                )
                res = conn.execute(stmt, {"val": typed_value})
                backfilled_count = res.rowcount or 0
        elif nullable is False:
            with eng.connect() as conn:
                null_count = (
                    conn.execute(
                        text(
                            f"SELECT COUNT(*) FROM {table_name} WHERE {canonical_col_name} IS NULL"
                        )
                    ).scalar()
                    or 0
                )
                if null_count > 0:
                    raise ValueError(
                        f"Cannot set NOT NULL on column '{canonical_col_name}': {null_count} rows have NULL values and no default value was provided to backfill."
                    )

        # 2. Rebuild SQLite Table with updated DEFAULT and NOT NULL definition
        cls._rebuild_sqlite_table_with_new_default(
            eng,
            table_name,
            canonical_col_name,
            sql_default_literal,
            nullable=nullable,
        )

        logger.info(
            "Altered column '%s' on table '%s': new default=%s, nullable=%s, backfilled=%d",
            canonical_col_name,
            table_name,
            sql_default_literal,
            nullable,
            backfilled_count,
        )

        return {
            "success": True,
            "table": table_name,
            "column": canonical_col_name,
            "default_value": val_str,
            "default_literal": sql_default_literal,
            "nullable": nullable,
            "backfilled_count": backfilled_count,
            "message": f"Column '{canonical_col_name}' in table '{table_name}' updated successfully.",
        }

    @classmethod
    def get_schema_diff(
        cls,
        table_name: str,
        engine: Optional[Engine] = None,
    ) -> Dict[str, Any]:
        """
        Compares an active SQLite database table against linkarchivetools.model.definitions.
        Returns missing columns, extra columns to remove, and columns with defaults that can be reapplied.
        """
        import linkarchivetools.model.definitions as model_definitions

        eng = engine or get_engine()
        defined_table = model_definitions.Base.metadata.tables.get(table_name.lower())

        if defined_table is None:
            return {
                "table_name": table_name,
                "defined_in_models": False,
                "exists_in_db": True,
                "is_synced": True,
                "columns_to_add": [],
                "columns_to_remove": [],
                "defaults_to_reapply": [],
                "message": f"Table '{table_name}' has no model in linkarchivetools.model.definitions.",
            }

        inspector = inspect(eng)
        existing_tables = inspector.get_table_names()
        exists_in_db = table_name in existing_tables

        if not exists_in_db:
            columns_to_add = [
                {
                    "name": col.name,
                    "type": str(col.type),
                    "nullable": bool(col.nullable),
                    "default": (
                        str(col.server_default.arg).strip("'\"")
                        if col.server_default is not None
                        else None
                    ),
                }
                for col in defined_table.columns
            ]
            return {
                "table_name": table_name,
                "defined_in_models": True,
                "exists_in_db": False,
                "is_synced": False,
                "columns_to_add": columns_to_add,
                "columns_to_remove": [],
                "defaults_to_reapply": [],
                "total_null_defaults": 0,
                "message": f"Table '{table_name}' does not exist in database.",
            }

        raw_cols = inspector.get_columns(table_name)
        existing_by_name = {c["name"].lower(): c for c in raw_cols}
        defined_by_name = {c.name.lower(): c for c in defined_table.columns}

        columns_to_add = []
        for col in defined_table.columns:
            if col.name.lower() not in existing_by_name:
                columns_to_add.append(
                    {
                        "name": col.name,
                        "type": str(col.type),
                        "nullable": bool(col.nullable),
                        "default": (
                            str(col.server_default.arg).strip("'\"")
                            if col.server_default is not None
                            else None
                        ),
                    }
                )

        columns_to_remove = []
        for c in raw_cols:
            if c["name"].lower() not in defined_by_name:
                columns_to_remove.append(
                    {
                        "name": c["name"],
                        "type": str(c["type"]),
                    }
                )

        defaults_to_reapply = []
        with eng.connect() as conn:
            for col in defined_table.columns:
                if (
                    col.server_default is not None
                    and col.name.lower() in existing_by_name
                ):
                    actual_col_name = existing_by_name[col.name.lower()]["name"]
                    def_val = str(col.server_default.arg).strip("'\"")
                    null_count = 0
                    try:
                        null_count = (
                            conn.execute(
                                text(
                                    f'SELECT COUNT(*) FROM "{table_name}" WHERE "{actual_col_name}" IS NULL'
                                )
                            ).scalar()
                            or 0
                        )
                    except Exception:
                        null_count = 0

                    defaults_to_reapply.append(
                        {
                            "name": col.name,
                            "default": def_val,
                            "null_count": null_count,
                        }
                    )

        total_null_defaults = sum(d["null_count"] for d in defaults_to_reapply)
        is_synced = (
            len(columns_to_add) == 0
            and len(columns_to_remove) == 0
            and total_null_defaults == 0
        )

        return {
            "table_name": table_name,
            "defined_in_models": True,
            "exists_in_db": True,
            "is_synced": is_synced,
            "columns_to_add": columns_to_add,
            "columns_to_remove": columns_to_remove,
            "defaults_to_reapply": defaults_to_reapply,
            "total_null_defaults": total_null_defaults,
        }

    @classmethod
    def fix_table_schema(
        cls,
        table_name: str,
        reapply_defaults: bool = True,
        engine: Optional[Engine] = None,
    ) -> Dict[str, Any]:
        """
        Synchronizes an outdated SQLite table to match linkarchivetools.model.definitions:
        - Drops columns that are not defined in definitions.py
        - Adds missing columns defined in definitions.py
        - Reapplies default constraints and backfills existing NULL entries if reapply_defaults=True
        - Recreates defined indexes and preserves custom secondary indexes
        """
        import linkarchivetools.model.definitions as model_definitions
        from sqlalchemy.schema import CreateIndex, CreateTable

        eng = engine or get_engine()
        defined_table = model_definitions.Base.metadata.tables.get(table_name.lower())
        if defined_table is None:
            raise ValueError(
                f"Table '{table_name}' is not defined in linkarchivetools.model.definitions."
            )

        diff = cls.get_schema_diff(table_name, engine=eng)

        # Case 1: Table doesn't exist in DB at all
        if not diff.get("exists_in_db", False):
            with eng.begin() as conn:
                defined_table.create(conn)
            return {
                "success": True,
                "table": table_name,
                "created": True,
                "columns_added": [c["name"] for c in diff.get("columns_to_add", [])],
                "columns_removed": [],
                "defaults_applied": 0,
                "message": f"Table '{table_name}' was missing and has been created according to definitions.",
            }

        # Case 2: Table exists in DB -> Rebuild using defined schema
        raw_conn = eng.raw_connection()
        defaults_applied_count = 0
        try:
            cur = raw_conn.cursor()
            cur.execute("PRAGMA foreign_keys=OFF;")

            tmp_table = f"_yafr_tmp_{table_name}"
            cur.execute(f'DROP TABLE IF EXISTS "{tmp_table}";')

            # Compile authoritative DDL from definitions
            compiled_ddl = str(CreateTable(defined_table).compile(eng)).strip()
            tmp_ddl = re.sub(
                r"\bCREATE\s+TABLE\s+([\"\`']?\w+[\"\`']?)",
                f'CREATE TABLE "{tmp_table}"',
                compiled_ddl,
                count=1,
                flags=re.IGNORECASE,
            )
            cur.execute(tmp_ddl)

            # Inspect columns in current table
            inspector = inspect(eng)
            existing_cols = {
                c["name"].lower(): c["name"] for c in inspector.get_columns(table_name)
            }
            common_cols = [
                (col.name, existing_cols[col.name.lower()])
                for col in defined_table.columns
                if col.name.lower() in existing_cols
            ]

            if common_cols:
                target_cols_str = ", ".join(f'"{target}"' for target, _ in common_cols)
                source_cols_str = ", ".join(f'"{source}"' for _, source in common_cols)
                cur.execute(
                    f'INSERT INTO "{tmp_table}" ({target_cols_str}) SELECT {source_cols_str} FROM "{table_name}";'
                )

            # Reapply defaults on NULL fields
            if reapply_defaults:
                for col in defined_table.columns:
                    def_val = None
                    if col.server_default is not None:
                        def_val = str(col.server_default.arg).strip("'\"")
                    elif col.default is not None and col.default.is_scalar:
                        def_val = str(col.default.arg)

                    if def_val is not None:
                        sql_literal, _ = cls._format_default_literal(def_val)
                        cur.execute(
                            f'UPDATE "{tmp_table}" SET "{col.name}" = {sql_literal} WHERE "{col.name}" IS NULL;'
                        )
                        defaults_applied_count += (
                            cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
                        )

            # Fetch existing secondary index DDLs from sqlite_master
            cur.execute(
                "SELECT sql FROM sqlite_master WHERE type='index' AND tbl_name=? AND sql IS NOT NULL",
                (table_name,),
            )
            existing_index_sqls = [r[0] for r in cur.fetchall()]

            # Swap tables
            cur.execute(f'DROP TABLE "{table_name}";')
            cur.execute(f'ALTER TABLE "{tmp_table}" RENAME TO "{table_name}";')

            # Recreate defined indexes
            for idx in defined_table.indexes:
                try:
                    idx_ddl = str(CreateIndex(idx).compile(eng))
                    cur.execute(idx_ddl)
                except Exception as idx_err:
                    logger.warning(
                        "Could not create defined index on %s: %s", table_name, idx_err
                    )

            # Recreate custom index DDLs if possible
            for isql in existing_index_sqls:
                try:
                    cur.execute(isql)
                except Exception:
                    pass

            cur.execute("PRAGMA foreign_keys=ON;")
            raw_conn.commit()
        finally:
            raw_conn.close()

        cols_added_names = [c["name"] for c in diff.get("columns_to_add", [])]
        cols_removed_names = [c["name"] for c in diff.get("columns_to_remove", [])]

        return {
            "success": True,
            "table": table_name,
            "created": False,
            "columns_added": cols_added_names,
            "columns_removed": cols_removed_names,
            "defaults_applied": defaults_applied_count,
            "message": (
                f"Table '{table_name}' fixed: "
                f"+{len(cols_added_names)} cols added, "
                f"-{len(cols_removed_names)} cols removed, "
                f"{defaults_applied_count} defaults reapplied."
            ),
        }

    @classmethod
    def fix_all_tables(
        cls,
        reapply_defaults: bool = True,
        engine: Optional[Engine] = None,
    ) -> Dict[str, Any]:
        """
        Scans all tables defined in linkarchivetools.model.definitions and fixes any outdated tables.
        """
        import linkarchivetools.model.definitions as model_definitions

        eng = engine or get_engine()
        results = []
        fixed_count = 0

        for table_name in sorted(model_definitions.Base.metadata.tables.keys()):
            diff = cls.get_schema_diff(table_name, engine=eng)
            if not diff.get("is_synced", True):
                res = cls.fix_table_schema(
                    table_name, reapply_defaults=reapply_defaults, engine=eng
                )
                results.append(res)
                fixed_count += 1

        return {
            "success": True,
            "fixed_count": fixed_count,
            "results": results,
            "message": f"Fixed {fixed_count} outdated table(s).",
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
        cls,
        eng: Engine,
        table_name: str,
        column_name: str,
        default_literal: str,
        nullable: Optional[bool] = None,
    ) -> None:
        """
        Performs atomic SQLite table recreation to alter column DEFAULT constraint and nullability.
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

            # Update DDL with new default and nullability
            new_ddl = cls._update_ddl_column_default(
                original_ddl, column_name, default_literal, nullable=nullable
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
        cls,
        ddl: str,
        column_name: str,
        default_literal: str,
        nullable: Optional[bool] = None,
    ) -> str:
        """
        Parses CREATE TABLE DDL and updates the DEFAULT constraint and NOT NULL for a column.
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
                if nullable is False:
                    # Enforce NOT NULL
                    if not re.search(r"\bNOT\s+NULL\b", cleaned, re.IGNORECASE):
                        cleaned = f"{cleaned} NOT NULL"
                elif nullable is True:
                    # Remove NOT NULL
                    cleaned = re.sub(
                        r"\s+NOT\s+NULL\b", "", cleaned, flags=re.IGNORECASE
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
