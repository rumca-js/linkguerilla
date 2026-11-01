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


@api_status_bp.route("/worker", methods=["GET"])
def worker_status():
    """
    Returns background worker liveness status based on the systemoperation table.

    A worker is considered active if:
    - A row exists in systemoperation with status=True (ok).
    - Its date_created timestamp is within the last 10 minutes.

    If the row is missing, status=False, or older than 10 minutes, worker is 'dead'.

    Response:
        {
            "is_active": true,
            "status_label": "active",
            "last_written": "2026-10-18T18:05:00+00:00",
            "age_seconds": 42.1,
            "age_minutes": 0.7,
            "thread_id": "12345",
            "check_type": "worker",
            "message": "Worker is active and ok (last heartbeat 42.1s ago).",
            "max_age_seconds": 600
        }
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
        return (
            jsonify(
                {
                    "is_active": False,
                    "status_label": "dead",
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
