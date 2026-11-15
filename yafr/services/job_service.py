"""
Job Service Implementation for YAFR.

Coordinates background task queue operations, job creation, state transitions
(pause, resume), batch mutations, and prioritization according to project specifications.
"""

import logging
from typing import Any, Dict, List, Optional
from sqlalchemy.orm import Session
from linkarchivetools.model.definitions import BackgroundJob
from yafr.db.job_repository import JobRepository
from yafr.db.session import get_session

logger = logging.getLogger(__name__)

# Standard Background Job Types
JOB_PROCESS_SOURCE = "process-source"
JOB_LINK_ADD = "link-add"
JOB_LINK_SAVE = "link-save"
JOB_LINK_UPDATE_DATA = "link-update-data"
JOB_LINK_RESET_DATA = "link-reset-data"
JOB_LINK_RESET_LOCAL_DATA = "link-reset-local-data"
JOB_LINK_DOWNLOAD_SOCIAL = "link-social-data"
JOB_LINK_DOWNLOAD = "link-download"
JOB_LINK_DOWNLOAD_MUSIC = "download-music"
JOB_LINK_DOWNLOAD_VIDEO = "download-video"
JOB_DOWNLOAD_FILE = "download-file"  # TODO stor file, should mention DB
JOB_LINK_SCAN = "link-scan"
JOB_SOURCE_ADD = "source-add"
JOB_MOVE_TO_ARCHIVE = "move-to-archive"
JOB_WRITE_DAILY_DATA = "write-daily-data"
JOB_WRITE_YEAR_DATA = "write-year-data"
JOB_WRITE_NOTIME_DATA = "write-notime-data"
JOB_WRITE_TOPIC_DATA = "write-topic-data"
JOB_IMPORT_DAILY_DATA = "import-daily-data"
JOB_IMPORT_BOOKMARKS = "import-bookmarks"
JOB_IMPORT_SOURCES = "import-sources"
JOB_IMPORT_INSTANCE = "import-instance"
JOB_IMPORT_FROM_FILES = "import-from-files"
JOB_EXPORT_DATA = "export-data"
JOB_CLEANUP = "cleanup"
JOB_TRUNCATE_TABLE = "truncate-table"
JOB_REMOVE = "remove"
JOB_CHECK_DOMAINS = "check-domains"
JOB_RUN_RULE = "run-rule"
JOB_INITIALIZE = "initialize"
JOB_INITIALIZE_BLOCK_LIST = (
    "initialize-block-list"  # initializes one specific block list
)
JOB_REFRESH = "refresh"


class JobService:
    """
    Domain service managing background task jobs and queue workflows.
    """

    @classmethod
    def list_jobs(
        cls,
        enabled: Optional[bool] = None,
        order_by: str = "priority",
        limit: Optional[int] = 50,
        offset: Optional[int] = 0,
        has_errors: Optional[bool] = None,
        job_type: Optional[str] = None,
        session: Optional[Session] = None,
    ) -> List[BackgroundJob]:
        """
        Retrieves a paginated list of background jobs matching the criteria.

        :param enabled: Filter by active (True) or paused (False) state
        :param order_by: Sorting field ('priority', 'date_created', 'errors', 'enabled')
        :param limit: Maximum jobs to return
        :param offset: Number of records to skip
        :param has_errors: Filter by error presence
        :param job_type: Filter by specific job identifier
        :param session: Optional active database session
        :return: List of BackgroundJob instances
        """
        sess = session or get_session()
        repo = JobRepository(sess)
        return repo.list_jobs(
            enabled=enabled,
            order_by=order_by,
            limit=limit,
            offset=offset,
            has_errors=has_errors,
            job_type=job_type,
        )

    @classmethod
    def count_jobs(
        cls,
        enabled: Optional[bool] = None,
        has_errors: Optional[bool] = None,
        job_type: Optional[str] = None,
        session: Optional[Session] = None,
    ) -> int:
        """
        Counts total background jobs matching the given filters.

        :param enabled: Filter by active (True) or paused (False) state
        :param has_errors: Filter by error presence
        :param job_type: Filter by specific job identifier
        :param session: Optional active database session
        :return: Total matching count
        """
        sess = session or get_session()
        repo = JobRepository(sess)
        return repo.count_jobs(
            enabled=enabled,
            has_errors=has_errors,
            job_type=job_type,
        )

    @classmethod
    def get_job(
        cls, job_id: int, session: Optional[Session] = None
    ) -> Optional[BackgroundJob]:
        """
        Retrieves a single background job by primary key.

        :param job_id: Primary key ID
        :param session: Optional active database session
        :return: BackgroundJob instance or None
        """
        sess = session or get_session()
        repo = JobRepository(sess)
        return repo.get_by_id(BackgroundJob, job_id)

    @classmethod
    def find_job(
        cls,
        job: str,
        subject: str,
        task: Optional[str] = None,
        args: Optional[str] = None,
        session: Optional[Session] = None,
    ) -> Optional[BackgroundJob]:
        """
        Searches for an existing background job matching the given properties.

        :param job: Job type identifier
        :param subject: Target resource string
        :param task: Optional sub-task
        :param args: Optional arguments string
        :param session: Optional active database session
        :return: Matching BackgroundJob instance or None
        """
        sess = session or get_session()
        repo = JobRepository(sess)
        return repo.find_job(job=job, subject=subject, task=task, args=args)

    @classmethod
    def create_job(
        cls,
        job: str,
        subject: str,
        task: Optional[str] = None,
        args: Optional[str] = None,
        priority: int = 1,
        enabled: bool = True,
        raise_on_duplicate: bool = False,
        session: Optional[Session] = None,
    ) -> BackgroundJob:
        """
        Enqueues a new background task, avoiding duplicate jobs.

        :param job: Job type identifier (e.g. 'link-update-data', 'process-source')
        :param subject: Target URL, source ID, or resource string
        :param task: Optional sub-task description
        :param args: Optional arguments (e.g. JSON string)
        :param priority: Integer priority (lower = higher priority)
        :param enabled: Ready status (default: True)
        :param raise_on_duplicate: If True, raises ValueError if identical job already exists
        :param session: Optional active database session
        :return: Newly created or existing BackgroundJob instance
        """
        sess = session or get_session()
        repo = JobRepository(sess)
        return repo.enqueue_job(
            job=job,
            subject=subject,
            task=task,
            args=args,
            priority=priority,
            enabled=enabled,
            raise_on_duplicate=raise_on_duplicate,
        )

    @classmethod
    def pause_job(cls, job_id: int, session: Optional[Session] = None) -> bool:
        """
        Pauses an active job by setting enabled = False.

        :param job_id: Job ID
        :param session: Optional active database session
        :return: True if updated, False if not found
        """
        sess = session or get_session()
        repo = JobRepository(sess)
        return repo.set_job_status(job_id, enabled=False)

    @classmethod
    def resume_job(cls, job_id: int, session: Optional[Session] = None) -> bool:
        """
        Resumes a paused job by setting enabled = True.

        :param job_id: Job ID
        :param session: Optional active database session
        :return: True if updated, False if not found
        """
        sess = session or get_session()
        repo = JobRepository(sess)
        return repo.set_job_status(job_id, enabled=True)

    @classmethod
    def delete_job(cls, job_id: int, session: Optional[Session] = None) -> bool:
        """
        Deletes a background task by ID.

        :param job_id: Job ID
        :param session: Optional active database session
        :return: True if deleted, False if not found
        """
        sess = session or get_session()
        repo = JobRepository(sess)
        return repo.delete_job(job_id)

    @classmethod
    def batch_action(
        cls,
        job_ids: List[int],
        action: str,
        session: Optional[Session] = None,
    ) -> int:
        """
        Executes a batch mutation across multiple background jobs.

        :param job_ids: List of job IDs
        :param action: Action name: 'pause', 'resume', or 'delete'
        :param session: Optional active database session
        :return: Number of affected jobs
        """
        if not job_ids:
            return 0

        sess = session or get_session()
        repo = JobRepository(sess)

        if action == "pause":
            return repo.batch_set_status(job_ids, enabled=False)
        elif action == "resume":
            return repo.batch_set_status(job_ids, enabled=True)
        elif action == "delete":
            return repo.delete_jobs(job_ids)
        else:
            raise ValueError(f"Unsupported batch action: {action}")

    @classmethod
    def get_job_types(cls, session: Optional[Session] = None) -> List[str]:
        """
        Retrieves all distinct job type names currently in the database.

        :param session: Optional active database session
        :return: List of job type strings
        """
        sess = session or get_session()
        repo = JobRepository(sess)
        return repo.get_distinct_job_types()

    @classmethod
    def count_error_jobs(cls, session: Optional[Session] = None) -> int:
        """
        Retrieves total number of jobs with errors > 0.

        :param session: Optional active database session
        :return: Error job count
        """
        sess = session or get_session()
        repo = JobRepository(sess)
        return repo.count_error_jobs()

    @classmethod
    def clear_all_jobs(cls, session: Optional[Session] = None) -> int:
        """
        Deletes all jobs from the queue.

        :param session: Optional active database session
        :return: Number of deleted jobs
        """
        sess = session or get_session()
        repo = JobRepository(sess)
        return repo.clear_all_jobs()

    @classmethod
    def get_jobs_for_subjects(
        cls,
        subjects: List[str],
        include_history: bool = True,
        limit_history: int = 20,
        session: Optional[Session] = None,
    ) -> Dict[str, Any]:
        """
        Retrieves active jobs and historical records matching any of the given subjects.

        :param subjects: Target subject identifiers (e.g. entry ID or link)
        :param include_history: Whether to query historical jobs
        :param limit_history: Maximum history records to return
        :param session: Optional active database session
        :return: Dict containing 'jobs' and 'history' lists
        """
        sess = session or get_session()
        repo = JobRepository(sess)
        active_jobs = repo.get_jobs_for_subjects(subjects)
        history_jobs = (
            repo.get_history_for_subjects(subjects, limit=limit_history)
            if include_history
            else []
        )
        return {
            "jobs": active_jobs,
            "history": history_jobs,
        }

    @classmethod
    def clear_error_jobs(cls, session: Optional[Session] = None) -> int:
        """
        Deletes all jobs with errors > 0 from the queue.

        :param session: Optional active database session
        :return: Number of deleted jobs
        """
        sess = session or get_session()
        repo = JobRepository(sess)
        return repo.clear_error_jobs()

    @classmethod
    def clear_history(cls, session: Optional[Session] = None) -> int:
        """
        Clears all records in the backgroundjobhistory table.

        :param session: Optional active database session
        :return: Number of deleted rows
        """
        sess = session or get_session()
        repo = JobRepository(sess)
        return repo.clear_history()

    @classmethod
    def list_history(
        cls,
        job_type: Optional[str] = None,
        order_by: str = "date_created",
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        session: Optional[Session] = None,
    ) -> List[Any]:
        """
        Lists historical background jobs.

        :param job_type: Optional filter by job type
        :param order_by: Sorting column
        :param limit: Maximum rows to return
        :param offset: Number of rows to skip
        :param session: Optional active database session
        :return: List of BackgroundJobHistory instances
        """
        sess = session or get_session()
        repo = JobRepository(sess)
        return repo.list_history(
            job_type=job_type,
            order_by=order_by,
            limit=limit,
            offset=offset,
        )

    @classmethod
    def count_history(
        cls,
        job_type: Optional[str] = None,
        session: Optional[Session] = None,
    ) -> int:
        """
        Counts historical background jobs matching specified filters.

        :param job_type: Optional filter by job type
        :param session: Optional active database session
        :return: Total number of matching history records
        """
        sess = session or get_session()
        repo = JobRepository(sess)
        return repo.count_history(job_type=job_type)

    @classmethod
    def get_history_job_types(
        cls,
        session: Optional[Session] = None,
    ) -> List[str]:
        """
        Returns list of distinct job types present in the history table.

        :param session: Optional active database session
        :return: List of distinct job names
        """
        sess = session or get_session()
        repo = JobRepository(sess)
        return repo.get_distinct_history_job_types()
