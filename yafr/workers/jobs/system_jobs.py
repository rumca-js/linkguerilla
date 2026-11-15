"""
System and Maintenance Background Jobs Handlers for YAFR.

Contains handlers for cleanup, storage limit enforcement, and generic tasks.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from sqlalchemy import select
from sqlalchemy.orm import Session
from linkarchivetools.model.definitions import (
    BackgroundJob,
    ConfigurationEntry,
    LinkDataModel,
    SearchHistory,
)
from yafr.db.config_repository import ConfigRepository
from yafr.db.entry_repository import EntryRepository
from yafr.db.history_repository import HistoryRepository
from yafr.workers.jobs.base import BaseJobHandler

logger = logging.getLogger(__name__)

JOB_CLEANUP = "cleanup"


class CleanupJobHandler(BaseJobHandler):
    """
    Handler for JOB_CLEANUP ('cleanup').

    Enforces storage retention quotas across search history and other capped tables.
    Also removes entries older than days_to_remove_links (by date_published/date_created)
    and entries dead for longer than days_to_remove_stale_entries (by date_dead_since).
    Skips removal when the respective days_ property is 0.
    """

    job_types = (JOB_CLEANUP, "JOB_CLEANUP")

    def execute(self, job: BackgroundJob, session: Session) -> Dict[str, Any]:
        """
        Executes storage cleanup task.

        :param job: BackgroundJob record
        :param session: Active database session
        :return: Execution result dictionary
        """
        config_repo = ConfigRepository(session)
        history_repo = HistoryRepository(session)
        entry_repo = EntryRepository(session)
        config = config_repo.get_config()

        max_searches = config.max_number_of_user_search or 300
        history_repo.apply_storage_limit(SearchHistory, SearchHistory.id, max_searches)

        removed_links = self._remove_old_links(
            session, entry_repo, config.days_to_remove_links, config
        )
        removed_stale = self._remove_stale_dead_entries(
            session, entry_repo, config.days_to_remove_stale_entries, config
        )

        msg = (
            f"Enforced storage caps: max_searches={max_searches}. "
            f"Removed links older than days_to_remove_links={config.days_to_remove_links}: {removed_links}. "
            f"Removed stale dead entries older than days_to_remove_stale_entries={config.days_to_remove_stale_entries}: {removed_stale}."
        )
        return {
            "success": True,
            "consume": True,
            "status": "completed",
            "message": msg,
        }

    def _apply_retention_filters(self, stmt: Any, config: ConfigurationEntry) -> Any:
        """
        Applies exclusion filters on entry queries based on ConfigurationEntry switches:
        - allow_remove_permanent_entries: protects permanent entries when False
        - allow_remove_bookmarked_entries: protects bookmarked entries when False
        - allow_remove_votes_entries: protects voted entries (or capped by remove_entry_vote_threshold)
        """
        return EntryRepository.apply_retention_filters(stmt, config)

    def _remove_old_links(
        self,
        session: Session,
        entry_repo: EntryRepository,
        days: int,
        config: Optional[ConfigurationEntry] = None,
    ) -> int:
        """
        Removes entries whose date_published (or date_created if date_published is NULL)
        is older than the given number of days. Skips if days <= 0.
        Respects protection switches on ConfigurationEntry.

        :param session: Active database session
        :param entry_repo: EntryRepository instance
        :param days: Retention period in days; 0 means disabled
        :param config: Optional active ConfigurationEntry instance
        :return: Number of entries removed
        """
        if not days or days <= 0:
            return 0

        if config is None:
            config = ConfigRepository(session).get_config()

        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        stmt = select(LinkDataModel.id).where(
            (
                (LinkDataModel.date_published != None)
                & (LinkDataModel.date_published < cutoff)
            )
            | (
                (LinkDataModel.date_published == None)
                & (LinkDataModel.date_created != None)
                & (LinkDataModel.date_created < cutoff)
            )
        )
        stmt = self._apply_retention_filters(stmt, config)
        entry_ids: List[int] = list(session.execute(stmt).scalars().all())
        if not entry_ids:
            return 0

        removed = entry_repo.delete_entries(entry_ids)
        logger.info(
            "Cleanup: removed %d link entries older than %d days.", removed, days
        )
        return removed

    def _remove_stale_dead_entries(
        self,
        session: Session,
        entry_repo: EntryRepository,
        days: int,
        config: Optional[ConfigurationEntry] = None,
    ) -> int:
        """
        Removes entries where date_dead_since is older than the given number of days.
        Skips if days <= 0.
        Respects protection switches on ConfigurationEntry.

        :param session: Active database session
        :param entry_repo: EntryRepository instance
        :param days: Retention period in days for dead entries; 0 means disabled
        :param config: Optional active ConfigurationEntry instance
        :return: Number of entries removed
        """
        if not days or days <= 0:
            return 0

        if config is None:
            config = ConfigRepository(session).get_config()

        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        stmt = (
            select(LinkDataModel.id)
            .where(LinkDataModel.date_dead_since != None)
            .where(LinkDataModel.date_dead_since < cutoff)
        )
        stmt = self._apply_retention_filters(stmt, config)
        entry_ids: List[int] = list(session.execute(stmt).scalars().all())
        if not entry_ids:
            return 0

        removed = entry_repo.delete_entries(entry_ids)
        logger.info(
            "Cleanup: removed %d stale dead entries (dead for >%d days).", removed, days
        )
        return removed


class GenericJobHandler(BaseJobHandler):
    """
    Fallback handler for custom or unknown job types.
    """

    job_types = ()

    def can_handle(self, job_type: str) -> bool:
        return True

    def execute(self, job: BackgroundJob, session: Session) -> Dict[str, Any]:
        logger.info("Executing custom/generic job type: '%s'", job.job)
        return {
            "success": True,
            "consume": True,
            "status": "completed",
            "message": f"Processed generic task: {job.job}",
        }
