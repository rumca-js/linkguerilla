"""
API endpoints for application log management.

Provides JSON API for listing, deleting individual, and clearing
all log entries from the applogging table.
"""

import logging
from typing import Any, Optional
from flask import Blueprint, request
from yafr.db import LoggingRepository, get_session
from yafr.web.shared import api_response

logger = logging.getLogger(__name__)

api_logs_bp = Blueprint("api_logs", __name__)


@api_logs_bp.route("/api/logs", methods=["GET"])
def api_list_logs():
    """
    Returns paginated log entries as JSON.

    Query parameters:
        - level: Minimum severity filter (10, 20, 30, 40, 50)
        - limit: Max results per page (default: 50)
        - offset: Pagination offset (default: 0)

    :return: JSON response with log entries and total count
    """
    try:
        min_level = request.args.get("level", None, type=int)
        limit = request.args.get("limit", 50, type=int)
        offset = request.args.get("offset", 0, type=int)

        session = get_session()
        log_repo = LoggingRepository(session)
        logs = log_repo.list_logs(min_level=min_level, limit=limit, offset=offset)
        total = log_repo.count_logs(min_level=min_level)

        return api_response(
            success=True,
            data={
                "logs": [
                    {
                        "id": log.id,
                        "info_text": log.info_text,
                        "detail_text": log.detail_text,
                        "level": log.level,
                        "level_name": _level_name(log.level),
                        "date": log.date.isoformat() if log.date else None,
                    }
                    for log in logs
                ],
                "total": total,
            },
        )
    except Exception as err:
        logger.error("Failed to list logs: %s", err)
        return api_response(success=False, error=str(err), status_code=500)


@api_logs_bp.route("/api/logs/<int:log_id>", methods=["DELETE"])
def api_delete_log(log_id: int):
    """
    Deletes a single log entry by ID.

    :param log_id: Primary key of the log entry
    :return: JSON success/failure response
    """
    try:
        session = get_session()
        log_repo = LoggingRepository(session)
        deleted = log_repo.delete_log(log_id)
        if not deleted:
            return api_response(
                success=False, error="Log entry not found", status_code=404
            )
        return api_response(success=True, message="Log entry deleted")
    except Exception as err:
        logger.error("Failed to delete log id=%d: %s", log_id, err)
        return api_response(success=False, error=str(err), status_code=500)


@api_logs_bp.route("/api/logs/clear", methods=["POST"])
def api_clear_logs():
    """
    Clears log entries from the applogging table.
    Supports clearing all entries or entries of a specific severity level.

    Optional body or query parameters:
        - level: Severity level to clear (e.g. 'info', 'debug', 'error', or 10, 20, 40).
                 If omitted or 'all', clears all entries.

    This is a destructive operation — the frontend must present
    a confirmation modal before calling this endpoint.

    :return: JSON response with count of deleted rows
    """
    try:
        level_arg = None
        if request.is_json and request.json:
            level_arg = request.json.get("level")
        if level_arg is None:
            level_arg = request.form.get("level") or request.args.get("level")

        level_int, error = LoggingRepository.parse_level(level_arg)
        if error:
            return api_response(success=False, error=error, status_code=400)

        session = get_session()
        log_repo = LoggingRepository(session)
        count = log_repo.clear_logs(level=level_int)

        level_str = (
            LoggingRepository.get_level_name(level_int)
            if level_int is not None
            else "All"
        )
        message = (
            f"Cleared {count} {level_str} log entries"
            if level_int is not None
            else f"Cleared {count} log entries"
        )
        return api_response(
            success=True,
            message=message,
            data={"deleted_count": count, "level": level_int},
        )
    except Exception as err:
        logger.error("Failed to clear logs: %s", err)
        return api_response(success=False, error=str(err), status_code=500)


def _parse_level(val: Any) -> tuple[Optional[int], Optional[str]]:
    """Delegates level parsing to LoggingRepository (single source of truth)."""
    return LoggingRepository.parse_level(val)


def _level_name(level: int) -> str:
    """Delegates level name mapping to LoggingRepository (single source of truth)."""
    return LoggingRepository.get_level_name(level)
