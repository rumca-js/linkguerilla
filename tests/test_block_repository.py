"""
Unit tests for BlockEntry, BlockEntryList, and BlockRepository.

Tests reading, parsing, splitting plain text block lists (EasyList, hosts, plain lists),
and performing CRUD and bulk operations in the database layer.

Can be run with:
    poetry run python -m unittest tests/test_block_repository.py
"""

from io import StringIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from linkarchivetools.model.definitions import BlockEntry, BlockEntryList
from yafr.db import (
    BlockEntryListRepository,
    BlockEntryRepository,
    BlockRepository,
    close_session,
    fetch_and_split_block_list_url,
    get_session,
    init_db,
    read_and_split_block_list_file,
    split_block_list_text,
)


class TestBlockRepository(unittest.TestCase):
    """
    Test suite for BlockEntry, BlockEntryList repositories and text parser utilities.
    """

    def setUp(self):
        """Initializes an in-memory SQLite database for each test."""
        self.engine = init_db(db_path=":memory:", sync_schema=True)
        self.session = get_session()
        self.repo = BlockRepository(self.session)
        self.list_repo = BlockEntryListRepository(self.session)
        self.entry_repo = BlockEntryRepository(self.session)

    def tearDown(self):
        """Cleans up scoped session after each test."""
        close_session()

    def test_split_block_list_text_comments_and_formatting(self):
        """Tests that split_block_list_text handles comments, headers, and empty lines."""
        sample_text = """
        [Adblock Plus 2.0]
        ! Title: EasyList
        ! Version: 20261026
        # Comment line in hosts style

        ||doubleclick.net^
        &ad_channel=
        |https://malicious.org/payload.exe*
        evil-tracker.com
        """
        entries = split_block_list_text(sample_text)
        self.assertEqual(
            entries,
            [
                "||doubleclick.net^",
                "&ad_channel=",
                "|https://malicious.org/payload.exe*",
                "evil-tracker.com",
            ],
        )

    def test_split_block_list_text_hosts_file_format(self):
        """Tests that hosts file syntax (0.0.0.0 / 127.0.0.1 / ::1) is correctly parsed."""
        hosts_text = """
        # Standard hosts format
        127.0.0.1 localhost
        ::1 localhost
        0.0.0.0 ads.adnetwork.com tracker.telemetry.io # comment
        127.0.0.1 badware.biz
        """
        entries = split_block_list_text(hosts_text)
        self.assertIn("ads.adnetwork.com", entries)
        self.assertIn("tracker.telemetry.io", entries)
        self.assertIn("badware.biz", entries)
        self.assertNotIn("localhost", entries)

    def test_split_block_list_text_deduplication_and_order(self):
        """Tests that duplicate items in the text are deduplicated preserving order."""
        raw = "first.com\nsecond.com\nfirst.com\nthird.com\nsecond.com\n"
        entries = split_block_list_text(raw)
        self.assertEqual(entries, ["first.com", "second.com", "third.com"])

    def test_read_and_split_block_list_file_from_stringio_and_disk(self):
        """Tests reading block lists from both a file-like object and a disk file."""
        content = "||banner.com^\n0.0.0.0 tracker.com\n"
        # Test StringIO
        sio = StringIO(content)
        entries = read_and_split_block_list_file(sio)
        self.assertEqual(entries, ["||banner.com^", "tracker.com"])

        # Test temporary disk file
        with tempfile.NamedTemporaryFile("w+", encoding="utf-8", delete=False) as tf:
            tf.write(content)
            temp_path = tf.name

        try:
            disk_entries = read_and_split_block_list_file(temp_path)
            self.assertEqual(disk_entries, ["||banner.com^", "tracker.com"])
        finally:
            Path(temp_path).unlink(missing_ok=True)

    @patch("yafr.db.block_repository.fetch_and_split_block_list_url")
    def test_fetch_and_split_block_list_url_mocked(self, mock_fetch):
        """Tests network block list fetching delegation."""
        mock_fetch.return_value = ["blocked1.com", "blocked2.com"]
        res = self.repo.fetch_url("https://example.com/easylist.txt")
        self.assertEqual(res, ["blocked1.com", "blocked2.com"])
        mock_fetch.assert_called_once_with(
            "https://example.com/easylist.txt", timeout=15
        )

    def test_block_entry_list_crud(self):
        """Tests CRUD operations on BlockEntryList."""
        # Add list
        bl1 = self.list_repo.add_list("https://easylist.to/easylist.txt")
        self.assertIsNotNone(bl1.id)
        self.assertEqual(bl1.url, "https://easylist.to/easylist.txt")
        self.assertFalse(bl1.processed)

        # Retrieve list
        retrieved = self.list_repo.get_list(bl1.id)
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.url, bl1.url)

        # Retrieve by URL
        by_url = self.list_repo.get_list_by_url("https://easylist.to/easylist.txt")
        self.assertIsNotNone(by_url)
        self.assertEqual(by_url.id, bl1.id)

        # Mark processed
        updated = self.list_repo.mark_processed(bl1.id, processed=True)
        self.assertTrue(updated.processed)

        # List lists with filter
        bl2 = self.list_repo.add_list("https://hosts.site/hosts.txt", processed=False)
        all_lists = self.list_repo.list_lists()
        self.assertEqual(len(all_lists), 2)

        processed_lists = self.list_repo.list_lists(processed=True)
        self.assertEqual(len(processed_lists), 1)
        self.assertEqual(processed_lists[0].id, bl1.id)

        unprocessed_lists = self.list_repo.list_lists(processed=False)
        self.assertEqual(len(unprocessed_lists), 1)
        self.assertEqual(unprocessed_lists[0].id, bl2.id)

        # Count
        self.assertEqual(self.list_repo.count_lists(), 2)
        self.assertEqual(self.list_repo.count_lists(processed=True), 1)

        # Delete single list
        self.assertTrue(self.list_repo.delete_list(bl2.id))
        self.assertIsNone(self.list_repo.get_list(bl2.id))
        self.assertEqual(self.list_repo.count_lists(), 1)

        # Batch delete lists
        bl3 = self.list_repo.add_list("https://example.com/3.txt")
        bl4 = self.list_repo.add_list("https://example.com/4.txt")
        deleted_count = self.list_repo.delete_lists([bl1.id, bl3.id, bl4.id])
        self.assertEqual(deleted_count, 3)
        self.assertEqual(self.list_repo.count_lists(), 0)

    def test_block_entry_crud_and_bulk_operations(self):
        """Tests CRUD, search, and bulk operations on BlockEntry."""
        bl = self.list_repo.add_list("https://example.com/block.txt")

        # Add single entry
        e1 = self.entry_repo.add_entry("https://ads.com/ad.js", block_list_id=bl.id)
        self.assertIsNotNone(e1.id)
        self.assertEqual(e1.url, "https://ads.com/ad.js")
        self.assertEqual(e1.block_list_id, bl.id)

        # is_blocked
        self.assertTrue(self.entry_repo.is_blocked("https://ads.com/ad.js"))
        self.assertFalse(self.entry_repo.is_blocked("https://clean.org"))

        # Bulk add entries (including duplicate of e1 and duplicate within batch)
        urls_to_add = [
            "https://ads.com/ad.js",  # already in db
            "banner.ads.net",
            "telemetry.net",
            "banner.ads.net",  # duplicate in batch
            "malware.site/download",
        ]
        inserted = self.entry_repo.add_entries(urls_to_add, block_list_id=bl.id)
        # Should insert exactly 3 new entries
        self.assertEqual(inserted, 3)

        # Total count
        self.assertEqual(self.entry_repo.count_entries(), 4)
        self.assertEqual(self.entry_repo.count_entries(block_list_id=bl.id), 4)

        # Search entries
        search_res = self.entry_repo.list_entries(search="ads")
        self.assertEqual(len(search_res), 2)

        # Delete by ID
        self.assertTrue(self.entry_repo.delete_entry(e1.id))
        self.assertFalse(self.entry_repo.is_blocked("https://ads.com/ad.js"))
        self.assertEqual(self.entry_repo.count_entries(), 3)

        # Delete by list ID
        deleted_count = self.entry_repo.delete_by_list_id(bl.id)
        self.assertEqual(deleted_count, 3)
        self.assertEqual(self.entry_repo.count_entries(), 0)

    def test_delete_list_cascades_entries(self):
        """Tests that deleting a BlockEntryList with delete_entries=True deletes child entries."""
        bl = self.list_repo.add_list("https://example.com/list.txt")
        self.entry_repo.add_entries(["bad1.com", "bad2.com"], block_list_id=bl.id)
        self.assertEqual(self.entry_repo.count_entries(block_list_id=bl.id), 2)

        # Delete list with delete_entries=True (default)
        self.list_repo.delete_list(bl.id, delete_entries=True)
        self.assertIsNone(self.list_repo.get_list(bl.id))
        self.assertEqual(self.entry_repo.count_entries(), 0)

    def test_unified_process_block_list(self):
        """Tests BlockRepository.process_block_list with provided content."""
        bl = self.repo.add_list("https://easylist.to/easylist.txt")
        self.assertFalse(bl.processed)

        content = """
        [Adblock Plus 2.0]
        ! EasyList sample
        0.0.0.0 tracking.example.com
        ||badad.com^
        http://malicious.org/exploit
        """

        inserted = self.repo.process_block_list(bl.id, content=content)
        self.assertEqual(inserted, 3)

        # List should now be marked processed
        updated_list = self.repo.get_list(bl.id)
        self.assertTrue(updated_list.processed)

        # Entries should exist in DB linked to bl.id
        entries = self.repo.list_entries(block_list_id=bl.id)
        self.assertEqual(len(entries), 3)
        urls = {e.url for e in entries}
        self.assertIn("tracking.example.com", urls)
        self.assertIn("||badad.com^", urls)
        self.assertIn("http://malicious.org/exploit", urls)

    def test_process_block_list_nonexistent_raises_value_error(self):
        """Tests that process_block_list raises ValueError for unknown ID."""
        with self.assertRaises(ValueError):
            self.repo.process_block_list(9999, content="bad.com")

    def test_get_matching_entry_and_is_blocked_substring(self):
        """Tests that get_matching_entry and is_blocked match substrings, domains, and paths."""
        self.entry_repo.add_entry("tracker.io")
        self.entry_repo.add_entry("ad_channel=")

        # Substring match in full URL
        matched = self.entry_repo.get_matching_entry(
            "https://subdomain.tracker.io/analytics.js"
        )
        self.assertIsNotNone(matched)
        self.assertEqual(matched.url, "tracker.io")

        # Query param match
        matched_param = self.entry_repo.get_matching_entry(
            "https://example.com/page?ad_channel=top"
        )
        self.assertIsNotNone(matched_param)
        self.assertEqual(matched_param.url, "ad_channel=")

        # is_blocked
        self.assertTrue(self.entry_repo.is_blocked("https://tracker.io/test"))
        self.assertTrue(self.repo.is_blocked("https://tracker.io/test"))
        self.assertFalse(self.entry_repo.is_blocked("https://safe-domain.org/index"))


if __name__ == "__main__":
    unittest.main()
