"""Tests for search history API operations."""

import unittest

from yafr.app import create_app
from yafr.db import HistoryRepository, close_session, get_session


class TestSearchHistoryApi(unittest.TestCase):
    def setUp(self):
        self.app = create_app(
            {"TESTING": True, "DATABASE_PATH": ":memory:", "SECRET_KEY": "test-history"}
        )
        self.client = self.app.test_client()
        self.session = get_session()
        self.repo = HistoryRepository(self.session)
        self.repo.add_search("python")
        self.repo.add_search("flask")
        self.repo.add_search("python")

    def tearDown(self):
        close_session()

    def test_delete_search_removes_all_exact_occurrences(self):
        response = self.client.delete("/api/history/search", json={"query": "python"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["data"]["deleted_count"], 2)
        self.assertEqual(self.repo.get_recent_searches(), ["flask"])

    def test_list_search_history_returns_all_retained_distinct_queries(self):
        response = self.client.get("/api/history")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["data"]["suggestions"], ["python", "flask"])

    def test_delete_search_requires_query(self):
        response = self.client.delete("/api/history/search", json={"query": "  "})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(len(self.repo.get_recent_searches(limit=10)), 2)

    def test_clear_search_history(self):
        response = self.client.delete("/api/history")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["data"]["deleted_count"], 3)
        self.assertEqual(self.repo.get_recent_searches(limit=10), [])


if __name__ == "__main__":
    unittest.main()
