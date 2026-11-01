"""
RESTful JSON API Endpoints for SearchView Management.

Provides small, focused endpoints returning JSON responses for listing,
creating, updating, deleting, and setting default SearchViews.
"""

import logging
from flask import Blueprint, jsonify, request
from yafr.db import get_session
from yafr.services.search_view_service import SearchViewService
from yafr.web.shared import api_response

logger = logging.getLogger(__name__)

api_search_views_bp = Blueprint(
    "api_search_views", __name__, url_prefix="/api/search-views"
)


@api_search_views_bp.route("", methods=["GET"])
def list_search_views():
    """
    Returns all configured search views ordered by priority.
    """
    try:
        session = get_session()
        order_by = request.args.get("order_by", "priority")
        views = SearchViewService.list_views(order_by=order_by, session=session)
        data = [SearchViewService.to_dict(v) for v in views]
        return jsonify({"success": True, "search_views": data, "count": len(data)})
    except Exception as err:
        logger.error("Failed to list search views: %s", err)
        return api_response(success=False, error=str(err), status_code=500)


@api_search_views_bp.route("/<int:view_id>", methods=["GET"])
def get_search_view(view_id: int):
    """
    Retrieves a single search view by ID.
    """
    try:
        session = get_session()
        view = SearchViewService.get_view(view_id, session=session)
        if not view:
            return api_response(
                success=False,
                error=f"Search view with ID {view_id} not found.",
                status_code=404,
            )
        return jsonify(
            {"success": True, "search_view": SearchViewService.to_dict(view)}
        )
    except Exception as err:
        logger.error("Failed to get search view %d: %s", view_id, err)
        return api_response(success=False, error=str(err), status_code=500)


@api_search_views_bp.route("", methods=["POST"])
def create_search_view():
    """
    Creates a new search view.
    Accepts JSON or form data.
    """
    try:
        payload = request.get_json(silent=True) or request.form.to_dict()
        if not payload:
            return api_response(
                success=False,
                error="Request body is empty.",
                status_code=400,
            )

        session = get_session()
        view = SearchViewService.create_view(payload, session=session)
        return (
            jsonify(
                {
                    "success": True,
                    "message": "Search view created successfully.",
                    "search_view": SearchViewService.to_dict(view),
                }
            ),
            201,
        )
    except ValueError as val_err:
        return api_response(success=False, error=str(val_err), status_code=400)
    except Exception as err:
        logger.error("Failed to create search view: %s", err)
        return api_response(success=False, error=str(err), status_code=500)


@api_search_views_bp.route("/<int:view_id>", methods=["POST", "PUT"])
def update_search_view(view_id: int):
    """
    Updates an existing search view.
    Accepts JSON or form data.
    """
    try:
        payload = request.get_json(silent=True) or request.form.to_dict()
        if not payload:
            return api_response(
                success=False,
                error="Request body is empty.",
                status_code=400,
            )

        session = get_session()
        view = SearchViewService.update_view(view_id, payload, session=session)
        return jsonify(
            {
                "success": True,
                "message": "Search view updated successfully.",
                "search_view": SearchViewService.to_dict(view),
            }
        )
    except ValueError as val_err:
        return api_response(success=False, error=str(val_err), status_code=400)
    except Exception as err:
        logger.error("Failed to update search view %d: %s", view_id, err)
        return api_response(success=False, error=str(err), status_code=500)


@api_search_views_bp.route("/<int:view_id>", methods=["DELETE"])
def delete_search_view(view_id: int):
    """
    Deletes a search view.
    """
    try:
        session = get_session()
        SearchViewService.delete_view(view_id, session=session)
        return jsonify(
            {
                "success": True,
                "deleted_id": view_id,
                "message": "Search view deleted successfully.",
            }
        )
    except ValueError as val_err:
        return api_response(success=False, error=str(val_err), status_code=404)
    except Exception as err:
        logger.error("Failed to delete search view %d: %s", view_id, err)
        return api_response(success=False, error=str(err), status_code=500)


@api_search_views_bp.route("/<int:view_id>/set-default", methods=["POST"])
def set_default_search_view(view_id: int):
    """
    Sets a search view as default and clears default from others.
    """
    try:
        session = get_session()
        view = SearchViewService.set_default(view_id, session=session)
        return jsonify(
            {
                "success": True,
                "message": f"Search view '{view.name}' set as default.",
                "search_view": SearchViewService.to_dict(view),
            }
        )
    except ValueError as val_err:
        return api_response(success=False, error=str(val_err), status_code=404)
    except Exception as err:
        logger.error("Failed to set default search view %d: %s", view_id, err)
        return api_response(success=False, error=str(err), status_code=500)
