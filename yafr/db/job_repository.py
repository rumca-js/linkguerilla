"""
Job Repository Implementation for YAFR.

Manages persistent task queue operations in the backgroundjob and
backgroundjobhistory SQLite tables without external message brokers.
"""

from datetime import datetime, timezone
import logging
from typing import Any, List, Optional
from sqlalchemy import delete, distinct, func, select
from sqlalchemy.orm import Session
from linkarchivetools.model.definitions import BackgroundJob, BackgroundJobHistory
from yafr.db.base_repository import BaseRepository

logger = logging.getLogger(__name__)


class JobRepository(BaseRepository[BackgroundJob]):
    """
    Data access repository for SQLite-backed background task jobs.
    """

    def __init__(self, session: Optional[Session] = None) -> None:
        super().__init__(session=session)

    def find_job(
        self,
        job: str,
        subject: str,
        task: Optional[str] = None,
        args: Optional[str] = None,
    ) -> Optional[BackgroundJob]:
        """
        Finds an existing background job in the queue matching the given properties.

        :param job: Job type identifier
        :param subject: Target resource string
        :param task: Optional sub-task
        :param args: Optional arguments string
        :return: Matching BackgroundJob instance or None
        """
        norm_task = task.strip() if isinstance(task, str) and task.strip() else ""
        norm_args = args.strip() if isinstance(args, str) and args.strip() else ""

        stmt = select(BackgroundJob).where(
            BackgroundJob.job == job,
            BackgroundJob.subject == subject,
        )

        if norm_task:
            stmt = stmt.where(BackgroundJob.task == norm_task)
        else:
            stmt = stmt.where((BackgroundJob.task == None) | (BackgroundJob.task == ""))

        if norm_args:
            stmt = stmt.where(BackgroundJob.args == norm_args)
        else:
            stmt = stmt.where((BackgroundJob.args == None) | (BackgroundJob.args == ""))

        return self.session.execute(stmt.limit(1)).scalar_one_or_none()

    def enqueue_job(
        self,
        job: str,
        subject: str,
        task: Optional[str] = None,
        args: Optional[str] = None,
        priority: int = 0,
        enabled: bool = True,
        raise_on_duplicate: bool = False,
    ) -> BackgroundJob:
        """
        Enqueues a new background task in the backgroundjob table.
        Prevents adding duplicate jobs with identical properties (job, subject, task, args).

        :param job: Job type identifier (e.g., 'JOB_PROCESS_SOURCE')
        :param subject: Target resource (e.g. source URL or entry ID)
        :param task: Optional sub-task description
        :param args: Optional JSON-encoded task arguments
        :param priority: Integer priority (lower number = higher priority)
        :param enabled: Whether the job is ready for execution
        :param raise_on_duplicate: If True, raises ValueError if an identical job already exists
        :return: Created or existing BackgroundJob instance
        """
        norm_task = task.strip() if isinstance(task, str) and task.strip() else ""
        norm_args = args.strip() if isinstance(args, str) and args.strip() else ""

        existing = self.find_job(
            job=job,
            subject=subject,
            task=norm_task,
            args=norm_args,
        )
        if existing:
            if raise_on_duplicate:
                raise ValueError(
                    f"A job with the same properties already exists in the queue (Job #{existing.id})."
                )
            logger.info(
                "Job '%s' for subject '%s' (task=%s, args=%s) already exists as #%d; skipping duplicate insert.",
                job,
                subject,
                norm_task,
                norm_args,
                existing.id,
            )
            return existing

        bg_job = BackgroundJob(
            job=job,
            subject=subject,
            task=norm_task,
            args=norm_args,
            priority=priority,
            enabled=enabled,
            errors=0,
            date_created=datetime.now(timezone.utc),
            user_id=1,
        )
        self.session.add(bg_job)
        self.session.commit()
        return bg_job

    def get_next_pending_job(self) -> Optional[BackgroundJob]:
        """
        Pulls the next highest-priority enabled job ready for execution.

        Jobs are prioritized by priority ASC, followed by oldest date_created ASC.

        :return: Next pending BackgroundJob or None
        """
        stmt = (
            select(BackgroundJob)
            .where(BackgroundJob.enabled == True)
            .order_by(BackgroundJob.priority.asc(), BackgroundJob.date_created.asc())
            .limit(1)
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def set_job_status(self, job_id: int, enabled: bool) -> bool:
        """
        Pauses or resumes a background job.

        :param job_id: Job ID
        :param enabled: New enabled state
        :return: True if updated, False if not found
        """
        job = self.get_by_id(BackgroundJob, job_id)
        if not job:
            return False
        job.enabled = enabled
        self.session.commit()
        return True

    def record_job_error(
        self, job_id: int, max_retries: int = 3
    ) -> Optional[BackgroundJob]:
        """
        Increments the failure counter for a job. If consecutive errors
        reach max_retries, disables the job to avoid blocking the queue.

        :param job_id: Job ID
        :param max_retries: Max allowed failures before disabling (default: 3)
        :return: Updated BackgroundJob or None
        """
        job = self.get_by_id(BackgroundJob, job_id)
        if not job:
            return None

        job.errors = (job.errors or 0) + 1
        if job.errors >= max_retries:
            job.enabled = False
            logger.warning(
                "Job id=%d (%s) disabled after reaching %d failures",
                job.id,
                job.job,
                job.errors,
            )

        self.session.commit()
        return job

    def complete_job(self, job_id: int) -> bool:
        """
        Archives a completed task into backgroundjobhistory and deletes it from backgroundjob.

        :param job_id: Job ID
        :return: True if completed and archived, False if not found
        """
        job = self.get_by_id(BackgroundJob, job_id)
        if not job:
            return False

        # Archive to history
        history_entry = BackgroundJobHistory(
            job=job.job,
            subject=job.subject,
            task=job.task,
            args=job.args,
            date_created=job.date_created,
        )
        self.session.add(history_entry)

        # Delete active task
        self.session.delete(job)
        self.session.commit()
        return True

    def list_jobs(
        self,
        enabled: Optional[bool] = None,
        order_by: str = "priority",
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        has_errors: Optional[bool] = None,
        job_type: Optional[str] = None,
    ) -> List[BackgroundJob]:
        """
        Lists background jobs with optional status filter, type filter, and sorting.

        :param enabled: Optional filter by enabled state
        :param order_by: Sorting column ('priority', 'date_created', 'errors', 'enabled')
        :param limit: Maximum rows to return
        :param offset: Number of rows to skip
        :param has_errors: Optional filter for jobs with errors (True: errors > 0, False: errors == 0)
        :param job_type: Optional filter by specific job type identifier
        :return: List of BackgroundJob instances
        """
        stmt = select(BackgroundJob)
        if enabled is not None:
            stmt = stmt.where(BackgroundJob.enabled == enabled)
        if has_errors is True:
            stmt = stmt.where(BackgroundJob.errors > 0)
        elif has_errors is False:
            stmt = stmt.where(
                (BackgroundJob.errors == 0) | (BackgroundJob.errors.is_(None))
            )
        if job_type:
            stmt = stmt.where(BackgroundJob.job == job_type)

        if order_by == "date_created":
            stmt = stmt.order_by(BackgroundJob.date_created.desc())
        elif order_by == "errors":
            stmt = stmt.order_by(
                BackgroundJob.errors.desc(), BackgroundJob.priority.asc()
            )
        elif order_by == "enabled":
            stmt = stmt.order_by(
                BackgroundJob.enabled.desc(), BackgroundJob.priority.asc()
            )
        else:
            stmt = stmt.order_by(
                BackgroundJob.priority.asc(), BackgroundJob.date_created.asc()
            )

        if offset is not None:
            stmt = stmt.offset(offset)
        if limit is not None:
            stmt = stmt.limit(limit)

        return list(self.session.execute(stmt).scalars().all())

    def count_jobs(
        self,
        enabled: Optional[bool] = None,
        has_errors: Optional[bool] = None,
        job_type: Optional[str] = None,
    ) -> int:
        """
        Counts background jobs matching specified filters.

        :param enabled: Optional filter by enabled state
        :param has_errors: Optional filter for jobs with errors
        :param job_type: Optional filter by specific job type identifier
        :return: Total number of matching jobs
        """
        stmt = select(func.count(BackgroundJob.id))
        if enabled is not None:
            stmt = stmt.where(BackgroundJob.enabled == enabled)
        if has_errors is True:
            stmt = stmt.where(BackgroundJob.errors > 0)
        elif has_errors is False:
            stmt = stmt.where(
                (BackgroundJob.errors == 0) | (BackgroundJob.errors.is_(None))
            )
        if job_type:
            stmt = stmt.where(BackgroundJob.job == job_type)

        return self.session.execute(stmt).scalar() or 0

    def get_jobs_for_subjects(self, subjects: List[str]) -> List[BackgroundJob]:
        """
        Retrieves active background jobs matching any of the given subjects.

        :param subjects: List of subject strings (e.g. entry ID or URL)
        :return: List of BackgroundJob instances
        """
        if not subjects:
            return []
        stmt = (
            select(BackgroundJob)
            .where(BackgroundJob.subject.in_(subjects))
            .order_by(BackgroundJob.priority.asc(), BackgroundJob.date_created.desc())
        )
        return list(self.session.execute(stmt).scalars().all())

    def get_history_for_subjects(
        self, subjects: List[str], limit: int = 20
    ) -> List[BackgroundJobHistory]:
        """
        Retrieves historical background jobs matching any of the given subjects.

        :param subjects: List of subject strings (e.g. entry ID or URL)
        :param limit: Maximum history records to return
        :return: List of BackgroundJobHistory instances
        """
        if not subjects:
            return []
        stmt = (
            select(BackgroundJobHistory)
            .where(BackgroundJobHistory.subject.in_(subjects))
            .order_by(BackgroundJobHistory.date_created.desc())
            .limit(limit)
        )
        return list(self.session.execute(stmt).scalars().all())

    def get_distinct_job_types(self) -> List[str]:
        """
        Returns list of distinct job types currently present in the queue.

        :return: List of distinct job names
        """
        stmt = select(distinct(BackgroundJob.job)).order_by(BackgroundJob.job)
        return [str(j) for j in self.session.execute(stmt).scalars().all() if j]

    def delete_job(self, job_id: int) -> bool:
        """
        Deletes a job from the queue.

        :param job_id: Job ID
        :return: True if deleted, False if not found
        """
        job = self.get_by_id(BackgroundJob, job_id)
        if not job:
            return False
        self.session.delete(job)
        self.session.commit()
        return True

    def delete_jobs(self, job_ids: List[int]) -> int:
        """
        Deletes multiple jobs by ID list.

        :param job_ids: List of job IDs
        :return: Number of deleted jobs
        """
        if not job_ids:
            return 0
        stmt = delete(BackgroundJob).where(BackgroundJob.id.in_(job_ids))
        result = self.session.execute(stmt)
        self.session.commit()
        return result.rowcount or 0

    def batch_set_status(self, job_ids: List[int], enabled: bool) -> int:
        """
        Pauses or resumes multiple jobs by ID list.

        :param job_ids: List of job IDs
        :param enabled: New enabled state
        :return: Number of updated jobs
        """
        if not job_ids:
            return 0
        stmt = select(BackgroundJob).where(BackgroundJob.id.in_(job_ids))
        jobs = list(self.session.execute(stmt).scalars().all())
        for job in jobs:
            job.enabled = enabled
        self.session.commit()
        return len(jobs)

    def count_error_jobs(self) -> int:
        """
        Counts jobs that have logged errors.

        :return: Total number of jobs with errors > 0
        """
        stmt = select(func.count(BackgroundJob.id)).where(BackgroundJob.errors > 0)
        return self.session.execute(stmt).scalar() or 0

    def clear_all_jobs(self) -> int:
        """
        Clears all records in the backgroundjob table.

        :return: Number of deleted rows
        """
        stmt = delete(BackgroundJob)
        result = self.session.execute(stmt)
        self.session.commit()
        return result.rowcount or 0

    def clear_error_jobs(self) -> int:
        """
        Clears all records in the backgroundjob table that have errors > 0.

        :return: Number of deleted rows
        """
        stmt = delete(BackgroundJob).where(BackgroundJob.errors > 0)
        result = self.session.execute(stmt)
        self.session.commit()
        return result.rowcount or 0

    def clear_history(self) -> int:
        """
        Clears all records in the backgroundjobhistory table.

        :return: Number of deleted rows
        """
        stmt = delete(BackgroundJobHistory)
        result = self.session.execute(stmt)
        self.session.commit()
        return result.rowcount or 0
