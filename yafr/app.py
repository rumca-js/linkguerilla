"""
Flask application factory for YAFR.
"""

import logging
from flask import Flask, jsonify, render_template, request
from sqlalchemy.exc import SQLAlchemyError
from yafr.config import Config
from yafr.db import close_session, init_db
from yafr.web import register_blueprints

logger = logging.getLogger(__name__)


def create_app(config_object=None) -> Flask:
    """
    Constructs and configures the Flask application.

    :param config_object: Optional configuration dict or class
    :return: Configured Flask application instance
    """
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
    )

    app.config.from_object(Config)
    if config_object:
        if isinstance(config_object, dict):
            app.config.from_mapping(config_object)
        else:
            app.config.from_object(config_object)

    # Initialize SQLite database connection & schema
    db_path = app.config.get("DATABASE_PATH", Config.DATABASE_PATH)
    try:
        init_db(db_path)
    except Exception as err:
        logger.error("Failed to initialize database at %s: %s", db_path, err)

    # Teardown context hook to close scoped session
    @app.teardown_appcontext
    def shutdown_session(exception=None):
        close_session()

    # Register routes and views
    register_blueprints(app)

    # Error Handlers
    @app.errorhandler(SQLAlchemyError)
    def database_error(error):
        logger.error("Database error occurred: %s", error)
        close_session()
        if request.path.startswith("/api/") or request.is_json:
            return jsonify({"success": False, "error": f"Database failure: {error}"}), 500
        return (
            render_template(
                "entries/list.html",
                error_message=f"Database failure: {error}",
                query="",
                has_query=False,
                entries=[],
            ),
            500,
        )

    @app.errorhandler(404)
    def not_found_error(error):
        if request.path.startswith("/api/") or request.is_json:
            return jsonify({"success": False, "error": "Not found (404)."}), 404
        return (
            render_template(
                "entries/list.html",
                error_message="Page or entry not found (404).",
                query="",
                has_query=False,
                entries=[],
            ),
            404,
        )

    @app.errorhandler(500)
    def internal_error(error):
        if request.path.startswith("/api/") or request.is_json:
            return jsonify({"success": False, "error": f"Internal server error: {error}"}), 500
        return (
            render_template(
                "entries/list.html",
                error_message="Internal server error (500).",
                query="",
                has_query=False,
                entries=[],
            ),
            500,
        )

    return app
