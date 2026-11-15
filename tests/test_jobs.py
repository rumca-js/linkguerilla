"""
Integration and unit tests for Background Jobs view and API endpoints.
"""

from datetime import datetime, timedelta, timezone
import json
import unittest
from linkarchivetools.model.definitions import BackgroundJob
from yafr.app import create_app
from yafr.db import (
    JobRepository,
    close_session,
    get_session,
)
from yafr.services import JobService


class TestJobRepositoryAndService(unittest.TestCase):
    """
    Test suite for JobRepository and JobService operations.
    """

    def setUp(self):
        self.app = create_app(
            {
                "TESTING": True,
                "DATABASE_PATH": ":memory:",
                "SECRET_KEY": "test-key-jobs",
            }
        )
        self.session = get_session()
        self.repo = JobRepository(self.session)

        # Seed sample jobs
        self.j1 = self.repo.enqueue_job(
            job="process-source",
            subject="https://news.ycombinator.com/rss",
            task="fetch feed",
            priority=5,
            enabled=True,
        )
        self.j2 = self.repo.enqueue_job(
            job="link-update-data",
            subject="https://example.com/item1",
            priority=1,
            enabled=False,
        )
        self.j3 = self.repo.enqueue_job(
            job="process-source",
            subject="https://lwn.net/rss",
            priority=10,
            enabled=True,
        )
        # Give j3 some errors
        self.repo.record_job_error(self.j3.id, max_retries=10)

    def tearDown(self):
        close_session()

    def test_list_jobs_filtering(self):
        """Verifies filtering by enabled, errors, and job_type."""
        # Enabled only
        active_jobs = self.repo.list_jobs(enabled=True)
        self.assertEqual(len(active_jobs), 2)
        self.assertTrue(all(j.enabled for j in active_jobs))

        # Paused only
        paused_jobs = self.repo.list_jobs(enabled=False)
        self.assertEqual(len(paused_jobs), 1)
        self.assertEqual(paused_jobs[0].id, self.j2.id)

        # Has errors
        error_jobs = self.repo.list_jobs(has_errors=True)
        self.assertEqual(len(error_jobs), 1)
        self.assertEqual(error_jobs[0].id, self.j3.id)

        # Job type filter
        process_jobs = self.repo.list_jobs(job_type="process-source")
        self.assertEqual(len(process_jobs), 2)
        update_jobs = self.repo.list_jobs(job_type="link-update-data")
        self.assertEqual(len(update_jobs), 1)

    def test_list_jobs_ordering(self):
        """Verifies sorting by priority, errors, and enabled."""
        # By priority (default)
        by_priority = self.repo.list_jobs(order_by="priority")
        self.assertEqual(
            [j.id for j in by_priority], [self.j2.id, self.j1.id, self.j3.id]
        )

        # By errors
        by_errors = self.repo.list_jobs(order_by="errors")
        self.assertEqual(by_errors[0].id, self.j3.id)

        # By enabled
        by_enabled = self.repo.list_jobs(order_by="enabled")
        self.assertTrue(by_enabled[0].enabled)

    def test_count_jobs(self):
        """Verifies count_jobs with various filters."""
        self.assertEqual(self.repo.count_jobs(), 3)
        self.assertEqual(self.repo.count_jobs(enabled=True), 2)
        self.assertEqual(self.repo.count_jobs(enabled=False), 1)
        self.assertEqual(self.repo.count_jobs(has_errors=True), 1)
        self.assertEqual(self.repo.count_jobs(job_type="process-source"), 2)

    def test_get_distinct_job_types(self):
        """Verifies retrieval of unique job type identifiers."""
        types = self.repo.get_distinct_job_types()
        self.assertIn("process-source", types)
        self.assertIn("link-update-data", types)

    def test_batch_operations(self):
        """Verifies batch pause, resume, and delete."""
        # Batch pause
        updated = self.repo.batch_set_status([self.j1.id, self.j3.id], enabled=False)
        self.assertEqual(updated, 2)
        self.assertEqual(self.repo.count_jobs(enabled=True), 0)

        # Batch resume
        updated = self.repo.batch_set_status([self.j1.id, self.j2.id], enabled=True)
        self.assertEqual(updated, 2)
        self.assertEqual(self.repo.count_jobs(enabled=True), 2)

        # Batch delete
        deleted = self.repo.delete_jobs([self.j1.id, self.j2.id])
        self.assertEqual(deleted, 2)
        self.assertEqual(self.repo.count_jobs(), 1)

    def test_job_service_batch_action(self):
        """Verifies JobService.batch_action wrapper."""
        affected = JobService.batch_action(
            [self.j1.id], action="pause", session=self.session
        )
        self.assertEqual(affected, 1)
        job = JobService.get_job(self.j1.id, session=self.session)
        self.assertFalse(job.enabled)

        with self.assertRaises(ValueError):
            JobService.batch_action(
                [self.j1.id], action="invalid-action", session=self.session
            )

    def test_clear_error_jobs_and_all_jobs(self):
        """Verifies clearing erroneous jobs and clearing all jobs."""
        # We start with 3 jobs: j1 (0 errors), j2 (0 errors), j3 (1 error)
        self.assertEqual(self.repo.count_error_jobs(), 1)
        self.assertEqual(self.repo.count_jobs(), 3)

        # Clear error jobs only
        deleted_errors = self.repo.clear_error_jobs()
        self.assertEqual(deleted_errors, 1)
        self.assertEqual(self.repo.count_error_jobs(), 0)
        self.assertEqual(self.repo.count_jobs(), 2)

        # Clear remaining jobs
        deleted_all = self.repo.clear_all_jobs()
        self.assertEqual(deleted_all, 2)
        self.assertEqual(self.repo.count_jobs(), 0)

    def test_service_clear_jobs(self):
        """Verifies JobService.clear_error_jobs and clear_all_jobs."""
        self.assertEqual(JobService.count_error_jobs(session=self.session), 1)
        deleted_errors = JobService.clear_error_jobs(session=self.session)
        self.assertEqual(deleted_errors, 1)

        deleted_all = JobService.clear_all_jobs(session=self.session)
        self.assertEqual(deleted_all, 2)
        self.assertEqual(JobService.count_jobs(session=self.session), 0)

    def test_duplicate_job_prevention(self):
        """Verifies that an identical second job is not added to the queue."""
        initial_count = self.repo.count_jobs()

        # Enqueue identical job with same job, subject, task, and args as self.j1
        dup = self.repo.enqueue_job(
            job="process-source",
            subject="https://news.ycombinator.com/rss",
            task="fetch feed",
        )
        self.assertEqual(dup.id, self.j1.id)
        self.assertEqual(self.repo.count_jobs(), initial_count)

        # Enqueue with different task -> should be added
        different_task = self.repo.enqueue_job(
            job="process-source",
            subject="https://news.ycombinator.com/rss",
            task="custom task",
        )
        self.assertNotEqual(different_task.id, self.j1.id)
        self.assertEqual(self.repo.count_jobs(), initial_count + 1)

        # Enqueue with different args -> should be added
        different_args = self.repo.enqueue_job(
            job="process-source",
            subject="https://news.ycombinator.com/rss",
            task="fetch feed",
            args='{"extra": true}',
        )
        self.assertNotEqual(different_args.id, self.j1.id)
        self.assertEqual(self.repo.count_jobs(), initial_count + 2)

        # Calling with raise_on_duplicate=True raises ValueError on identical job
        with self.assertRaises(ValueError):
            self.repo.enqueue_job(
                job="process-source",
                subject="https://news.ycombinator.com/rss",
                task="fetch feed",
                raise_on_duplicate=True,
            )

    def test_list_and_count_history(self):
        """Verifies listing, filtering, pagination and counting of job history."""
        # Complete j1 and j3 to archive them to history
        self.repo.complete_job(self.j1.id)
        self.repo.complete_job(self.j3.id)

        # Count history
        self.assertEqual(self.repo.count_history(), 2)
        self.assertEqual(self.repo.count_history(job_type="process-source"), 2)
        self.assertEqual(self.repo.count_history(job_type="non-existent"), 0)

        # List history
        history = self.repo.list_history()
        self.assertEqual(len(history), 2)

        # Pagination
        paginated = self.repo.list_history(limit=1, offset=0)
        self.assertEqual(len(paginated), 1)

        # Types
        types = self.repo.get_distinct_history_job_types()
        self.assertIn("process-source", types)

        # JobService wrapper
        svc_history = JobService.list_history(session=self.session)
        self.assertEqual(len(svc_history), 2)
        self.assertEqual(JobService.count_history(session=self.session), 2)

    def test_clear_history(self):
        """Verifies clearing all job history records."""
        self.repo.complete_job(self.j1.id)
        self.assertEqual(self.repo.count_history(), 1)

        deleted = JobService.clear_history(session=self.session)
        self.assertEqual(deleted, 1)
        self.assertEqual(self.repo.count_history(), 0)


class TestJobWebRoutes(unittest.TestCase):
    """
    Test suite for JobsView HTML route and /api/jobs REST endpoints.
    """

    def setUp(self):
        self.app = create_app(
            {
                "TESTING": True,
                "DATABASE_PATH": ":memory:",
                "SECRET_KEY": "test-key-job-routes",
            }
        )
        self.client = self.app.test_client()
        self.session = get_session()

        self.repo = JobRepository(self.session)
        self.job = self.repo.enqueue_job(
            job="process-source",
            subject="https://news.ycombinator.com/rss",
            priority=1,
            enabled=True,
        )

    def tearDown(self):
        close_session()

    def test_jobs_view_html(self):
        """GET /jobs renders job table with seeded job and controls."""
        res = self.client.get("/jobs")
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)
        self.assertIn("Background Jobs", html)
        self.assertIn("process-source", html)
        self.assertIn("https://news.ycombinator.com/rss", html)
        self.assertIn("Create Job", html)

    def test_jobs_view_filtering_query_params(self):
        """GET /jobs with status and order_by query parameters works."""
        res = self.client.get("/jobs?status=enabled&order_by=priority")
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)
        self.assertIn("process-source", html)

    def test_api_list_jobs(self):
        """GET /api/jobs returns JSON job payload."""
        res = self.client.get("/api/jobs")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()["data"]
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["jobs"][0]["job"], "process-source")

    def test_api_create_job(self):
        """POST /api/jobs/create creates a new background job."""
        res = self.client.post(
            "/api/jobs/create",
            json={
                "job": "link-update-data",
                "subject": "https://example.com/test",
                "priority": 2,
                "task": "refresh metadata",
                "args": json.dumps({"download_media": True}),
                "enabled": True,
            },
        )
        self.assertEqual(res.status_code, 201)
        data = res.get_json()
        self.assertTrue(data["success"])
        new_job_id = data["job_id"]

        # Verify job in database
        job = self.repo.get_by_id(BackgroundJob, new_job_id)
        self.assertIsNotNone(job)
        self.assertEqual(job.job, "link-update-data")
        self.assertEqual(job.priority, 2)

    def test_api_create_duplicate_job_rejected(self):
        """POST /api/jobs/create rejects duplicate job submission with 409."""
        payload = {
            "job": "cleanup",
            "subject": "cache",
            "task": "temp-files",
            "args": json.dumps({"older_than": 3600}),
        }

        # First request succeeds with 201
        res1 = self.client.post("/api/jobs/create", json=payload)
        self.assertEqual(res1.status_code, 201)
        job_id = res1.get_json()["job_id"]

        # Second request with identical properties fails with 409
        res2 = self.client.post("/api/jobs/create", json=payload)
        self.assertEqual(res2.status_code, 409)
        data2 = res2.get_json()
        self.assertFalse(data2["success"])
        self.assertIn("already exists", data2["error"])
        self.assertEqual(data2["job_id"], job_id)

        # Confirm queue still has only 1 job for this task
        matching = self.repo.list_jobs(job_type="cleanup")
        self.assertEqual(len(matching), 1)

    def test_api_create_job_missing_fields(self):
        """POST /api/jobs/create returns 400 when required fields are missing."""
        res = self.client.post("/api/jobs/create", json={"job": "only-type"})
        self.assertEqual(res.status_code, 400)

        res2 = self.client.post("/api/jobs/create", json={"subject": "only-subject"})
        self.assertEqual(res2.status_code, 400)

    def test_api_pause_and_resume_job(self):
        """POST /api/jobs/<id>/pause and /resume toggles job state."""
        # Pause
        res = self.client.post(f"/api/jobs/{self.job.id}/pause")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertFalse(data["enabled"])

        # Resume
        res2 = self.client.post(f"/api/jobs/{self.job.id}/resume")
        self.assertEqual(res2.status_code, 200)
        data2 = res2.get_json()
        self.assertTrue(data2["success"])
        self.assertTrue(data2["enabled"])

        # 404 for non-existent job
        res_404 = self.client.post("/api/jobs/99999/pause")
        self.assertEqual(res_404.status_code, 404)

    def test_api_delete_job(self):
        """DELETE /api/jobs/<id> removes the job."""
        res = self.client.delete(f"/api/jobs/{self.job.id}")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()["success"])

        # Subsequent delete returns 404
        res2 = self.client.delete(f"/api/jobs/{self.job.id}")
        self.assertEqual(res2.status_code, 404)

    def test_api_batch_action(self):
        """POST /api/jobs/batch-action executes batch pause, resume, and delete."""
        j2 = self.repo.enqueue_job(job="test-job", subject="sub2")

        # Batch pause
        res = self.client.post(
            "/api/jobs/batch-action",
            json={"job_ids": [self.job.id, j2.id], "action": "pause"},
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["affected_count"], 2)

        # Batch resume
        res = self.client.post(
            "/api/jobs/batch-action",
            json={"job_ids": [self.job.id, j2.id], "action": "resume"},
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["affected_count"], 2)

        # Batch delete
        res = self.client.post(
            "/api/jobs/batch-action",
            json={"job_ids": [self.job.id, j2.id], "action": "delete"},
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["affected_count"], 2)
        self.assertEqual(self.repo.count_jobs(), 0)

    def test_api_batch_action_invalid_action(self):
        """POST /api/jobs/batch-action with invalid action returns 400."""
        res = self.client.post(
            "/api/jobs/batch-action",
            json={"job_ids": [self.job.id], "action": "invalid-action"},
        )
        self.assertEqual(res.status_code, 400)

    def test_api_clear_all_jobs(self):
        """POST /api/jobs/clear-all deletes all queued jobs."""
        self.repo.enqueue_job(job="job2", subject="sub2")
        self.assertEqual(self.repo.count_jobs(), 2)

        res = self.client.post("/api/jobs/clear-all")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["deleted_count"], 2)
        self.assertEqual(self.repo.count_jobs(), 0)

    def test_api_clear_error_jobs(self):
        """POST /api/jobs/clear-errors deletes only jobs with failures."""
        j_err = self.repo.enqueue_job(job="job_failing", subject="sub_err")
        self.repo.record_job_error(j_err.id)
        self.assertEqual(self.repo.count_error_jobs(), 1)
        self.assertEqual(self.repo.count_jobs(), 2)

        res = self.client.post("/api/jobs/clear-errors")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["deleted_count"], 1)
        self.assertEqual(self.repo.count_error_jobs(), 0)
        self.assertEqual(self.repo.count_jobs(), 1)

    def test_routes_clear_all_and_clear_errors(self):
        """POST /jobs/clear-all and /jobs/clear-errors redirect and flash."""
        j_err = self.repo.enqueue_job(job="job_err", subject="err_sub")
        self.repo.record_job_error(j_err.id)

        # Clear errors via web route
        res_err = self.client.post("/jobs/clear-errors", follow_redirects=True)
        self.assertEqual(res_err.status_code, 200)
        self.assertIn(
            "Successfully cleared 1 erroneous jobs", res_err.get_data(as_text=True)
        )
        self.assertEqual(self.repo.count_error_jobs(), 0)

        # Clear all via web route
        res_all = self.client.post("/jobs/clear-all", follow_redirects=True)
        self.assertEqual(res_all.status_code, 200)
        self.assertIn("Successfully cleared all 1 jobs", res_all.get_data(as_text=True))
        self.assertEqual(self.repo.count_jobs(), 0)

    def test_jobs_view_has_history_button(self):
        """GET /jobs has a Job History button linking to /jobs/history."""
        res = self.client.get("/jobs")
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)
        self.assertIn("/jobs/history", html)
        self.assertIn("Job History", html)

    def test_job_history_view_html(self):
        """GET /jobs/history renders the historical completed jobs view."""
        # Archive job to history
        self.repo.complete_job(self.job.id)

        res = self.client.get("/jobs/history")
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)
        self.assertIn("Job History", html)
        self.assertIn("process-source", html)
        self.assertIn("https://news.ycombinator.com/rss", html)
        self.assertIn("/jobs", html)

    def test_routes_clear_history(self):
        """POST /jobs/history/clear clears all history and redirects."""
        self.repo.complete_job(self.job.id)
        self.assertEqual(self.repo.count_history(), 1)

        res = self.client.post("/jobs/history/clear", follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        self.assertIn(
            "Successfully cleared 1 history records", res.get_data(as_text=True)
        )
        self.assertEqual(self.repo.count_history(), 0)

    def test_api_list_history(self):
        """GET /api/jobs/history returns JSON history payload."""
        self.repo.complete_job(self.job.id)

        res = self.client.get("/api/jobs/history")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["data"]["total"], 1)
        self.assertEqual(data["data"]["history"][0]["job"], "process-source")

    def test_api_clear_history(self):
        """POST /api/jobs/history/clear clears history via JSON API."""
        self.repo.complete_job(self.job.id)
        self.assertEqual(self.repo.count_history(), 1)

        res = self.client.post("/api/jobs/history/clear")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["deleted_count"], 1)
        self.assertEqual(self.repo.count_history(), 0)


if __name__ == "__main__":
    unittest.main()
