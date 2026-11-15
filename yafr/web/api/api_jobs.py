"""
RESTful JSON API endpoints for Background Job management.

Implements small, focused server endpoints returning JSON responses for creating,
pausing, resuming, deleting, and batch-managing background jobs.
"""

import json
import logging
from flask import Blueprint, jsonify, request
from yafr.db import get_session
from yafr.services import JobService
from yafr.web.shared import api_response

logger = logging.getLogger(__name__)

api_jobs_bp = Blueprint("api_jobs", __name__, url_prefix="/api/jobs")


@api_jobs_bp.route("", methods=["GET"])
def list_jobs_api():
    """
    Returns a paginated list of background jobs as JSON.
    """
    try:
        active_status = request.args.get("status", "all")
        active_type = request.args.get("job_type", "all")
        order_by = request.args.get("order_by", "priority")
        page = max(1, request.args.get("page", 1, type=int))
        limit = max(1, min(request.args.get("limit", 50, type=int), 200))
        offset = (page - 1) * limit

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
        total = JobService.count_jobs(
            enabled=enabled_filter,
            has_errors=has_errors_filter,
            job_type=type_filter,
            session=session,
        )
        jobs = JobService.list_jobs(
            enabled=enabled_filter,
            order_by=order_by,
            limit=limit,
            offset=offset,
            has_errors=has_errors_filter,
            job_type=type_filter,
            session=session,
        )

        return api_response(
            success=True,
            data={
                "jobs": [
                    {
                        "id": j.id,
                        "job": j.job,
                        "subject": j.subject,
                        "task": j.task,
                        "args": j.args,
                        "priority": j.priority,
                        "errors": j.errors or 0,
                        "enabled": bool(j.enabled),
                        "date_created": (
                            j.date_created.isoformat() if j.date_created else None
                        ),
                    }
                    for j in jobs
                ],
                "total": total,
                "page": page,
                "limit": limit,
            },
        )
    except Exception as err:
        logger.error("Failed to list jobs via API: %s", err)
        return api_response(success=False, error=str(err), status_code=500)


@api_jobs_bp.route("/create", methods=["POST"])
def create_job():
    """
    Creates/enqueues a new background job.

    Request JSON / Form:
        - job: Job type identifier (required)
        - subject: Target resource string (required)
        - priority: Integer priority (default: 1)
        - task: Optional sub-task
        - args: Optional argument string / JSON
        - enabled: Boolean flag (default: True)
    """
    try:
        data = request.get_json(silent=True) or request.form.to_dict()
        job = data.get("job", "").strip()
        subject = data.get("subject", "").strip()

        if not job:
            return api_response(
                success=False, error="Job type ('job') is required", status_code=400
            )
        if not subject:
            return api_response(
                success=False, error="Job subject is required", status_code=400
            )

        priority = int(data.get("priority", 1))
        task = data.get("task", "").strip() or None
        args = data.get("args")
        if isinstance(args, dict):
            args = json.dumps(args)
        elif isinstance(args, str):
            args = args.strip() or None

        raw_enabled = data.get("enabled", True)
        if isinstance(raw_enabled, str):
            enabled = raw_enabled.lower() in ("true", "1", "yes", "on")
        else:
            enabled = bool(raw_enabled)

        session = get_session()
        existing = JobService.find_job(
            job=job,
            subject=subject,
            task=task,
            args=args,
            session=session,
        )
        if existing:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": f"A job with identical properties already exists in the queue (Job #{existing.id}).",
                        "job_id": existing.id,
                    }
                ),
                409,
            )

        created_job = JobService.create_job(
            job=job,
            subject=subject,
            task=task,
            args=args,
            priority=priority,
            enabled=enabled,
            session=session,
        )

        return (
            jsonify(
                {
                    "success": True,
                    "job_id": created_job.id,
                    "message": f"Job #{created_job.id} created successfully.",
                }
            ),
            201,
        )
    except Exception as err:
        logger.error("Failed to create job: %s", err)
        return api_response(success=False, error=str(err), status_code=500)


@api_jobs_bp.route("/<int:job_id>/pause", methods=["POST"])
def pause_job(job_id: int):
    """
    Pauses an active background job (enabled = False).
    """
    try:
        session = get_session()
        job = JobService.get_job(job_id, session=session)
        if not job:
            return api_response(success=False, error="Job not found", status_code=404)

        success = JobService.pause_job(job_id, session=session)
        if not success:
            return api_response(
                success=False, error="Failed to pause job", status_code=500
            )

        return jsonify({"success": True, "job_id": job_id, "enabled": False})
    except Exception as err:
        logger.error("Failed to pause job %d: %s", job_id, err)
        return api_response(success=False, error=str(err), status_code=500)


@api_jobs_bp.route("/<int:job_id>/resume", methods=["POST"])
def resume_job(job_id: int):
    """
    Resumes a paused background job (enabled = True).
    """
    try:
        session = get_session()
        job = JobService.get_job(job_id, session=session)
        if not job:
            return api_response(success=False, error="Job not found", status_code=404)

        success = JobService.resume_job(job_id, session=session)
        if not success:
            return api_response(
                success=False, error="Failed to resume job", status_code=500
            )

        return jsonify({"success": True, "job_id": job_id, "enabled": True})
    except Exception as err:
        logger.error("Failed to resume job %d: %s", job_id, err)
        return api_response(success=False, error=str(err), status_code=500)


@api_jobs_bp.route("/<int:job_id>", methods=["DELETE"])
def delete_job(job_id: int):
    """
    Deletes a background job from the queue.
    """
    try:
        session = get_session()
        job = JobService.get_job(job_id, session=session)
        if not job:
            return api_response(success=False, error="Job not found", status_code=404)

        success = JobService.delete_job(job_id, session=session)
        if not success:
            return api_response(
                success=False, error="Failed to delete job", status_code=500
            )

        return jsonify({"success": True, "deleted_job_id": job_id})
    except Exception as err:
        logger.error("Failed to delete job %d: %s", job_id, err)
        return api_response(success=False, error=str(err), status_code=500)


@api_jobs_bp.route("/batch-action", methods=["POST"])
def batch_action():
    """
    Executes pause, resume, or delete across multiple selected jobs.

    Request Body:
        { "job_ids": [101, 102], "action": "pause" }
    """
    try:
        payload = request.get_json(silent=True) or {}
        job_ids = payload.get("job_ids", [])
        action = payload.get("action", "").strip().lower()

        if not isinstance(job_ids, list) or not job_ids:
            return api_response(
                success=False, error="Invalid or empty job_ids list", status_code=400
            )

        if action not in ("pause", "resume", "delete"):
            return api_response(
                success=False,
                error=f"Invalid action '{action}'. Supported actions: pause, resume, delete",
                status_code=400,
            )

        session = get_session()
        affected_count = JobService.batch_action(
            job_ids, action=action, session=session
        )

        return jsonify(
            {
                "success": True,
                "affected_count": affected_count,
                "action": action,
                "message": f"Successfully performed '{action}' on {affected_count} jobs.",
            }
        )
    except Exception as err:
        logger.error("Failed to execute batch job action: %s", err)
        return api_response(success=False, error=str(err), status_code=500)


@api_jobs_bp.route("/clear-all", methods=["POST"])
def clear_all_jobs():
    """
    Clears all background jobs from the queue.
    """
    try:
        session = get_session()
        deleted_count = JobService.clear_all_jobs(session=session)
        return jsonify(
            {
                "success": True,
                "deleted_count": deleted_count,
                "message": f"Successfully cleared all {deleted_count} jobs.",
            }
        )
    except Exception as err:
        logger.error("Failed to clear all jobs: %s", err)
        return api_response(success=False, error=str(err), status_code=500)


@api_jobs_bp.route("/clear-errors", methods=["POST"])
def clear_error_jobs():
    """
    Clears all erroneous background jobs (errors > 0) from the queue.
    """
    try:
        session = get_session()
        deleted_count = JobService.clear_error_jobs(session=session)
        return jsonify(
            {
                "success": True,
                "deleted_count": deleted_count,
                "message": f"Successfully cleared {deleted_count} erroneous jobs.",
            }
        )
    except Exception as err:
        logger.error("Failed to clear error jobs: %s", err)
        return api_response(success=False, error=str(err), status_code=500)


@api_jobs_bp.route("/history", methods=["GET"])
def list_history_api():
    """
    Returns a paginated list of historical completed background jobs as JSON.
    """
    try:
        active_type = request.args.get("job_type", "all")
        order_by = request.args.get("order_by", "date_created")
        page = max(1, request.args.get("page", 1, type=int))
        limit = max(1, min(request.args.get("limit", 50, type=int), 200))
        offset = (page - 1) * limit

        type_filter = None if active_type == "all" else active_type

        session = get_session()
        total = JobService.count_history(
            job_type=type_filter,
            session=session,
        )
        history = JobService.list_history(
            order_by=order_by,
            limit=limit,
            offset=offset,
            job_type=type_filter,
            session=session,
        )

        return api_response(
            success=True,
            data={
                "history": [
                    {
                        "id": h.id,
                        "job": h.job,
                        "subject": h.subject,
                        "task": h.task,
                        "args": h.args,
                        "date_created": (
                            h.date_created.isoformat() if h.date_created else None
                        ),
                    }
                    for h in history
                ],
                "total": total,
                "page": page,
                "limit": limit,
            },
        )
    except Exception as err:
        logger.error("Failed to list job history via API: %s", err)
        return api_response(success=False, error=str(err), status_code=500)


@api_jobs_bp.route("/history/clear", methods=["POST"])
def clear_history_api():
    """
    Clears all historical background jobs.
    """
    try:
        session = get_session()
        deleted_count = JobService.clear_history(session=session)
        return jsonify(
            {
                "success": True,
                "deleted_count": deleted_count,
                "message": f"Successfully cleared {deleted_count} history records.",
            }
        )
    except Exception as err:
        logger.error("Failed to clear job history: %s", err)
        return api_response(success=False, error=str(err), status_code=500)
