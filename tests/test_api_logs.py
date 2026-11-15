"""
Unit tests for Application Logs API endpoints and LogsView clear options.
"""

import os
import shutil
import subprocess
import unittest
from yafr.app import create_app
from yafr.db import LoggingRepository, close_session, get_session


class TestApiLogs(unittest.TestCase):
    """
    Test suite for /api/logs endpoints including clearing by level and clear all.
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
        self.repo = LoggingRepository(self.session)

        # Seed initial log entries of different levels
        self.repo.log(info_text="Debug test 1", level=10)
        self.repo.log(info_text="Debug test 2", level=10)
        self.repo.log(info_text="Info test 1", level=20)
        self.repo.log(info_text="Info test 2", level=20)
        self.repo.log(info_text="Notification test 1", level=25)
        self.repo.log(info_text="Warning test 1", level=30)
        self.repo.log(info_text="Error test 1", level=40)
        self.repo.log(info_text="Critical test 1", level=50)

    def tearDown(self):
        close_session()

    def test_clear_logs_by_level_name(self):
        """POST /api/logs/clear with level='info' clears only INFO logs."""
        res = self.client.post("/api/logs/clear", json={"level": "info"})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["data"]["deleted_count"], 2)
        self.assertEqual(data["data"]["level"], 20)

        # Verify INFO logs are gone while other levels remain
        all_logs = self.repo.list_logs()
        self.assertEqual(len(all_logs), 6)
        info_logs = [l for l in all_logs if l.level == 20]
        self.assertEqual(len(info_logs), 0)

    def test_clear_logs_by_level_errors(self):
        """POST /api/logs/clear with level='errors' (or 'error') clears only ERROR logs."""
        res = self.client.post("/api/logs/clear", json={"level": "errors"})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["data"]["deleted_count"], 1)
        self.assertEqual(data["data"]["level"], 40)

        all_logs = self.repo.list_logs()
        self.assertEqual(len(all_logs), 7)
        error_logs = [l for l in all_logs if l.level == 40]
        self.assertEqual(len(error_logs), 0)

    def test_clear_logs_by_level_debug(self):
        """POST /api/logs/clear with level='debug' clears only DEBUG logs."""
        res = self.client.post("/api/logs/clear", json={"level": "debug"})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["data"]["deleted_count"], 2)
        self.assertEqual(data["data"]["level"], 10)

        all_logs = self.repo.list_logs()
        self.assertEqual(len(all_logs), 6)
        debug_logs = [l for l in all_logs if l.level == 10]
        self.assertEqual(len(debug_logs), 0)

    def test_clear_logs_by_integer_level(self):
        """POST /api/logs/clear with integer level (e.g. 30 for WARNING)."""
        res = self.client.post("/api/logs/clear", json={"level": 30})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["data"]["deleted_count"], 1)
        self.assertEqual(data["data"]["level"], 30)

    def test_clear_all_logs(self):
        """POST /api/logs/clear with no level or level='all' clears all logs."""
        res = self.client.post("/api/logs/clear", json={})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["data"]["deleted_count"], 8)
        self.assertIsNone(data["data"]["level"])

        self.assertEqual(self.repo.count_logs(), 0)

    def test_clear_logs_invalid_level(self):
        """POST /api/logs/clear with invalid level returns 400 error."""
        res = self.client.post("/api/logs/clear", json={"level": "nonexistent_level"})
        self.assertEqual(res.status_code, 400)
        data = res.get_json()
        self.assertFalse(data["success"])
        self.assertIn("Invalid log level", data["error"])

    def test_batch_delete_logs_success(self):
        """POST /api/logs/batch-delete deletes specified log entries."""
        all_logs = self.repo.list_logs()
        ids_to_delete = [all_logs[0].id, all_logs[1].id]

        res = self.client.post(
            "/api/logs/batch-delete",
            json={"ids": ids_to_delete},
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["data"]["deleted_count"], 2)

        # Confirm entries were removed
        remaining_ids = {l.id for l in self.repo.list_logs()}
        self.assertNotIn(ids_to_delete[0], remaining_ids)
        self.assertNotIn(ids_to_delete[1], remaining_ids)

    def test_batch_delete_logs_invalid_payload(self):
        """POST /api/logs/batch-delete with empty or invalid payload returns 400."""
        # Empty payload
        res = self.client.post("/api/logs/batch-delete", json={})
        self.assertEqual(res.status_code, 400)
        self.assertFalse(res.get_json()["success"])

        # Empty ids list
        res2 = self.client.post("/api/logs/batch-delete", json={"ids": []})
        self.assertEqual(res2.status_code, 400)
        self.assertFalse(res2.get_json()["success"])

        # Non-integer IDs
        res3 = self.client.post("/api/logs/batch-delete", json={"ids": ["abc"]})
        self.assertEqual(res3.status_code, 400)
        self.assertFalse(res3.get_json()["success"])

    def test_logs_view_html_rendering(self):
        """GET /logs renders clear controls, checkboxes, and level options."""
        res = self.client.get("/logs")
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)
        self.assertIn("Clear All", html)
        self.assertIn("data-clear-level", html)
        self.assertIn("clearLogsModal", html)
        self.assertIn("select-all-logs", html)
        self.assertIn("log-select-checkbox", html)
        self.assertIn("btn-batch-delete-logs", html)

    def test_logs_view_html_with_active_level(self):
        """GET /logs?level=error renders active level clear option."""
        res = self.client.get("/logs?level=error")
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)
        self.assertIn("Clear Error", html)
        self.assertIn("Clear All", html)

    def test_logs_js_syntax_and_select_all_handling(self):
        """Verify yafr/static/js/logs.js is valid JavaScript syntax and binds #select-all-logs."""
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        js_file = os.path.join(project_root, "yafr", "static", "js", "logs.js")
        self.assertTrue(os.path.exists(js_file), f"logs.js not found at {js_file}")

        with open(js_file, "r", encoding="utf-8") as f:
            content = f.read()

        # Check that #select-all-logs handler is present and controls .log-select-checkbox
        self.assertIn("#select-all-logs", content)
        self.assertIn(".log-select-checkbox", content)
        self.assertIn("updateBatchDeleteBar", content)

        # If node is available in the environment, run a syntax check
        node_bin = shutil.which("node")
        if node_bin:
            proc = subprocess.run(
                [node_bin, "--check", js_file],
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                proc.returncode,
                0,
                f"Syntax error in logs.js:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}",
            )


if __name__ == "__main__":
    unittest.main()
