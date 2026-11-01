"""
SystemOperation Repository Implementation for YAFR.

Manages heartbeat, status tracking, and liveness checks for background worker
threads using the systemoperation SQLite table.
"""

from datetime import datetime, timezone
import logging
from typing import Any, Dict, List, Optional
from sqlalchemy import delete, select
from sqlalchemy.orm import Session
from linkarchivetools.model.definitions import SystemOperation
from yafr.db.base_repository import BaseRepository

logger = logging.getLogger(__name__)

DEFAULT_WORKER_TIMEOUT_SECONDS = 600  # 10 minutes


def _normalize_datetime(dt: Any) -> Optional[datetime]:
    """
    Normalizes a datetime or ISO string to a UTC timezone-aware datetime.
    """
    if dt is None:
        return None
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt)
        except Exception:
            return None
    if isinstance(dt, datetime):
        if dt.tzinfo is not None:
            return dt.astimezone(timezone.utc)
        return dt.replace(tzinfo=timezone.utc)
    return None


class SystemOperationRepository(BaseRepository[SystemOperation]):
    """
    Data access repository for worker liveness and operational heartbeat status.
    """

    def __init__(self, session: Optional[Session] = None) -> None:
        super().__init__(session=session)

    def get_latest_operation(
        self, check_type: Optional[str] = None
    ) -> Optional[SystemOperation]:
        """
        Retrieves the latest SystemOperation record.

        :param check_type: Optional filter by check_type (e.g. 'worker')
        :return: SystemOperation instance or None
        """
        stmt = select(SystemOperation)
        if check_type:
            stmt = stmt.where(SystemOperation.check_type == check_type)
        stmt = stmt.order_by(SystemOperation.id.desc())
        return self.session.execute(stmt).scalars().first()

    def record_heartbeat(
        self,
        status: bool = True,
        thread_id: Optional[str] = None,
        check_type: str = "worker",
    ) -> SystemOperation:
        """
        Records or updates a worker heartbeat in the systemoperation table.

        Guarantees that the table contains only one row holding the date/status.

        :param status: Boolean status (True indicates worker is ok)
        :param thread_id: Thread or process identifier string
        :param check_type: Operation type identifier (default: 'worker')
        :return: The updated or newly created SystemOperation record
        """
        now = datetime.now(timezone.utc)
        stmt = select(SystemOperation).order_by(SystemOperation.id.asc())
        rows = list(self.session.execute(stmt).scalars().all())

        if rows:
            record = rows[0]
            record.date_created = now
            record.status = bool(status)
            record.check_type = check_type
            if thread_id is not None:
                record.thread_id = str(thread_id)

            # Keep only one row in the table
            if len(rows) > 1:
                for excess in rows[1:]:
                    self.session.delete(excess)
        else:
            record = SystemOperation(
                date_created=now,
                thread_id=str(thread_id or ""),
                check_type=check_type,
                status=bool(status),
            )
            self.session.add(record)

        self.commit()
        self.session.refresh(record)
        logger.debug(
            "Recorded worker heartbeat: status=%s, check_type='%s', thread_id='%s'",
            status,
            check_type,
            thread_id,
        )
        return record

    def check_worker_status(
        self,
        max_age_seconds: int = DEFAULT_WORKER_TIMEOUT_SECONDS,
        check_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Evaluates whether the background worker/thread is active or dead based
        on the systemoperation table row and its last written timestamp.

        A worker is considered 'active' if and only if:
        1. A systemoperation row exists.
        2. Its 'status' column is True (indicating it is ok).
        3. Its 'date_created' is within max_age_seconds (default 600s = 10 minutes).

        If older than 10 minutes, status is False, or row is missing, it is 'dead'.

        :param max_age_seconds: Maximum allowed age in seconds before considered dead (default: 600)
        :param check_type: Optional filter by check_type
        :return: Dict describing worker liveness state
        """
        record = self.get_latest_operation(check_type=check_type)
        now = datetime.now(timezone.utc)

        if not record:
            return {
                "is_active": False,
                "status": False,
                "status_label": "dead",
                "date_created": None,
                "last_written": None,
                "age_seconds": None,
                "age_minutes": None,
                "thread_id": "",
                "check_type": check_type or "",
                "message": "No worker heartbeat record found in systemoperation table. Worker is dead.",
                "max_age_seconds": max_age_seconds,
            }

        normalized_date = _normalize_datetime(record.date_created)
        if normalized_date is None:
            return {
                "is_active": False,
                "status": bool(record.status),
                "status_label": "dead",
                "date_created": None,
                "last_written": None,
                "age_seconds": None,
                "age_minutes": None,
                "thread_id": record.thread_id or "",
                "check_type": record.check_type or "",
                "message": "Worker record has invalid or missing timestamp. Worker is dead.",
                "max_age_seconds": max_age_seconds,
            }

        age_seconds = max(0.0, (now - normalized_date).total_seconds())
        age_minutes = round(age_seconds / 60.0, 1)

        is_timed_out = age_seconds > max_age_seconds
        is_ok_status = bool(record.status)
        is_active = is_ok_status and not is_timed_out

        status_label = "active" if is_active else "dead"

        if not is_ok_status:
            message = "Worker status flag is set to not ok. Worker is dead."
        elif is_timed_out:
            message = (
                f"Worker heartbeat is older than 10 minutes ({age_minutes} min ago, "
                f"limit: {max_age_seconds // 60} min). Worker is dead."
            )
        else:
            message = f"Worker is active and ok (last heartbeat {round(age_seconds, 1)}s ago)."

        return {
            "is_active": is_active,
            "status": is_ok_status,
            "status_label": status_label,
            "date_created": normalized_date.isoformat(),
            "last_written": normalized_date.isoformat(),
            "age_seconds": round(age_seconds, 1),
            "age_minutes": age_minutes,
            "thread_id": record.thread_id or "",
            "check_type": record.check_type or "",
            "message": message,
            "max_age_seconds": max_age_seconds,
        }

    def clear_operations(self) -> int:
        """
        Deletes all rows in the systemoperation table.

        :return: Count of deleted rows
        """
        stmt = delete(SystemOperation)
        res = self.session.execute(stmt)
        self.commit()
        return res.rowcount or 0
