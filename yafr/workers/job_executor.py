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
import gc
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
        fix_schema_on_startup: bool = True,
    ) -> None:
        """
        Initializes the JobExecutor.

        :param session: Optional active database session
        :param max_retries: Maximum failures allowed before a job is disabled
        :param auto_refresh_sources: Whether to check and refresh outdated sources when queue is empty
        :param registry: Optional JobRegistry instance for custom handler registration
        :param fix_schema_on_startup: Whether to check and repair database schema at worker startup
        """
        self._session = session
        self.max_retries = max_retries
        self.auto_refresh_sources = auto_refresh_sources
        self.registry = registry or default_registry
        self.fix_schema_on_startup = fix_schema_on_startup

    def fix_database_schema(
        self, reapply_defaults: bool = True
    ) -> Dict[str, Any]:
        """
        Executes DatabaseService.fix_all_tables to reconcile SQLite schema
        and fix eventual missing columns, obsolete columns, and default constraints.
        """
        from yafr.services.database_service import DatabaseService

        sess = self._get_session()
        engine = None
        if sess is not None:
            try:
                engine = sess.get_bind()
            except Exception:
                engine = None

        return DatabaseService.fix_all_tables(
            reapply_defaults=reapply_defaults, engine=engine
        )

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
            should_consume = result.get("consume")
            if should_consume is None:
                should_consume = True
            else:
                should_consume = bool(should_consume)

            if success:
                # 3. On success: archive to history and remove from queue
                if should_consume:
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
                # 4. On task failure: record error and increment retry count (consume if max retries reached and should_consume is True)
                err_msg = result.get("error", "Unknown job error")
                updated_job = job_repo.record_job_error(
                    job_id,
                    max_retries=self.max_retries,
                    consume_on_max_retries=should_consume,
                )
                try:
                    if updated_job is None:
                        log_repo.log(
                            info_text=f"Job #{job_id} [{job_type}] failed after {self.max_retries} attempts and was consumed: {err_msg}",
                            detail_text=f"Subject: {job_subject} | Consumed after {self.max_retries} retries",
                            level=40,  # ERROR
                        )
                    elif not updated_job.enabled:
                        log_repo.log(
                            info_text=f"Job #{job_id} [{job_type}] failed after {self.max_retries} attempts and was disabled: {err_msg}",
                            detail_text=f"Subject: {job_subject} | Retries: {updated_job.errors}",
                            level=40,  # ERROR
                        )
                    else:
                        log_repo.log(
                            info_text=f"Job #{job_id} [{job_type}] failed: {err_msg}",
                            detail_text=f"Subject: {job_subject} | Retries: {updated_job.errors}/{self.max_retries}",
                            level=40,  # ERROR
                        )
                except Exception:
                    pass
                if updated_job is None:
                    logger.warning(
                        "Job #%d [%s] failed and was consumed after reaching %d failures: %s",
                        job_id,
                        job_type,
                        self.max_retries,
                        err_msg,
                    )
                else:
                    logger.warning(
                        "Job #%d [%s] recorded failure (%d/%d): %s",
                        job_id,
                        job_type,
                        updated_job.errors or 0,
                        self.max_retries,
                        err_msg,
                    )

            return {
                "processed": True,
                "job_id": job_id,
                "job_type": job_type,
                "subject": job_subject,
                "success": success,
                "consume": should_consume,
                "status": result.get("status", "completed" if success else "failed"),
                "message": result.get("message") or result.get("error", ""),
            }

        except Exception as exc:
            # 5. On unhandled exception: record error
            logger.exception(
                "Exception executing job #%d [%s]: %s", job_id, job_type, exc
            )
            from yafr.services.webtools_service import WebToolsWrapper

            is_wt_active = WebToolsWrapper.is_status_active(sess)
            job_repo.record_job_error(
                job_id,
                max_retries=self.max_retries,
                consume_on_max_retries=is_wt_active,
            )
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
                "consume": is_wt_active,
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

    def _process_outdated_entry(
        self, session: Session, days_to_check: Optional[int] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Checks for the oldest entry by date_update_last exceeding days_to_check_std_entries
        and refreshes its metadata, updating date_update_last to 'now'.
        """
        config_repo = ConfigRepository(session)
        config = config_repo.get_config()
        limit = config.number_of_update_entries
        if limit is not None and limit <= 0:
            return None

        days = (
            days_to_check
            if days_to_check is not None
            else config.days_to_check_std_entries
        )
        if days is None or days <= 0:
            days = 1
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        stmt = (
            select(LinkDataModel)
            .where(LinkDataModel.link.isnot(None))
            .where(LinkDataModel.link != "")
            .where(
                or_(
                    LinkDataModel.date_update_last < cutoff,
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
                    BackgroundJob.enabled == True,
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
            task="",
            args="",
            priority=5,
            enabled=True,
            errors=0,
            date_created=datetime.now(timezone.utc),
            user_id=1,
        )
        sess.add(bg_job)
        sess.commit()
        logger.info(
            "Enqueued outdated source job for source #%d (%s) into queue.",
            src.id,
            src.title or src.url,
        )
        return 1

    def enqueue_outdated_entry_jobs(
        self, session: Optional[Session] = None, days_to_check: Optional[int] = None
    ) -> int:
        """
        Enqueues link-update-data jobs for the oldest entries based on date_update_last
        exceeding days_to_check_std_entries, limited by ConfigurationEntry.number_of_update_entries.

        :param session: Optional active database session
        :param days_to_check: Optional override for days elapsed before entry is considered outdated
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

        days = (
            days_to_check
            if days_to_check is not None
            else config.days_to_check_std_entries
        )
        if days is None or days <= 0:
            days = 1
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        candidates = (
            sess.execute(
                select(LinkDataModel)
                .where(LinkDataModel.link.isnot(None))
                .where(LinkDataModel.link != "")
                .where(
                    or_(
                        LinkDataModel.date_update_last < cutoff,
                        LinkDataModel.date_update_last.is_(None),
                    )
                )
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
        self,
        session: Optional[Session] = None,
        max_age_seconds: int = 3600,
        days_to_check: Optional[int] = None,
    ) -> int:
        """
        When idle, checks what should be done next:
        - Checks how many sources to fetch (outdated sources) and enqueues them.
        - Checks how many entries to update (ConfigurationEntry.number_of_update_entries)
          based on date_update_last (exceeding ConfigurationEntry.days_to_check_std_entries)
          and enqueues link-update-data jobs.

        :param session: Optional active database session
        :param max_age_seconds: Maximum age before a source is considered outdated (default: 3600s = 1 hour)
        :param days_to_check: Optional override for days elapsed before entry is considered outdated
        :return: Total count of newly enqueued jobs
        """
        sources_enqueued = self.enqueue_outdated_source_jobs(
            session=session, max_age_seconds=max_age_seconds
        )
        entries_enqueued = self.enqueue_outdated_entry_jobs(
            session=session, days_to_check=days_to_check
        )
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

        # Fix eventual database schema issues at worker startup before processing jobs
        if self.fix_schema_on_startup:
            try:
                logger.info("Checking and repairing database schema at worker startup...")
                fix_res = self.fix_database_schema(reapply_defaults=True)
                fixed_count = fix_res.get("fixed_count", 0)
                if fixed_count > 0:
                    logger.info(
                        "Worker startup schema fix repaired %d table(s): %s",
                        fixed_count,
                        [r["table"] for r in fix_res.get("results", [])],
                    )
            except Exception as schema_err:
                logger.warning(
                    "Worker startup schema fix encountered an issue: %s", schema_err
                )

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
                # Release session before sleeping so the identity map doesn't
                # accumulate stale objects while the worker is effectively idle.
                close_session()
                time.sleep(interval)
                continue

            result = self.process_one()

            # Release the scoped session after each job iteration so that the
            # SQLAlchemy identity map (ORM object cache) is cleared and memory
            # held by loaded ORM objects (LinkDataModel rows, BackgroundJob
            # records, etc.) is returned to the heap promptly.
            try:
                close_session()
            except Exception as cs_err:
                logger.debug("Failed to close session after job iteration: %s", cs_err)

            gc.collect()

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
