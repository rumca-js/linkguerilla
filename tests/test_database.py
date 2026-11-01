"""
Unit and integration tests for DatabaseView and /api/database REST endpoints.
"""

import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from linkarchivetools.model.definitions import (
    ConfigurationEntry,
    EntryVisitHistory,
    LinkDataModel,
    ReadLater,
    SearchHistory,
    SocialData,
)
from yafr.app import create_app
from yafr.db import (
    ConfigRepository,
    EntryRepository,
    HistoryRepository,
    close_session,
    get_session,
    init_db,
)
from yafr.services import DatabaseService


class TestDatabaseService(unittest.TestCase):
    """
    Test suite for DatabaseService logic.
    """

    def setUp(self):
        self.app = create_app(
            {
                "TESTING": True,
                "DATABASE_PATH": ":memory:",
                "SECRET_KEY": "test-key-db-service",
            }
        )
        self.session = get_session()

        # Seed data in various tables
        self.history_repo = HistoryRepository(self.session)
        self.history_repo.add_search("test search 1")
        self.history_repo.add_search("test search 2")

        self.entry_repo = EntryRepository(self.session)
        entry = self.entry_repo.add_entry(
            link="https://example.com/test", title="Test Entry"
        )
        self.entry_id = entry.id
        self.history_repo.record_visit(self.entry_id)
        self.history_repo.toggle_read_later(self.entry_id)

        self.session.add(SocialData(entry_id=self.entry_id, view_count=42))
        self.session.commit()

    def tearDown(self):
        close_session()

    def test_get_database_info(self):
        """Verifies database info dictionary structure and row counts."""
        info = DatabaseService.get_database_info(session=self.session)
        self.assertIn("database_name", info)
        self.assertIn("database_type", info)
        self.assertIn("database_file", info)
        self.assertIn("file_size_formatted", info)
        self.assertIn("tables", info)
        self.assertIn("tables_detailed", info)

        tables = info["tables"]
        self.assertEqual(tables.get("searchhistory"), 2)
        self.assertEqual(tables.get("entryvisithistory"), 1)
        self.assertEqual(tables.get("readlater"), 1)
        self.assertEqual(tables.get("socialdata"), 1)
        self.assertEqual(tables.get("linkdatamodel"), 1)

    def test_update_database_name(self):
        """Verifies changing instance display title."""
        updated = DatabaseService.update_database_name(
            "My Custom Feed Archive", session=self.session
        )
        self.assertEqual(updated, "My Custom Feed Archive")

        info = DatabaseService.get_database_info(session=self.session)
        self.assertEqual(info["database_name"], "My Custom Feed Archive")

        # Empty name raises ValueError
        with self.assertRaises(ValueError):
            DatabaseService.update_database_name("   ", session=self.session)

    def test_clear_search_history(self):
        """Verifies clearing user search queries."""
        deleted = DatabaseService.clear_search_history(session=self.session)
        self.assertEqual(deleted, 2)
        info = DatabaseService.get_database_info(session=self.session)
        self.assertEqual(info["tables"]["searchhistory"], 0)

    def test_clear_visited_entries(self):
        """Verifies clearing user visit records."""
        deleted = DatabaseService.clear_visited_entries(session=self.session)
        self.assertEqual(deleted, 1)
        info = DatabaseService.get_database_info(session=self.session)
        self.assertEqual(info["tables"]["entryvisithistory"], 0)

    def test_clear_read_later(self):
        """Verifies clearing read later queue."""
        deleted = DatabaseService.clear_read_later(session=self.session)
        self.assertEqual(deleted, 1)
        info = DatabaseService.get_database_info(session=self.session)
        self.assertEqual(info["tables"]["readlater"], 0)

    def test_clear_social_data(self):
        """Verifies clearing cached social metrics."""
        deleted = DatabaseService.clear_social_data(session=self.session)
        self.assertEqual(deleted, 1)
        info = DatabaseService.get_database_info(session=self.session)
        self.assertEqual(info["tables"]["socialdata"], 0)

    def test_clear_sources(self):
        """Verifies clearing sources and operational data."""
        deleted_counts = DatabaseService.clear_sources(session=self.session)
        self.assertIsInstance(deleted_counts, dict)
        info = DatabaseService.get_database_info(session=self.session)
        self.assertEqual(info["tables"]["sourcedatamodel"], 0)

    def test_clear_links(self):
        """Verifies clearing link entries and all dependent tables."""
        info_before = DatabaseService.get_database_info(session=self.session)
        self.assertGreaterEqual(info_before["tables"]["linkdatamodel"], 1)

        deleted_counts = DatabaseService.clear_links(session=self.session)
        self.assertIsInstance(deleted_counts, dict)
        self.assertIn("linkdatamodel", deleted_counts)
        self.assertGreaterEqual(deleted_counts["linkdatamodel"], 1)

        info_after = DatabaseService.get_database_info(session=self.session)
        self.assertEqual(info_after["tables"]["linkdatamodel"], 0)
        self.assertEqual(info_after["tables"]["socialdata"], 0)
        self.assertEqual(info_after["tables"]["readlater"], 0)
        self.assertEqual(info_after["tables"]["entryvisithistory"], 0)

    def test_replace_database_validation(self):
        """Verifies URL scheme validation and error handling."""
        with self.assertRaises(ValueError):
            DatabaseService.replace_database_from_url("ftp://example.com/db.sqlite")

        with self.assertRaises(ValueError):
            DatabaseService.replace_database_from_url("not-a-url")


class TestDatabaseWebRoutes(unittest.TestCase):
    """
    Test suite for DatabaseView HTML page and REST API endpoints.
    """

    def setUp(self):
        # Create a real temporary database file for route testing
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_db_path = str(Path(self.temp_dir.name) / "test_table.db")

        self.app = create_app(
            {
                "TESTING": True,
                "DATABASE_PATH": self.temp_db_path,
                "SECRET_KEY": "test-key-db-routes",
            }
        )
        self.client = self.app.test_client()
        self.session = get_session()

        # Seed data
        repo = HistoryRepository(self.session)
        repo.add_search("sample search")

    def tearDown(self):
        close_session()
        self.temp_dir.cleanup()

    def test_database_view_html(self):
        """GET /database renders database view with metrics and action buttons."""
        res = self.client.get("/database")
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)
        self.assertIn("Database Information", html)
        self.assertIn("Refresh", html)
        self.assertIn("Edit Name", html)
        self.assertIn("Replace Database", html)
        self.assertIn("linkdatamodel", html)
        self.assertIn("Clear Search History", html)
        self.assertIn("/api/database/clear-sources", html)
        self.assertIn("/api/database/clear-links", html)

    def test_api_database_stats(self):
        """GET /api/database/stats returns JSON metrics and table counts."""
        res = self.client.get("/api/database/stats")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertIn("tables", data)
        self.assertIn("searchhistory", data["tables"])
        self.assertEqual(data["tables"]["searchhistory"], 1)

    def test_api_update_name(self):
        """POST /api/database/update-name modifies the display name."""
        res = self.client.post(
            "/api/database/update-name",
            json={"instance_title": "Renamed Archive"},
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["instance_title"], "Renamed Archive")

        # Empty name returns 400
        res2 = self.client.post(
            "/api/database/update-name",
            json={"instance_title": "  "},
        )
        self.assertEqual(res2.status_code, 400)

    def test_api_clear_tables(self):
        """POST /api/database/clear-* endpoints clear corresponding tables."""
        # Clear search history
        res1 = self.client.post("/api/database/clear-search-history")
        self.assertEqual(res1.status_code, 200)
        self.assertTrue(res1.get_json()["success"])

        # Clear visited
        res2 = self.client.post("/api/database/clear-visited")
        self.assertEqual(res2.status_code, 200)
        self.assertTrue(res2.get_json()["success"])

        # Clear read later
        res3 = self.client.post("/api/database/clear-read-later")
        self.assertEqual(res3.status_code, 200)
        self.assertTrue(res3.get_json()["success"])

        # Clear social data
        res4 = self.client.post("/api/database/clear-social-data")
        self.assertEqual(res4.status_code, 200)
        self.assertTrue(res4.get_json()["success"])

        # Clear sources
        res5 = self.client.post("/api/database/clear-sources")
        self.assertEqual(res5.status_code, 200)
        self.assertTrue(res5.get_json()["success"])
        self.assertIn("deleted_counts", res5.get_json())

        # Clear links
        res6 = self.client.post("/api/database/clear-links")
        self.assertEqual(res6.status_code, 200)
        self.assertTrue(res6.get_json()["success"])
        self.assertIn("deleted_counts", res6.get_json())

    def test_api_replace_from_url_invalid(self):
        """POST /api/database/replace-from-url returns 400 for empty or invalid URL."""
        res = self.client.post(
            "/api/database/replace-from-url",
            json={"remote_url": ""},
        )
        self.assertEqual(res.status_code, 400)

        res2 = self.client.post(
            "/api/database/replace-from-url",
            json={"remote_url": "ftp://bad-scheme.com/db.db"},
        )
        self.assertEqual(res2.status_code, 400)

    @patch("urllib.request.urlopen")
    def test_api_replace_from_url_success(self, mock_urlopen):
        """POST /api/database/replace-from-url downloads and replaces active file."""
        # Create a valid SQLite file bytes
        temp_remote_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        try:
            con = sqlite3.connect(temp_remote_db.name)
            con.execute("CREATE TABLE test_sample (id INTEGER PRIMARY KEY, name TEXT);")
            con.execute("INSERT INTO test_sample VALUES (1, 'hello');")
            con.commit()
            con.close()

            with open(temp_remote_db.name, "rb") as f:
                valid_db_bytes = f.read()
        finally:
            os.unlink(temp_remote_db.name)

        # Mock urlopen to return valid_db_bytes
        mock_response = MagicMock()
        mock_response.read.side_effect = [valid_db_bytes, b""]
        mock_response.__enter__.return_value = mock_response
        mock_urlopen.return_value = mock_response

        res = self.client.post(
            "/api/database/replace-from-url",
            json={"remote_url": "https://example.com/backup.db"},
        )
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()["success"])


if __name__ == "__main__":
    unittest.main()
