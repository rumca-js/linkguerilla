"""
Web layer blueprints registration.
"""

from flask import Flask
from yafr.web.api import (
    api_config_bp,
    api_database_bp,
    api_entries_bp,
    api_history_bp,
    api_jobs_bp,
    api_logs_bp,
    api_preview_bp,
    api_rules_bp,
    api_search_views_bp,
    api_sources_bp,
    api_status_bp,
)
from yafr.web.routes_config import config_bp
from yafr.web.routes_credentials import credentials_bp
from yafr.web.routes_database import database_bp
from yafr.web.routes_entries import entries_bp
from yafr.web.routes_jobs import jobs_bp
from yafr.web.routes_logs import logs_bp
from yafr.web.routes_preview import preview_bp
from yafr.web.routes_rules import rules_bp
from yafr.web.routes_sources import sources_bp
from yafr.web.shared import get_shared_context


def register_blueprints(app: Flask) -> None:
    """
    Registers all view and API blueprints onto the Flask application.
    """
    app.register_blueprint(entries_bp)
    app.register_blueprint(sources_bp)
    app.register_blueprint(jobs_bp)
    app.register_blueprint(logs_bp)
    app.register_blueprint(preview_bp)
    app.register_blueprint(rules_bp)
    app.register_blueprint(credentials_bp)
    app.register_blueprint(database_bp)
    app.register_blueprint(config_bp)
    app.register_blueprint(api_entries_bp)
    app.register_blueprint(api_history_bp)
    app.register_blueprint(api_jobs_bp)
    app.register_blueprint(api_logs_bp)
    app.register_blueprint(api_preview_bp)
    app.register_blueprint(api_rules_bp)
    app.register_blueprint(api_search_views_bp)
    app.register_blueprint(api_sources_bp)
    app.register_blueprint(api_database_bp)
    app.register_blueprint(api_config_bp)
    app.register_blueprint(api_status_bp)

    @app.context_processor
    def inject_shared_context():
        return get_shared_context()
