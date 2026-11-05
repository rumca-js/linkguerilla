"""
Job Executor and Task Dispatcher for YAFR.

Processes background tasks sequentially, one at a time, pulling enabled jobs from
the backgroundjob SQLite table in priority/FIFO order, updating retry counts,
archiving completed tasks to backgroundjobhistory, and falling back to source
refreshing when the queue is empty.
"""

from datetime import datetime, timezone, timedelta
import json
import logging
import threading
import time
from typing import Any, Callable, Dict, Optional
from sqlalchemy import or_, select
from sqlalchemy.orm import Session
from linkarchivetools.model.definitions import BackgroundJob, LinkDataModel
from yafr.db.config_repository import ConfigRepository
from yafr.db.job_repository import JobRepository
from yafr.db.logging_repository import LoggingRepository
from yafr.db.session import close_session, get_session
from yafr.db.source_repository import SourceRepository
from yafr.db.system_operation_repository import SystemOperationRepository
from yafr.services.source_service import SourceService
from yafr.workers.jobs import (
    JOB_CLEANUP,
    JOB_LINK_UPDATE_DATA,
    JOB_PROCESS_SOURCE,
    BaseJobHandler,
    CleanupJobHandler,
    GenericJobHandler,
    JobRegistry,
    LinkUpdateDataJobHandler,
    ProcessSourceJobHandler,
    default_registry,
)

logger = logging.getLogger(__name__)


class JobExecutor:
    """
    Dispatcher and sequential execution runner for background tasks.
    Delegates task execution to modular handlers in yafr.workers.jobs.
    """

    def __init__(
        self,
        session: Optional[Session] = None,
        max_retries: int = 3,
        auto_refresh_sources: bool = True,
        registry: Optional[JobRegistry] = None,
    ) -> None:
        """
        Initializes the JobExecutor.

        :param session: Optional active database session
        :param max_retries: Maximum failures allowed before a job is disabled
        :param auto_refresh_sources: Whether to check and refresh outdated sources when queue is empty
        :param registry: Optional JobRegistry instance for custom handler registration
        """
        self._session = session
        self.max_retries = max_retries
        self.auto_refresh_sources = auto_refresh_sources
        self.registry = registry or default_registry

    def _get_session(self, session: Optional[Session] = None) -> Session:
        return session or self._session or get_session()

    def process_one(
        self, session: Optional[Session] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Fetches and processes exactly one pending background job.

        If no pending jobs are in the queue and auto_refresh_sources is enabled,
        enqueues jobs for outdated sources and entries, then processes the next pending job.

        :param session: Optional active database session
        :return: Dict describing task execution results, or None if no work was available
        """
        sess = self._get_session(session)
        job_repo = JobRepository(sess)
        log_repo = LoggingRepository(sess)

        # 1. Fetch next highest-priority enabled job
        job = job_repo.get_next_pending_job()

        if job is None:
            # Check what should be done next when job queue is empty:
            # Enqueue jobs for all outdated sources and entries, then pick the next pending job.
            if self.auto_refresh_sources:
                self.enqueue_outdated_jobs(sess)
                job = job_repo.get_next_pending_job()

        if job is None:
            return None

        job_id = job.id
        job_type = job.job or "unknown"
        job_subject = job.subject or ""
        logger.info(
            "Processing job #%d [%s] subject='%s' (priority=%d, errors=%d)",
            job_id,
            job_type,
            job_subject,
            job.priority,
            job.errors or 0,
        )

        try:
            # 2. Dispatch to matching handler via modular job registry
            result = self.registry.dispatch(job, sess)

            success = result.get("success", False)

            if success:
                # 3. On success: archive to history and remove from queue
                job_repo.complete_job(job_id)
                is_error = result.get("status") == "error" or bool(result.get("error"))
                try:
                    if is_error:
                        log_repo.log(
                            info_text=f"Job #{job_id} [{job_type}] completed with error: {result.get('error') or result.get('message')}",
                            detail_text=f"Subject: {job_subject} | Result: {result.get('message', 'Error')}",
                            level=40,  # ERROR
                        )
                    else:
                        log_repo.log(
                            info_text=f"Job #{job_id} [{job_type}] completed successfully.",
                            detail_text=f"Subject: {job_subject} | Result: {result.get('message', 'OK')}",
                            level=20,  # INFO
                        )
                except Exception:
                    pass
                if is_error:
                    logger.warning(
                        "Job #%d [%s] completed with error and archived to history: %s",
                        job_id,
                        job_type,
                        result.get("error"),
                    )
                else:
                    logger.info(
                        "Job #%d [%s] completed and archived to history.",
                        job_id,
                        job_type,
                    )
            else:
                # 4. On task failure: record error and increment retry count
                err_msg = result.get("error", "Unknown job error")
                updated_job = job_repo.record_job_error(
                    job_id, max_retries=self.max_retries
                )
                try:
                    log_repo.log(
                        info_text=f"Job #{job_id} [{job_type}] failed: {err_msg}",
                        detail_text=f"Subject: {job_subject} | Retries: {updated_job.errors if updated_job else '?'}",
                        level=40,  # ERROR
                    )
                except Exception:
                    pass
                logger.warning("Job #%d recorded failure: %s", job_id, err_msg)

            return {
                "processed": True,
                "job_id": job_id,
                "job_type": job_type,
                "subject": job_subject,
                "success": success,
                "status": result.get("status", "completed" if success else "failed"),
                "message": result.get("message") or result.get("error", ""),
            }

        except Exception as exc:
            # 5. On unhandled exception: record error
            logger.exception(
                "Exception executing job #%d [%s]: %s", job_id, job_type, exc
            )
            job_repo.record_job_error(job_id, max_retries=self.max_retries)
            try:
                log_repo.log(
                    info_text=f"Job #{job_id} [{job_type}] crashed with exception: {exc}",
                    detail_text=str(exc),
                    level=50,  # CRITICAL
                )
            except Exception:
                pass

            return {
                "processed": True,
                "job_id": job_id,
                "job_type": job_type,
                "subject": job_subject,
                "success": False,
                "status": "crashed",
                "message": str(exc),
            }

    def _handle_process_source(
        self, job: BackgroundJob, session: Session
    ) -> Dict[str, Any]:
        """
        Executes a process-source task (delegating to ProcessSourceJobHandler).
        """
        return self.registry.get_handler("process-source").execute(job, session)

    def _handle_link_update_data(
        self, job: BackgroundJob, session: Session
    ) -> Dict[str, Any]:
        """
        Executes a link-update-data task (delegating to LinkUpdateDataJobHandler).
        """
        return self.registry.get_handler("link-update-data").execute(job, session)

    def _handle_cleanup(self, job: BackgroundJob, session: Session) -> Dict[str, Any]:
        """
        Executes a cleanup task (delegating to CleanupJobHandler).
        """
        return self.registry.get_handler("cleanup").execute(job, session)

    def _handle_unknown_job(
        self, job: BackgroundJob, session: Session
    ) -> Dict[str, Any]:
        """
        Fallback handler for unhandled or custom job types (delegating to GenericJobHandler).
        """
        return GenericJobHandler().execute(job, session)

    def _process_outdated_source(self, session: Session) -> Optional[Dict[str, Any]]:
        """
        Checks if any enabled source is outdated (> 1h since last fetch) and refreshes it.
        """
        source_repo = SourceRepository(session)
        outdated_sources = source_repo.get_outdated_sources(max_age_seconds=3600)

        if not outdated_sources:
            return None

        source = outdated_sources[0]
        logger.info(
            "Job queue empty. Auto-refreshing oldest outdated source #%d (%s)...",
            source.id,
            source.title or source.url,
        )

        res = SourceService.fetch_source(source.id, session=session)
        return {
            "processed": True,
            "job_id": None,
            "job_type": "source-auto-refresh",
            "subject": source.url,
            "success": res.get("success", False),
            "status": res.get("status", "completed"),
            "message": res.get("message") or res.get("error", "Source refreshed."),
        }

    def _process_outdated_entry(self, session: Session) -> Optional[Dict[str, Any]]:
        """
        Checks for the oldest entry by date_update_last and refreshes its metadata,
        updating date_update_last to 'now'.
        """
        config_repo = ConfigRepository(session)
        config = config_repo.get_config()
        limit = config.number_of_update_entries
        if limit is not None and limit <= 0:
            return None

        one_day_ago = datetime.now(timezone.utc) - timedelta(days=1)

        stmt = (
            select(LinkDataModel)
            .where(LinkDataModel.link.isnot(None))
            .where(LinkDataModel.link != "")
            .where(
                # TODO this needs to be obtained from configuration
                or_(
                    LinkDataModel.date_update_last < one_day_ago,
                    LinkDataModel.date_update_last.is_(None),
                )
            )
            .order_by(
                LinkDataModel.date_update_last.asc().nullsfirst(),
                LinkDataModel.id.asc(),
            )
            .limit(1)
        )
        entry = session.execute(stmt).scalars().first()
        if not entry:
            return None

        logger.info(
            "Job queue empty. Auto-updating oldest entry #%d (%s)...",
            entry.id,
            entry.link,
        )

        handler = self.registry.get_handler("link-update-data")
        dummy_job = BackgroundJob(
            id=0,
            job="link-update-data",
            subject=str(entry.id),
            priority=10,
            enabled=True,
        )
        res = handler.execute(dummy_job, session)
        return {
            "processed": True,
            "job_id": None,
            "job_type": "entry-auto-update",
            "subject": str(entry.id),
            "success": res.get("success", False),
            "status": res.get("status", "completed"),
            "message": res.get("message") or res.get("error", "Entry updated."),
        }

    def enqueue_outdated_source_jobs(
        self, session: Optional[Session] = None, max_age_seconds: int = 3600
    ) -> int:
        """
        Enqueues the next outdated source refresh job into the backgroundjob queue (1-by-1).

        :param session: Optional active database session
        :param max_age_seconds: Maximum age before a source is considered outdated (default: 3600s = 1 hour)
        :return: Count of newly enqueued source refresh jobs (1 or 0)
        """
        sess = self._get_session(session)
        source_repo = SourceRepository(sess)

        # In 1-by-1 mode, if there is already an active/pending process-source job in queue, wait
        existing = (
            sess.execute(
                select(BackgroundJob.subject).where(
                    BackgroundJob.job.in_(("process-source", "JOB_PROCESS_SOURCE")),
                )
            )
            .scalars()
            .first()
        )
        if existing:
            return 0

        outdated = source_repo.get_outdated_sources(
            max_age_seconds=max_age_seconds, limit=1
        )
        if not outdated:
            return 0

        src = outdated[0]
        bg_job = BackgroundJob(
            job="process-source",
            subject=str(src.id),
            priority=5,
            enabled=True,
            errors=0,
            date_created=datetime.now(timezone.utc),
        )
        sess.add(bg_job)
        sess.commit()
        logger.info(
            "Enqueued outdated source job for source #%d (%s) into queue.",
            src.id,
            src.title or src.url,
        )
        return 1

    def enqueue_outdated_entry_jobs(self, session: Optional[Session] = None) -> int:
        """
        Enqueues link-update-data jobs for the oldest entries based on date_update_last,
        limited by ConfigurationEntry.number_of_update_entries.

        :param session: Optional active database session
        :return: Count of newly enqueued entry update jobs
        """
        sess = self._get_session(session)
        config_repo = ConfigRepository(sess)
        job_repo = JobRepository(sess)
        config = config_repo.get_config()

        max_entries = config.number_of_update_entries
        if max_entries is None:
            max_entries = 10
        if max_entries <= 0:
            return 0

        # Find existing active link-update-data jobs to avoid duplicates and respect queue capacity
        existing_subjects = set(
            sess.execute(
                select(BackgroundJob.subject).where(
                    BackgroundJob.job.in_(("link-update-data", "JOB_LINK_UPDATE_DATA")),
                    BackgroundJob.enabled == True,
                )
            )
            .scalars()
            .all()
        )

        remaining_slots = max_entries - len(existing_subjects)
        if remaining_slots <= 0:
            return 0

        candidates = (
            sess.execute(
                select(LinkDataModel)
                .where(LinkDataModel.link.isnot(None))
                .where(LinkDataModel.link != "")
                .order_by(
                    LinkDataModel.date_update_last.asc().nullsfirst(),
                    LinkDataModel.id.asc(),
                )
                .limit(remaining_slots * 2)
            )
            .scalars()
            .all()
        )

        enqueued_count = 0
        for entry in candidates:
            if str(entry.id) not in existing_subjects:
                job_repo.enqueue_job(
                    job="link-update-data",
                    subject=str(entry.id),
                    priority=10,
                    enabled=True,
                )
                existing_subjects.add(str(entry.id))
                enqueued_count += 1
                if enqueued_count >= remaining_slots:
                    break

        if enqueued_count > 0:
            sess.commit()
            logger.info(
                "Enqueued %d entry update job(s) based on date_update_last (cap: %d).",
                enqueued_count,
                max_entries,
            )

        return enqueued_count

    def enqueue_outdated_jobs(
        self, session: Optional[Session] = None, max_age_seconds: int = 3600
    ) -> int:
        """
        When idle, checks what should be done next:
        - Checks how many sources to fetch (outdated sources) and enqueues them.
        - Checks how many entries to update (ConfigurationEntry.number_of_update_entries)
          based on date_update_last and enqueues link-update-data jobs.

        :param session: Optional active database session
        :param max_age_seconds: Maximum age before a source is considered outdated (default: 3600s = 1 hour)
        :return: Total count of newly enqueued jobs
        """
        sources_enqueued = self.enqueue_outdated_source_jobs(
            session=session, max_age_seconds=max_age_seconds
        )
        entries_enqueued = self.enqueue_outdated_entry_jobs(session=session)
        return sources_enqueued + entries_enqueued

    def run_loop(
        self,
        interval: float = 5.0,
        max_jobs: Optional[int] = None,
        stop_event: Optional[threading.Event] = None,
        callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> int:
        """
        Continuously processes jobs one at a time.

        Records a liveness heartbeat into the systemoperation table on every
        iteration so the web UI can detect whether the worker is running or dead
        (a timestamp older than 10 minutes indicates the worker is dead).

        :param interval: Sleep interval in seconds when idle
        :param max_jobs: Optional maximum jobs to execute before stopping
        :param stop_event: Threading event to signal graceful termination
        :param callback: Optional callable invoked with task result after each job
        :return: Total number of jobs executed
        """
        import threading as _threading

        executed_count = 0
        thread_id = str(_threading.current_thread().ident)

        # Enqueue outdated jobs at worker startup if auto_refresh_sources is enabled
        if self.auto_refresh_sources:
            try:
                self.enqueue_outdated_jobs(self._get_session())
            except Exception as err:
                logger.debug("Failed checking outdated jobs before run_loop: %s", err)

        while True:
            if stop_event and stop_event.is_set():
                break

            # Record worker heartbeat so the UI can detect liveness
            try:
                op_repo = SystemOperationRepository(self._get_session())
                op_repo.record_heartbeat(
                    status=True,
                    thread_id=thread_id,
                    check_type="worker",
                )
            except Exception as hb_err:
                logger.debug("Failed to record worker heartbeat: %s", hb_err)

            config_repo = ConfigRepository(self._get_session())
            config = config_repo.get_config()
            if not config.enable_background_jobs:
                time.sleep(interval)
                continue

            result = self.process_one()

            if result and result.get("processed"):
                executed_count += 1
                if callback:
                    callback(result)

                if max_jobs is not None and executed_count >= max_jobs:
                    break
            else:
                # If auto_refresh_sources is enabled and queue is empty, enqueue outdated jobs
                if self.auto_refresh_sources:
                    try:
                        self.enqueue_outdated_jobs(self._get_session())
                    except Exception as err:
                        logger.debug(
                            "Failed checking outdated jobs in run_loop: %s", err
                        )

                # No pending job or work: wait before next poll
                if stop_event:
                    stop_event.wait(interval)
                else:
                    time.sleep(interval)

        return executed_count
