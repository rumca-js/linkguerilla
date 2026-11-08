"""
System and Maintenance Background Jobs Handlers for YAFR.

Contains handlers for cleanup, storage limit enforcement, and generic tasks.
"""

import logging
from typing import Any, Dict
from sqlalchemy.orm import Session
from linkarchivetools.model.definitions import BackgroundJob, SearchHistory
from yafr.db.config_repository import ConfigRepository
from yafr.db.history_repository import HistoryRepository
from yafr.workers.jobs.base import BaseJobHandler

logger = logging.getLogger(__name__)

JOB_CLEANUP = "cleanup"


class CleanupJobHandler(BaseJobHandler):
    """
    Handler for JOB_CLEANUP ('cleanup').

    Enforces storage retention quotas across search history and other capped tables.
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
        config = config_repo.get_config()

        max_searches = config.max_number_of_user_search or 300
        history_repo.apply_storage_limit(SearchHistory, SearchHistory.id, max_searches)

        return {
            "success": True,
            "consume": True,
            "status": "completed",
            "message": f"Enforced storage caps: max_searches={max_searches}.",
        }


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
