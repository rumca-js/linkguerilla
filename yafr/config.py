"""
Configuration settings for YAFR application.
"""

import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = BASE_DIR / "data" / "table.db"


class Config:
    """Base application configuration."""

    # Instance identity & naming (can be customized via environment variables)
    INSTANCE_TITLE = os.environ.get("YAFR_INSTANCE_TITLE", "LinkGuerilla")
    INSTANCE_DESCRIPTION = os.environ.get(
        "YAFR_INSTANCE_DESCRIPTION", "Link manager and aggregator"
    )
    APP_NAME = INSTANCE_TITLE
    APP_DESCRIPTION = INSTANCE_DESCRIPTION

    # Console display titles
    APP_CONSOLE_TITLE = os.environ.get(
        "YAFR_APP_CONSOLE_TITLE", f"{INSTANCE_TITLE} - {INSTANCE_DESCRIPTION}"
    )
    WORKER_CONSOLE_TITLE = os.environ.get(
        "YAFR_WORKER_CONSOLE_TITLE", f"{INSTANCE_TITLE} - Background Task Processor"
    )

    SECRET_KEY = os.environ.get("YAFR_SECRET_KEY", "yafr-dev-secret-key-change-in-prod")
    DEBUG = os.environ.get("YAFR_DEBUG", "True").lower() in ("true", "1", "yes")
    HOST = os.environ.get("YAFR_HOST", "127.0.0.1")
    PORT = int(os.environ.get("YAFR_PORT", 5000))

    # SQLite Database File Location - Defaults to data/table.db
    DATABASE_PATH = os.environ.get("YAFR_DATABASE_PATH", str(DEFAULT_DB_PATH))

    # UI Configurations (Defaults loaded from or synced with configurationentry in database)
    DEFAULT_DISPLAY_STYLE = "style-dark"  # "style-light" or "style-dark"
    DEFAULT_DISPLAY_TYPE = "gallery"  # "standard", "gallery", "search-engine", "content-centric", "links-only"

    # Default limits
    MAX_SEARCH_HISTORY = 300
    MAX_VISIT_HISTORY = 5000
    LINKS_PER_PAGE = 25


# Convenience top-level constants
INSTANCE_TITLE = Config.INSTANCE_TITLE
INSTANCE_DESCRIPTION = Config.INSTANCE_DESCRIPTION
APP_NAME = Config.APP_NAME
APP_DESCRIPTION = Config.APP_DESCRIPTION
APP_CONSOLE_TITLE = Config.APP_CONSOLE_TITLE
WORKER_CONSOLE_TITLE = Config.WORKER_CONSOLE_TITLE


def set_console_title(title: str) -> None:
    """
    Sets terminal or console window title using standard ANSI escape codes,
    with an optional fallback to setproctitle if available.
    """
    try:
        if sys.stdout and hasattr(sys.stdout, "isatty") and sys.stdout.isatty():
            sys.stdout.write(f"\033]0;{title}\007")
            sys.stdout.flush()
    except Exception:
        pass

    try:
        import setproctitle  # type: ignore

        setproctitle.setproctitle(title)
    except Exception:
        pass
