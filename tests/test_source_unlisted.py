"""
Unit tests for remove_unlisted_entries in ConfigRepository and Source processing.
"""

from datetime import datetime, timezone
import unittest
from unittest.mock import patch
from sqlalchemy import select
from webtoolkit import BaseUrl
from webtoolkit.response import PageResponseObject

from linkarchivetools.model.definitions import (
    BackgroundJob,
    ConfigurationEntry,
    LinkDataModel,
    SourceOperationalData,
    SourcesTable,
)
from yafr.app import create_app
from yafr.db import (
    ConfigRepository,
    EntryRepository,
    SourceRepository,
    close_session,
    get_session,
)
from yafr.services.source_service import SourceService
from yafr.workers.jobs.source_jobs import ProcessSourceJobHandler


class TestSourceRemoveUnlistedEntries(unittest.TestCase):
    """
    Test suite for remove_unlisted_entries functionality during source ingestion.
    """

    def setUp(self):
        self.app = create_app(
            {
                "TESTING": True,
                "DATABASE_PATH": ":memory:",
                "SECRET_KEY": "test-unlisted-key",
            }
        )
        self.client = self.app.test_client()
        self.session = get_session()

        self.config_repo = ConfigRepository(self.session)
        self.config = self.config_repo.get_config()
        self.source_repo = SourceRepository(self.session)
        self.entry_repo = EntryRepository(self.session)

        # Create test source
        self.source = self.source_repo.add_source(
            url="https://example.com/feed.xml",
            title="Example Feed",
            source_type="RSS",
            enabled=True,
        )
        self.session.commit()

    def tearDown(self):
        close_session()

    def test_config_repository_default_and_toggle(self):
        """ConfigRepository includes remove_unlisted_entries in defaults and supports toggling."""
        config = self.config_repo.get_config()
        self.assertTrue(hasattr(config, "remove_unlisted_entries"))
        self.assertTrue(config.remove_unlisted_entries)

        # Toggle to False
        self.config_repo.update_config(remove_unlisted_entries=False)
        self.assertFalse(self.config_repo.get_config().remove_unlisted_entries)

        # Toggle to True
        self.config_repo.update_config(remove_unlisted_entries=True)
        self.assertTrue(self.config_repo.get_config().remove_unlisted_entries)

        # Reset defaults
        self.config_repo.reset_defaults()
        self.assertTrue(self.config_repo.get_config().remove_unlisted_entries)

    def test_unlisted_entries_removed_when_flag_enabled(self):
        """When remove_unlisted_entries is enabled, entries absent from latest feed fetch are removed."""
        self.config_repo.update_config(remove_unlisted_entries=True)

        # Feed version 1 with three items
        feed_v1 = """<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0">
          <channel>
            <title>Example Feed</title>
            <link>https://example.com</link>
            <item>
              <title>Item 1</title>
              <link>https://example.com/item-1</link>
            </item>
            <item>
              <title>Item 2</title>
              <link>https://example.com/item-2</link>
            </item>
            <item>
              <title>Item 3</title>
              <link>https://example.com/item-3</link>
            </item>
          </channel>
        </rss>"""

        resp_v1 = PageResponseObject(
            url=self.source.url,
            status_code=200,
            text=feed_v1,
            binary=feed_v1.encode("utf-8"),
        )

        with patch.object(BaseUrl, "get_response", return_value=resp_v1):
            res1 = SourceService.fetch_source(self.source.id, session=self.session)
            self.assertTrue(res1.get("success"))
            self.assertEqual(res1.get("entries_added"), 3)

        entries = (
            self.session.execute(
                select(LinkDataModel).where(LinkDataModel.source_id == self.source.id)
            )
            .scalars()
            .all()
        )
        self.assertEqual(len(entries), 3)

        # Feed version 2 where Item 2 and Item 3 have rolled off, and Item 4 is new
        feed_v2 = """<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0">
          <channel>
            <title>Example Feed</title>
            <link>https://example.com</link>
            <item>
              <title>Item 1</title>
              <link>https://example.com/item-1</link>
            </item>
            <item>
              <title>Item 4</title>
              <link>https://example.com/item-4</link>
            </item>
          </channel>
        </rss>"""

        resp_v2 = PageResponseObject(
            url=self.source.url,
            status_code=200,
            text=feed_v2,
            binary=feed_v2.encode("utf-8"),
        )

        with patch.object(BaseUrl, "get_response", return_value=resp_v2):
            res2 = SourceService.fetch_source(self.source.id, session=self.session)
            self.assertTrue(res2.get("success"))
            self.assertEqual(res2.get("entries_added"), 1)
            self.assertEqual(res2.get("entries_removed"), 2)

        # Verify database contents: item-2 and item-3 removed, item-1 and item-4 present
        remaining = (
            self.session.execute(
                select(LinkDataModel).where(LinkDataModel.source_id == self.source.id)
            )
            .scalars()
            .all()
        )
        remaining_links = {e.link for e in remaining}
        self.assertEqual(len(remaining), 2)
        self.assertIn("https://example.com/item-1", remaining_links)
        self.assertIn("https://example.com/item-4", remaining_links)
        self.assertNotIn("https://example.com/item-2", remaining_links)
        self.assertNotIn("https://example.com/item-3", remaining_links)

    def test_unlisted_entries_retained_when_flag_disabled(self):
        """When remove_unlisted_entries is disabled, old entries absent from feed are NOT removed."""
        self.config_repo.update_config(remove_unlisted_entries=False)

        # Seed 2 entries for this source
        e1 = self.entry_repo.add_entry(
            "https://example.com/old-1", source_id=self.source.id
        )
        e2 = self.entry_repo.add_entry(
            "https://example.com/old-2", source_id=self.source.id
        )
        self.session.commit()

        # Feed returns only new entry
        feed = """<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0">
          <channel>
            <title>Example Feed</title>
            <link>https://example.com</link>
            <item>
              <title>New Item</title>
              <link>https://example.com/new-item</link>
            </item>
          </channel>
        </rss>"""

        mock_resp = PageResponseObject(
            url=self.source.url,
            status_code=200,
            text=feed,
            binary=feed.encode("utf-8"),
        )

        with patch.object(BaseUrl, "get_response", return_value=mock_resp):
            res = SourceService.fetch_source(self.source.id, session=self.session)
            self.assertTrue(res.get("success"))
            self.assertEqual(res.get("entries_removed", 0), 0)

        entries = (
            self.session.execute(
                select(LinkDataModel).where(LinkDataModel.source_id == self.source.id)
            )
            .scalars()
            .all()
        )
        links = {e.link for e in entries}
        self.assertEqual(len(entries), 3)
        self.assertIn("https://example.com/old-1", links)
        self.assertIn("https://example.com/old-2", links)
        self.assertIn("https://example.com/new-item", links)

    def test_unlisted_entries_respects_retention_protection(self):
        """Permanent, bookmarked, and voted entries are preserved when respective allow_remove_* switches are False."""
        self.config_repo.update_config(
            remove_unlisted_entries=True,
            allow_remove_permanent_entries=False,
            allow_remove_bookmarked_entries=False,
            allow_remove_votes_entries=False,
        )

        # Add entries with various protection attributes
        normal = self.entry_repo.add_entry(
            "https://example.com/normal", source_id=self.source.id
        )
        perm = self.entry_repo.add_entry(
            "https://example.com/perm", source_id=self.source.id
        )
        perm.permanent = True
        bm = self.entry_repo.add_entry(
            "https://example.com/bookmarked", source_id=self.source.id
        )
        bm.bookmarked = True
        voted = self.entry_repo.add_entry(
            "https://example.com/voted", source_id=self.source.id
        )
        voted.page_rating_votes = 10
        self.session.commit()

        # Feed has none of the existing entries (empty feed)
        empty_feed = """<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0">
          <channel>
            <title>Example Feed</title>
            <link>https://example.com</link>
          </channel>
        </rss>"""

        mock_resp = PageResponseObject(
            url=self.source.url,
            status_code=200,
            text=empty_feed,
            binary=empty_feed.encode("utf-8"),
        )

        with patch.object(BaseUrl, "get_response", return_value=mock_resp):
            res = SourceService.fetch_source(self.source.id, session=self.session)
            self.assertTrue(res.get("success"))
            self.assertEqual(res.get("entries_removed"), 1)  # only normal removed

        remaining = (
            self.session.execute(
                select(LinkDataModel).where(LinkDataModel.source_id == self.source.id)
            )
            .scalars()
            .all()
        )
        remaining_links = {e.link for e in remaining}
        self.assertNotIn("https://example.com/normal", remaining_links)
        self.assertIn("https://example.com/perm", remaining_links)
        self.assertIn("https://example.com/bookmarked", remaining_links)
        self.assertIn("https://example.com/voted", remaining_links)

    def test_unlisted_entries_does_not_remove_other_sources(self):
        """Unlisted entry removal for source A never affects entries belonging to source B."""
        self.config_repo.update_config(remove_unlisted_entries=True)

        other_source = self.source_repo.add_source(
            url="https://other.com/feed.xml",
            title="Other Feed",
            source_type="RSS",
            enabled=True,
        )
        self.session.commit()

        # Seed entries for both sources
        self.entry_repo.add_entry("https://example.com/src-a", source_id=self.source.id)
        self.entry_repo.add_entry("https://other.com/src-b", source_id=other_source.id)
        self.session.commit()

        # Fetch source A with empty feed
        empty_feed = """<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0">
          <channel>
            <title>Example Feed</title>
            <link>https://example.com</link>
          </channel>
        </rss>"""

        mock_resp = PageResponseObject(
            url=self.source.url,
            status_code=200,
            text=empty_feed,
            binary=empty_feed.encode("utf-8"),
        )

        with patch.object(BaseUrl, "get_response", return_value=mock_resp):
            res = SourceService.fetch_source(self.source.id, session=self.session)
            self.assertTrue(res.get("success"))
            self.assertEqual(res.get("entries_removed"), 1)

        # Source A entry deleted
        src_a_entries = (
            self.session.execute(
                select(LinkDataModel).where(LinkDataModel.source_id == self.source.id)
            )
            .scalars()
            .all()
        )
        self.assertEqual(len(src_a_entries), 0)

        # Source B entry preserved
        src_b_entries = (
            self.session.execute(
                select(LinkDataModel).where(LinkDataModel.source_id == other_source.id)
            )
            .scalars()
            .all()
        )
        self.assertEqual(len(src_b_entries), 1)
        self.assertEqual(src_b_entries[0].link, "https://other.com/src-b")

    def test_job_handler_process_source_removes_unlisted(self):
        """ProcessSourceJobHandler executes source processing and triggers unlisted entry removal."""
        self.config_repo.update_config(remove_unlisted_entries=True)

        self.entry_repo.add_entry(
            "https://example.com/old-item", source_id=self.source.id
        )
        self.session.commit()

        job = BackgroundJob(
            job="process-source",
            subject=str(self.source.id),
            priority=1,
            enabled=True,
        )
        self.session.add(job)
        self.session.commit()

        feed = """<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0">
          <channel>
            <title>Example Feed</title>
            <link>https://example.com</link>
            <item>
              <title>New Feed Item</title>
              <link>https://example.com/new-feed-item</link>
            </item>
          </channel>
        </rss>"""

        mock_resp = PageResponseObject(
            url=self.source.url,
            status_code=200,
            text=feed,
            binary=feed.encode("utf-8"),
        )

        handler = ProcessSourceJobHandler()
        with patch.object(BaseUrl, "get_response", return_value=mock_resp):
            res = handler.execute(job, self.session)
            self.assertTrue(res.get("success"))
            self.assertEqual(res.get("entries_added"), 1)
            self.assertEqual(res.get("entries_removed"), 1)

        remaining = (
            self.session.execute(
                select(LinkDataModel).where(LinkDataModel.source_id == self.source.id)
            )
            .scalars()
            .all()
        )
        remaining_links = {e.link for e in remaining}
        self.assertEqual(len(remaining), 1)
        self.assertIn("https://example.com/new-feed-item", remaining_links)
        self.assertNotIn("https://example.com/old-item", remaining_links)
