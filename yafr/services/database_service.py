"""
Database Management Service for YAFR.

Coordinates database statistics calculation, row counts across all relevant tables,
table truncations / cache clearing, display name updates, and safe remote database
download and atomic replacement.
"""

from datetime import datetime, timezone
import logging
import os
from pathlib import Path
import sqlite3
import time
from typing import Any, Dict, List, Optional
import urllib.request
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session
from linkarchivetools.model.definitions import (
    ConfigurationEntry,
    SourceOperationalData,
)
from yafr.config import Config
from yafr.db.config_repository import ConfigRepository
from yafr.db.entry_repository import EntryRepository
from yafr.db.history_repository import HistoryRepository
from yafr.db.source_repository import SourceRepository
from yafr.db.session import (
    close_session,
    get_engine,
    get_session,
    init_db,
)

logger = logging.getLogger(__name__)

# List of relevant database tables with friendly labels and descriptions
DATABASE_TABLE_METADATA = [
    {
        "table_name": "linkdatamodel",
        "label": "Link Entries",
        "description": "Primary searchable archive links, articles, and bookmarks",
        "icon": "bi-link-45deg",
    },
    {
        "table_name": "sourcedatamodel",
        "label": "Sources",
        "description": "Configured RSS feeds, Email IMAP inboxes, and XPath parsers",
        "icon": "bi-rss",
    },
    {
        "table_name": "sourceoperationaldata",
        "label": "Source Operational Data",
        "description": "Fetch timestamps, content hashes, and error counters for sources",
        "icon": "bi-activity",
    },
    {
        "table_name": "entrycompactedtags",
        "label": "Entry Tags",
        "description": "Relational tag mappings assigned to individual entries",
        "icon": "bi-tags",
    },
    {
        "table_name": "usertags",
        "label": "User Tags",
        "description": "User-defined unique tag keywords",
        "icon": "bi-tag",
    },
    {
        "table_name": "compactedtags",
        "label": "Compacted Tags",
        "description": "Global catalog of unique tags with aggregated counts",
        "icon": "bi-hash",
    },
    {
        "table_name": "backgroundjob",
        "label": "Background Jobs",
        "description": "Asynchronous task queue for feeds and metadata updates",
        "icon": "bi-cpu",
    },
    {
        "table_name": "configurationentry",
        "label": "Configuration",
        "description": "Instance display styles, themes, and storage limit quotas",
        "icon": "bi-gear",
    },
    {
        "table_name": "searchhistory",
        "label": "Search History",
        "description": "Historical search queries recorded for autocomplete",
        "icon": "bi-clock-history",
    },
    {
        "table_name": "entryvisithistory",
        "label": "Visited Entries",
        "description": "Tracking logs and frequency counters for visited entries",
        "icon": "bi-eye",
    },
    {
        "table_name": "readlater",
        "label": "Read Later",
        "description": "Bookmarked entries flagged for deferred reading",
        "icon": "bi-bookmark-check",
    },
    {
        "table_name": "socialdata",
        "label": "Social Data",
        "description": "Cached likes, views, followers, and social engagement metrics",
        "icon": "bi-heart",
    },
    {
        "table_name": "applogging",
        "label": "Application Logs",
        "description": "Structured operational log entries across severity levels",
        "icon": "bi-journal-text",
    },
    {
        "table_name": "entryrules",
        "label": "Entry Rules",
        "description": "Regex pattern rules for blocking, trusting, and auto-tagging",
        "icon": "bi-shield-check",
    },
    {
        "table_name": "blockentrylist",
        "label": "Block Entry Lists",
        "description": "Source URLs of plain text blocklists (e.g. EasyList)",
        "icon": "bi-shield-slash",
    },
    {
        "table_name": "blockentry",
        "label": "Block Entries",
        "description": "Blocked URLs, domains, and patterns extracted from blocklists",
        "icon": "bi-slash-circle",
    },
    {
        "table_name": "entrytransitionhistory",
        "label": "Entry Transitions",
        "description": "Directed navigation transitions between entries with frequency counters",
        "icon": "bi-arrow-left-right",
    },
]


def format_file_size(size_bytes: int) -> str:
    """
    Formats a raw byte count into a human-readable file size string.
    """
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


class DatabaseService:
    """
    Domain service for database administration, statistics, and remote downloads.
    """

    @classmethod
    def get_active_db_path(cls) -> str:
        """
        Resolves the filesystem path or connection string of the active database.
        """
        engine = get_engine()
        if engine and engine.url and engine.url.database:
            return str(engine.url.database)
        return os.environ.get("YAFR_DATABASE_PATH", "data/table.db")

    @classmethod
    def get_database_info(cls, session: Optional[Session] = None) -> Dict[str, Any]:
        """
        Collects comprehensive metadata, file metrics, and table row counts.

        :param session: Optional active database session
        :return: Dict containing database statistics and metadata
        """
        sess = session or get_session()
        config_repo = ConfigRepository(sess)
        config = config_repo.get_config()

        db_path_str = cls.get_active_db_path()
        file_size_bytes = 0
        date_created_str = "—"
        date_modified_str = "—"
        is_memory = db_path_str == ":memory:"

        if not is_memory and os.path.exists(db_path_str):
            try:
                st = os.stat(db_path_str)
                file_size_bytes = st.st_size
                date_created_str = datetime.fromtimestamp(
                    st.st_ctime, tz=timezone.utc
                ).strftime("%Y-%m-%d %H:%M:%S")
                date_modified_str = datetime.fromtimestamp(
                    st.st_mtime, tz=timezone.utc
                ).strftime("%Y-%m-%d %H:%M:%S")
            except Exception as err:
                logger.warning(
                    "Could not read stat for database file %s: %s", db_path_str, err
                )

        # Check last fetch timestamp from SourceOperationalData
        try:
            stmt = select(func.max(SourceOperationalData.date_fetched))
            last_fetch_dt = sess.execute(stmt).scalar()
            if last_fetch_dt:
                date_last_refresh_str = last_fetch_dt.strftime("%Y-%m-%d %H:%M:%S")
            else:
                date_last_refresh_str = date_modified_str
        except Exception:
            date_last_refresh_str = date_modified_str

        # Table row counts
        tables_counts: Dict[str, int] = {}
        tables_detailed: List[Dict[str, Any]] = []

        for meta in DATABASE_TABLE_METADATA:
            t_name = meta["table_name"]
            try:
                count = (
                    sess.execute(text(f"SELECT count(*) FROM {t_name}")).scalar() or 0
                )
            except Exception:
                count = 0
            tables_counts[t_name] = count
            tables_detailed.append(
                {
                    "table_name": t_name,
                    "label": meta["label"],
                    "description": meta["description"],
                    "icon": meta["icon"],
                    "count": count,
                }
            )

        return {
            "database_name": config.instance_title or Config.INSTANCE_TITLE,
            "database_description": config.instance_description
            or Config.INSTANCE_DESCRIPTION,
            "database_type": (
                "SQLite 3 (:memory:)" if is_memory else "SQLite 3 (WAL mode)"
            ),
            "database_file": db_path_str,
            "file_size_bytes": file_size_bytes,
            "file_size_formatted": (
                "0 B (In-Memory)" if is_memory else format_file_size(file_size_bytes)
            ),
            "remote_url": config.instance_internet_location,
            "date_created": date_created_str,
            "date_last_modified": date_modified_str,
            "date_last_refresh": date_last_refresh_str,
            "tables": tables_counts,
            "tables_detailed": tables_detailed,
        }

    @classmethod
    def update_database_name(
        cls, instance_title: str, session: Optional[Session] = None
    ) -> str:
        """
        Updates the human-readable display name for the database instance.

        :param instance_title: New display title
        :param session: Optional active database session
        :return: Updated title
        """
        cleaned = instance_title.strip()
        if not cleaned:
            raise ValueError("Database display name cannot be empty.")

        sess = session or get_session()
        config_repo = ConfigRepository(sess)
        config = config_repo.update_config(instance_title=cleaned)
        return config.instance_title

    @classmethod
    def clear_search_history(cls, session: Optional[Session] = None) -> int:
        """
        Clears all records in the searchhistory table.
        """
        sess = session or get_session()
        repo = HistoryRepository(sess)
        return repo.clear_search_history()

    @classmethod
    def clear_visited_entries(cls, session: Optional[Session] = None) -> int:
        """
        Clears all records in the entryvisithistory table.
        """
        sess = session or get_session()
        repo = HistoryRepository(sess)
        return repo.clear_visit_history()

    @classmethod
    def clear_read_later(cls, session: Optional[Session] = None) -> int:
        """
        Clears all records in the readlater table.
        """
        sess = session or get_session()
        repo = HistoryRepository(sess)
        return repo.clear_read_later()

    @classmethod
    def clear_social_data(cls, session: Optional[Session] = None) -> int:
        """
        Clears all records in the socialdata table.
        """
        sess = session or get_session()
        repo = EntryRepository(sess)
        return repo.clear_all_social_data()

    @classmethod
    def clear_sources(cls, session: Optional[Session] = None) -> Dict[str, int]:
        """
        Clears all source-related data: sourcedatamodel, sourceoperationaldata,
        sourcecategories, and sourcesubcategories tables.
        Entries are unlinked (source_id set to NULL) but not deleted.

        :param session: Optional active database session
        :return: Dict mapping table names to deleted row counts
        """
        sess = session or get_session()
        repo = SourceRepository(sess)
        return repo.clear_all_sources()

    @classmethod
    def clear_links(cls, session: Optional[Session] = None) -> Dict[str, int]:
        """
        Clears all records in linkdatamodel and all tables that depend on it
        (tags, social data, read later, visit history, transition history).

        :param session: Optional active database session
        :return: Dict mapping table names to deleted row counts
        """
        sess = session or get_session()
        repo = EntryRepository(sess)
        return repo.clear_all_entries()

    @classmethod
    def replace_database_from_url(cls, remote_url: str) -> Dict[str, Any]:
        """
        Downloads a remote SQLite database file from a URL, validates integrity,
        and atomically swaps it with the current active database file.

        :param remote_url: HTTP or HTTPS URL to download .db file from
        :return: Dict with success flag and message
        """
        cleaned_url = remote_url.strip()
        if not (
            cleaned_url.startswith("http://") or cleaned_url.startswith("https://")
        ):
            raise ValueError("URL must start with http:// or https://")

        active_db_path = cls.get_active_db_path()
        if active_db_path == ":memory:":
            raise ValueError(
                "Cannot replace an in-memory database (:memory:) with an external file."
            )

        active_path = Path(active_db_path).resolve()
        temp_file_path = active_path.parent / f"download_{int(time.time())}.db"

        try:
            # 1. Download file with user agent and timeout
            req = urllib.request.Request(
                cleaned_url,
                headers={"User-Agent": "YAFR-Database-Sync/1.0"},
            )
            with urllib.request.urlopen(req, timeout=30) as response:
                with open(temp_file_path, "wb") as out_file:
                    while chunk := response.read(65536):
                        out_file.write(chunk)

            # 2. Validate SQLite Header (first 16 bytes)
            if not temp_file_path.exists() or temp_file_path.stat().st_size < 100:
                raise ValueError(
                    "Downloaded file is too small to be a valid SQLite database."
                )

            with open(temp_file_path, "rb") as f:
                header = f.read(16)
                if header != b"SQLite format 3\x00":
                    raise ValueError(
                        "Downloaded file is not a valid SQLite 3 database."
                    )

            # 3. Verify Database Integrity using sqlite3 library
            con = sqlite3.connect(str(temp_file_path))
            try:
                cur = con.cursor()
                integrity = cur.execute("PRAGMA integrity_check;").fetchall()
                if not integrity or integrity[0][0] != "ok":
                    raise ValueError("Database failed SQLite integrity check.")
            finally:
                con.close()

            # 4. Atomic Swap
            close_session()
            engine = get_engine()
            if engine:
                engine.dispose()

            # Create backup of old database if it exists
            backup_path = active_path.parent / f"{active_path.name}.bak"
            if active_path.exists():
                try:
                    active_path.replace(backup_path)
                except Exception as b_err:
                    logger.warning(
                        "Could not create .bak backup of database: %s", b_err
                    )

            # Atomically replace active file
            os.replace(str(temp_file_path), str(active_path))

            # Remove any stale -wal or -shm files from old database
            wal_file = Path(f"{active_path}-wal")
            shm_file = Path(f"{active_path}-shm")
            if wal_file.exists():
                try:
                    wal_file.unlink()
                except Exception:
                    pass
            if shm_file.exists():
                try:
                    shm_file.unlink()
                except Exception:
                    pass

            # 5. Reinitialize Database Connection
            init_db(str(active_path), sync_schema=True)

            logger.info(
                "Successfully replaced database from remote URL: %s", cleaned_url
            )
            return {
                "success": True,
                "message": "Database downloaded, verified, and replaced successfully.",
            }
        except Exception as err:
            logger.error("Failed to replace database from URL %s: %s", cleaned_url, err)
            if temp_file_path.exists():
                try:
                    temp_file_path.unlink()
                except Exception:
                    pass
            raise

    @classmethod
    def get_known_tables(cls) -> List[Dict[str, Any]]:
        """
        Dynamically returns all discovered database tables with row counts and metadata.
        """
        from yafr.services.schema_service import SchemaService

        return SchemaService.get_tables(
            engine=get_engine(), metadata_lookup=DATABASE_TABLE_METADATA
        )

    @classmethod
    def get_table_columns(cls, table_name: str) -> List[Dict[str, Any]]:
        """
        Dynamically inspects and returns all columns of a specified table.
        """
        from yafr.services.schema_service import SchemaService

        return SchemaService.get_table_columns(
            table_name=table_name, engine=get_engine()
        )

    @classmethod
    def alter_column_default(
        cls,
        table_name: str,
        column_name: str,
        default_value: Any,
        backfill_existing: bool = True,
    ) -> Dict[str, Any]:
        """
        Modifies a column's default value constraint and optionally backfills existing NULL rows.
        """
        from yafr.services.schema_service import SchemaService

        return SchemaService.alter_column_default(
            table_name=table_name,
            column_name=column_name,
            default_value=default_value,
            backfill_existing=backfill_existing,
            engine=get_engine(),
        )
