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


@api_sources_bp.route("/<int:source_id>/related-urls", methods=["GET"])
def related_urls(source_id: int):
    """
    Discovers related URLs for a source by calling webtoolkit.BaseUrl.get_feeds()
    and BaseUrl.get_urls() on the source's URL.

    Returns feeds and alternate URL variants that differ from the stored source URL,
    de-duplicated. This is a potentially slow network call; it is triggered lazily
    from the detail page.
    """
    session = get_session()
    repo = SourceRepository(session)
    source = repo.get_by_id(source_id)
    if not source:
        return api_response(success=False, error="Source not found", status_code=404)

    import webtoolkit

    source_url = source.url.strip()
    result_feeds = []
    result_urls = []
    seen_urls = {source_url}
    error_msg = None
    b = None

    try:
        b = webtoolkit.BaseUrl(url=source_url)

        # get_feeds() – RSS/Atom feed URLs discovered on the page
        try:
            feeds = b.get_feeds() or []
            for f in feeds:
                f = (f or "").strip()
                if f and f not in seen_urls:
                    result_feeds.append(f)
                    seen_urls.add(f)
        except Exception as exc:
            logger.debug("get_feeds failed for %s: %s", source_url, exc)

        # get_urls() – canonical / channel / cleaned URL variants
        try:
            urls_map = b.get_urls() or {}
            for key, val in urls_map.items():
                val = (val or "").strip()
                if val and val not in seen_urls:
                    result_urls.append({"label": key, "url": val})
                    seen_urls.add(val)
        except Exception as exc:
            logger.debug("get_urls failed for %s: %s", source_url, exc)

    except Exception as exc:
        logger.warning("related_urls: BaseUrl init failed for %s: %s", source_url, exc)
        error_msg = str(exc)
    finally:
        if b is not None and hasattr(b, "close"):
            try:
                b.close()
            except Exception:
                pass

    return jsonify(
        {
            "success": True,
            "source_id": source_id,
            "source_url": source_url,
            "feeds": result_feeds,
            "urls": result_urls,
            "error": error_msg,
        }
    )


@api_sources_bp.route("/batch-add", methods=["POST"])
def batch_add():
    """
    Batch ingestion of up to 100 source URLs.

    Accepts a list of raw URLs and an optional source_type per entry (or a global
    default). If source_type is omitted or empty it is stored as NULL so it can be
    resolved later (e.g. auto-detected on first fetch).

    Request body:
        {
            "sources": [
                {"url": "https://example.com/feed.xml", "source_type": "RSS"},
                {"url": "https://example.com/page",     "source_type": "PARSE"},
                {"url": "https://example.com/other"}     // source_type omitted → NULL
            ]
        }
    """
    payload = request.get_json(silent=True) or {}
    raw_sources = payload.get("sources", [])

    if not isinstance(raw_sources, list) or not raw_sources:
        return api_response(
            success=False, error="Empty or invalid 'sources' list", status_code=400
        )

    candidates = raw_sources[:100]  # hard cap

    session = get_session()
    repo = SourceRepository(session)

    added = []
    skipped_duplicate = []
    skipped_invalid = []

    allowed_types = {
        Sources.SOURCE_TYPE_RSS,
        Sources.SOURCE_TYPE_PARSE,
        Sources.SOURCE_TYPE_EMAIL,
    }

    for item in candidates:
        url = (
            (item.get("url") or "").strip()
            if isinstance(item, dict)
            else str(item).strip()
        )
        if not url:
            continue

        raw_type = (
            (item.get("source_type") or "").strip().upper()
            if isinstance(item, dict)
            else ""
        )
        source_type = raw_type if raw_type in allowed_types else None

        # Duplicate check
        from sqlalchemy import select as sa_select
        from linkarchivetools.model.definitions import SourcesTable as ST

        exists = session.execute(
            sa_select(ST.id).where(ST.url == url).limit(1)
        ).scalar()
        if exists:
            skipped_duplicate.append(url)
            continue

        try:
            source = repo.add_source(
                url=url,
                title=url,
                source_type=source_type,
                enabled=True,
            )
            added.append(
                {"id": source.id, "url": source.url, "source_type": source.source_type}
            )
        except Exception as exc:
            logger.warning("batch-add: failed to add %s: %s", url, exc)
            session.rollback()
            skipped_invalid.append(url)

    return jsonify(
        {
            "success": True,
            "added_count": len(added),
            "duplicate_count": len(skipped_duplicate),
            "invalid_count": len(skipped_invalid),
            "added": added,
            "message": (
                f"Added {len(added)} sources"
                + (
                    f", {len(skipped_duplicate)} duplicates skipped"
                    if skipped_duplicate
                    else ""
                )
                + (f", {len(skipped_invalid)} invalid" if skipped_invalid else "")
                + "."
            ),
        }
    )


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
