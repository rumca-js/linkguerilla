"""
Logging Repository Implementation for YAFR.

Persists structured application events into the applogging SQLite table
with standard severity levels and FIFO retention management.
"""

from datetime import datetime, timezone
import logging
from typing import List, Optional
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session
from linkarchivetools.model.definitions import AppLogging
from yafr.db.base_repository import BaseRepository

logger = logging.getLogger(__name__)

NOTIFICATION = 25
logging.addLevelName(NOTIFICATION, "NOTIFICATION")


def _logger_notification(self: logging.Logger, message: str, *args, **kwargs) -> None:
    """Convenience method to log events at NOTIFICATION (25) severity level."""
    if self.isEnabledFor(NOTIFICATION):
        self._log(NOTIFICATION, message, args, **kwargs)


if not hasattr(logging.Logger, "notification"):
    logging.Logger.notification = _logger_notification


class LoggingRepository(BaseRepository[AppLogging]):
    """
    Data access repository for application logging events.
    """

    # Severity Level Constants matching standard Python logging
    DEBUG = 10
    INFO = 20
    NOTIFICATION = 25
    WARNING = 30
    ERROR = 40
    CRITICAL = 50

    def __init__(self, session: Optional[Session] = None) -> None:
        super().__init__(session=session)

    def log(
        self,
        info_text: str,
        detail_text: Optional[str] = None,
        level: int = INFO,
        max_limit: int = 2000,
    ) -> AppLogging:
        """
        Records an event log entry and enforces rolling FIFO retention.

        :param info_text: Brief description of the event
        :param detail_text: Optional detailed message, traceback, or context
        :param level: Integer severity level (10=DEBUG, 20=INFO, 30=WARN, 40=ERROR, 50=CRIT)
        :param max_limit: Maximum log rows to retain in database (default: 2000)
        :return: Persisted AppLogging instance
        """
        entry = AppLogging(
            info_text=info_text[:2000] if info_text else "",
            detail_text=detail_text[:2000] if detail_text else None,
            level=level,
            date=datetime.now(timezone.utc),
        )
        self.session.add(entry)
        self.session.commit()

        # Enforce storage cap
        self.apply_storage_limit(AppLogging, AppLogging.id, max_limit)
        return entry

    def list_logs(
        self,
        min_level: Optional[int] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[AppLogging]:
        """
        Retrieves log events ordered by most recent first.

        :param min_level: Optional minimum severity level filter
        :param limit: Maximum rows to return (default: 100)
        :param offset: Number of rows to skip
        :return: List of AppLogging instances
        """
        stmt = select(AppLogging).order_by(AppLogging.id.desc())
        if min_level is not None:
            stmt = stmt.where(AppLogging.level >= min_level)

        if offset > 0:
            stmt = stmt.offset(offset)
        if limit > 0:
            stmt = stmt.limit(limit)

        return list(self.session.execute(stmt).scalars().all())

    def count_logs(self, min_level: Optional[int] = None) -> int:
        """
        Counts log entries matching optional severity filter.

        :param min_level: Optional minimum severity level filter
        :return: Total count of matching log entries
        """
        stmt = select(func.count(AppLogging.id))
        if min_level is not None:
            stmt = stmt.where(AppLogging.level >= min_level)
        return self.session.execute(stmt).scalar() or 0

    def delete_log(self, log_id: int) -> bool:
        """
        Deletes a single log entry by ID.

        :param log_id: Primary key of the log entry
        :return: True if deleted, False if not found
        """
        entry = self.get_by_id(AppLogging, log_id)
        if not entry:
            return False
        self.session.delete(entry)
        self.session.commit()
        return True

    def clear_logs(self) -> int:
        """
        Truncates all entries in the applogging table.

        :return: Count of deleted rows
        """
        stmt = delete(AppLogging)
        result = self.session.execute(stmt)
        self.session.commit()
        return result.rowcount or 0


class AppLoggingHandler(logging.Handler):
    """
    Standard logging.Handler that persists records >= threshold (default NOTIFICATION = 25)
    into the SQLite applogging table via LoggingRepository.
    """

    def __init__(self, level: int = NOTIFICATION, max_limit: int = 2000) -> None:
        super().__init__(level=level)
        self.max_limit = max_limit

    def emit(self, record: logging.LogRecord) -> None:
        # Prevent recursive logging loops from database operations or sqlalchemy
        if record.name.startswith(
            "yafr.db.logging_repository"
        ) or record.name.startswith("sqlalchemy"):
            return

        try:
            from yafr.db.session import get_engine

            engine = get_engine()
            info_text = record.getMessage()
            detail_text = None

            if record.exc_info:
                detail_text = self.format(record)
            elif record.levelno >= logging.ERROR:
                detail_text = f"{record.name} ({record.filename}:{record.lineno})"

            with Session(engine) as session:
                repo = LoggingRepository(session=session)
                repo.log(
                    info_text=info_text,
                    detail_text=detail_text,
                    level=record.levelno,
                    max_limit=self.max_limit,
                )
        except Exception:
            self.handleError(record)


def setup_app_logging(
    logger_name: str = "yafr",
    level: int = NOTIFICATION,
    max_limit: int = 2000,
) -> AppLoggingHandler:
    """
    Attaches AppLoggingHandler to the specified logger if not already attached.

    :param logger_name: Name of logger to attach handler to (default: "yafr")
    :param level: Minimum severity level threshold (default: NOTIFICATION = 25)
    :param max_limit: Maximum log rows to retain in database (default: 2000)
    :return: Attached or existing AppLoggingHandler instance
    """
    target_logger = logging.getLogger(logger_name)
    for h in target_logger.handlers:
        if isinstance(h, AppLoggingHandler):
            return h

    handler = AppLoggingHandler(level=level, max_limit=max_limit)
    target_logger.addHandler(handler)
    return handler
