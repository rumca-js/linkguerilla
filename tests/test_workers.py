"""
Unit and integration tests for background task execution and JobExecutor.
"""

from datetime import datetime, timedelta, timezone
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import MagicMock, patch
from sqlalchemy import select
from linkarchivetools.model.definitions import (
    BackgroundJob,
    BackgroundJobHistory,
    LinkDataModel,
    SearchHistory,
    SocialData,
    SourcesTable,
)
from yafr.app import create_app
from yafr.db import (
    BlockEntryRepository,
    ConfigRepository,
    EntryRepository,
    HistoryRepository,
    JobRepository,
    RulesRepository,
    SourceRepository,
    close_session,
    get_session,
    init_db,
)
from yafr.services.job_service import JOB_LINK_DOWNLOAD_SOCIAL
from yafr.workers.job_executor import JobExecutor


class TestJobExecutor(unittest.TestCase):
    """
    Test suite for JobExecutor sequential execution and task dispatching.
    """

    def setUp(self):
        self.app = create_app(
            {
                "TESTING": True,
                "DATABASE_PATH": ":memory:",
                "SECRET_KEY": "test-key-workers",
            }
        )
        self.session = get_session()
        self.job_repo = JobRepository(self.session)
        self.source_repo = SourceRepository(self.session)
        self.entry_repo = EntryRepository(self.session)
        self.history_repo = HistoryRepository(self.session)
        self.config_repo = ConfigRepository(self.session)
        self.rules_repo = RulesRepository(self.session)
        self.block_repo = BlockEntryRepository(self.session)

    def tearDown(self):
        close_session()

    def test_process_cleanup_job(self):
        """JobExecutor processes cleanup task and archives it to history."""
        # Seed searches exceeding limit
        for i in range(10):
            self.history_repo.add_search(f"query_{i}")

        job = self.job_repo.enqueue_job(
            job="cleanup",
            subject="system",
            priority=1,
            enabled=True,
        )

        executor = JobExecutor(session=self.session, auto_refresh_sources=False)
        result = executor.process_one(session=self.session)

        self.assertIsNotNone(result)
        self.assertTrue(result["processed"])
        self.assertEqual(result["job_id"], job.id)
        self.assertTrue(result["success"])

        # Job must be deleted from queue and present in history
        self.assertIsNone(self.job_repo.get_by_id(BackgroundJob, job.id))
        history_entry = (
            self.session.execute(
                select(BackgroundJobHistory).where(
                    BackgroundJobHistory.job == "cleanup"
                )
            )
            .scalars()
            .first()
        )
        self.assertIsNotNone(history_entry)

    def test_process_link_update_data_job(self):
        """JobExecutor processes link-update-data task and updates title, description, and timestamp."""
        entry = self.entry_repo.add_entry(
            link="https://example.com/item",
            title="Old Item",
            description="Old Description",
        )
        entry_id = entry.id

        job = self.job_repo.enqueue_job(
            job="link-update-data",
            subject=str(entry_id),
            priority=1,
            enabled=True,
        )

        executor = JobExecutor(session=self.session, auto_refresh_sources=False)

        pub_date = datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc)
        with patch("yafr.workers.jobs.link_jobs.WebToolsWrapper") as mock_webtools_cls:
            mock_client = MagicMock()
            mock_handler = MagicMock()
            mock_handler.get_title.return_value = "Updated Web Title"
            mock_handler.get_description.return_value = "Updated Web Description"
            mock_handler.get_date_published.return_value = pub_date
            mock_handler.get_author.return_value = "Updated Author"
            mock_client.url_handler = mock_handler
            mock_client.get_title.return_value = "Updated Web Title"
            mock_client.get_description.return_value = "Updated Web Description"
            mock_client.get_date_published.return_value = pub_date
            mock_client.get_author.return_value = "Updated Author"
            mock_client.get_response.return_value = MagicMock(is_valid=lambda: True)
            mock_client.is_valid.return_value = True
            mock_client.get_status_code.return_value = 200
            mock_webtools_cls.return_value = mock_client

            result = executor.process_one(session=self.session)

        self.assertIsNotNone(result)
        self.assertTrue(result["success"])
        self.assertEqual(result["job_id"], job.id)

        # Verify entry properties updated in database
        updated_entry = self.entry_repo.get_by_id(entry_id)
        self.assertEqual(updated_entry.title, "Updated Web Title")
        self.assertEqual(updated_entry.description, "Updated Web Description")
        self.assertEqual(updated_entry.date_published, pub_date)
        self.assertEqual(updated_entry.author, "Updated Author")
        self.assertEqual(updated_entry.status_code, 200)
        self.assertIsNone(updated_entry.date_dead_since)
        self.assertIsNotNone(updated_entry.date_update_last)

        # Job completed and archived
        self.assertIsNone(self.job_repo.get_by_id(BackgroundJob, job.id))

    def test_process_link_update_data_job_dead_link(self):
        """When link fetch fails, date_dead_since timestamp is recorded."""
        entry = self.entry_repo.add_entry(
            link="https://example.com/dead-link",
            title="Dead Link Entry",
        )
        entry_id = entry.id
        self.assertIsNone(entry.date_dead_since)

        job = self.job_repo.enqueue_job(
            job="link-update-data",
            subject=str(entry_id),
            priority=1,
            enabled=True,
        )

        executor = JobExecutor(session=self.session, auto_refresh_sources=False)

        with patch("yafr.workers.jobs.link_jobs.WebToolsWrapper") as mock_webtools_cls:
            mock_client = MagicMock()
            mock_client.get_response.return_value = None
            mock_client.is_valid.return_value = False
            mock_webtools_cls.return_value = mock_client

            result = executor.process_one(session=self.session)

        # Worker handled the dead link
        updated_entry = self.entry_repo.get_by_id(entry_id)
        self.assertIsNotNone(updated_entry.date_dead_since)

    def test_process_link_update_data_job_deletes_when_blocked_by_entry_rule(self):
        """When link-update-data runs on an entry matching a blocking EntryRule, entry is deleted."""
        entry = self.entry_repo.add_entry(
            link="https://spammy-site.com/offer",
            title="Spam Offer",
        )
        entry_id = entry.id

        # Add EntryRule with block=True matching this domain
        self.rules_repo.add_rule(
            rule_name="Block Spammy",
            trigger_rule_url=r".*spammy-site\.com.*",
            block=True,
            priority=1,
            enabled=True,
        )

        job = self.job_repo.enqueue_job(
            job="link-update-data",
            subject=str(entry_id),
            priority=1,
            enabled=True,
        )

        executor = JobExecutor(session=self.session, auto_refresh_sources=False)

        with patch("yafr.workers.jobs.link_jobs.WebToolsWrapper") as mock_webtools_cls:
            mock_client = MagicMock()
            mock_client.get_title.return_value = "Spam Offer"
            mock_client.get_description.return_value = "Buy now"
            mock_client.get_response.return_value = MagicMock(is_valid=lambda: True)
            mock_client.is_valid.return_value = True
            mock_client.get_status_code.return_value = 200
            mock_webtools_cls.return_value = mock_client

            result = executor.process_one(session=self.session)

        self.assertIsNotNone(result)
        self.assertTrue(result["success"])

        # Entry should have been deleted from DB
        self.assertIsNone(self.entry_repo.get_by_id(entry_id))

    def test_process_link_update_data_job_deletes_when_blocked_by_block_entry(self):
        """When link-update-data runs on an entry matching a BlockEntry pattern, entry is deleted."""
        entry = self.entry_repo.add_entry(
            link="https://tracker.badware.org/download/payload.exe",
            title="Download Payload",
        )
        entry_id = entry.id

        # Add BlockEntry whose url matches part of the entry link
        self.block_repo.add_entry("badware.org")

        job = self.job_repo.enqueue_job(
            job="link-update-data",
            subject=str(entry_id),
            priority=1,
            enabled=True,
        )

        executor = JobExecutor(session=self.session, auto_refresh_sources=False)

        with patch("yafr.workers.jobs.link_jobs.WebToolsWrapper") as mock_webtools_cls:
            mock_client = MagicMock()
            mock_client.get_title.return_value = "Download Payload"
            mock_client.get_description.return_value = "Malware"
            mock_client.get_response.return_value = MagicMock(is_valid=lambda: True)
            mock_client.is_valid.return_value = True
            mock_client.get_status_code.return_value = 200
            mock_webtools_cls.return_value = mock_client

            result = executor.process_one(session=self.session)

        self.assertIsNotNone(result)
        self.assertTrue(result["success"])

        # Entry should have been deleted from DB
        self.assertIsNone(self.entry_repo.get_by_id(entry_id))

    def test_process_link_download_social_job(self):
        """JobExecutor processes link-download-social task and stores data in socialdata table."""
        entry = self.entry_repo.add_entry(
            link="https://example.com/social-entry",
            title="Social Test",
        )
        entry_id = entry.id

        job = self.job_repo.enqueue_job(
            job=JOB_LINK_DOWNLOAD_SOCIAL,
            subject=str(entry_id),
            priority=1,
            enabled=True,
        )

        executor = JobExecutor(session=self.session, auto_refresh_sources=False)

        with patch("yafr.workers.jobs.link_jobs.WebToolsWrapper") as mock_webtools_cls:
            mock_client = MagicMock()
            mock_client.get_social_properties.return_value = {
                "rating": 4.8,
                "thumbs_up": 120,
                "thumbs_down": 5,
                "view_count": 3500,
                "upvote_ratio": 0.96,
                "upvote_diff": 115,
                "upvote_view_ratio": 0.034,
                "stars": None,
                "followers_count": 1000,
            }
            mock_webtools_cls.return_value = mock_client

            result = executor.process_one(session=self.session)

        self.assertIsNotNone(result)
        self.assertTrue(result["success"])

        social = self.entry_repo.get_social_data(entry_id)
        self.assertIsNotNone(social)
        self.assertEqual(social.thumbs_up, 120)
        self.assertEqual(social.thumbs_down, 5)
        self.assertEqual(social.view_count, 3500)
        self.assertEqual(social.upvote_diff, 115)
        self.assertEqual(social.followers_count, 1000)
        self.assertIsNotNone(social.date_updated)

    def test_enqueue_outdated_jobs(self):
        """enqueue_outdated_jobs enqueues process-source jobs for outdated sources."""
        source = self.source_repo.add_source(
            url="https://example.com/outdated_feed.xml",
            title="Outdated Feed For Queue",
            source_type="RSS",
            enabled=True,
        )
        self.source_repo.update_operational_data(
            source.id,
            date_fetched=datetime.now(timezone.utc) - timedelta(hours=2),
        )

        executor = JobExecutor(session=self.session, auto_refresh_sources=False)
        enqueued = executor.enqueue_outdated_jobs(session=self.session)

        self.assertGreaterEqual(enqueued, 1)
        pending_job = self.session.execute(
            select(BackgroundJob).where(
                BackgroundJob.job == "process-source",
                BackgroundJob.subject == str(source.id),
            )
        ).scalar_one_or_none()
        self.assertIsNotNone(pending_job)

    def test_process_source_job_success(self):
        """JobExecutor processes process-source task for an existing source."""
        source = self.source_repo.add_source(
            url="https://example.com/rss",
            title="Sample RSS",
            source_type="RSS",
            enabled=True,
        )

        job = self.job_repo.enqueue_job(
            job="process-source",
            subject=str(source.id),
            priority=1,
            enabled=True,
        )

        executor = JobExecutor(session=self.session, auto_refresh_sources=False)

        with patch(
            "yafr.services.source_service.SourceService.fetch_source"
        ) as mock_fetch:
            mock_fetch.return_value = {
                "success": True,
                "status": "completed",
                "message": "Fetched 5 entries",
            }
            result = executor.process_one(session=self.session)

            self.assertTrue(result["success"])
            self.assertEqual(result["job_id"], job.id)
            mock_fetch.assert_called_once_with(source.id, session=self.session)

        # Job completed and archived
        self.assertIsNone(self.job_repo.get_by_id(BackgroundJob, job.id))

    def test_process_source_job_failure_retry(self):
        """Job failure records error and disables job after reaching max_retries."""
        job = self.job_repo.enqueue_job(
            job="process-source",
            subject="99999",  # Non-existent source ID
            priority=1,
            enabled=True,
        )

        executor = JobExecutor(
            session=self.session, max_retries=2, auto_refresh_sources=False
        )

        # First failure
        res1 = executor.process_one(session=self.session)
        self.assertFalse(res1["success"])
        updated_job = self.job_repo.get_by_id(BackgroundJob, job.id)
        self.assertEqual(updated_job.errors, 1)
        self.assertTrue(updated_job.enabled)

        # Second failure -> reaches max_retries=2 -> disabled
        res2 = executor.process_one(session=self.session)
        self.assertFalse(res2["success"])
        updated_job = self.job_repo.get_by_id(BackgroundJob, job.id)
        self.assertEqual(updated_job.errors, 2)
        self.assertFalse(updated_job.enabled)

        # No more pending jobs (disabled job is skipped)
        res3 = executor.process_one(session=self.session)
        self.assertIsNone(res3)

    def test_empty_queue_fallback_to_outdated_source(self):
        """When queue is empty, auto-refreshes oldest outdated source."""
        source = self.source_repo.add_source(
            url="https://example.com/outdated.xml",
            title="Outdated Feed",
            source_type="RSS",
            enabled=True,
        )
        self.source_repo.update_operational_data(
            source.id,
            date_fetched=datetime.now(timezone.utc) - timedelta(hours=3),
        )

        executor = JobExecutor(session=self.session, auto_refresh_sources=True)

        with patch(
            "yafr.services.source_service.SourceService.fetch_source"
        ) as mock_fetch:
            mock_fetch.return_value = {
                "success": True,
                "status": "completed",
                "message": "Auto-refreshed",
            }
            result = executor.process_one(session=self.session)

            self.assertIsNotNone(result)
            self.assertEqual(result["job_type"], "source-auto-refresh")
            self.assertEqual(result["subject"], source.url)
            self.assertTrue(result["success"])
            mock_fetch.assert_called_once_with(source.id, session=self.session)

    def test_enqueue_outdated_entry_jobs_respects_number_of_update_entries(self):
        """enqueue_outdated_entry_jobs respects number_of_update_entries and uses date_update_last."""
        now = datetime.now(timezone.utc)
        # Entry 1: date_update_last = None (oldest)
        e1 = self.entry_repo.add_entry(link="https://example.com/item1", title="Item 1")
        e1.date_update_last = None

        # Entry 2: date_update_last = 2 days ago
        e2 = self.entry_repo.add_entry(link="https://example.com/item2", title="Item 2")
        e2.date_update_last = now - timedelta(days=2)

        # Entry 3: date_update_last = 1 day ago
        e3 = self.entry_repo.add_entry(link="https://example.com/item3", title="Item 3")
        e3.date_update_last = now - timedelta(days=1)

        # Entry 4: date_update_last = 1 hour ago
        e4 = self.entry_repo.add_entry(link="https://example.com/item4", title="Item 4")
        e4.date_update_last = now - timedelta(hours=1)
        self.session.commit()

        # Set number_of_update_entries = 2 in config
        config = self.config_repo.get_config()
        config.number_of_update_entries = 2
        self.session.commit()

        executor = JobExecutor(session=self.session, auto_refresh_sources=False)
        enqueued = executor.enqueue_outdated_entry_jobs(session=self.session)

        # Exactly 2 jobs enqueued for the 2 oldest entries (e1 and e2)
        self.assertEqual(enqueued, 2)
        enqueued_subjects = list(
            self.session.execute(
                select(BackgroundJob.subject).where(
                    BackgroundJob.job == "link-update-data",
                    BackgroundJob.enabled == True,
                )
            ).scalars().all()
        )
        self.assertIn(str(e1.id), enqueued_subjects)
        self.assertIn(str(e2.id), enqueued_subjects)
        self.assertNotIn(str(e3.id), enqueued_subjects)
        self.assertNotIn(str(e4.id), enqueued_subjects)

        # Running again does not create duplicate jobs
        enqueued_again = executor.enqueue_outdated_entry_jobs(session=self.session)
        self.assertEqual(enqueued_again, 0)

    def test_empty_queue_fallback_to_outdated_entry(self):
        """When queue is empty and no outdated sources exist, auto-updates oldest entry and sets date_update_last."""
        e = self.entry_repo.add_entry(link="https://example.com/old-entry", title="Old Entry")
        e.date_update_last = None
        self.session.commit()

        executor = JobExecutor(session=self.session, auto_refresh_sources=True)

        with patch("yafr.workers.jobs.link_jobs.WebToolsWrapper") as mock_webtools_cls:
            mock_client = MagicMock()
            mock_client.get_title.return_value = "Updated Entry Title"
            mock_client.get_description.return_value = "Updated Entry Description"
            mock_client.get_date_published.return_value = None
            mock_client.get_author.return_value = None
            mock_client.get_response.return_value = MagicMock(is_valid=lambda: True)
            mock_client.is_valid.return_value = True
            mock_client.get_status_code.return_value = 200
            mock_webtools_cls.return_value = mock_client

            result = executor.process_one(session=self.session)

        self.assertIsNotNone(result)
        self.assertEqual(result["job_type"], "entry-auto-update")
        self.assertEqual(result["subject"], str(e.id))
        self.assertTrue(result["success"])

        # Check date_update_last was updated to now
        refreshed_entry = self.entry_repo.get_by_id(e.id)
        self.assertIsNotNone(refreshed_entry.date_update_last)
        self.assertEqual(refreshed_entry.title, "Updated Entry Title")

    def test_run_loop_with_max_jobs(self):
        """run_loop terminates cleanly after executing max_jobs."""
        self.job_repo.enqueue_job(job="cleanup", subject="1")
        self.job_repo.enqueue_job(job="cleanup", subject="2")
        self.job_repo.enqueue_job(job="cleanup", subject="3")

        executor = JobExecutor(session=self.session, auto_refresh_sources=False)
        executed = executor.run_loop(interval=0.01, max_jobs=2)

        self.assertEqual(executed, 2)
        self.assertEqual(self.job_repo.count_jobs(), 1)


class TestProcessJobsScriptCLI(unittest.TestCase):
    """
    Test suite for process_jobs.py standalone CLI entrypoint.
    """

    def test_process_jobs_cli_help(self):
        """process_jobs.py --help exits with 0."""
        cmd = [sys.executable, "process_jobs.py", "--help"]
        result = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        self.assertIn("Background Task Processor", result.stdout)
        self.assertIn("--once", result.stdout)
        self.assertIn("--interval", result.stdout)

    def test_process_jobs_cli_once_mode(self):
        """process_jobs.py --once processes one job and terminates with code 0."""
        with tempfile.NamedTemporaryFile(suffix=".db") as temp_db:
            init_db(temp_db.name, sync_schema=True)
            sess = get_session()
            repo = JobRepository(sess)
            repo.enqueue_job(job="cleanup", subject="cli-test", priority=1)
            close_session()

            cmd = [
                sys.executable,
                "process_jobs.py",
                "--db",
                temp_db.name,
                "--once",
                "--no-refresh-sources",
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0)
            self.assertIn("[OK]", result.stdout)
            self.assertIn("cleanup", result.stdout)


class TestModularJobHandlersAndRegistry(unittest.TestCase):
    """
    Test suite for modular background job handlers and JobRegistry.
    """

    def setUp(self):
        self.app = create_app(
            {
                "TESTING": True,
                "DATABASE_PATH": ":memory:",
                "SECRET_KEY": "test-key-modular-jobs",
            }
        )
        self.session = get_session()
        self.entry_repo = EntryRepository(self.session)
        self.job_repo = JobRepository(self.session)

    def tearDown(self):
        close_session()

    def test_custom_handler_registration(self):
        """JobRegistry allows registering custom job handlers for new job types."""
        from yafr.workers.jobs import BaseJobHandler, JobRegistry

        class CustomExportJobHandler(BaseJobHandler):
            job_types = ("custom-export",)

            def execute(self, job, session):
                return {
                    "success": True,
                    "status": "completed",
                    "message": f"Exported {job.subject}",
                }

        registry = JobRegistry()
        custom_handler = CustomExportJobHandler()
        registry.register(custom_handler)

        self.assertIs(registry.get_handler("custom-export"), custom_handler)

        # Test execution via JobExecutor with custom registry
        job = self.job_repo.enqueue_job(job="custom-export", subject="data.json")
        executor = JobExecutor(
            session=self.session, registry=registry, auto_refresh_sources=False
        )
        result = executor.process_one(session=self.session)

        self.assertTrue(result["success"])
        self.assertEqual(result["message"], "Exported data.json")


if __name__ == "__main__":
    unittest.main()
