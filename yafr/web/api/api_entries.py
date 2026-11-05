"""
Lightweight REST / JSON API endpoints for Entry interactions.

Provides AJAX handlers for voting, bookmarking, read-later toggling,
visit recording, status code changes, and tags updates.
"""

import logging
import re
from flask import Blueprint, request
import webtoolkit
from linkarchivetools.model.definitions import ReadLater
from yafr.db import EntryRepository, HistoryRepository, get_session
from yafr.services.entry_builder import EntryBuilder
from yafr.web.shared import api_response

logger = logging.getLogger(__name__)
api_entries_bp = Blueprint("api_entries", __name__, url_prefix="/api/entries")


@api_entries_bp.route("/<int:entry_id>/vote", methods=["POST"])
def vote_entry(entry_id: int):
    """
    Sets a user rating vote for an entry to an explicit number between -100 and 100.
    The vote value is set directly without increasing or decreasing.
    """
    session = get_session()
    repo = EntryRepository(session)
    entry = repo.get_by_id(entry_id)
    if not entry:
        return api_response(success=False, error="Entry not found", status_code=404)

    payload = request.get_json(silent=True) or {}
    if "vote" not in payload:
        return api_response(
            success=False,
            error="Missing 'vote' number in request payload",
            status_code=400,
        )

    try:
        vote_value = int(payload["vote"])
    except (ValueError, TypeError):
        return api_response(
            success=False,
            error="Vote must be a valid number",
            status_code=400,
        )

    if vote_value < -100 or vote_value > 100:
        return api_response(
            success=False,
            error="Vote must be between -100 and 100",
            status_code=400,
        )

    new_votes = repo.vote_entry(entry_id, vote_value)
    return api_response(
        success=True,
        data={"entry_id": entry_id, "page_rating_votes": new_votes},
        message=f"Vote set to {new_votes}",
    )


@api_entries_bp.route("/<int:entry_id>/bookmark", methods=["POST"])
def toggle_bookmark(entry_id: int):
    """
    Toggles the bookmarked flag for an entry.
    """
    session = get_session()
    repo = EntryRepository(session)
    state = repo.toggle_bookmark(entry_id)
    if state is None:
        return api_response(success=False, error="Entry not found", status_code=404)

    return api_response(
        success=True,
        data={"entry_id": entry_id, "bookmarked": state},
        message="Bookmark toggled",
    )


@api_entries_bp.route("/<int:entry_id>/read-later", methods=["POST"])
def toggle_read_later(entry_id: int):
    """
    Toggles the Read Later state for an entry.
    """
    session = get_session()
    entry_repo = EntryRepository(session)
    if not entry_repo.get_by_id(entry_id):
        return api_response(success=False, error="Entry not found", status_code=404)

    history_repo = HistoryRepository(session)
    is_saved = history_repo.toggle_read_later(entry_id)

    return api_response(
        success=True,
        data={"entry_id": entry_id, "read_later": is_saved},
        message="Read later updated",
    )


@api_entries_bp.route("/<int:entry_id>/visit", methods=["POST"])
def record_visit(entry_id: int):
    """
    Records a visit when a user navigates to an entry link.
    Optionally records navigation transition if 'from_entry_id' is supplied.
    """
    session = get_session()
    entry_repo = EntryRepository(session)
    if not entry_repo.get_by_id(entry_id):
        return api_response(success=False, error="Entry not found", status_code=404)

    history_repo = HistoryRepository(session)
    visit = history_repo.record_visit(entry_id)

    payload = request.get_json(silent=True) or {}
    from_entry_id = payload.get("from_entry_id")
    if from_entry_id is not None:
        try:
            from_id = int(from_entry_id)
            if from_id != entry_id and entry_repo.get_by_id(from_id):
                history_repo.record_transition(from_id, entry_id)
        except (ValueError, TypeError) as err:
            logger.debug("Ignored invalid from_entry_id: %s", err)

    return api_response(
        success=True,
        data={"entry_id": entry_id, "visits": visit.visits},
        message="Visit recorded",
    )


@api_entries_bp.route("/<int:entry_id>/status", methods=["POST"])
def set_status(entry_id: int):
    """
    Sets manual status code: 200 = active, 400 = dead.
    """
    session = get_session()
    repo = EntryRepository(session)

    payload = request.get_json(silent=True) or {}
    status_code = payload.get("status_code", 200)

    try:
        status_code = int(status_code)
    except (ValueError, TypeError):
        return api_response(success=False, error="Invalid status code", status_code=400)

    success = repo.set_manual_status(entry_id, status_code)
    if not success:
        return api_response(success=False, error="Entry not found", status_code=404)

    return api_response(
        success=True,
        data={"entry_id": entry_id, "manual_status_code": status_code},
        message="Status updated",
    )


@api_entries_bp.route("/<int:entry_id>/mark-active", methods=["POST"])
def mark_active(entry_id: int):
    """
    Sets manual_status_code = 200 (marking the entry as verified active).
    """
    session = get_session()
    repo = EntryRepository(session)
    success = repo.set_manual_status(entry_id, 200)
    if not success:
        return api_response(success=False, error="Entry not found", status_code=404)

    return api_response(
        success=True,
        data={"entry_id": entry_id, "manual_status_code": 200},
        message="Entry marked active",
    )


@api_entries_bp.route("/<int:entry_id>/mark-dead", methods=["POST"])
def mark_dead(entry_id: int):
    """
    Sets manual_status_code = 400 (marking the entry as dead).
    """
    session = get_session()
    repo = EntryRepository(session)
    success = repo.set_manual_status(entry_id, 400)
    if not success:
        return api_response(success=False, error="Entry not found", status_code=404)

    return api_response(
        success=True,
        data={"entry_id": entry_id, "manual_status_code": 400},
        message="Entry marked dead",
    )


@api_entries_bp.route("/<int:entry_id>/update-data", methods=["POST"])
def update_data(entry_id: int):
    """
    Enqueues a link metadata refresh job for the entry.
    """
    try:
        session = get_session()
        entry_repo = EntryRepository(session)
        entry = entry_repo.get_by_id(entry_id)
        if not entry:
            return api_response(success=False, error="Entry not found", status_code=404)

        from yafr.services.job_service import JobService

        job = JobService.create_job(
            job="link-update-data",
            subject=str(entry_id),
            session=session,
        )
        return api_response(
            success=True,
            data={"entry_id": entry_id, "job_id": job.id},
            message="Link update queued.",
        )
    except Exception as err:
        logger.error("Failed to enqueue update-data for entry %d: %s", entry_id, err)
        return api_response(success=False, error=str(err), status_code=500)


@api_entries_bp.route("/<int:entry_id>/update-social", methods=["POST"])
@api_entries_bp.route("/<int:entry_id>/download-social", methods=["POST"])
def update_social_data(entry_id: int):
    """
    Enqueues a social data download job (JOB_LINK_DOWNLOAD_SOCIAL) for the entry.
    """
    try:
        session = get_session()
        entry_repo = EntryRepository(session)
        entry = entry_repo.get_by_id(entry_id)
        if not entry:
            return api_response(success=False, error="Entry not found", status_code=404)

        from yafr.services.job_service import JOB_LINK_DOWNLOAD_SOCIAL, JobService

        job = JobService.create_job(
            job=JOB_LINK_DOWNLOAD_SOCIAL,
            subject=str(entry_id),
            session=session,
        )
        return api_response(
            success=True,
            data={"entry_id": entry_id, "job_id": job.id},
            message="Social data download queued.",
        )
    except Exception as err:
        logger.error("Failed to enqueue update-social for entry %d: %s", entry_id, err)
        return api_response(success=False, error=str(err), status_code=500)


@api_entries_bp.route("/<int:entry_id>/jobs", methods=["GET"])
def get_entry_jobs(entry_id: int):
    """
    Returns all background jobs (active and historical) connected to the entry.
    """
    session = get_session()
    entry_repo = EntryRepository(session)
    entry = entry_repo.get_by_id(entry_id)
    if not entry:
        return api_response(success=False, error="Entry not found", status_code=404)

    subjects = [str(entry.id)]
    if entry.link:
        subjects.append(entry.link)

    from yafr.services.job_service import JobService

    raw = JobService.get_jobs_for_subjects(subjects=subjects, session=session)
    active = [
        {
            "id": j.id,
            "job": j.job,
            "subject": j.subject,
            "task": j.task,
            "args": j.args,
            "priority": j.priority,
            "errors": j.errors or 0,
            "enabled": bool(j.enabled),
            "date_created": (j.date_created.isoformat() if j.date_created else None),
        }
        for j in raw.get("jobs", [])
    ]
    history = [
        {
            "id": h.id,
            "job": h.job,
            "subject": h.subject,
            "task": h.task,
            "args": h.args,
            "date_created": (h.date_created.isoformat() if h.date_created else None),
        }
        for h in raw.get("history", [])
    ]

    return api_response(
        success=True,
        data={
            "entry_id": entry_id,
            "jobs": active,
            "history": history,
            "total_active": len(active),
            "total_history": len(history),
        },
        message="Connected jobs retrieved.",
    )


@api_entries_bp.route("/<int:entry_id>/reset-data", methods=["POST"])
def reset_data(entry_id: int):
    """
    Resets extracted metadata hashes and status code back to raw state.
    """
    session = get_session()
    entry_repo = EntryRepository(session)
    entry = entry_repo.get_by_id(entry_id)
    if not entry:
        return api_response(success=False, error="Entry not found", status_code=404)

    entry.contents_hash = None
    entry.body_hash = None
    entry.meta_hash = None
    entry.status_code = 0
    session.commit()

    return api_response(
        success=True,
        data={"entry_id": entry_id},
        message="Link data reset.",
    )


@api_entries_bp.route("/<int:entry_id>/tags", methods=["POST"])
def update_tags(entry_id: int):
    """
    Replaces the tags for an entry.
    """
    session = get_session()
    repo = EntryRepository(session)
    payload = request.get_json(silent=True) or {}
    tags = payload.get("tags", [])

    if not isinstance(tags, list):
        return api_response(
            success=False, error="Tags must be a list of strings", status_code=400
        )

    updated_tags = repo.set_tags(entry_id, tags)
    return api_response(
        success=True,
        data={"entry_id": entry_id, "tags": updated_tags},
        message="Tags updated",
    )


@api_entries_bp.route("/<int:entry_id>", methods=["DELETE"])
def delete_entry(entry_id: int):
    """
    Deletes an entry and cascades to all satellite tables.
    """
    session = get_session()
    repo = EntryRepository(session)
    success = repo.delete_entry(entry_id)
    if not success:
        return api_response(success=False, error="Entry not found", status_code=404)

    return api_response(
        success=True,
        data={"entry_id": entry_id},
        message="Entry deleted successfully",
    )


@api_entries_bp.route("/batch-delete", methods=["POST"])
def batch_delete():
    """
    Batch deletes multiple entries by ID list.
    """
    session = get_session()
    repo = EntryRepository(session)
    payload = request.get_json(silent=True) or {}
    ids = payload.get("ids", [])

    if not isinstance(ids, list) or not ids:
        return api_response(
            success=False, error="Invalid or empty ID list", status_code=400
        )

    deleted_count = repo.delete_entries(ids)
    return api_response(
        success=True,
        data={"deleted_count": deleted_count},
        message=f"Deleted {deleted_count} entries",
    )


@api_entries_bp.route("/validate-link", methods=["POST"])
def validate_link():
    """
    Validates a candidate URL, checks duplicate status, policy allowance,
    and returns clickable suggestions/propositions (cleaned, no-slash, no-www, https).
    """
    payload = request.get_json(silent=True) or {}
    raw_url = payload.get("url", "")
    trimmed_url = (raw_url or "").strip()

    if not trimmed_url:
        return api_response(
            success=False,
            error="URL link cannot be empty",
            status_code=400,
        )

    session = get_session()
    builder = EntryBuilder(session=session)

    # 1. Web link validation
    loc = webtoolkit.UrlLocation(trimmed_url)
    is_web_link = (
        loc.is_web_link()
        or trimmed_url.startswith("http://")
        or trimmed_url.startswith("https://")
        or loc.is_onion()
    )

    cleaned = builder.sanitize_url(trimmed_url)
    clean_loc = webtoolkit.UrlLocation(cleaned)

    # 2. Duplicate and policy check
    is_duplicate = builder.is_duplicate(cleaned)
    allowed, rejection_reason = builder.can_build(
        cleaned,
        check_duplicates=False,  # We report duplicate separately
        ignore_policy=False,
    )

    # 3. Generate Clickable Propositions / Suggestions
    propositions = []

    # Proposition: Cleaned version
    if cleaned and cleaned != trimmed_url:
        propositions.append({"label": "Cleaned URL", "url": cleaned})

    # Proposition: Without trailing slash
    if trimmed_url.endswith("/") and not loc.is_domain():
        no_slash = trimmed_url.rstrip("/")
        if no_slash != cleaned and no_slash != trimmed_url:
            propositions.append({"label": "Remove trailing /", "url": no_slash})

    # Proposition: Without 'www.'
    if "://www." in trimmed_url.lower():
        no_www = re.sub(r"://www\.", "://", trimmed_url, flags=re.IGNORECASE)
        if no_www != cleaned and not any(p["url"] == no_www for p in propositions):
            propositions.append({"label": "Remove 'www.'", "url": no_www})

    # Proposition: Upgrade to HTTPS
    if trimmed_url.lower().startswith("http://") and not loc.is_onion():
        https_url = "https://" + trimmed_url[7:]
        if https_url != cleaned and not any(
            p["url"] == https_url for p in propositions
        ):
            propositions.append({"label": "Upgrade to HTTPS", "url": https_url})

    return api_response(
        success=True,
        data={
            "url": trimmed_url,
            "cleaned_url": cleaned,
            "is_web_link": is_web_link,
            "is_duplicate": is_duplicate,
            "allowed": allowed,
            "rejection_reason": rejection_reason,
            "propositions": propositions,
        },
        message="URL validated.",
    )


@api_entries_bp.route("/quick-add", methods=["POST"])
def quick_add():
    """
    Fast JSON creation of a single link entry with optional tags, title, description,
    and read_later flag.
    """
    payload = request.get_json(silent=True) or {}
    raw_link = payload.get("link", "")
    link = (raw_link or "").strip()

    if not link:
        return api_response(
            success=False, error="URL link is required", status_code=400
        )

    title = payload.get("title") or None
    description = payload.get("description") or None
    author = payload.get("author") or None
    language = payload.get("language") or None
    thumbnail = payload.get("thumbnail") or None
    tags = payload.get("tags") or []
    read_later = bool(payload.get("read_later", False))
    ignore_policy = bool(payload.get("ignore_policy", False))

    session = get_session()
    builder = EntryBuilder(session=session)

    try:
        entry = builder.build_and_save(
            link=link,
            title=title,
            description=description,
            author=author,
            language=language,
            thumbnail=thumbnail,
            tags=tags,
            check_duplicates=True,
            ignore_policy=ignore_policy,
            enqueue_update_job=True,
            commit=False,
        )

        if entry is None:
            reason = builder.last_rejection_reason or "Failed to add entry."
            return api_response(success=False, error=reason, status_code=400)

        if read_later:
            session.add(ReadLater(entry_id=entry.id, user_id=1))

        session.commit()

        return api_response(
            success=True,
            data={
                "entry_id": entry.id,
                "link": entry.link,
                "title": entry.title,
            },
            message="Entry created successfully.",
        )
    except Exception as exc:
        session.rollback()
        logger.error("Failed to add entry: %s", exc)
        return api_response(
            success=False, error=f"Database error: {exc}", status_code=500
        )


@api_entries_bp.route("/batch-add", methods=["POST"])
def batch_add():
    """
    Batch ingestion of up to 200 links.
    """
    payload = request.get_json(silent=True) or {}
    raw_links = payload.get("links", [])
    default_tags = payload.get("tags", [])
    read_later = bool(payload.get("read_later", False))
    ignore_policy = bool(payload.get("ignore_policy", False))

    if not isinstance(raw_links, list) or not raw_links:
        return api_response(
            success=False, error="Empty or invalid links list", status_code=400
        )

    # Input limit: max 200 links per field/batch (as defined in PROJECT.md)
    candidate_links = raw_links[:200]

    session = get_session()
    builder = EntryBuilder(session=session)

    added_entries = []
    duplicate_count = 0
    rejected_count = 0

    try:
        for raw in candidate_links:
            cleaned_str = (raw or "").strip()
            if not cleaned_str:
                continue

            entry = builder.build_and_save(
                link=cleaned_str,
                tags=default_tags,
                check_duplicates=True,
                ignore_policy=ignore_policy,
                enqueue_update_job=True,
                commit=False,
            )

            if entry is not None:
                if read_later:
                    session.add(ReadLater(entry_id=entry.id, user_id=1))
                added_entries.append(
                    {"id": entry.id, "link": entry.link, "title": entry.title}
                )
            else:
                if "Duplicate" in (builder.last_rejection_reason or ""):
                    duplicate_count += 1
                else:
                    rejected_count += 1

        session.commit()

        return api_response(
            success=True,
            data={
                "total_submitted": len(candidate_links),
                "added_count": len(added_entries),
                "duplicate_count": duplicate_count,
                "rejected_count": rejected_count,
                "entries": added_entries,
            },
            message=f"Added {len(added_entries)} entries ({duplicate_count} duplicates skipped, {rejected_count} rejected).",
        )
    except Exception as exc:
        session.rollback()
        logger.error("Failed during batch add: %s", exc)
        return api_response(
            success=False, error=f"Database error: {exc}", status_code=500
        )
