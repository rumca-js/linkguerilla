"""
Shared helpers, constants, and utilities for YAFR web views.
"""

import logging
from typing import Any, Dict, Optional
from flask import jsonify, Response
from yafr.config import Config
from yafr.db import ConfigRepository, JobRepository, SourceRepository
from yafr.db.source_repository import DEFAULT_SOURCE_REFRESH_SECONDS

logger = logging.getLogger(__name__)

# Display Styles
DISPLAY_STYLE_LIGHT = "style-light"
DISPLAY_STYLE_DARK = "style-dark"

# Display Types (Layouts)
DISPLAY_TYPE_STANDARD = "standard"
DISPLAY_TYPE_GALLERY = "gallery"
DISPLAY_TYPE_SEARCH_ENGINE = "search-engine"
DISPLAY_TYPE_CONTENT_CENTRIC = "content-centric"
DISPLAY_TYPE_LINKS_ONLY = "links-only"

# Display Presets
CONFIGURATION_SEARCH_ENGINE = "Search Engine"
CONFIGURATION_GALLERY = "Gallery"
CONFIGURATION_NEWS = "News"

DISPLAY_TYPES = [
    {
        "id": DISPLAY_TYPE_GALLERY,
        "name": "Gallery",
        "icon": "bi-grid-3x3-gap",
        "description": "Card grid with prominent thumbnails (YouTube / TikTok style)",
    },
    {
        "id": DISPLAY_TYPE_STANDARD,
        "name": "Standard",
        "icon": "bi-view-list",
        "description": "Feed reader list with side thumbnails (RSS reader style)",
    },
    {
        "id": DISPLAY_TYPE_SEARCH_ENGINE,
        "name": "Search Engine",
        "icon": "bi-search",
        "description": "Emphasis on titles and URLs (Google / DuckDuckGo style)",
    },
    {
        "id": DISPLAY_TYPE_CONTENT_CENTRIC,
        "name": "Content Centric",
        "icon": "bi-chat-square-text",
        "description": "Expanded descriptions and metadata (Reddit style)",
    },
    {
        "id": DISPLAY_TYPE_LINKS_ONLY,
        "name": "Links Only",
        "icon": "bi-table",
        "description": "High-density tabular list of links",
    },
]

DISPLAY_STYLES = [
    {"id": DISPLAY_STYLE_DARK, "name": "Dark Theme", "icon": "bi-moon-stars"},
    {"id": DISPLAY_STYLE_LIGHT, "name": "Light Theme", "icon": "bi-sun"},
]

# Predefined Filters for Entries
ENTRY_FILTERS = [
    {"id": "date_published", "name": "by Date published", "default": True},
    {"id": "read_later", "name": "Read Later", "default": False},
    {"id": "visited", "name": "Visited", "default": False},
    {"id": "votes", "name": "by Votes", "default": False},
    {"id": "visits", "name": "by Visits", "default": False},
]


def api_response(
    success: bool = True,
    data: Optional[Any] = None,
    message: Optional[str] = None,
    error: Optional[str] = None,
    status_code: int = 200,
) -> Response:
    """
    Standardized JSON API response wrapper.

    :param success: Whether the operation succeeded
    :param data: Optional payload data
    :param message: Optional human-readable message
    :param error: Optional error description
    :param status_code: HTTP status code
    :return: Flask JSON response object
    """
    payload: Dict[str, Any] = {"success": success}
    if data is not None:
        payload["data"] = data
    if message is not None:
        payload["message"] = message
    if error is not None:
        payload["error"] = error

    response = jsonify(payload)
    response.status_code = status_code
    return response


def get_shared_context() -> Dict[str, Any]:
    """
    Returns application-wide context variables injected into templates,
    retrieving live configuration and operational badge counters from SQLite.
    """
    active_theme = DISPLAY_STYLE_LIGHT
    display_type = DISPLAY_TYPE_GALLERY
    sources_outdated = 0
    sources_errors = 0
    jobs_errors = 0
    instance_title = Config.INSTANCE_TITLE
    instance_description = Config.INSTANCE_DESCRIPTION
    enable_background_jobs = True

    try:
        config_repo = ConfigRepository()
        active_theme = config_repo.get_display_style()
        display_type = config_repo.get_display_type()
        config = config_repo.get_config()
        enable_background_jobs = bool(config.enable_background_jobs)
        instance_title = (
            config.instance_title or Config.INSTANCE_TITLE
        ).strip() or Config.INSTANCE_TITLE
        instance_description = (
            config.instance_description or Config.INSTANCE_DESCRIPTION
        ).strip() or Config.INSTANCE_DESCRIPTION

        source_repo = SourceRepository()
        default_period = int(config.sources_refresh_period or DEFAULT_SOURCE_REFRESH_SECONDS)
        sources_outdated = source_repo.count_outdated_sources(max_age_seconds=default_period)
        sources_errors = source_repo.count_error_sources()

        job_repo = JobRepository()
        jobs_errors = job_repo.count_error_jobs()
    except Exception as err:
        logger.debug("Could not read shared context from DB (using defaults): %s", err)

    show_icons = (
        bool(config.show_icons) if config and config.show_icons is not None else True
    )

    return {
        "app_name": instance_title,
        "app_tagline": instance_description,
        "app_version": Config.VERSION,
        "entry_filters": ENTRY_FILTERS,
        "active_theme": active_theme,
        "display_type": display_type,
        "enable_background_jobs": enable_background_jobs,
        "config": config,
        "show_icons": show_icons,
        "badges": {
            "sources_outdated": sources_outdated,
            "sources_errors": sources_errors,
            "jobs_errors": jobs_errors,
        },
    }
