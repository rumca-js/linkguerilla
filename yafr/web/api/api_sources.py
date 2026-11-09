"""
RESTful JSON API endpoints for Source interactions.

Provides AJAX handlers for enabling/disabling sources, triggering fetches,
batch deletion, batch refresh, progress status tracking, and IMAP connection testing.
"""

import logging
from flask import Blueprint, jsonify, request
from yafr.db import JobRepository, SourceRepository, get_session
from yafr.services import SourceService
from yafr.web.shared import api_response

from webtoolkit.utils.emailreader import EmailReader
from linkarchivetools.model.sources import Sources

logger = logging.getLogger(__name__)
api_sources_bp = Blueprint("api_sources", __name__, url_prefix="/api/sources")


@api_sources_bp.route("/test-email-connection", methods=["POST"])
def test_email_connection():
    """
    Tests IMAP credentials by attempting to connect and login to the given server.

    Uses webtoolkit.utils.emailreader.EmailReader.connect(username, password)
    which internally calls imaplib.IMAP4_SSL(server).login(username, password).

    :request body: { "host": "imap.example.com", "username": "...", "password": "..." }
    :return: JSON with success flag and message.
    """
    payload = request.get_json(silent=True) or {}
    host = (payload.get("host") or "").strip()
    username = (payload.get("username") or "").strip()
    password = payload.get("password") or ""

    if not host or not username or not password:
        return jsonify(
            {
                "success": False,
                "message": "IMAP host, username, and password are all required for the connection test.",
            }
        )

    try:

        reader = EmailReader(host)
        result = reader.connect(username, password)
        # imaplib.login() returns ('OK', [b'...']) on success; any exception means failure.
        if result and result[0] == "OK":
            return jsonify(
                {
                    "success": True,
                    "message": f"Connection to {host} succeeded. Credentials are valid.",
                }
            )
        else:
            return jsonify(
                {
                    "success": False,
                    "message": f"Login to {host} was rejected (server response: {result}).",
                }
            )
    except Exception as exc:
        logger.info("Email connection test failed for %s / %s: %s", host, username, exc)
        return jsonify(
            {
                "success": False,
                "message": f"Connection failed: {exc}",
            }
        )


@api_sources_bp.route("/<int:source_id>/fetch", methods=["POST"])
def fetch_source(source_id: int):
    """
    Enqueues a process-source background job for the given source ID.

    Clears operational hashes so that the next fetch will re-read and parse
    the feed even if the remote content hash matches the prior fetch.
    The job will be picked up by the background worker (process_jobs.py / JobExecutor)
    on its next loop cycle. This avoids doing a blocking synchronous HTTP fetch
    inside the web request.
    """
    session = get_session()
    repo = SourceRepository(session)
    source = repo.get_by_id(source_id)
    if not source:
        return api_response(success=False, error="Source not found", status_code=404)

    # Invalidate operational hashes to force re-parsing on user-initiated fetch
    repo.clear_hashes(source_id)

    job_repo = JobRepository(session)
    job = job_repo.enqueue_job(
        job="process-source",
        subject=str(source_id),
        priority=1,
        enabled=True,
    )
    session.commit()

    logger.info(
        "Enqueued process-source job #%d for source %d (%s)",
        job.id,
        source_id,
        source.title or source.url,
    )

    return jsonify(
        {
            "success": True,
            "source_id": source_id,
            "job_id": job.id,
            "status": "queued",
            "message": f"Source fetch queued as background job #{job.id}. The worker will process it shortly.",
        }
    )


@api_sources_bp.route("/<int:source_id>/disable", methods=["POST"])
def disable_source(source_id: int):
    """
    Disables a source (enabled = False).
    """
    session = get_session()
    repo = SourceRepository(session)
    success = repo.set_enabled(source_id, False)
    if not success:
        return api_response(success=False, error="Source not found", status_code=404)

    return jsonify({"success": True, "source_id": source_id, "enabled": False})


@api_sources_bp.route("/<int:source_id>/enable", methods=["POST"])
def enable_source(source_id: int):
    """
    Enables a source (enabled = True).
    """
    session = get_session()
    repo = SourceRepository(session)
    success = repo.set_enabled(source_id, True)
    if not success:
        return api_response(success=False, error="Source not found", status_code=404)

    return jsonify({"success": True, "source_id": source_id, "enabled": True})


@api_sources_bp.route("/<int:source_id>/convert", methods=["POST"])
def convert_source(source_id: int):
    """
    Converts a source's type between RSS and Parse.
    - Not filled source type can be converted to parse or rss.
    - Parse can be changed to rss.
    - RSS can be changed to parse.
    - Email cannot be changed (returns 400).
    """
    session = get_session()
    source_repo = SourceRepository(session)
    source = source_repo.get_by_id(source_id)
    if not source:
        return api_response(success=False, error="Source not found", status_code=404)

    payload = request.get_json(silent=True) or request.form or {}
    target_type = (payload.get("target_type") or "").strip().upper()

    if target_type not in (Sources.SOURCE_TYPE_RSS, Sources.SOURCE_TYPE_PARSE):
        return api_response(
            success=False,
            error=f"Invalid target type '{target_type}'. Allowed types: RSS, PARSE",
            status_code=400,
        )

    current_type = (source.source_type or "").strip().upper()
    if current_type == Sources.SOURCE_TYPE_EMAIL:
        return api_response(
            success=False,
            error="Email sources cannot be converted.",
            status_code=400,
        )

    if current_type == target_type:
        return api_response(
            success=False,
            error=f"Source is already of type {target_type}.",
            status_code=400,
        )

    source_repo.update_source(source_id, source_type=target_type)
    source_repo.update_operational_data(source_id, page_hash=None, body_hash=None)

    return jsonify(
        {
            "success": True,
            "source_id": source_id,
            "source_type": target_type,
            "message": f"Source converted to {target_type} successfully.",
        }
    )


@api_sources_bp.route("/<int:source_id>", methods=["DELETE"])
def delete_source(source_id: int):
    """
    Deletes a source and cascades deletion to operational data.
    """
    session = get_session()
    repo = SourceRepository(session)
    success = repo.delete_source(source_id)
    if not success:
        return api_response(success=False, error="Source not found", status_code=404)

    return jsonify({"success": True, "deleted_source_id": source_id})


@api_sources_bp.route("/batch-delete", methods=["POST"])
def batch_delete():
    """
    Deletes multiple sources by ID list.
    """
    session = get_session()
    repo = SourceRepository(session)
    payload = request.get_json(silent=True) or {}
    source_ids = payload.get("source_ids", [])

    if not isinstance(source_ids, list) or not source_ids:
        return api_response(
            success=False, error="Invalid or empty source_ids list", status_code=400
        )

    deleted_count = repo.delete_sources(source_ids)
    return jsonify(
        {
            "success": True,
            "deleted_count": deleted_count,
            "deleted_ids": source_ids,
            "message": f"Deleted {deleted_count} sources.",
        }
    )


@api_sources_bp.route("/fetch-all", methods=["POST"])
def fetch_all():
    """
    Triggers a batch refresh for outdated sources and optionally sources with errors.
    """
    payload = request.get_json(silent=True) or {}
    include_errors = payload.get("include_errors", True)
    source_ids = payload.get("source_ids")

    queued_count = SourceService.start_batch_refresh(
        source_ids=source_ids,
        include_errors=include_errors,
    )

    return jsonify(
        {
            "success": True,
            "queued_sources_count": queued_count,
            "message": (
                f"Batch refresh initiated for {queued_count} sources."
                if queued_count > 0
                else "No outdated sources found to refresh."
            ),
        }
    )


@api_sources_bp.route("/refresh-status", methods=["GET"])
def refresh_status():
    """
    Returns live progress data for the linear progress bar during source refresh.
    """
    status = SourceService.get_refresh_status()
    return jsonify(status)
