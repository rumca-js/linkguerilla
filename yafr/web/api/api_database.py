"""
RESTful JSON API endpoints for Database and Storage management.

Implements small, focused server endpoints returning JSON responses for database
statistics, table row counts, clearing specific cache tables, renaming instance,
and downloading & atomically replacing database files from a remote URL.
"""

import logging
from flask import Blueprint, jsonify, request
from yafr.db import get_session
from yafr.services import DatabaseService
from yafr.web.shared import api_response

logger = logging.getLogger(__name__)

api_database_bp = Blueprint("api_database", __name__, url_prefix="/api/database")


@api_database_bp.route("/stats", methods=["GET"])
def get_stats():
    """
    Retrieves active database table row counts, storage metrics, and file information.
    """
    try:
        session = get_session()
        db_info = DatabaseService.get_database_info(session=session)
        return jsonify(
            {
                "success": True,
                "database_file": db_info["database_file"],
                "database_name": db_info["database_name"],
                "database_type": db_info["database_type"],
                "file_size_bytes": db_info["file_size_bytes"],
                "file_size_formatted": db_info["file_size_formatted"],
                "date_created": db_info["date_created"],
                "date_last_modified": db_info["date_last_modified"],
                "date_last_refresh": db_info["date_last_refresh"],
                "tables": db_info["tables"],
                "tables_detailed": db_info["tables_detailed"],
            }
        )
    except Exception as err:
        logger.error("Failed to retrieve database stats: %s", err)
        return api_response(success=False, error=str(err), status_code=500)


@api_database_bp.route("/update-name", methods=["POST"])
def update_name():
    """
    Updates the database display title in configurationentry.
    """
    try:
        payload = request.get_json(silent=True) or request.form.to_dict()
        new_name = payload.get("instance_title", "").strip()
        if not new_name:
            return api_response(
                success=False,
                error="Database display name cannot be empty.",
                status_code=400,
            )

        session = get_session()
        updated_title = DatabaseService.update_database_name(new_name, session=session)
        return jsonify(
            {
                "success": True,
                "instance_title": updated_title,
                "message": f"Database name updated to '{updated_title}'.",
            }
        )
    except Exception as err:
        logger.error("Failed to update database display name: %s", err)
        return api_response(success=False, error=str(err), status_code=500)


@api_database_bp.route("/clear-search-history", methods=["POST"])
def clear_search_history():
    """
    Truncates searchhistory table.
    """
    try:
        session = get_session()
        count = DatabaseService.clear_search_history(session=session)
        return jsonify(
            {
                "success": True,
                "message": "Search history cleared.",
                "deleted_count": count,
            }
        )
    except Exception as err:
        logger.error("Failed to clear search history: %s", err)
        return api_response(success=False, error=str(err), status_code=500)


@api_database_bp.route("/clear-visited", methods=["POST"])
def clear_visited():
    """
    Truncates entryvisithistory table.
    """
    try:
        session = get_session()
        count = DatabaseService.clear_visited_entries(session=session)
        return jsonify(
            {
                "success": True,
                "message": "Visit history cleared.",
                "deleted_count": count,
            }
        )
    except Exception as err:
        logger.error("Failed to clear visited entries: %s", err)
        return api_response(success=False, error=str(err), status_code=500)


@api_database_bp.route("/clear-read-later", methods=["POST"])
def clear_read_later():
    """
    Truncates readlater table.
    """
    try:
        session = get_session()
        count = DatabaseService.clear_read_later(session=session)
        return jsonify(
            {
                "success": True,
                "message": "Read later list cleared.",
                "deleted_count": count,
            }
        )
    except Exception as err:
        logger.error("Failed to clear read later list: %s", err)
        return api_response(success=False, error=str(err), status_code=500)


@api_database_bp.route("/clear-social-data", methods=["POST"])
def clear_social_data():
    """
    Truncates socialdata table.
    """
    try:
        session = get_session()
        count = DatabaseService.clear_social_data(session=session)
        return jsonify(
            {
                "success": True,
                "message": "Social data cleared.",
                "deleted_count": count,
            }
        )
    except Exception as err:
        logger.error("Failed to clear social data: %s", err)
        return api_response(success=False, error=str(err), status_code=500)


@api_database_bp.route("/clear-sources", methods=["POST"])
def clear_sources():
    """
    Truncates all source-related tables: sourcedatamodel, sourceoperationaldata,
    sourcecategories, and sourcesubcategories. Entries are unlinked but not deleted.
    """
    try:
        session = get_session()
        counts = DatabaseService.clear_sources(session=session)
        total = sum(counts.values())
        return jsonify(
            {
                "success": True,
                "message": "All source data cleared.",
                "deleted_count": total,
                "deleted_counts": counts,
            }
        )
    except Exception as err:
        logger.error("Failed to clear sources: %s", err)
        return api_response(success=False, error=str(err), status_code=500)


@api_database_bp.route("/clear-links", methods=["POST"])
def clear_links():
    """
    Truncates linkdatamodel and all tables that depend on it
    (tags, social data, read later, visit history, transition history).
    """
    try:
        session = get_session()
        counts = DatabaseService.clear_links(session=session)
        total = sum(counts.values())
        return jsonify(
            {
                "success": True,
                "message": "All links and dependent data cleared.",
                "deleted_count": total,
                "deleted_counts": counts,
            }
        )
    except Exception as err:
        logger.error("Failed to clear links: %s", err)
        return api_response(success=False, error=str(err), status_code=500)


@api_database_bp.route("/replace-from-url", methods=["POST"])
def replace_from_url():
    """
    Downloads a remote SQLite database file from a URL, validates integrity,
    and atomically swaps it with the current active database.
    """
    try:
        payload = request.get_json(silent=True) or request.form.to_dict()
        remote_url = payload.get("remote_url", "").strip()
        if not remote_url:
            return api_response(
                success=False, error="Remote database URL is required.", status_code=400
            )

        result = DatabaseService.replace_database_from_url(remote_url)
        return jsonify(result)
    except ValueError as val_err:
        return api_response(success=False, error=str(val_err), status_code=400)
    except Exception as err:
        logger.error("Failed to replace database from URL: %s", err)
        return api_response(success=False, error=str(err), status_code=500)


@api_database_bp.route("/truncate-table/<table_name>", methods=["POST"])
def truncate_table(table_name: str):
    """
    Truncates all rows in the specified database table.

    :param table_name: Name of the table to truncate.
    """
    try:
        session = get_session()
        count = DatabaseService.truncate_table(table_name, session=session)
        return jsonify(
            {
                "success": True,
                "table": table_name,
                "message": f"Table '{table_name}' truncated.",
                "deleted_count": count,
            }
        )
    except ValueError as val_err:
        return api_response(success=False, error=str(val_err), status_code=400)
    except Exception as err:
        logger.error("Failed to truncate table %s: %s", table_name, err)
        return api_response(success=False, error=str(err), status_code=500)


@api_database_bp.route("/tables", methods=["GET"])
def get_tables():
    """
    Dynamically returns all discovered database tables with row counts and metadata.
    """
    try:
        tables = DatabaseService.get_known_tables()
        return jsonify({"success": True, "tables": tables})
    except Exception as err:
        logger.error("Failed to retrieve database tables: %s", err)
        return api_response(success=False, error=str(err), status_code=500)


@api_database_bp.route("/tables/<table_name>/columns", methods=["GET"])
def get_columns(table_name: str):
    """
    Dynamically inspects and returns all columns of a specified table.
    """
    try:
        columns = DatabaseService.get_table_columns(table_name)
        return jsonify({"success": True, "table": table_name, "columns": columns})
    except ValueError as val_err:
        return api_response(success=False, error=str(val_err), status_code=404)
    except Exception as err:
        logger.error("Failed to retrieve columns for table %s: %s", table_name, err)
        return api_response(success=False, error=str(err), status_code=500)


@api_database_bp.route("/alter-column-default", methods=["POST"])
def alter_column_default():
    """
    Modifies a column's default value constraint and optionally backfills existing NULL rows.
    """
    try:
        payload = request.get_json(silent=True) or request.form.to_dict()
        table_name = payload.get("table", "").strip()
        column_name = payload.get("column", "").strip()
        default_value = payload.get("default_value")
        backfill_existing = payload.get("backfill_existing", True)
        nullable_param = payload.get("nullable")

        if isinstance(backfill_existing, str):
            backfill_existing = backfill_existing.lower() in ("true", "1", "yes", "on")

        nullable = None
        if nullable_param is not None:
            if isinstance(nullable_param, str):
                if nullable_param.lower() in ("true", "1", "yes", "nullable"):
                    nullable = True
                elif nullable_param.lower() in ("false", "0", "no", "not_null"):
                    nullable = False
            elif isinstance(nullable_param, bool):
                nullable = nullable_param

        if not table_name:
            return api_response(
                success=False, error="Target table name is required.", status_code=400
            )
        if not column_name:
            return api_response(
                success=False, error="Target column name is required.", status_code=400
            )

        result = DatabaseService.alter_column_default(
            table_name=table_name,
            column_name=column_name,
            default_value=default_value,
            nullable=nullable,
            backfill_existing=backfill_existing,
        )
        return jsonify(result)
    except ValueError as val_err:
        return api_response(success=False, error=str(val_err), status_code=400)
    except Exception as err:
        logger.error("Failed to alter column default: %s", err)
        return api_response(success=False, error=str(err), status_code=500)
