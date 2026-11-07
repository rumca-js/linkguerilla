"""
Unit tests for Entry and History REST / JSON API endpoints.
"""

import unittest
from yafr.app import create_app
from yafr.db import EntryRepository, HistoryRepository, close_session, get_session


class TestApiEntries(unittest.TestCase):
    """
    Test suite for /api/entries/* and /api/history/* JSON endpoints.
    """

    def setUp(self):
        self.app = create_app(
            {
                "TESTING": True,
                "DATABASE_PATH": ":memory:",
                "SECRET_KEY": "test-key",
            }
        )
        self.client = self.app.test_client()
        self.session = get_session()
        self.repo = EntryRepository(self.session)

        self.entry = self.repo.add_entry(
            link="https://example.com/api-test",
            title="API Test Entry",
            description="Testing API endpoints",
        )

    def tearDown(self):
        close_session()

    def test_api_vote_entry(self):
        """POST /api/entries/<id>/vote sets rating vote to a direct number."""
        # Set vote to 70 directly
        res = self.client.post(
            f"/api/entries/{self.entry.id}/vote",
            json={"vote": 70},
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()["data"]
        self.assertEqual(data["page_rating_votes"], 70)

        # Set vote to negative number directly (-45)
        res2 = self.client.post(
            f"/api/entries/{self.entry.id}/vote",
            json={"vote": -45},
        )
        self.assertEqual(res2.status_code, 200)
        self.assertEqual(res2.get_json()["data"]["page_rating_votes"], -45)

        # Missing vote parameter returns 400
        res_missing = self.client.post(
            f"/api/entries/{self.entry.id}/vote",
            json={},
        )
        self.assertEqual(res_missing.status_code, 400)

        # Out-of-bounds vote number returns 400
        res_overflow = self.client.post(
            f"/api/entries/{self.entry.id}/vote",
            json={"vote": 150},
        )
        self.assertEqual(res_overflow.status_code, 400)

    def test_api_toggle_bookmark(self):
        """POST /api/entries/<id>/bookmark toggles bookmark flag."""
        res = self.client.post(f"/api/entries/{self.entry.id}/bookmark")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()["data"]["bookmarked"])

        res2 = self.client.post(f"/api/entries/{self.entry.id}/bookmark")
        self.assertEqual(res2.status_code, 200)
        self.assertFalse(res2.get_json()["data"]["bookmarked"])

    def test_api_toggle_read_later(self):
        """POST /api/entries/<id>/read-later toggles Read Later."""
        res = self.client.post(f"/api/entries/{self.entry.id}/read-later")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()["data"]["read_later"])

        res2 = self.client.post(f"/api/entries/{self.entry.id}/read-later")
        self.assertEqual(res2.status_code, 200)
        self.assertFalse(res2.get_json()["data"]["read_later"])

    def test_api_record_visit(self):
        """POST /api/entries/<id>/visit increments visit counter."""
        res = self.client.post(f"/api/entries/{self.entry.id}/visit")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["data"]["visits"], 1)

    def test_api_set_status(self):
        """POST /api/entries/<id>/status updates manual status code."""
        res = self.client.post(
            f"/api/entries/{self.entry.id}/status",
            json={"status_code": 400},
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["data"]["manual_status_code"], 400)

    def test_api_update_tags(self):
        """POST /api/entries/<id>/tags updates tags."""
        res = self.client.post(
            f"/api/entries/{self.entry.id}/tags",
            json={"tags": ["python", "flask", "web"]},
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["data"]["tags"], ["flask", "python", "web"])

    def test_api_delete_entry(self):
        """DELETE /api/entries/<id> deletes entry."""
        res = self.client.delete(f"/api/entries/{self.entry.id}")
        self.assertEqual(res.status_code, 200)
        self.assertIsNone(self.repo.get_by_id(self.entry.id))

    def test_api_batch_delete(self):
        """POST /api/entries/batch-delete deletes multiple entries."""
        e2 = self.repo.add_entry(link="https://example.com/e2", title="E2")
        e3 = self.repo.add_entry(link="https://example.com/e3", title="E3")

        res = self.client.post(
            "/api/entries/batch-delete",
            json={"ids": [e2.id, e3.id]},
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["data"]["deleted_count"], 2)

    def test_api_autocomplete(self):
        """GET /api/history/autocomplete returns query suggestions."""
        history = HistoryRepository(self.session)
        history.add_search("youtube gaming")
        history.add_search("youtube music")
        history.add_search("python tutorial")

        res = self.client.get("/api/history/autocomplete?q=you")
        self.assertEqual(res.status_code, 200)
        suggestions = res.get_json()["data"]["suggestions"]
        self.assertIn("youtube music", suggestions)
        self.assertIn("youtube gaming", suggestions)
        self.assertNotIn("python tutorial", suggestions)

    def test_api_mark_active_and_dead(self):
        """POST /api/entries/<id>/mark-active and /mark-dead sets manual status codes."""
        # Mark dead (400)
        res_dead = self.client.post(f"/api/entries/{self.entry.id}/mark-dead")
        self.assertEqual(res_dead.status_code, 200)
        self.assertEqual(res_dead.get_json()["data"]["manual_status_code"], 400)
        self.assertEqual(self.repo.get_by_id(self.entry.id).manual_status_code, 400)

        # Mark active (200)
        res_active = self.client.post(f"/api/entries/{self.entry.id}/mark-active")
        self.assertEqual(res_active.status_code, 200)
        self.assertEqual(res_active.get_json()["data"]["manual_status_code"], 200)
        self.assertEqual(self.repo.get_by_id(self.entry.id).manual_status_code, 200)

    def test_api_update_data_enqueues_job(self):
        """POST /api/entries/<id>/update-data enqueues background link-update-data job."""
        res = self.client.post(f"/api/entries/{self.entry.id}/update-data")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()["data"]
        self.assertEqual(data["entry_id"], self.entry.id)
        self.assertIn("job_id", data)

    def test_api_update_social_enqueues_job(self):
        """POST /api/entries/<id>/update-social enqueues background link-download-social job."""
        res = self.client.post(f"/api/entries/{self.entry.id}/update-social")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()["data"]
        self.assertEqual(data["entry_id"], self.entry.id)
        self.assertIn("job_id", data)

        from linkarchivetools.model.definitions import BackgroundJob
        from yafr.services.job_service import JOB_LINK_DOWNLOAD_SOCIAL

        job = self.session.get(BackgroundJob, data["job_id"])
        self.assertIsNotNone(job)
        self.assertEqual(job.job, JOB_LINK_DOWNLOAD_SOCIAL)
        self.assertEqual(job.subject, str(self.entry.id))

    def test_api_get_entry_jobs(self):
        """GET /api/entries/<id>/jobs returns connected active jobs and history."""
        # When no jobs exist
        res_empty = self.client.get(f"/api/entries/{self.entry.id}/jobs")
        self.assertEqual(res_empty.status_code, 200)
        data_empty = res_empty.get_json()["data"]
        self.assertEqual(data_empty["entry_id"], self.entry.id)
        self.assertEqual(data_empty["total_active"], 0)
        self.assertEqual(len(data_empty["jobs"]), 0)

        # Enqueue an active job
        from linkarchivetools.model.definitions import (
            BackgroundJob,
            BackgroundJobHistory,
        )
        from yafr.services.job_service import (
            JOB_LINK_DOWNLOAD_SOCIAL,
            JOB_LINK_UPDATE_DATA,
        )

        active_job = BackgroundJob(
            job=JOB_LINK_UPDATE_DATA,
            subject=str(self.entry.id),
            priority=1,
            enabled=True,
            errors=0,
        )
        history_job = BackgroundJobHistory(
            job=JOB_LINK_DOWNLOAD_SOCIAL,
            subject=self.entry.link,
        )
        self.session.add(active_job)
        self.session.add(history_job)
        self.session.commit()

        res = self.client.get(f"/api/entries/{self.entry.id}/jobs")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()["data"]
        self.assertEqual(data["entry_id"], self.entry.id)
        self.assertEqual(data["total_active"], 1)
        self.assertEqual(data["jobs"][0]["job"], JOB_LINK_UPDATE_DATA)
        self.assertEqual(data["jobs"][0]["subject"], str(self.entry.id))
        self.assertEqual(data["total_history"], 1)
        self.assertEqual(data["history"][0]["job"], JOB_LINK_DOWNLOAD_SOCIAL)

        # 404 for unknown entry
        res_404 = self.client.get("/api/entries/999999/jobs")
        self.assertEqual(res_404.status_code, 404)

    def test_api_reset_data(self):
        """POST /api/entries/<id>/reset-data clears hashes and status code."""
        self.entry.contents_hash = b"fake-hash"
        self.entry.status_code = 200
        self.session.commit()

        res = self.client.post(f"/api/entries/{self.entry.id}/reset-data")
        self.assertEqual(res.status_code, 200)
        refreshed = self.repo.get_by_id(self.entry.id)
        self.assertIsNone(refreshed.contents_hash)
        self.assertEqual(refreshed.status_code, 0)

    def test_api_visit_with_transition(self):
        """POST /api/entries/<id>/visit with from_entry_id records navigation transition."""
        e2 = self.repo.add_entry(link="https://example.com/target-page", title="Target")
        res = self.client.post(
            f"/api/entries/{e2.id}/visit",
            json={"from_entry_id": self.entry.id},
        )
        self.assertEqual(res.status_code, 200)
        history = HistoryRepository(self.session)
        transitions = history.get_transitions_from(self.entry.id)
        self.assertEqual(len(transitions), 1)
        self.assertEqual(transitions[0].entry_to_id, e2.id)

    def test_api_validate_link(self):
        """POST /api/entries/validate-link returns validation status and clickable propositions."""
        # Test URL with whitespace, www, and trailing slash
        res = self.client.post(
            "/api/entries/validate-link",
            json={"url": "  http://www.example.org/article/  "},
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()["data"]
        self.assertEqual(data["url"], "http://www.example.org/article/")
        self.assertTrue(data["is_web_link"])
        self.assertFalse(data["is_duplicate"])
        self.assertTrue(data["allowed"])

        # Check propositions
        prop_labels = [p["label"] for p in data["propositions"]]
        self.assertIn("Cleaned URL", prop_labels)

        # Test duplicate URL check
        res_dup = self.client.post(
            "/api/entries/validate-link",
            json={"url": "https://example.com/api-test"},
        )
        self.assertEqual(res_dup.status_code, 200)
        self.assertTrue(res_dup.get_json()["data"]["is_duplicate"])

    def test_api_quick_add_success(self):
        """POST /api/entries/quick-add creates entry and optionally marks read-later."""
        res = self.client.post(
            "/api/entries/quick-add",
            json={
                "link": "https://example.com/quick-created",
                "title": "Quick Created",
                "tags": ["quick", "test"],
                "read_later": True,
            },
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()["data"]
        self.assertIsNotNone(data["entry_id"])
        self.assertEqual(data["link"], "https://example.com/quick-created")

        # Verify entry in DB
        created = self.repo.get_by_id(data["entry_id"])
        self.assertIsNotNone(created)
        self.assertEqual(created.title, "Quick Created")

        # Verify tags
        tags = self.repo.get_tags(created.id)
        self.assertIn("quick", tags)
        self.assertIn("test", tags)

        # Verify read-later
        history = HistoryRepository(self.session)
        self.assertTrue(history.is_read_later(created.id))

        # Verify link-update-data background job was enqueued
        from yafr.db.job_repository import JobRepository
        from linkarchivetools.model.definitions import BackgroundJob
        from sqlalchemy import select

        job_repo = JobRepository(self.session)
        queued_job = self.session.execute(
            select(BackgroundJob).where(
                BackgroundJob.job == "link-update-data",
                BackgroundJob.subject == str(created.id),
            )
        ).scalar_one_or_none()
        self.assertIsNotNone(queued_job)

    def test_api_batch_add_success(self):
        """POST /api/entries/batch-add creates multiple entries and reports counts."""
        links = [
            "https://example.com/batch-1",
            "https://example.com/batch-2",
            "https://example.com/api-test",  # Duplicate of existing in setUp
        ]
        res = self.client.post(
            "/api/entries/batch-add",
            json={
                "links": links,
                "tags": ["batch-tag"],
                "read_later": False,
            },
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()["data"]
        self.assertEqual(data["total_submitted"], 3)
        self.assertEqual(data["added_count"], 2)
        self.assertEqual(data["duplicate_count"], 1)

        # Verify in DB
        b1 = self.repo.get_by_link("https://example.com/batch-1")
        b2 = self.repo.get_by_link("https://example.com/batch-2")
        self.assertIsNotNone(b1)
        self.assertIsNotNone(b2)
        self.assertIn("batch-tag", self.repo.get_tags(b1.id))

        # Verify link-update-data jobs were enqueued for newly added entries
        from linkarchivetools.model.definitions import BackgroundJob
        from sqlalchemy import select

        b1_job = self.session.execute(
            select(BackgroundJob).where(
                BackgroundJob.job == "link-update-data",
                BackgroundJob.subject == str(b1.id),
            )
        ).scalar_one_or_none()
        b2_job = self.session.execute(
            select(BackgroundJob).where(
                BackgroundJob.job == "link-update-data",
                BackgroundJob.subject == str(b2.id),
            )
        ).scalar_one_or_none()
        self.assertIsNotNone(b1_job)
        self.assertIsNotNone(b2_job)


if __name__ == "__main__":
    unittest.main()
