"""
RESTful JSON API Endpoints for Dynamic Link Preview & Inspection.

Provides lightweight JSON endpoints returning dynamically resolved metadata,
media embeds, feed entries, and rule blocking status for URLs via WebToolsWrapper.
"""

import logging
from flask import Blueprint, jsonify, request
from yafr.db import get_session
from yafr.services.preview_service import PreviewService
from yafr.web.shared import api_response

logger = logging.getLogger(__name__)

api_preview_bp = Blueprint("api_preview", __name__, url_prefix="/api/preview")


@api_preview_bp.route("/inspect", methods=["POST"])
def inspect_url():
    """
    Dynamically inspects a candidate URL using WebToolsWrapper (BaseUrl / RemoteUrl)
    and RuleService.

    Accepts JSON body: {"url": "https://example.com"}
    or Form data: url=https://example.com

    Returns JSON containing:
      - title, description, author, language, publication date, thumbnail, album
      - HTTP status code and response validity
      - media_type ('video', 'audio', 'feed', 'webpage') and embed_url
      - feed entries (list of parsed child items)
      - content links (discovered URLs)
      - rule blocking status (is_blocked, blocking_rule, blocking_block_entry)
    """
    try:
        url = None
        if request.is_json:
            body = request.get_json(silent=True) or {}
            url = body.get("url")
        if not url:
            url = request.form.get("url")

        if not url or not str(url).strip():
            return jsonify({"success": False, "error": "URL is required."}), 400

        session = get_session()
        result = PreviewService.inspect_url(str(url).strip(), session=session)
        status_code = 200 if result.get("success") else 400
        return jsonify(result), status_code

    except Exception as err:
        logger.error("Error inspecting URL preview: %s", err)
        return api_response(success=False, error=str(err), status_code=500)
