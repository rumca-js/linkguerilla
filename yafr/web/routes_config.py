"""
Configuration routes and view controller for YAFR.

Implements ConfigurationView for managing display themes, card layouts,
alpha transparencies, quotas, limits, crawler rules, and quick UI presets.
"""

import logging
from flask import Blueprint, flash, redirect, render_template, request, url_for
from yafr.db import get_session
from yafr.services import ConfigService, SearchViewService
from yafr.web.shared import (
    CONFIGURATION_GALLERY,
    CONFIGURATION_NEWS,
    CONFIGURATION_SEARCH_ENGINE,
    DISPLAY_STYLES,
    DISPLAY_TYPES,
)

logger = logging.getLogger(__name__)

config_bp = Blueprint("config", __name__)

# Known boolean fields in the configuration form that should be False if missing
BOOLEAN_CONFIG_FIELDS = [
    "show_icons",
    "thumbnails_as_icons",
    "small_icons",
    "local_icons",
    "highlight_bookmarks",
    "click_behavior_modal_window",
    "track_user_searches",
    "track_user_navigation",
    "prefer_https_links",
    "prefer_non_www_links",
    "accept_dead_links",
    "accept_domain_links",
    "accept_non_domain_links",
    "accept_ip_links",
    "accept_onion_links",
    "accept_same_hashes",
    "auto_store_thumbnails",
    "enable_background_jobs",
    "enable_social_data",
    "enable_crawling",
    "enable_keyword_support",
    "enable_domain_support",
    "enable_file_support",
    "enable_link_archiving",
    "enable_source_archiving",
    "debug_mode",
]


@config_bp.route("/configuration", methods=["GET"])
def configuration_view():
    """
    Renders ConfigurationView displaying all user-customizable application settings,
    appearance options, limits, alphas, presets, and search views management.
    """
    session = get_session()
    config = ConfigService.get_config_model(session=session)
    search_views = SearchViewService.list_views(session=session)

    presets = [
        {
            "id": "gallery",
            "name": CONFIGURATION_GALLERY,
            "icon": "bi-grid-3x3-gap",
            "description": "Visual grid with large media thumbnails, ideal for video feeds and rich bookmarks.",
        },
        {
            "id": "search-engine",
            "name": CONFIGURATION_SEARCH_ENGINE,
            "icon": "bi-search",
            "description": "Textual search layout with minimal distractions and direct external links.",
        },
        {
            "id": "news",
            "name": CONFIGURATION_NEWS,
            "icon": "bi-newspaper",
            "description": "Content-centric card list with expanded descriptions and article metadata.",
        },
    ]

    return render_template(
        "configuration/view.html",
        config=config,
        display_types=DISPLAY_TYPES,
        display_styles=DISPLAY_STYLES,
        presets=presets,
        search_views=search_views,
    )


@config_bp.route("/configuration", methods=["POST"])
def update_configuration():
    """
    Processes form submissions to update application settings and redirects back to view.
    """
    session = get_session()
    form_data = request.form.to_dict()

    # Form checkboxes only send values when checked; set unchecked ones to False
    update_payload = {}
    for bool_field in BOOLEAN_CONFIG_FIELDS:
        update_payload[bool_field] = bool_field in form_data

    # Add other non-boolean fields present in the form
    for key, value in form_data.items():
        if key not in BOOLEAN_CONFIG_FIELDS and key != "csrf_token":
            update_payload[key] = value

    try:
        ConfigService.update_config(update_payload, session=session)
        flash("Configuration updated successfully.", "success")
    except Exception as err:
        logger.error("Failed to save configuration from form: %s", err)
        flash(f"Error saving configuration: {err}", "danger")

    return redirect(url_for("config.configuration_view"))


@config_bp.route("/configuration/search-views/save", methods=["POST"])
def save_search_view():
    """
    Processes form submissions to create or update a SearchView.
    """
    session = get_session()
    form_data = request.form.to_dict()
    view_id = form_data.get("id")

    payload = {
        "name": form_data.get("name", "").strip(),
        "default": "default" in form_data,
        "priority": form_data.get("priority", 0),
        "filter_statement": form_data.get("filter_statement", "").strip(),
        "order_by": form_data.get("order_by", "").strip(),
    }

    try:
        if view_id and view_id.strip():
            SearchViewService.update_view(int(view_id), payload, session=session)
            flash(f"Search view '{payload['name']}' updated successfully.", "success")
        else:
            SearchViewService.create_view(payload, session=session)
            flash(f"Search view '{payload['name']}' created successfully.", "success")
    except ValueError as val_err:
        flash(str(val_err), "danger")
    except Exception as err:
        logger.error("Failed to save search view: %s", err)
        flash(f"Error saving search view: {err}", "danger")

    return redirect(url_for("config.configuration_view") + "#tab-searchviews")


@config_bp.route("/configuration/search-views/<int:view_id>/delete", methods=["POST"])
def delete_search_view(view_id: int):
    """
    Processes form submission to delete a SearchView.
    """
    session = get_session()
    try:
        SearchViewService.delete_view(view_id, session=session)
        flash("Search view deleted successfully.", "success")
    except Exception as err:
        logger.error("Failed to delete search view %d: %s", view_id, err)
        flash(f"Error deleting search view: {err}", "danger")

    return redirect(url_for("config.configuration_view") + "#tab-searchviews")


@config_bp.route("/configuration/search-views/<int:view_id>/default", methods=["POST"])
def set_default_search_view(view_id: int):
    """
    Processes form submission to set a SearchView as default.
    """
    session = get_session()
    try:
        view = SearchViewService.set_default(view_id, session=session)
        flash(f"Search view '{view.name}' set as default.", "success")
    except Exception as err:
        logger.error("Failed to set default search view %d: %s", view_id, err)
        flash(f"Error setting default search view: {err}", "danger")

    return redirect(url_for("config.configuration_view") + "#tab-searchviews")
