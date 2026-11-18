"""
History and Autocomplete REST / JSON API Endpoints.
"""

from flask import Blueprint, request
from yafr.db import HistoryRepository, get_session
from yafr.web.shared import api_response

api_history_bp = Blueprint("api_history", __name__, url_prefix="/api/history")


@api_history_bp.route("/autocomplete", methods=["GET"])
def autocomplete():
    """
    Returns search query suggestions matching the prefix parameter 'q'.
    """
    prefix = request.args.get("q", "").strip()
    session = get_session()
    repo = HistoryRepository(session)
    suggestions = repo.get_recent_searches(
        query_prefix=prefix if prefix else None, limit=10
    )
    return api_response(success=True, data={"suggestions": suggestions})


@api_history_bp.route("/search", methods=["DELETE"])
def delete_search():
    """Remove all stored occurrences of one exact search expression."""
    payload = request.get_json(silent=True) or {}
    query = payload.get("query", "")
    if not isinstance(query, str) or not query.strip():
        return api_response(
            success=False,
            error="A non-empty query is required.",
            status_code=400,
        )

    deleted_count = HistoryRepository(get_session()).delete_search(query)
    return api_response(
        success=True,
        data={"deleted_count": deleted_count},
        message="Search removed from history.",
    )


@api_history_bp.route("", methods=["DELETE"])
def clear_search_history():
    """Remove all stored search history."""
    deleted_count = HistoryRepository(get_session()).clear_search_history()
    return api_response(
        success=True,
        data={"deleted_count": deleted_count},
        message="Search history cleared.",
    )


@api_history_bp.route("", methods=["GET"])
def list_search_history():
    """Return the retained distinct search history for the history dropdown."""
    suggestions = HistoryRepository(get_session()).get_recent_searches(limit=300)
    return api_response(success=True, data={"suggestions": suggestions})
