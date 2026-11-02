"""
Unit and integration tests for worker liveness status API and configuration-aware indications.
"""

from datetime import datetime, timedelta, timezone
import unittest
from yafr.app import create_app
from yafr.db import (
    ConfigRepository,
    close_session,
    get_session,
)
from yafr.db.system_operation_repository import (
    DEFAULT_WORKER_TIMEOUT_SECONDS,
    SystemOperationRepository,
)
from yafr.web.shared import get_shared_context


class TestApiStatus(unittest.TestCase):
    """
    Test suite for /api/status, /api/status/worker and status flags.
    """

    def setUp(self):
        self.app = create_app(
            {
                "TESTING": True,
                "DATABASE_PATH": ":memory:",
                "SECRET_KEY": "test-key-status",
            }
        )
        self.client = self.app.test_client()
        self.session = get_session()
        self.config_repo = ConfigRepository(self.session)
        self.op_repo = SystemOperationRepository(self.session)

    def tearDown(self):
        close_session()

    def test_worker_status_active(self):
        """When worker heartbeat is fresh, status is active and worker_dead is False."""
        self.op_repo.record_heartbeat(status=True, thread_id="t-123", check_type="worker")

        res = self.client.get("/api/status/worker")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["is_active"])
        self.assertEqual(data["status_label"], "active")
        self.assertTrue(data["enable_background_jobs"])
        self.assertEqual(data["thread_id"], "t-123")
        self.assertIn("flags", data)
        self.assertTrue(data["flags"]["worker_active"])
        self.assertFalse(data["flags"]["worker_dead"])
        self.assertTrue(data["flags"]["background_jobs_enabled"])

    def test_worker_status_dead_when_enabled(self):
        """When worker has no heartbeat and enable_background_jobs is True, worker_dead is True."""
        self.config_repo.update_config(enable_background_jobs=True)

        res = self.client.get("/api/status/worker")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertFalse(data["is_active"])
        self.assertEqual(data["status_label"], "dead")
        self.assertTrue(data["enable_background_jobs"])
        self.assertIn("Worker is dead", data["message"])
        self.assertIn("flags", data)
        self.assertFalse(data["flags"]["worker_active"])
        self.assertTrue(data["flags"]["worker_dead"])
        self.assertTrue(data["flags"]["background_jobs_enabled"])

    def test_worker_status_disabled_when_enable_background_jobs_false(self):
        """When enable_background_jobs is False and worker has no heartbeat, worker_dead is False."""
        self.config_repo.update_config(enable_background_jobs=False)

        res = self.client.get("/api/status/worker")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertFalse(data["is_active"])
        self.assertEqual(data["status_label"], "disabled")
        self.assertFalse(data["enable_background_jobs"])
        self.assertNotIn("Worker is dead", data["message"])
        self.assertIn("Background jobs are disabled", data["message"])
        self.assertIn("flags", data)
        self.assertFalse(data["flags"]["worker_active"])
        self.assertFalse(data["flags"]["worker_dead"])
        self.assertFalse(data["flags"]["background_jobs_enabled"])

    def test_worker_status_timed_out_disabled(self):
        """When worker heartbeat is older than timeout and enable_background_jobs is False, status is disabled."""
        self.config_repo.update_config(enable_background_jobs=False)
        rec = self.op_repo.record_heartbeat(status=True, thread_id="t-old", check_type="worker")
        # Artificially set date_created to 20 minutes ago
        rec.date_created = datetime.now(timezone.utc) - timedelta(minutes=20)
        self.op_repo.commit()

        status_data = self.op_repo.check_worker_status(max_age_seconds=DEFAULT_WORKER_TIMEOUT_SECONDS)
        self.assertFalse(status_data["is_active"])
        self.assertEqual(status_data["status_label"], "disabled")
        self.assertFalse(status_data["enable_background_jobs"])
        self.assertNotIn("Worker is dead", status_data["message"])
        self.assertFalse(status_data["flags"]["worker_active"])
        self.assertFalse(status_data["flags"]["worker_dead"])

    def test_system_status_endpoint_flags(self):
        """GET /api/status returns full set of flags translated into badges."""
        self.config_repo.update_config(enable_background_jobs=False)
        res = self.client.get("/api/status")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertIn("flags", data)
        flags = data["flags"]
        self.assertIn("worker_active", flags)
        self.assertIn("worker_dead", flags)
        self.assertIn("background_jobs_enabled", flags)
        self.assertIn("database_ok", flags)
        self.assertIn("sources_ok", flags)
        self.assertIn("jobs_ok", flags)
        self.assertIn("webtools_configured", flags)
        self.assertIn("webtools_online", flags)
        self.assertTrue(flags["database_ok"])
        self.assertFalse(flags["background_jobs_enabled"])
        self.assertFalse(flags["worker_dead"])

        self.assertIn("badges", data)
        self.assertIn("sources_outdated", data["badges"])
        self.assertIn("sources_errors", data["badges"])
        self.assertIn("jobs_errors", data["badges"])

    def test_shared_context_includes_enable_background_jobs(self):
        """Shared context should provide enable_background_jobs boolean."""
        self.config_repo.update_config(enable_background_jobs=False)
        ctx = get_shared_context()
        self.assertIn("enable_background_jobs", ctx)
        self.assertFalse(ctx["enable_background_jobs"])

        self.config_repo.update_config(enable_background_jobs=True)
        ctx = get_shared_context()
        self.assertTrue(ctx["enable_background_jobs"])

    def test_navbar_worker_badge_hidden_when_background_jobs_disabled(self):
        """Navbar should hide worker-badge with d-none if enable_background_jobs is false."""
        self.config_repo.update_config(enable_background_jobs=False)
        res = self.client.get("/")
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)
        self.assertIn('id="worker-badge" class="badge d-none', html)

    def test_navbar_worker_badge_shown_when_background_jobs_enabled(self):
        """Navbar should render worker-badge without d-none if enable_background_jobs is true."""
        self.config_repo.update_config(enable_background_jobs=True)
        res = self.client.get("/")
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)
        self.assertNotIn('id="worker-badge" class="badge d-none', html)
        self.assertIn('id="worker-badge"', html)
