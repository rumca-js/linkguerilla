"""
RESTful JSON API endpoints for System Status, Indications, and Badges.

Provides lightweight JSON endpoints for checking overall application status,
UI indications (visibility and health), quantitative badges, and background
worker heartbeat via the systemoperation table.
"""

import logging
from flask import Blueprint, jsonify
from sqlalchemy import text
from yafr.db import (
    ConfigRepository,
    JobRepository,
    SourceRepository,
    get_session,
)
from yafr.db.system_operation_repository import (
    DEFAULT_WORKER_TIMEOUT_SECONDS,
    SystemOperationRepository,
)
from yafr.services.webtools_service import WebToolsWrapper

logger = logging.getLogger(__name__)

api_status_bp = Blueprint("api_status", __name__, url_prefix="/api/status")


@api_status_bp.route("", methods=["GET"])
@api_status_bp.route("/", methods=["GET"])
def system_status():
    """
    Returns full system status, component indications, and badges.

    Provides component-level indications (with visibility and health status)
    and quantitative badge counters across system components.
    """
    session = get_session()
    database_ok = False
    try:
        session.execute(text("SELECT 1"))
        database_ok = True
    except Exception as db_err:
        logger.debug("Database health check failed: %s", db_err)

    op_repo = SystemOperationRepository(session)
    worker_info = op_repo.check_worker_status(
        max_age_seconds=DEFAULT_WORKER_TIMEOUT_SECONDS
    )

    webtools_configured = False
    webtools_online = False
    try:
        wt_res = WebToolsWrapper.check_remote_status(session=session)
        webtools_configured = bool(wt_res.get("configured"))
        webtools_online = bool(wt_res.get("online"))
    except Exception as wt_err:
        logger.debug("WebTools health check failed: %s", wt_err)

    sources_outdated = 0
    sources_errors = 0
    try:
        source_repo = SourceRepository(session)
        sources_outdated = source_repo.count_outdated_sources()
        sources_errors = source_repo.count_error_sources()
    except Exception as src_err:
        logger.debug("Source counts check failed: %s", src_err)

    jobs_errors = 0
    try:
        job_repo = JobRepository(session)
        jobs_errors = job_repo.count_error_jobs()
    except Exception as job_err:
        logger.debug("Job errors count failed: %s", job_err)

    worker_visible = bool(worker_info.get("visible", False))
    worker_indication = {"visible": worker_visible}
    if worker_visible:
        worker_indication["active"] = bool(worker_info.get("is_active", False))
        worker_indication["message"] = worker_info.get("message", "")
    else:
        worker_indication["message"] = worker_info.get(
            "message", "Background jobs are disabled in configuration."
        )

    indications = {
        "worker": worker_indication,
        "webtools": {
            "visible": webtools_configured,
            "ok": webtools_online,
        },
        "database": {
            "ok": database_ok,
        },
        "sources": {
            "ok": sources_errors == 0,
        },
        "jobs": {
            "ok": jobs_errors == 0,
        },
    }

    badges = {
        "sources_outdated": sources_outdated,
        "sources_errors": sources_errors,
        "jobs_errors": jobs_errors,
    }

    return jsonify(
        {
            "success": True,
            "indications": indications,
            "badges": badges,
            "worker": worker_info,
        }
    )


@api_status_bp.route("/worker", methods=["GET"])
def worker_status():
    """
    Returns background worker liveness status based on the systemoperation table
    and background job configuration from configurationentry.

    A worker is considered visible if background jobs are enabled in configuration.
    If visible:
      - active if heartbeat is ok and within max_age_seconds (10 minutes)
      - dead if heartbeat is missing, stale, or marked not ok

    If not visible:
      - visible is False and status_label is 'disabled'.
    """
    try:
        session = get_session()
        repo = SystemOperationRepository(session)
        result = repo.check_worker_status(
            max_age_seconds=DEFAULT_WORKER_TIMEOUT_SECONDS
        )
        return jsonify(result)
    except Exception as err:
        logger.error("Failed to retrieve worker status: %s", err)
        enable_bg = True
        try:
            enable_bg = bool(
                ConfigRepository(get_session()).get_config().enable_background_jobs
            )
        except Exception:
            pass
        return (
            jsonify(
                {
                    "visible": enable_bg,
                    "is_active": False,
                    "status_label": "disabled" if not enable_bg else "dead",
                    "last_written": None,
                    "age_seconds": None,
                    "age_minutes": None,
                    "thread_id": "",
                    "check_type": "worker",
                    "message": f"Error retrieving worker status: {err}",
                    "max_age_seconds": DEFAULT_WORKER_TIMEOUT_SECONDS,
                }
            ),
            500,
        )
