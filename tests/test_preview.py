"""
Unit and integration tests for UrlPreview and PreviewService.
"""

import unittest
from unittest.mock import MagicMock, patch
from yafr.app import create_app
from yafr.db import (
    BlockEntryRepository,
    RulesRepository,
    close_session,
    get_session,
)
from yafr.services.preview_service import PreviewService


class TestPreviewService(unittest.TestCase):
    """
    Test suite for PreviewService metadata extraction and rule checks.
    """

    def setUp(self):
        self.app = create_app(
            {
                "TESTING": True,
                "DATABASE_PATH": ":memory:",
                "SECRET_KEY": "test-preview-key",
            }
        )
        self.client = self.app.test_client()
        self.session = get_session()
        self.rules_repo = RulesRepository(self.session)
        self.block_repo = BlockEntryRepository(self.session)

    def tearDown(self):
        close_session()

    def test_preview_empty_url(self):
        """Empty URL returns success: False."""
        res = PreviewService.inspect_url("", session=self.session)
        self.assertFalse(res["success"])
        self.assertIn("empty", res["error"].lower())

    @patch("yafr.services.preview_service.WebToolsWrapper")
    def test_preview_extracts_metadata_from_webtools(self, mock_wrapper_cls):
        """Verifies metadata (title, entries, description, author, etc.) obtained dynamically via WebToolsWrapper."""
        mock_wrapper = MagicMock()
        mock_wrapper.get_title.return_value = "Sample Feed Title"
        mock_wrapper.get_description.return_value = "An informative feed description"
        mock_wrapper.get_author.return_value = "Jane Doe"
        mock_wrapper.get_language.return_value = "en"
        mock_wrapper.get_thumbnail.return_value = "https://example.com/thumb.png"
        mock_wrapper.get_album.return_value = None
        mock_wrapper.get_status_code.return_value = 200
        mock_wrapper.is_valid.return_value = True
        mock_wrapper.get_canonical_url.return_value = "https://example.com/feed"
        mock_wrapper.get_entries.return_value = [
            {
                "title": "Article 1",
                "link": "https://example.com/article-1",
                "date": "2026-11-15T10:00:00Z",
                "description": "Article 1 snippet",
            },
            {
                "title": "Article 2",
                "link": "https://example.com/article-2",
                "date": "2026-11-15T11:00:00Z",
                "description": "Article 2 snippet",
            },
        ]
        mock_wrapper.get_content_links.return_value = [
            "https://example.com/ref1",
            "https://example.com/ref2",
        ]
        mock_wrapper.get_social_properties.return_value = {"likes": 42}
        mock_wrapper_cls.return_value = mock_wrapper

        data = PreviewService.inspect_url("https://example.com/feed", session=self.session)

        self.assertTrue(data["success"])
        self.assertEqual(data["title"], "Sample Feed Title")
        self.assertEqual(data["description"], "An informative feed description")
        self.assertEqual(data["author"], "Jane Doe")
        self.assertEqual(data["language"], "en")
        self.assertEqual(data["thumbnail"], "https://example.com/thumb.png")
        self.assertEqual(data["status_code"], 200)
        self.assertEqual(len(data["entries"]), 2)
        self.assertEqual(data["entries"][0]["title"], "Article 1")
        self.assertEqual(len(data["content_links"]), 2)
        self.assertFalse(data["is_blocked"])

    def test_preview_youtube_embed_detection(self):
        """YouTube URLs are detected as video media_type with proper embed_url."""
        with patch("yafr.services.preview_service.WebToolsWrapper") as mock_wrapper_cls:
            mock_wrapper = MagicMock()
            mock_wrapper.get_title.return_value = "Never Gonna Give You Up"
            mock_wrapper.get_thumbnail.return_value = None
            mock_wrapper.get_entries.return_value = []
            mock_wrapper.get_content_links.return_value = []
            mock_wrapper_cls.return_value = mock_wrapper

            data = PreviewService.inspect_url(
                "https://www.youtube.com/watch?v=dQw4w9WgXcQ", session=self.session
            )
            self.assertTrue(data["success"])
            self.assertEqual(data["media_type"], "video")
            self.assertIn("embed/dQw4w9WgXcQ", data["embed_url"])
            self.assertIn("hqdefault.jpg", data["thumbnail"])

    def test_preview_identifies_blocking_rule(self):
        """URL matching blocking rule is reported with is_blocked=True and blocking_rule."""
        rule = self.rules_repo.add_rule(
            rule_name="Block Phishing",
            trigger_rule_url=r".*phishing-site\.org.*",
            enabled=True,
            block=True,
        )

        with patch("yafr.services.preview_service.WebToolsWrapper") as mock_wrapper_cls:
            mock_wrapper = MagicMock()
            mock_wrapper.get_title.return_value = "Phishing Login"
            mock_wrapper.get_entries.return_value = []
            mock_wrapper.get_content_links.return_value = []
            mock_wrapper_cls.return_value = mock_wrapper

            data = PreviewService.inspect_url(
                "https://phishing-site.org/account", session=self.session
            )
            self.assertTrue(data["success"])
            self.assertTrue(data["is_blocked"])
            self.assertTrue(data["is_blocked_by_rule"])
            self.assertEqual(data["blocking_rule"], "Block Phishing")

    def test_preview_identifies_block_entry(self):
        """URL matching block entry is reported with is_blocked=True and blocking_block_entry."""
        b = self.block_repo.add_entry("malicious-ad.com")

        with patch("yafr.services.preview_service.WebToolsWrapper") as mock_wrapper_cls:
            mock_wrapper = MagicMock()
            mock_wrapper.get_title.return_value = "Malicious Ad"
            mock_wrapper.get_entries.return_value = []
            mock_wrapper.get_content_links.return_value = []
            mock_wrapper_cls.return_value = mock_wrapper

            data = PreviewService.inspect_url(
                "https://cdn.malicious-ad.com/banner.js", session=self.session
            )
            self.assertTrue(data["success"])
            self.assertTrue(data["is_blocked"])
            self.assertTrue(data["is_blocked_by_block_entry"])
            self.assertEqual(data["blocking_block_entry"], "malicious-ad.com")

    def test_route_get_preview_screen_empty(self):
        """GET /preview without URL renders the preview form with search input."""
        res = self.client.get("/preview")
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)
        self.assertIn("URL Preview", html)
        self.assertIn("preview-url-input", html)

    @patch("yafr.services.preview_service.WebToolsWrapper")
    def test_route_get_preview_screen_with_url(self, mock_wrapper_cls):
        """GET /preview?url=... displays dynamically extracted metadata."""
        mock_wrapper = MagicMock()
        mock_wrapper.get_title.return_value = "Dynamically Discovered Title"
        mock_wrapper.get_description.return_value = "Dynamic preview description content"
        mock_wrapper.get_entries.return_value = [
            {"title": "Child Feed Item", "link": "https://example.com/child-1"}
        ]
        mock_wrapper.get_content_links.return_value = []
        mock_wrapper_cls.return_value = mock_wrapper

        res = self.client.get("/preview?url=https://example.com/news")
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)
        self.assertIn("Dynamically Discovered Title", html)
        self.assertIn("Dynamic preview description content", html)
        self.assertIn("Child Feed Item", html)

    @patch("yafr.services.preview_service.WebToolsWrapper")
    def test_api_preview_inspect(self, mock_wrapper_cls):
        """POST /api/preview/inspect returns full dynamic preview JSON."""
        mock_wrapper = MagicMock()
        mock_wrapper.get_title.return_value = "API Inspect Title"
        mock_wrapper.get_description.return_value = "API inspect summary"
        mock_wrapper.get_status_code.return_value = 200
        mock_wrapper.get_entries.return_value = []
        mock_wrapper.get_content_links.return_value = ["https://example.com/item"]
        mock_wrapper_cls.return_value = mock_wrapper

        res = self.client.post(
            "/api/preview/inspect",
            json={"url": "https://example.com/page"},
        )
        self.assertEqual(res.status_code, 200)
        json_data = res.get_json()
        self.assertTrue(json_data["success"])
        self.assertEqual(json_data["title"], "API Inspect Title")
        self.assertEqual(len(json_data["content_links"]), 1)
