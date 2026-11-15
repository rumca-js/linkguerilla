"""
URL Preview View Controller for YAFR.

Implements UrlPreview screen (/preview): dynamic metadata extraction
via WebToolsWrapper (title, entries, embed player, description, thumbnail)
and entry rule / block evaluation.
"""

import logging
from flask import Blueprint, render_template, request
from yafr.db import get_session
from yafr.services.preview_service import PreviewService

logger = logging.getLogger(__name__)

preview_bp = Blueprint("preview", __name__)


@preview_bp.route("/preview", methods=["GET", "POST"])
def preview_view():
    """
    Renders the UrlPreview screen.

    Displays dynamic metadata, media player embed, feed child entries,
    and rule evaluation for a candidate link passed via query param or form.
    """
    url = request.args.get("url", "").strip() or request.form.get("url", "").strip()
    preview_data = None
    error = None

    if url:
        try:
            session = get_session()
            preview_data = PreviewService.inspect_url(url, session=session)
            if not preview_data.get("success"):
                error = preview_data.get("error", "Failed to resolve URL preview.")
        except Exception as exc:
            logger.error("Failed to render preview for '%s': %s", url, exc)
            error = f"Error fetching link preview: {exc}"

    return render_template(
        "preview/view.html",
        url=url,
        preview_data=preview_data,
        error=error,
    )
