"""
RESTful JSON API endpoints for Application Configuration.

Implements small, focused server endpoints returning JSON responses for updating
display styles, display types, alphas, presets, and general configuration settings.
"""

import logging
from flask import Blueprint, jsonify, request
from yafr.db import get_session
from yafr.services import ConfigService, WebToolsWrapper
from yafr.web.shared import api_response

logger = logging.getLogger(__name__)

api_config_bp = Blueprint("api_config", __name__, url_prefix="/api/config")


@api_config_bp.route("", methods=["GET"])
def get_config():
    """
    Retrieves the current application configuration as JSON.
    """
    try:
        session = get_session()
        config_data = ConfigService.get_config_dict(session=session)
        return jsonify({"success": True, "config": config_data})
    except Exception as err:
        logger.error("Failed to fetch configuration: %s", err)
        return api_response(success=False, error=str(err), status_code=500)


@api_config_bp.route("/style", methods=["POST"])
def update_style():
    """
    Quickly switches display style theme ('style-light' or 'style-dark').
    """
    try:
        payload = request.get_json(silent=True) or request.form.to_dict()
        display_style = payload.get("display_style", "").strip()

        if not display_style:
            return api_response(
                success=False,
                error="Field 'display_style' is required.",
                status_code=400,
            )

        session = get_session()
        config = ConfigService.set_display_style(display_style, session=session)
        return jsonify({"success": True, "display_style": config.display_style})
    except ValueError as val_err:
        return api_response(success=False, error=str(val_err), status_code=400)
    except Exception as err:
        logger.error("Failed to update display style: %s", err)
        return api_response(success=False, error=str(err), status_code=500)


@api_config_bp.route("/display-type", methods=["POST"])
def update_display_type():
    """
    Switches entry layout card type ('gallery', 'standard', 'search-engine', etc.).
    """
    try:
        payload = request.get_json(silent=True) or request.form.to_dict()
        display_type = payload.get("display_type", "").strip()

        if not display_type:
            return api_response(
                success=False,
                error="Field 'display_type' is required.",
                status_code=400,
            )

        session = get_session()
        config = ConfigService.set_display_type(display_type, session=session)
        return jsonify({"success": True, "display_type": config.display_type})
    except ValueError as val_err:
        return api_response(success=False, error=str(val_err), status_code=400)
    except Exception as err:
        logger.error("Failed to update display type: %s", err)
        return api_response(success=False, error=str(err), status_code=500)


@api_config_bp.route("/preset", methods=["POST"])
def apply_preset():
    """
    Applies a predefined UI display preset ('search-engine', 'gallery', or 'news').
    """
    try:
        payload = request.get_json(silent=True) or request.form.to_dict()
        preset_name = payload.get("preset", "").strip()

        if not preset_name:
            return api_response(
                success=False,
                error="Field 'preset' is required.",
                status_code=400,
            )

        session = get_session()
        config = ConfigService.apply_preset(preset_name, session=session)
        return jsonify(
            {
                "success": True,
                "preset": preset_name,
                "display_type": config.display_type,
                "message": f"Applied '{preset_name}' preset successfully.",
            }
        )
    except ValueError as val_err:
        return api_response(success=False, error=str(val_err), status_code=400)
    except Exception as err:
        logger.error("Failed to apply preset: %s", err)
        return api_response(success=False, error=str(err), status_code=500)


@api_config_bp.route("/update", methods=["POST"])
def update_config():
    """
    Updates arbitrary configuration settings via JSON payload.
    """
    try:
        payload = request.get_json(silent=True) or request.form.to_dict()
        if not payload:
            return api_response(
                success=False,
                error="No configuration payload provided.",
                status_code=400,
            )

        session = get_session()
        config = ConfigService.update_config(payload, session=session)
        return jsonify(
            {
                "success": True,
                "message": "Configuration updated successfully.",
                "display_style": config.display_style,
                "display_type": config.display_type,
            }
        )
    except Exception as err:
        logger.error("Failed to update configuration: %s", err)
        return api_response(success=False, error=str(err), status_code=500)


@api_config_bp.route("/reset", methods=["POST"])
def reset_config():
    """
    Resets all configuration values to system defaults.
    """
    try:
        session = get_session()
        ConfigService.reset_defaults(session=session)
        return jsonify(
            {
                "success": True,
                "message": "Configuration successfully reset to defaults.",
            }
        )
    except Exception as err:
        logger.error("Failed to reset configuration: %s", err)
        return api_response(success=False, error=str(err), status_code=500)


@api_config_bp.route("/features", methods=["GET"])
@api_config_bp.route("/enable", methods=["GET"])
def get_features():
    """
    Retrieves all enable_* feature flags and their current boolean values.
    """
    try:
        session = get_session()
        features = ConfigService.get_feature_flags(session=session)
        return jsonify({"success": True, "features": features})
    except Exception as err:
        logger.error("Failed to fetch feature flags: %s", err)
        return api_response(success=False, error=str(err), status_code=500)


@api_config_bp.route("/enable/<feature_name>", methods=["GET", "POST"])
def manage_feature(feature_name: str):
    """
    GET: Returns the boolean state of a feature flag.
    POST: Updates or toggles a feature flag (accepts {"enabled": bool} or toggles if omitted).
    """
    try:
        session = get_session()
        if request.method == "GET":
            canonical = feature_name.lower().replace("-", "_")
            if not canonical.startswith("enable_"):
                canonical = f"enable_{canonical}"
            features = ConfigService.get_feature_flags(session=session)
            if canonical not in features:
                return api_response(
                    success=False,
                    error=f"Unknown feature flag '{feature_name}'.",
                    status_code=404,
                )
            return jsonify(
                {"success": True, "feature": canonical, "enabled": features[canonical]}
            )

        # POST: toggle or set state
        payload = request.get_json(silent=True) or request.form.to_dict() or {}
        enabled_val = payload.get("enabled")
        if enabled_val is not None and isinstance(enabled_val, str):
            enabled_val = enabled_val.lower() in ("true", "1", "yes", "on")

        canonical, new_state = ConfigService.set_feature_flag(
            feature_name, enabled=enabled_val, session=session
        )
        return jsonify(
            {
                "success": True,
                "feature": canonical,
                "enabled": new_state,
                "message": f"Feature '{canonical}' updated to {new_state}.",
            }
        )
    except ValueError as val_err:
        return api_response(success=False, error=str(val_err), status_code=400)
    except Exception as err:
        logger.error("Failed to update feature '%s': %s", feature_name, err)
        return api_response(success=False, error=str(err), status_code=500)


@api_config_bp.route("/enable-background-jobs", methods=["POST"])
def enable_background_jobs_endpoint():
    """
    Convenience endpoint to enable, disable, or toggle enable_background_jobs.
    """
    return manage_feature("enable_background_jobs")


@api_config_bp.route("/enable-social-data", methods=["POST"])
def enable_social_data_endpoint():
    """
    Convenience endpoint to enable, disable, or toggle enable_social_data.
    """
    return manage_feature("enable_social_data")


@api_config_bp.route("/enable-crawling", methods=["POST"])
def enable_crawling_endpoint():
    """
    Convenience endpoint to enable, disable, or toggle enable_crawling.
    """
    return manage_feature("enable_crawling")


@api_config_bp.route("/webtools-status", methods=["GET"])
def get_webtools_status():
    """
    Checks the reachability of the configured remote webtools server.
    """
    try:
        session = get_session()
        result = WebToolsWrapper.check_remote_status(session=session)
        return jsonify({"success": True, **result})
    except Exception as err:
        logger.error("Failed to check WebTools status: %s", err)
        return api_response(success=False, error=str(err), status_code=500)


@api_config_bp.route("/test-webtools", methods=["POST"])
def test_webtools():
    """
    Tests reachability of an explicitly provided remote webtools server URL.
    """
    try:
        payload = request.get_json(silent=True) or request.form.to_dict() or {}
        test_url = payload.get("url")
        result = WebToolsWrapper.check_remote_status(remote_server_location=test_url)
        return jsonify({"success": True, **result})
    except Exception as err:
        logger.error("Failed to test WebTools server: %s", err)
        return api_response(success=False, error=str(err), status_code=500)
