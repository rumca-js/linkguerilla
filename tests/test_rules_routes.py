"""
Unit and integration tests for EntryRules and BlockEntry web routes.
"""

import unittest
from unittest.mock import patch
from yafr.app import create_app
from yafr.db import (
    BlockEntryListRepository,
    BlockEntryRepository,
    RulesRepository,
    close_session,
    get_session,
)


class TestRulesRoutes(unittest.TestCase):
    """
    Test suite for Entry Rules views, block URL modal/routes, and rule management.
    """

    def setUp(self):
        self.app = create_app(
            {
                "TESTING": True,
                "DATABASE_PATH": ":memory:",
                "SECRET_KEY": "test-key-rules-routes",
            }
        )
        self.client = self.app.test_client()
        self.session = get_session()
        self.rules_repo = RulesRepository(self.session)
        self.block_repo = BlockEntryRepository(self.session)
        self.list_repo = BlockEntryListRepository(self.session)

    def tearDown(self):
        close_session()

    def test_rules_list_contains_add_rule_and_block_url_buttons(self):
        """GET /rules renders the page with 'Add Rule', 'Block Url', 'Blocked Urls', and 'Block Lists' buttons."""
        response = self.client.get("/rules")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Add Rule", html)
        self.assertIn("Block Url", html)
        self.assertIn("Blocked Urls", html)
        self.assertIn("Block Lists", html)
        self.assertIn("blockUrlModal", html)
        self.assertIn("/rules/blocked-urls", html)

    def test_get_blocked_urls_view_renders_entries_and_search(self):
        """GET /rules/blocked-urls renders Blocked URLs view with pagination and search."""
        self.block_repo.add_entry("test-ad-1.com")
        self.block_repo.add_entry("tracker-xyz.net")

        # View all
        res = self.client.get("/rules/blocked-urls")
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)
        self.assertIn("Blocked URLs", html)
        self.assertIn("test-ad-1.com", html)
        self.assertIn("tracker-xyz.net", html)

        # Search query
        res_search = self.client.get("/rules/blocked-urls?q=tracker")
        self.assertEqual(res_search.status_code, 200)
        html_search = res_search.get_data(as_text=True)
        self.assertIn("tracker-xyz.net", html_search)
        self.assertNotIn("test-ad-1.com", html_search)

    def test_post_batch_delete_blocked_urls(self):
        """POST /rules/blocked-urls/batch-delete deletes selected BlockEntry items."""
        e1 = self.block_repo.add_entry("badsite1.com")
        e2 = self.block_repo.add_entry("badsite2.com")
        e3 = self.block_repo.add_entry("safe-remains.com")

        res = self.client.post(
            "/rules/blocked-urls/batch-delete",
            data={"selected_ids": [str(e1.id), str(e2.id)]},
            follow_redirects=True,
        )
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)
        self.assertIn("removed 2", html.lower())
        self.assertIsNone(self.block_repo.get_entry(e1.id))
        self.assertIsNone(self.block_repo.get_entry(e2.id))
        self.assertIsNotNone(self.block_repo.get_entry(e3.id))

    def test_get_block_lists_view_renders_lists_and_status(self):
        """GET /rules/block-lists renders blockentrylists with processed and not processed badges."""
        self.list_repo.add_list("https://example.com/processed.txt", processed=True)
        self.list_repo.add_list("https://example.com/unprocessed.txt", processed=False)

        response = self.client.get("/rules/block-lists")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Block Entry Lists", html)
        self.assertIn("https://example.com/processed.txt", html)
        self.assertIn("https://example.com/unprocessed.txt", html)
        self.assertIn("Processed", html)
        self.assertIn("Not Processed", html)
        self.assertIn("selectAllCheckbox", html)
        self.assertIn("list-row-checkbox", html)

    def test_post_add_block_list(self):
        """POST /rules/block-lists/add creates a BlockEntryList."""
        response = self.client.post(
            "/rules/block-lists/add",
            data={"url": "https://easylist.to/easylist.txt", "process_now": ""},
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("https://easylist.to/easylist.txt", html)

        obj = self.list_repo.get_list_by_url("https://easylist.to/easylist.txt")
        self.assertIsNotNone(obj)
        self.assertFalse(obj.processed)

    def test_post_delete_single_block_list(self):
        """POST /rules/block-lists/<id>/delete removes a single list and its entries."""
        l = self.list_repo.add_list("https://example.com/delete-me.txt")
        self.block_repo.add_entry("bad-item.com", block_list_id=l.id)

        response = self.client.post(
            f"/rules/block-lists/{l.id}/delete",
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(self.list_repo.get_list(l.id))
        self.assertEqual(self.block_repo.count_entries(block_list_id=l.id), 0)

    def test_post_batch_delete_block_lists(self):
        """POST /rules/block-lists/batch-delete removes all selected block lists."""
        l1 = self.list_repo.add_list("https://example.com/batch1.txt")
        l2 = self.list_repo.add_list("https://example.com/batch2.txt")
        l3 = self.list_repo.add_list("https://example.com/batch3.txt")

        response = self.client.post(
            "/rules/block-lists/batch-delete",
            data={"selected_ids": [str(l1.id), str(l2.id)]},
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(self.list_repo.get_list(l1.id))
        self.assertIsNone(self.list_repo.get_list(l2.id))
        self.assertIsNotNone(self.list_repo.get_list(l3.id))

    def test_post_batch_delete_empty_selection_warns(self):
        """POST /rules/block-lists/batch-delete without selection flashes warning."""
        response = self.client.post(
            "/rules/block-lists/batch-delete",
            data={},
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("No block lists selected", html)

    def test_post_process_block_list(self):
        """POST /rules/block-lists/<id>/process splits and ingests entries."""
        l = self.list_repo.add_list("https://example.com/list.txt")

        with patch(
            "yafr.db.block_repository.fetch_and_split_block_list_url"
        ) as mock_fetch:
            mock_fetch.return_value = ["tracker1.com", "tracker2.com", "adnetwork.io"]
            response = self.client.post(
                f"/rules/block-lists/{l.id}/process",
                follow_redirects=True,
            )
            self.assertEqual(response.status_code, 200)

        updated = self.list_repo.get_list(l.id)
        self.assertTrue(updated.processed)
        self.assertEqual(self.block_repo.count_entries(block_list_id=l.id), 3)

    def test_post_block_url_creates_block_entry_and_redirects(self):
        """POST /rules/block-url creates a BlockEntry record and redirects to /rules."""
        response = self.client.post(
            "/rules/block-url",
            data={"url": "tracker.adnetwork.com"},
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("tracker.adnetwork.com", html)
        self.assertIn("added successfully", html.lower())

        # Verify in database
        entry = self.block_repo.get_entry_by_url("tracker.adnetwork.com")
        self.assertIsNotNone(entry)
        self.assertEqual(entry.url, "tracker.adnetwork.com")

    def test_post_block_url_empty_does_not_create(self):
        """POST /rules/block-url with empty URL flashes warning and creates nothing."""
        initial_count = self.block_repo.count_entries()
        response = self.client.post(
            "/rules/block-url",
            data={"url": "   "},
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.block_repo.count_entries(), initial_count)

    def test_get_block_url_standalone_page(self):
        """GET /rules/block-url renders standalone Block URL form."""
        response = self.client.get("/rules/block-url")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Block URL / Domain", html)
        self.assertIn("action", html)

    def test_post_delete_block_entry(self):
        """POST /rules/block-entry/<id>/delete removes the BlockEntry."""
        entry = self.block_repo.add_entry("malicious.site")
        self.assertIsNotNone(self.block_repo.get_entry(entry.id))

        response = self.client.post(
            f"/rules/block-entry/{entry.id}/delete",
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("removed", html.lower())
        self.assertIsNone(self.block_repo.get_entry(entry.id))

    def test_post_delete_nonexistent_block_entry(self):
        """POST /rules/block-entry/<id>/delete with non-existent ID redirects safely."""
        response = self.client.post(
            "/rules/block-entry/99999/delete",
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)


if __name__ == "__main__":
    unittest.main()
