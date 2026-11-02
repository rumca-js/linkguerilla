"""
RESTful JSON API endpoints for System Status and Worker Liveness.

Provides lightweight JSON endpoints for checking the background worker
heartbeat status via the systemoperation SQLite table.
"""

import logging
from flask import Blueprint, jsonify
from yafr.db import get_session
from yafr.db.system_operation_repository import (
    DEFAULT_WORKER_TIMEOUT_SECONDS,
    SystemOperationRepository,
)

logger = logging.getLogger(__name__)

api_status_bp = Blueprint("api_status", __name__, url_prefix="/api/status")


"""
RESTful JSON API endpoints for System Status and Worker Liveness.

Provides lightweight JSON endpoints for checking overall application status,
operational health flags, and background worker heartbeat via systemoperation.
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
    Returns full system status and operational health flags.

    Provides a comprehensive dictionary of boolean flags representing what works
    or does not work across system components, which can be translated directly
    into UI badges and status indicators.
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
    worker_flags = worker_info.get("flags", {})

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

    flags = {
        "worker_active": bool(worker_flags.get("worker_active")),
        "worker_dead": bool(worker_flags.get("worker_dead")),
        "background_jobs_enabled": bool(worker_flags.get("background_jobs_enabled")),
        "webtools_configured": webtools_configured,
        "webtools_online": webtools_online,
        "database_ok": database_ok,
        "sources_ok": sources_errors == 0,
        "jobs_ok": jobs_errors == 0,
    }

    badges = {
        "sources_outdated": sources_outdated,
        "sources_errors": sources_errors,
        "jobs_errors": jobs_errors,
    }

    return jsonify(
        {
            "success": True,
            "flags": flags,
            "worker": worker_info,
            "badges": badges,
        }
    )


@api_status_bp.route("/worker", methods=["GET"])
def worker_status():
    """
    Returns background worker liveness status based on the systemoperation table
    and background job configuration from configurationentry.

    A worker is considered active if:
    - A row exists in systemoperation with status=True (ok).
    - Its date_created timestamp is within the last 10 minutes.

    If the row is missing, status=False, or older than 10 minutes:
    - If enable_background_jobs is True, worker is 'dead'.
    - If enable_background_jobs is False, worker is 'disabled'.

    Response includes operational flags:
        flags.worker_active: bool
        flags.worker_dead: bool
        flags.background_jobs_enabled: bool
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
                    "is_active": False,
                    "status_label": "disabled" if not enable_bg else "dead",
                    "enable_background_jobs": enable_bg,
                    "flags": {
                        "worker_active": False,
                        "worker_dead": bool(enable_bg),
                        "background_jobs_enabled": enable_bg,
                    },
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
