"""
Integration tests for Sources views and REST API endpoints.
"""

from datetime import datetime, timedelta, timezone
import json
import time
import unittest
from unittest.mock import patch
from sqlalchemy import select
from linkarchivetools.model.definitions import (
    Credentials,
    LinkDataModel,
    SourceOperationalData,
    SourcesTable,
)
from yafr.app import create_app
from yafr.db import (
    SourceRepository,
    close_session,
    get_session,
)


class TestSourceRoutes(unittest.TestCase):
    """
    Test suite for SourcesListView, SourceDetailScreen, and SourceEdit screens.
    """

    def setUp(self):
        self.app = create_app(
            {
                "TESTING": True,
                "DATABASE_PATH": ":memory:",
                "SECRET_KEY": "test-key-sources",
            }
        )
        self.client = self.app.test_client()
        self.session = get_session()

        self.repo = SourceRepository(self.session)

        # Seed sample sources
        self.s1 = self.repo.add_source(
            url="https://news.ycombinator.com/rss",
            title="Hacker News",
            source_type="RSS",
            enabled=True,
            auto_tag="tech, startups",
            fetch_period=1800,
        )

        self.s2 = self.repo.add_source(
            url="https://lwn.net/headlines/rss",
            title="Linux Weekly News",
            source_type="RSS",
            enabled=False,
            auto_tag="linux, kernel",
        )

        # Seed operational tracking data
        self.repo.update_operational_data(
            self.s1.id,
            consecutive_errors=0,
            number_of_entries=15,
            page_hash=b"fake_hash_1",
            body_hash=b"fake_hash_1",
            date_fetched=datetime.now(timezone.utc) - timedelta(minutes=10),
            date_successful_fetch=datetime.now(timezone.utc) - timedelta(minutes=10),
        )

        self.repo.update_operational_data(
            self.s2.id,
            consecutive_errors=2,
            number_of_entries=5,
            page_hash=b"fake_hash_2",
            body_hash=b"fake_hash_2",
            date_fetched=datetime.now(timezone.utc) - timedelta(hours=2),
        )

    def tearDown(self):
        close_session()

    def test_sources_list_empty_query(self):
        """GET /sources without query renders compact search bar and displays all sources."""
        response = self.client.get("/sources")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("top-source-search-input", html)
        self.assertIn("Search sources", html)
        self.assertIn("Add Source", html)
        self.assertIn("Hacker News", html)
        self.assertIn("Linux Weekly News", html)
        self.assertNotIn("main-source-search-input", html)
        self.assertNotIn("Browse All Sources", html)

    def test_sources_list_search_no_input_returns_all_data(self):
        """GET /sources?q= (source search with no input) returns all sources."""
        response = self.client.get("/sources?q=")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Hacker News", html)
        self.assertIn("Linux Weekly News", html)
        self.assertIn("Showing all", html)

    def test_sources_list_show_all(self):
        """GET /sources?all=1 renders list of all sources."""
        response = self.client.get("/sources?all=1")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Hacker News", html)
        self.assertIn("Linux Weekly News", html)
        self.assertIn("source-select-check", html)

    def test_sources_list_with_query(self):
        """GET /sources?q=Linux executes search and returns matching source."""
        response = self.client.get("/sources?q=Linux")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Linux Weekly News", html)
        self.assertNotIn("Hacker News", html)

    def test_sources_list_with_operator_and_filter(self):
        """GET /sources?q=title=Hacker&filter=title works properly."""
        response = self.client.get("/sources?q=title=Hacker&filter=title")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Hacker News", html)
        self.assertNotIn("Linux Weekly News", html)

    def test_sources_list_exact_operator(self):
        """GET /sources?q=title==Hacker News exact match."""
        response = self.client.get('/sources?q=title=="Hacker News"')
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Hacker News", html)

    def test_source_detail_screen(self):
        """GET /sources/<id> renders SourceDetailScreen with entries linking to /entries/<id>."""
        from linkarchivetools.model.definitions import LinkDataModel

        entry = LinkDataModel(
            link="https://news.ycombinator.com/item?id=123",
            title="Sample HN Item",
            source_id=self.s1.id,
            page_rating_votes=42,
        )
        self.session.add(entry)
        self.session.commit()

        response = self.client.get(f"/sources/{self.s1.id}")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Hacker News", html)
        self.assertIn("https://news.ycombinator.com/rss", html)
        self.assertIn("Operational Hashes", html)
        self.assertIn("Stored Entries", html)
        self.assertIn("Fetch Period", html)
        self.assertIn("1,800s", html)
        self.assertIn(f"/entries/{entry.id}", html)
        self.assertIn("Sample HN Item", html)
        self.assertIn("Search in Entries", html)
        self.assertIn("link%3Dhttps", html)

        # Also test source without custom fetch_period displays Default
        res_s2 = self.client.get(f"/sources/{self.s2.id}")
        self.assertEqual(res_s2.status_code, 200)
        html_s2 = res_s2.get_data(as_text=True)
        self.assertIn("Fetch Period", html_s2)
        self.assertIn("Default", html_s2)

    def test_source_detail_404(self):
        """GET /sources/99999 returns 404 for non-existent source."""
        response = self.client.get("/sources/99999")
        self.assertEqual(response.status_code, 404)

    def test_source_detail_convert_ui_rss_source(self):
        """GET /sources/<id> for RSS source provides conversion to Parse, but not to RSS."""
        response = self.client.get(f"/sources/{self.s1.id}")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("convertSourceDropdown", html)
        self.assertIn("btn-convert-to-parse", html)
        self.assertIn("Convert to Parse", html)
        self.assertNotIn("btn-convert-to-rss", html)

    def test_source_detail_convert_ui_parse_source(self):
        """GET /sources/<id> for Parse source provides conversion to RSS, but not to Parse."""
        parse_src = self.repo.add_source(
            url="https://example.com/parse-ui",
            title="Parse UI Source",
            source_type="PARSE",
        )
        response = self.client.get(f"/sources/{parse_src.id}")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("convertSourceDropdown", html)
        self.assertIn("btn-convert-to-rss", html)
        self.assertIn("Convert to RSS", html)
        self.assertNotIn("btn-convert-to-parse", html)

    def test_source_detail_convert_ui_unfilled_source(self):
        """GET /sources/<id> for unfilled source provides conversion to BOTH Parse and RSS."""
        unfilled_src = self.repo.add_source(
            url="https://example.com/unfilled-ui",
            title="Unfilled UI Source",
            source_type="",
        )
        response = self.client.get(f"/sources/{unfilled_src.id}")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("convertSourceDropdown", html)
        self.assertIn("btn-convert-to-rss", html)
        self.assertIn("btn-convert-to-parse", html)
        self.assertIn("Convert to RSS", html)
        self.assertIn("Convert to Parse", html)

    def test_source_detail_convert_ui_email_source(self):
        """GET /sources/<id> for EMAIL source does NOT provide conversion."""
        email_src = self.repo.add_source(
            url="imaps://imap.example.com",
            title="Email UI Source",
            source_type="EMAIL",
        )
        response = self.client.get(f"/sources/{email_src.id}")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertNotIn("convertSourceDropdown", html)
        self.assertNotIn("btn-convert-to-rss", html)
        self.assertNotIn("btn-convert-to-parse", html)

    def test_source_detail_convert_html_form_post(self):
        """POST /sources/<id>/convert updates source_type and redirects."""
        res = self.client.post(
            f"/sources/{self.s1.id}/convert",
            data={"target_type": "PARSE"},
            follow_redirects=True,
        )
        self.assertEqual(res.status_code, 200)
        updated = self.repo.get_by_id(self.s1.id)
        self.assertEqual(updated.source_type, "PARSE")
        html = res.get_data(as_text=True)
        self.assertIn("Source converted to PARSE successfully.", html)

    def test_add_rss_source(self):
        """GET and POST /sources/new/rss creates new RSS source with optional regex match pattern."""
        # Test GET
        res_get = self.client.get("/sources/new/rss")
        self.assertEqual(res_get.status_code, 200)
        self.assertIn("Add New RSS", res_get.get_data(as_text=True))
        self.assertIn("fetch_period", res_get.get_data(as_text=True))
        self.assertIn("re.match", res_get.get_data(as_text=True))
        self.assertIn('id="auto_add_to_read_later"', res_get.get_data(as_text=True))

        # Test POST
        res_post = self.client.post(
            "/sources/new/rss",
            data={
                "title": "Ars Technica",
                "url": "https://feeds.arstechnica.com/arstechnica/index",
                "xpath": r"https://arstechnica\.com/.*",
                "enabled": "on",
                "auto_add_to_read_later": "on",
                "auto_tag": "tech, hardware",
                "language": "en",
                "age": "18",
                "fetch_period": "7200",
            },
            follow_redirects=True,
        )
        self.assertEqual(res_post.status_code, 200)
        html = res_post.get_data(as_text=True)
        self.assertIn("Ars Technica", html)
        self.assertIn("7,200s", html)
        self.assertIn("badge-source-language", html)
        self.assertIn("badge-source-age", html)
        self.assertIn("badge-source-read-later", html)
        self.assertIn("Auto Read Later", html)
        self.assertIn("Age 18+", html)
        self.assertIn(r"https://arstechnica\.com/.*", html)

        # Verify in DB
        created = self.repo.get_by_url(
            "https://feeds.arstechnica.com/arstechnica/index"
        )
        self.assertIsNotNone(created)
        self.assertEqual(created.title, "Ars Technica")
        self.assertEqual(created.source_type, "RSS")
        self.assertTrue(created.auto_add_to_read_later)
        self.assertEqual(created.xpath, r"https://arstechnica\.com/.*")
        self.assertEqual(created.fetch_period, 7200)
        self.assertEqual(created.language, "en")
        self.assertEqual(created.age, 18)

    def test_edit_rss_source(self):
        """GET and POST /sources/<id>/edit-rss updates existing RSS source."""
        # Enable auto_add_to_read_later
        res_post = self.client.post(
            f"/sources/{self.s1.id}/edit-rss",
            data={
                "title": "Hacker News Frontpage",
                "url": "https://news.ycombinator.com/rss",
                "xpath": r"https://news\.ycombinator\.com/item\?id=\d+",
                "enabled": "on",
                "auto_add_to_read_later": "on",
                "auto_tag": "tech, yc",
                "language": "en",
                "age": "16",
                "fetch_period": "3600",
            },
            follow_redirects=True,
        )
        self.assertEqual(res_post.status_code, 200)
        updated = self.repo.get_by_id(self.s1.id)
        self.assertEqual(updated.title, "Hacker News Frontpage")
        self.assertEqual(updated.xpath, r"https://news\.ycombinator\.com/item\?id=\d+")
        self.assertTrue(updated.auto_add_to_read_later)
        self.assertEqual(updated.auto_tag, "tech, yc")
        self.assertEqual(updated.language, "en")
        self.assertEqual(updated.age, 16)
        self.assertEqual(updated.fetch_period, 3600)

        # Verify GET edit page shows checkbox checked
        res_get = self.client.get(f"/sources/{self.s1.id}/edit-rss")
        self.assertEqual(res_get.status_code, 200)
        self.assertIn('name="auto_add_to_read_later" \n            checked', res_get.get_data(as_text=True))

        # Disable auto_add_to_read_later
        res_post_disable = self.client.post(
            f"/sources/{self.s1.id}/edit-rss",
            data={
                "title": "Hacker News Frontpage",
                "url": "https://news.ycombinator.com/rss",
                "enabled": "on",
            },
            follow_redirects=True,
        )
        self.assertEqual(res_post_disable.status_code, 200)
        self.session.refresh(updated)
        self.assertFalse(updated.auto_add_to_read_later)

    def test_add_and_edit_email_source(self):
        """GET and POST /sources/new/email creates email source and credentials."""
        # Test GET
        res_get = self.client.get("/sources/new/email")
        self.assertEqual(res_get.status_code, 200)
        self.assertIn('id="auto_add_to_read_later"', res_get.get_data(as_text=True))

        res_post = self.client.post(
            "/sources/new/email",
            data={
                "title": "Daily Newsletter",
                "url": "imaps://imap.example.com:993",
                "username": "reader@example.com",
                "password": "secretpassword",
                "enabled": "on",
                "auto_add_to_read_later": "on",
                "fetch_period": "1800",
            },
            follow_redirects=True,
        )
        self.assertEqual(res_post.status_code, 200)

        # Verify source and credentials created
        created = self.repo.get_by_url("imaps://imap.example.com:993")
        self.assertIsNotNone(created)
        self.assertEqual(created.source_type, "EMAIL")
        self.assertTrue(created.auto_add_to_read_later)
        self.assertEqual(created.fetch_period, 1800)
        self.assertIsNotNone(created.credentials_id)

        cred = self.session.get(Credentials, created.credentials_id)
        self.assertIsNotNone(cred)
        self.assertEqual(cred.username, "reader@example.com")
        self.assertEqual(cred.password, "secretpassword")

        # Edit email source (turn off auto_add_to_read_later)
        res_edit = self.client.post(
            f"/sources/{created.id}/edit-email",
            data={
                "title": "Updated Newsletter",
                "url": "imaps://imap.example.com:993",
                "username": "newreader@example.com",
                "password": "newpassword",
                "enabled": "on",
                "fetch_period": "900",
            },
            follow_redirects=True,
        )
        self.assertEqual(res_edit.status_code, 200)
        self.session.refresh(cred)
        self.session.refresh(created)
        self.assertEqual(cred.username, "newreader@example.com")
        self.assertEqual(cred.password, "newpassword")
        self.assertFalse(created.auto_add_to_read_later)
        self.assertEqual(created.fetch_period, 900)

    def test_add_and_edit_parse_source(self):
        """GET and POST /sources/new/parse creates custom parse source with re.match pattern."""
        res_get = self.client.get("/sources/new/parse")
        self.assertEqual(res_get.status_code, 200)
        self.assertIn("re.match", res_get.get_data(as_text=True))
        self.assertIn('id="auto_add_to_read_later"', res_get.get_data(as_text=True))

        res_post = self.client.post(
            "/sources/new/parse",
            data={
                "title": "Lobsters Scraping",
                "url": "https://lobste.rs",
                "xpath": r"https://lobste\.rs/s/.*",
                "enabled": "on",
                "auto_add_to_read_later": "on",
                "fetch_period": "86400",
            },
            follow_redirects=True,
        )
        self.assertEqual(res_post.status_code, 200)

        created = self.repo.get_by_url("https://lobste.rs")
        self.assertIsNotNone(created)
        self.assertEqual(created.source_type, "PARSE")
        self.assertEqual(created.xpath, r"https://lobste\.rs/s/.*")
        self.assertTrue(created.auto_add_to_read_later)
        self.assertEqual(created.fetch_period, 86400)

        # Edit parse source (disable auto_add_to_read_later)
        res_edit = self.client.post(
            f"/sources/{created.id}/edit-parse",
            data={
                "title": "Lobsters Scraping Updated",
                "url": "https://lobste.rs",
                "xpath": r"https://lobste\.rs/s/\w+",
                "enabled": "on",
                "fetch_period": "43200",
            },
            follow_redirects=True,
        )
        self.assertEqual(res_edit.status_code, 200)
        self.session.refresh(created)
        self.assertEqual(created.xpath, r"https://lobste\.rs/s/\w+")
        self.assertFalse(created.auto_add_to_read_later)
        self.assertEqual(created.fetch_period, 43200)


class TestSourceApi(unittest.TestCase):
    """
    Test suite for Source REST API endpoints (/api/sources).
    """

    def setUp(self):
        self.app = create_app(
            {
                "TESTING": True,
                "DATABASE_PATH": ":memory:",
                "SECRET_KEY": "test-key-sources-api",
            }
        )
        self.client = self.app.test_client()
        self.session = get_session()
        self.repo = SourceRepository(self.session)

        self.s1 = self.repo.add_source(
            url="https://example.com/feed1",
            title="Source One",
            enabled=True,
        )
        self.s2 = self.repo.add_source(
            url="https://example.com/feed2",
            title="Source Two",
            enabled=False,
        )

    def tearDown(self):
        close_session()
        from yafr.services import SourceService

        SourceService._refresh_state["is_running"] = False

    def test_enable_disable_source(self):
        """POST /api/sources/<id>/disable and /enable toggles state."""
        # Disable s1
        res_dis = self.client.post(f"/api/sources/{self.s1.id}/disable")
        self.assertEqual(res_dis.status_code, 200)
        data = res_dis.get_json()
        self.assertTrue(data["success"])
        self.assertFalse(data["enabled"])

        s1_after_disable = SourceRepository(get_session()).get_by_id(self.s1.id)
        self.assertFalse(s1_after_disable.enabled)

        # Enable s1
        res_en = self.client.post(f"/api/sources/{self.s1.id}/enable")
        self.assertEqual(res_en.status_code, 200)
        data = res_en.get_json()
        self.assertTrue(data["success"])
        self.assertTrue(data["enabled"])

        s1_after_enable = SourceRepository(get_session()).get_by_id(self.s1.id)
        self.assertTrue(s1_after_enable.enabled)

    def test_delete_source(self):
        """DELETE /api/sources/<id> removes source and operational data."""
        source_id = self.s1.id
        res = self.client.delete(f"/api/sources/{source_id}")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["deleted_source_id"], source_id)

        # Verify removed from DB
        self.assertIsNone(self.repo.get_by_id(source_id))

    def test_batch_delete_sources(self):
        """POST /api/sources/batch-delete removes multiple sources."""
        s3 = self.repo.add_source(url="https://example.com/feed3", title="Source Three")
        ids = [self.s1.id, self.s2.id, s3.id]

        res = self.client.post(
            "/api/sources/batch-delete",
            json={"source_ids": ids},
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["deleted_count"], 3)

        for sid in ids:
            self.assertIsNone(self.repo.get_by_id(sid))

    def test_refresh_status(self):
        """GET /api/sources/refresh-status returns progress snapshot."""
        res = self.client.get("/api/sources/refresh-status")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("is_running", data)
        self.assertIn("percentage", data)
        self.assertIn("completed_sources", data)
        self.assertIn("total_sources", data)

    @patch("yafr.services.source_service.SourceService.fetch_source")
    def test_fetch_all_endpoint(self, mock_fetch):
        """POST /api/sources/fetch-all triggers batch refresh."""
        mock_fetch.return_value = {"success": True, "entries_added": 0}
        res = self.client.post(
            "/api/sources/fetch-all",
            json={"include_errors": True},
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertIn("queued_sources_count", data)
        # Give worker a moment to process the mocked fetches
        time.sleep(0.2)

    def test_fetch_source_endpoint_clears_hashes_and_enqueues_job(self):
        """POST /api/sources/<id>/fetch clears hashes and enqueues process-source job."""
        source_id = self.s1.id
        # Pre-set hashes
        self.repo.update_operational_data(
            source_id,
            page_hash=b"pre-existing-page-hash",
            body_hash=b"pre-existing-body-hash",
        )
        op_data = self.repo.get_operational_data(source_id)
        self.assertIsNotNone(op_data.page_hash)
        self.assertIsNotNone(op_data.body_hash)

        res = self.client.post(f"/api/sources/{source_id}/fetch")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["status"], "queued")
        self.assertIn("job_id", data)

        # Verify operational hashes were cleared
        op_data_after = self.repo.get_operational_data(source_id)
        self.assertIsNone(op_data_after.page_hash)
        self.assertIsNone(op_data_after.body_hash)

    def test_convert_source_rss_to_parse(self):
        """POST /api/sources/<id>/convert converts RSS source to PARSE."""
        self.assertEqual(self.s1.source_type.upper(), "RSS")
        res = self.client.post(
            f"/api/sources/{self.s1.id}/convert",
            json={"target_type": "PARSE"},
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["source_type"], "PARSE")

        self.session.expire_all()
        updated = self.repo.get_by_id(self.s1.id)
        self.assertEqual(updated.source_type, "PARSE")

    def test_convert_source_parse_to_rss(self):
        """POST /api/sources/<id>/convert converts PARSE source to RSS."""
        parse_src = self.repo.add_source(
            url="https://example.com/parse-feed",
            title="Parse Source",
            source_type="PARSE",
        )
        res = self.client.post(
            f"/api/sources/{parse_src.id}/convert",
            json={"target_type": "RSS"},
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["source_type"], "RSS")

        self.session.expire_all()
        updated = self.repo.get_by_id(parse_src.id)
        self.assertEqual(updated.source_type, "RSS")

    def test_convert_source_unfilled_to_rss_and_parse(self):
        """POST /api/sources/<id>/convert converts unfilled/empty source to RSS or PARSE."""
        unfilled_src1 = self.repo.add_source(
            url="https://example.com/unfilled1",
            title="Unfilled Source 1",
            source_type="",
        )
        res1 = self.client.post(
            f"/api/sources/{unfilled_src1.id}/convert",
            json={"target_type": "PARSE"},
        )
        self.assertEqual(res1.status_code, 200)
        self.session.expire_all()
        updated1 = self.repo.get_by_id(unfilled_src1.id)
        self.assertEqual(updated1.source_type, "PARSE")

        unfilled_src2 = self.repo.add_source(
            url="https://example.com/unfilled2",
            title="Unfilled Source 2",
            source_type=None,
        )
        res2 = self.client.post(
            f"/api/sources/{unfilled_src2.id}/convert",
            json={"target_type": "RSS"},
        )
        self.assertEqual(res2.status_code, 200)
        self.session.expire_all()
        updated2 = self.repo.get_by_id(unfilled_src2.id)
        self.assertEqual(updated2.source_type, "RSS")

    def test_convert_source_email_rejected(self):
        """POST /api/sources/<id>/convert rejects conversion for EMAIL sources."""
        email_src = self.repo.add_source(
            url="imaps://imap.mail.com",
            title="Email Source",
            source_type="EMAIL",
        )
        res = self.client.post(
            f"/api/sources/{email_src.id}/convert",
            json={"target_type": "PARSE"},
        )
        self.assertEqual(res.status_code, 400)
        data = res.get_json()
        self.assertFalse(data["success"])
        self.assertIn("Email sources cannot be converted", data["error"])

    def test_convert_source_invalid_or_same_type(self):
        """POST /api/sources/<id>/convert rejects same type or invalid targets."""
        # Same type
        res_same = self.client.post(
            f"/api/sources/{self.s1.id}/convert",
            json={"target_type": "RSS"},
        )
        self.assertEqual(res_same.status_code, 400)
        self.assertIn("already of type RSS", res_same.get_json()["error"])

        # Invalid target (EMAIL)
        res_email = self.client.post(
            f"/api/sources/{self.s1.id}/convert",
            json={"target_type": "EMAIL"},
        )
        self.assertEqual(res_email.status_code, 400)
        self.assertIn("Allowed types: RSS, PARSE", res_email.get_json()["error"])

        # Non-existent source
        res_404 = self.client.post(
            "/api/sources/99999/convert",
            json={"target_type": "PARSE"},
        )
        self.assertEqual(res_404.status_code, 404)
