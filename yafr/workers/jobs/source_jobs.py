"""
Source Background Jobs Handlers for YAFR.

Contains handlers for source-related tasks, including JOB_PROCESS_SOURCE ('process-source').
"""

import logging
from typing import Any, Dict, Optional
from sqlalchemy.orm import Session
from linkarchivetools.model.definitions import BackgroundJob, SourcesTable
from yafr.db.source_repository import SourceRepository
from yafr.services.source_service import SourceService
from yafr.workers.jobs.base import BaseJobHandler

logger = logging.getLogger(__name__)

JOB_PROCESS_SOURCE = "process-source"


class ProcessSourceJobHandler(BaseJobHandler):
    """
    Handler for JOB_PROCESS_SOURCE ('process-source').

    Fetches, parses, and ingests RSS/email feed entries for a configured source.
    """

    job_types = (JOB_PROCESS_SOURCE, "JOB_PROCESS_SOURCE")

    def execute(self, job: BackgroundJob, session: Session) -> Dict[str, Any]:
        """
        Executes a source feed fetch task.

        :param job: BackgroundJob record
        :param session: Active database session
        :return: Execution result dictionary
        """
        subject = (job.subject or "").strip()
        source_repo = SourceRepository(session)
        source: Optional[SourcesTable] = None

        if subject.isdigit():
            source = source_repo.get_by_id(int(subject))
        elif subject:
            source = source_repo.get_by_url(subject)

        if not source:
            return {
                "success": False,
                "consume": True,
                "status": "error",
                "error": f"Source not found for subject: '{subject}'",
            }

        if not source.enabled:
            logger.info(
                "Source #%d (%s) is disabled. Skipping fetch.", source.id, source.title
            )
            return {
                "success": True,
                "consume": True,
                "status": "skipped",
                "message": f"Source #{source.id} is disabled, skipped.",
            }

        res = SourceService.fetch_source(source.id, session=session)
        if "consume" not in res:
            res["consume"] = True
        return res
