"""
Configuration settings for YAFR application.
"""

import os
import re
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = BASE_DIR / "data" / "table.db"


def _load_version() -> str:
    """
    Retrieves application version.
    Loads from pyproject.toml if present, falls back to package metadata,
    and respects the YAFR_VERSION environment variable override.
    """
    env_ver = os.environ.get("YAFR_VERSION")
    if env_ver:
        return env_ver.strip()

    pyproject_file = BASE_DIR / "pyproject.toml"
    if pyproject_file.is_file():
        try:
            try:
                import tomllib
            except ImportError:
                import tomli as tomllib  # type: ignore

            with open(pyproject_file, "rb") as f:
                data = tomllib.load(f)
                ver = data.get("tool", {}).get("poetry", {}).get("version")
                if ver:
                    return str(ver).strip()
        except Exception:
            pass

        try:
            content = pyproject_file.read_text(encoding="utf-8")
            match = re.search(r'(?m)^\s*version\s*=\s*["\']([^"\']+)["\']', content)
            if match:
                return match.group(1).strip()
        except Exception:
            pass

    try:
        from importlib.metadata import version

        return version("yafr_next")
    except Exception:
        pass

    return "0.1.3"


class Config:
    """Base application configuration."""

    # Version information
    VERSION = _load_version()
    APP_VERSION = VERSION

    # Instance identity & naming (can be customized via environment variables)
    INSTANCE_TITLE = os.environ.get("YAFR_INSTANCE_TITLE", "LinkGuerilla")
    INSTANCE_DESCRIPTION = os.environ.get(
        "YAFR_INSTANCE_DESCRIPTION", "Link manager and aggregator"
    )
    APP_NAME = INSTANCE_TITLE
    APP_DESCRIPTION = INSTANCE_DESCRIPTION

    # Console and footer display titles
    APP_CONSOLE_TITLE = os.environ.get(
        "YAFR_APP_CONSOLE_TITLE", f"{INSTANCE_TITLE} - {INSTANCE_DESCRIPTION}"
    )
    WORKER_CONSOLE_TITLE = os.environ.get(
        "YAFR_WORKER_CONSOLE_TITLE", f"{INSTANCE_TITLE} - Background Task Processor"
    )
    FOOTER = os.environ.get(
        "YAFR_FOOTER", f"{INSTANCE_TITLE} v{VERSION} - {INSTANCE_DESCRIPTION}"
    )
    APP_FOOTER = FOOTER

    SECRET_KEY = os.environ.get("YAFR_SECRET_KEY", "yafr-dev-secret-key-change-in-prod")
    DEBUG = os.environ.get("YAFR_DEBUG", "False").lower() in ("true", "1", "yes")
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
VERSION = Config.VERSION
APP_VERSION = Config.APP_VERSION
__version__ = Config.VERSION
FOOTER = Config.FOOTER
APP_FOOTER = Config.APP_FOOTER
get_version = _load_version


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
