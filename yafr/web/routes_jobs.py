"""
Jobs routes and view controller for YAFR.

Implements JobsView for viewing, filtering, sorting, and managing
background task jobs in the backgroundjob SQLite table.
"""

import math
from flask import Blueprint, flash, redirect, render_template, request, url_for
from yafr.db import get_session
from yafr.services import JobService

jobs_bp = Blueprint("jobs", __name__)

# Status filter options for the UI dropdown
STATUS_FILTERS = [
    {"id": "all", "name": "All Statuses"},
    {"id": "enabled", "name": "Active / Enabled"},
    {"id": "paused", "name": "Paused"},
    {"id": "errors", "name": "With Errors"},
]

# Sorting options
ORDER_OPTIONS = [
    {"id": "priority", "name": "Priority (Highest first)"},
    {"id": "date_created", "name": "Date Created (Newest first)"},
    {"id": "errors", "name": "Errors (Most failures)"},
    {"id": "enabled", "name": "Status (Active first)"},
]

HISTORY_ORDER_OPTIONS = [
    {"id": "date_created", "name": "Date Created (Newest first)"},
    {"id": "date_created_asc", "name": "Date Created (Oldest first)"},
    {"id": "id", "name": "ID (Highest first)"},
    {"id": "job", "name": "Job Type (A-Z)"},
]


@jobs_bp.route("/jobs")
def jobs_list():
    """
    Renders JobsView — a paginated, filterable, and sortable table of background jobs.

    Query parameters:
        - status: Filter by status ('all', 'enabled', 'paused', 'errors')
        - job_type: Filter by specific job type or 'all'
        - order_by: Sort column ('priority', 'date_created', 'errors', 'enabled')
        - page: Page number (1-indexed)
    """
    active_status = request.args.get("status", "all")
    active_type = request.args.get("job_type", "all")
    order_by = request.args.get("order_by", "priority")
    page = max(1, request.args.get("page", 1, type=int))
    per_page = 50

    # Parse filter criteria
    enabled_filter = None
    has_errors_filter = None

    if active_status == "enabled":
        enabled_filter = True
    elif active_status == "paused":
        enabled_filter = False
    elif active_status == "errors":
        has_errors_filter = True

    type_filter = None if active_type == "all" else active_type

    session = get_session()

    total_results = JobService.count_jobs(
        enabled=enabled_filter,
        has_errors=has_errors_filter,
        job_type=type_filter,
        session=session,
    )
    total_pages = (
        max(1, math.ceil(total_results / per_page)) if total_results > 0 else 1
    )

    offset = (page - 1) * per_page
    jobs = JobService.list_jobs(
        enabled=enabled_filter,
        order_by=order_by,
        limit=per_page,
        offset=offset,
        has_errors=has_errors_filter,
        job_type=type_filter,
        session=session,
    )

    distinct_job_types = JobService.get_job_types(session=session)
    error_jobs_count = JobService.count_error_jobs(session=session)
    total_jobs_in_db = JobService.count_jobs(session=session)

    return render_template(
        "jobs/list.html",
        jobs=jobs,
        active_status=active_status,
        active_type=active_type,
        order_by=order_by,
        status_filters=STATUS_FILTERS,
        order_options=ORDER_OPTIONS,
        job_types=distinct_job_types,
        total_results=total_results,
        error_jobs_count=error_jobs_count,
        total_jobs_in_db=total_jobs_in_db,
        page=page,
        total_pages=total_pages,
        per_page=per_page,
    )


@jobs_bp.route("/jobs/clear-all", methods=["POST"])
def jobs_clear_all():
    """
    Clears all background jobs and redirects to JobsView.
    """
    session = get_session()
    deleted_count = JobService.clear_all_jobs(session=session)
    flash(f"Successfully cleared all {deleted_count} jobs from the queue.", "success")
    return redirect(url_for("jobs.jobs_list"))


@jobs_bp.route("/jobs/clear-errors", methods=["POST"])
def jobs_clear_errors():
    """
    Clears all erroneous background jobs (errors > 0) and redirects to JobsView.
    """
    session = get_session()
    deleted_count = JobService.clear_error_jobs(session=session)
    flash(
        f"Successfully cleared {deleted_count} erroneous jobs from the queue.",
        "success",
    )
    return redirect(url_for("jobs.jobs_list"))


@jobs_bp.route("/jobs/history")
def jobs_history():
    """
    Renders JobHistoryView — a paginated table of historical completed background jobs.

    Query parameters:
        - job_type: Filter by specific job type or 'all'
        - order_by: Sort column ('date_created', 'date_created_asc', 'id', 'job')
        - page: Page number (1-indexed)
    """
    active_type = request.args.get("job_type", "all")
    order_by = request.args.get("order_by", "date_created")
    page = max(1, request.args.get("page", 1, type=int))
    per_page = 50

    type_filter = None if active_type == "all" else active_type

    session = get_session()

    total_results = JobService.count_history(
        job_type=type_filter,
        session=session,
    )
    total_pages = (
        max(1, math.ceil(total_results / per_page)) if total_results > 0 else 1
    )

    offset = (page - 1) * per_page
    history = JobService.list_history(
        order_by=order_by,
        limit=per_page,
        offset=offset,
        job_type=type_filter,
        session=session,
    )

    distinct_job_types = JobService.get_history_job_types(session=session)
    total_history_in_db = JobService.count_history(session=session)

    return render_template(
        "jobs/history.html",
        history=history,
        active_type=active_type,
        order_by=order_by,
        order_options=HISTORY_ORDER_OPTIONS,
        job_types=distinct_job_types,
        total_results=total_results,
        total_history_in_db=total_history_in_db,
        page=page,
        total_pages=total_pages,
        per_page=per_page,
    )


@jobs_bp.route("/jobs/history/clear", methods=["POST"])
def jobs_history_clear():
    """
    Clears all background job history records and redirects to JobHistoryView.
    """
    session = get_session()
    deleted_count = JobService.clear_history(session=session)
    flash(f"Successfully cleared {deleted_count} history records.", "success")
    return redirect(url_for("jobs.jobs_history"))
