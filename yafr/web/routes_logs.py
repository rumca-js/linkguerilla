"""
Logs routes and view controller for YAFR.

Implements LogsView for displaying, filtering, and managing
application log entries from the applogging table.
"""

import math
from flask import Blueprint, render_template, request
from yafr.db import LoggingRepository, get_session

logs_bp = Blueprint("logs", __name__)

# Severity level filter options for the UI dropdown
LOG_LEVEL_FILTERS = [
    {"id": "all", "name": "All Levels", "level": None, "default": True},
    {"id": "debug", "name": "Debug", "level": LoggingRepository.DEBUG, "default": False},
    {"id": "info", "name": "Info", "level": LoggingRepository.INFO, "default": False},
    {
        "id": "notification",
        "name": "Notification",
        "level": LoggingRepository.NOTIFICATION,
        "default": False,
    },
    {"id": "warning", "name": "Warning", "level": LoggingRepository.WARNING, "default": False},
    {"id": "error", "name": "Error", "level": LoggingRepository.ERROR, "default": False},
    {"id": "critical", "name": "Critical", "level": LoggingRepository.CRITICAL, "default": False},
]

# Map filter IDs to minimum severity level values
_LEVEL_MAP = {f["id"]: f["level"] for f in LOG_LEVEL_FILTERS}


@logs_bp.route("/logs")
def logs_list():
    """
    Renders LogsView — a paginated, filterable view of application log entries.

    Query parameters:
        - level: Filter by minimum severity (all, debug, info, warning, error, critical)
        - page: Page number (1-indexed)
    """
    active_level = request.args.get("level", "all")
    page = max(1, request.args.get("page", 1, type=int))
    per_page = 50

    min_level = _LEVEL_MAP.get(active_level, None)

    session = get_session()
    log_repo = LoggingRepository(session)

    total_results = log_repo.count_logs(min_level=min_level)
    total_all_logs = total_results if active_level == "all" else log_repo.count_logs()
    active_filter = next((f for f in LOG_LEVEL_FILTERS if f["id"] == active_level), None)
    active_level_name = active_filter["name"] if active_filter else "All"

    total_pages = (
        max(1, math.ceil(total_results / per_page)) if total_results > 0 else 1
    )

    offset = (page - 1) * per_page
    logs = log_repo.list_logs(min_level=min_level, limit=per_page, offset=offset)

    return render_template(
        "logs/list.html",
        logs=logs,
        active_level=active_level,
        active_level_name=active_level_name,
        level_filters=LOG_LEVEL_FILTERS,
        total_results=total_results,
        total_all_logs=total_all_logs,
        page=page,
        total_pages=total_pages,
        per_page=per_page,
    )
