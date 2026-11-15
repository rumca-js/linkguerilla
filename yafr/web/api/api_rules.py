"""
RESTful JSON API Endpoints for Entry Rules & URL Inspection.

Provides small, focused endpoints returning JSON responses for evaluating
candidate URLs against configured EntryRules and BlockEntry records.
"""

import logging
from flask import Blueprint, jsonify, request
from yafr.db import get_session
from yafr.services.rule_service import RuleService
from yafr.web.shared import api_response

logger = logging.getLogger(__name__)

api_rules_bp = Blueprint("api_rules", __name__, url_prefix="/api/rules")


@api_rules_bp.route("/test", methods=["POST"])
def test_rule_url():
    """
    Evaluates a candidate URL against all configured EntryRules and BlockEntry records.

    Accepts JSON body: {"url": "https://example.com"}
    or Form data: url=https://example.com

    Returns detailed JSON reporting whether the URL is blocked, what actions
    (block, trust, auto-tags, age limits) apply, and which specific rules and
    block entries affect it.
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
        result = RuleService.test_url(str(url).strip(), session=session)
        status_code = 200 if result.get("success") else 400
        return jsonify(result), status_code

    except Exception as err:
        logger.error("Error evaluating URL test: %s", err)
        return api_response(success=False, error=str(err), status_code=500)
