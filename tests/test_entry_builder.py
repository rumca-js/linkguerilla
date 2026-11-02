"""
Unit and integration tests for EntryBuilder and Validation Pipeline.
"""

from datetime import datetime, timezone
import unittest
from unittest.mock import patch

from sqlalchemy import select
from linkarchivetools.model.definitions import (
    BlockEntry,
    ConfigurationEntry,
    EntryCompactedTags,
    EntryRules,
    LinkDataModel,
    ReadLater,
    SourcesTable,
)
from yafr.app import create_app
from yafr.db import (
    BlockEntryRepository,
    ConfigRepository,
    EntryRepository,
    RulesRepository,
    SourceRepository,
    close_session,
    get_session,
)
from yafr.services.entry_builder import EntryBuilder, EntryLinkBuilder
from yafr.services.source_service import SourceService
from webtoolkit.response import PageResponseObject


class TestEntryBuilder(unittest.TestCase):
    """
    Test suite for EntryBuilder sanitization, configuration policy validation,
    rule matching, source inheritance, and persistence.
    """

    def setUp(self):
        self.app = create_app(
            {
                "TESTING": True,
                "DATABASE_PATH": ":memory:",
                "SECRET_KEY": "test-key-entry-builder",
            }
        )
        self.session = get_session()
        self.config_repo = ConfigRepository(self.session)
        self.source_repo = SourceRepository(self.session)
        self.rules_repo = RulesRepository(self.session)
        self.entry_repo = EntryRepository(self.session)
        self.block_repo = BlockEntryRepository(self.session)

        # Get active default configuration
        self.config = self.config_repo.get_config()

    def tearDown(self):
        close_session()

    def test_sanitize_url_basic_and_trailing_slash(self):
        """Sanitizes raw URLs, strips whitespace, and removes superfluous trailing slash."""
        builder = EntryBuilder(session=self.session, config=self.config)

        # Trailing slash on path removed
        url1 = "   https://example.com/some/article/   "
        self.assertEqual(builder.sanitize_url(url1), "https://example.com/some/article")

        # Root domain URL
        url2 = "https://example.com/"
        self.assertEqual(builder.sanitize_url(url2), "https://example.com")

        # Empty URL
        self.assertEqual(builder.sanitize_url(""), "")

    def test_sanitize_url_prefer_https_and_non_www(self):
        """Applies prefer_https_links and prefer_non_www_links configuration settings."""
        self.config.prefer_https_links = True
        self.config.prefer_non_www_links = True
        self.session.commit()

        builder = EntryBuilder(session=self.session, config=self.config)

        # Upgrades HTTP to HTTPS and strips www.
        url = "http://www.example.com/page"
        cleaned = builder.sanitize_url(url)
        self.assertEqual(cleaned, "https://example.com/page")

        # Preserves HTTP for Tor onion links
        onion_url = "http://www.expyuz5wqqfdgah56trldsd.onion/index"
        cleaned_onion = builder.sanitize_url(onion_url)
        self.assertTrue(cleaned_onion.startswith("http://"))

    def test_can_build_empty_url(self):
        """Rejects empty candidate URLs."""
        builder = EntryBuilder(session=self.session)
        allowed, reason = builder.can_build("")
        self.assertFalse(allowed)
        self.assertIn("empty", reason.lower())

    def test_can_build_policy_ip_and_onion(self):
        """Enforces accept_ip_links and accept_onion_links policies."""
        # Disable IP and Onion links
        self.config.accept_ip_links = False
        self.config.accept_onion_links = False
        self.session.commit()

        builder = EntryBuilder(session=self.session, config=self.config)

        # IP address URL rejected
        allowed_ip, reason_ip = builder.can_build("http://192.168.1.1/info")
        self.assertFalse(allowed_ip)
        self.assertIn("IP address", reason_ip)

        # Onion URL rejected
        allowed_onion, reason_onion = builder.can_build(
            "http://expyuz5wqqfdgah56trldsd.onion/test"
        )
        self.assertFalse(allowed_onion)
        self.assertIn("Onion", reason_onion)

        # Allowed when ignored via override
        allowed_override, _ = builder.can_build(
            "http://192.168.1.1/info", ignore_policy=True
        )
        self.assertTrue(allowed_override)

    def test_can_build_policy_dead_links(self):
        """Rejects dead links when accept_dead_links is disabled."""
        self.config.accept_dead_links = False
        self.session.commit()

        builder = EntryBuilder(session=self.session, config=self.config)
        allowed, reason = builder.can_build("https://example.com/dead", status_code=404)
        self.assertFalse(allowed)
        self.assertIn("Dead links", reason)

        # Accept dead links when configured
        self.config.accept_dead_links = True
        self.session.commit()
        allowed2, _ = builder.can_build("https://example.com/dead", status_code=404)
        self.assertTrue(allowed2)

    def test_can_build_policy_domain_links(self):
        """Rejects domain links when accept_domain_links is disabled."""
        self.config.accept_domain_links = False
        self.session.commit()

        builder = EntryBuilder(session=self.session, config=self.config)
        allowed, reason = builder.can_build("https://example.com")
        self.assertFalse(allowed)
        self.assertIn("Domain links", reason)

    def test_can_build_policy_non_domain_links(self):
        """Rejects domain links when accept_domain_links is disabled."""
        self.config.accept_non_domain_links = False
        self.session.commit()

        builder = EntryBuilder(session=self.session, config=self.config)
        allowed, reason = builder.can_build("https://example.com/test")
        self.assertFalse(allowed)
        self.assertIn("Non domain links", reason)

    def test_rules_matching_block_rule(self):
        """Evaluates EntryRules with block=True to reject matching candidate links."""
        self.rules_repo.add_rule(
            rule_name="Block Spam",
            trigger_rule_url=r".*spam-site\.com.*",
            block=True,
            priority=1,
            enabled=True,
        )

        builder = EntryBuilder(session=self.session)
        allowed, reason = builder.can_build("https://spam-site.com/offer")
        self.assertFalse(allowed)
        self.assertIn("blocked by entry rule", reason)

    def test_rules_matching_comma_separated_regexes(self):
        """Supports comma-separated regex patterns in trigger_rule_url."""
        self.rules_repo.add_rule(
            rule_name="Block Multiple",
            trigger_rule_url=r".*bad-one\.org.*, .*bad-two\.org.*",
            block=True,
            priority=1,
            enabled=True,
        )

        builder = EntryBuilder(session=self.session)
        allowed1, _ = builder.can_build("https://bad-one.org/news")
        self.assertFalse(allowed1)

        allowed2, _ = builder.can_build("https://bad-two.org/articles")
        self.assertFalse(allowed2)

        allowed3, _ = builder.can_build("https://good-domain.org/articles")
        self.assertTrue(allowed3)

    def test_rules_matching_trust_auto_tag_and_age_limit(self):
        """EntryRules trust flag sets manual status to 200, adds auto_tag, and applies age limit."""
        self.rules_repo.add_rule(
            rule_name="Tech Rule",
            trigger_rule_url=r".*techcrunch\.com.*",
            trust=True,
            auto_tag="tech, startups",
            apply_age_limit=18,
            priority=1,
            enabled=True,
        )

        builder = EntryBuilder(session=self.session)
        entry, tags = builder.build_entry(
            link="https://techcrunch.com/2026/01/01/new-startup",
            title="Cool Startup",
            status_code=301,
        )

        self.assertIsNotNone(entry)
        self.assertEqual(entry.manual_status_code, 200)
        self.assertEqual(entry.age, 18)
        self.assertIn("tech", tags)
        self.assertIn("startups", tags)

    def test_source_attribute_inheritance(self):
        """Inherits source language, favicon fallback, age rating, auto_tags, and read_later."""
        source = self.source_repo.add_source(
            url="https://news.ycombinator.com/rss",
            title="Hacker News",
            language="en",
            favicon="https://news.ycombinator.com/favicon.ico",
            age=13,
            auto_tag="yc, news",
        )
        source.auto_add_to_read_later = True
        self.session.commit()

        builder = EntryBuilder(session=self.session)
        entry = builder.build_and_save(
            link="https://news.ycombinator.com/item?id=12345",
            title="Ask HN: Favorite tools?",
            source=source,
            commit=True,
        )

        self.assertIsNotNone(entry)
        self.assertEqual(entry.language, "en")
        self.assertEqual(entry.thumbnail, "https://news.ycombinator.com/favicon.ico")
        self.assertEqual(entry.age, 13)
        self.assertEqual(entry.source_id, source.id)

        # Check tags persisted
        tag_records = (
            self.session.execute(
                select(EntryCompactedTags.tag).where(
                    EntryCompactedTags.entry_id == entry.id
                )
            )
            .scalars()
            .all()
        )
        self.assertIn("yc", tag_records)
        self.assertIn("news", tag_records)

        # Check auto_add_to_read_later
        read_later_row = (
            self.session.execute(
                select(ReadLater).where(ReadLater.entry_id == entry.id)
            )
            .scalars()
            .first()
        )
        self.assertIsNotNone(read_later_row)

    def test_de_duplication(self):
        """Rejects duplicate entries when check_duplicates is True."""
        builder = EntryBuilder(session=self.session)
        e1 = builder.build_and_save(
            link="https://example.com/unique-link",
            title="Unique Link",
            commit=True,
        )
        self.assertIsNotNone(e1)

        # Attempt to insert identical URL
        e2 = builder.build_and_save(
            link="https://example.com/unique-link",
            title="Duplicate Attempt",
            commit=True,
        )
        self.assertIsNone(e2)
        self.assertIn("Duplicate entry", builder.last_rejection_reason)

    def test_convenience_factory_create(self):
        """EntryBuilder.create factory method builds and persists an entry."""
        entry = EntryBuilder.create(
            link="https://example.com/factory-created",
            title="Factory Item",
            session=self.session,
            commit=True,
        )
        self.assertIsNotNone(entry)
        self.assertEqual(entry.title, "Factory Item")
        self.assertEqual(entry.link, "https://example.com/factory-created")

    def test_worker_fetch_source_integrates_with_entry_builder(self):
        """SourceService.fetch_source uses EntryBuilder to parse feed and persist entries."""
        source = self.source_repo.add_source(
            url="https://example.com/rss.xml",
            title="Feed with Auto Tags",
            auto_tag="automated, testing",
            language="en",
            age=18,
        )

        sample_rss = """<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0">
          <channel>
            <title>Feed with Auto Tags</title>
            <link>https://example.com</link>
            <item>
              <title>Worker Entry One</title>
              <link>https://example.com/article-1</link>
              <description>Description for article 1</description>
            </item>
            <item>
              <title>Worker Entry Two</title>
              <link>https://example.com/article-2</link>
              <description>Description for article 2</description>
            </item>
          </channel>
        </rss>"""

        mock_resp = PageResponseObject(
            url=source.url,
            status_code=200,
            text=sample_rss,
            binary=sample_rss.encode("utf-8"),
        )

        from webtoolkit import BaseUrl

        with patch.object(BaseUrl, "get_response", return_value=mock_resp):
            res = SourceService.fetch_source(source.id, session=self.session)
            self.assertTrue(res.get("success"))
            self.assertEqual(res.get("entries_added"), 2)

            # Verify entries in DB with inherited attributes and tags
            entries = (
                self.session.execute(
                    select(LinkDataModel).where(LinkDataModel.source_id == source.id)
                )
                .scalars()
                .all()
            )
            self.assertEqual(len(entries), 2)
            links = [e.link for e in entries]
            self.assertIn("https://example.com/article-1", links)
            self.assertIn("https://example.com/article-2", links)

            for entry in entries:
                self.assertEqual(entry.language, "en")
                self.assertEqual(entry.age, 18)
                tags = (
                    self.session.execute(
                        select(EntryCompactedTags.tag).where(
                            EntryCompactedTags.entry_id == entry.id
                        )
                    )
                    .scalars()
                    .all()
                )
                self.assertIn("automated", tags)
                self.assertIn("testing", tags)

    def test_block_entry_matching_domain_rejects_link(self):
        """BlockEntry matching candidate URL domain prevents building."""
        self.block_repo.add_entry("adserver.net")

        builder = EntryBuilder(session=self.session)
        allowed, reason = builder.can_build("https://adserver.net/banner.js")
        self.assertFalse(allowed)
        self.assertIn("blocked by block entry 'adserver.net'", reason)
        self.assertEqual(builder.last_rejection_reason, reason)

    def test_block_entry_matching_substring_and_query_param(self):
        """BlockEntry matching substring or query parameter prevents building."""
        self.block_repo.add_entry("&track_click=1")

        builder = EntryBuilder(session=self.session)
        allowed, reason = builder.can_build("https://example.com/item?foo=bar&track_click=1")
        self.assertFalse(allowed)
        self.assertIn("blocked by block entry '&track_click=1'", reason)

    def test_block_entry_case_insensitive_matching(self):
        """BlockEntry matches regardless of case difference in candidate or pattern."""
        self.block_repo.add_entry("TRACKER-DOMAIN.COM")

        builder = EntryBuilder(session=self.session)
        allowed, reason = builder.can_build("https://tracker-domain.com/feed")
        self.assertFalse(allowed)
        self.assertIn("blocked by block entry", reason)

        # Candidate with uppercase
        allowed2, reason2 = builder.can_build("https://SUB.Tracker-Domain.com/page")
        self.assertFalse(allowed2)
        self.assertIn("blocked by block entry", reason2)

    def test_block_entry_prevents_build_and_save(self):
        """build_entry and build_and_save return None and do not persist blocked links."""
        self.block_repo.add_entry("malicious-site.org")

        builder = EntryBuilder(session=self.session)
        # build_entry
        entry, tags = builder.build_entry("https://malicious-site.org/payload")
        self.assertIsNone(entry)
        self.assertEqual(tags, [])

        # build_and_save
        saved = builder.build_and_save("https://malicious-site.org/payload", commit=True)
        self.assertIsNone(saved)

        # Verify not in DB
        existing = (
            self.session.execute(
                select(LinkDataModel).where(LinkDataModel.link == "https://malicious-site.org/payload")
            )
            .scalars()
            .first()
        )
        self.assertIsNone(existing)

    def test_clean_url_allowed_when_block_entries_exist(self):
        """URLs that do not match any BlockEntry.url are built normally."""
        self.block_repo.add_entry("malicious.org")
        self.block_repo.add_entry("adserver.com")

        builder = EntryBuilder(session=self.session)
        allowed, reason = builder.can_build("https://good-domain.org/article")
        self.assertTrue(allowed)
        self.assertIsNone(reason)

    def test_block_entry_blocks_even_with_ignore_policy(self):
        """BlockEntry blocking is enforced even when ignore_policy=True."""
        self.block_repo.add_entry("bad-site.org")

        builder = EntryBuilder(session=self.session)
        allowed, reason = builder.can_build("https://bad-site.org/page", ignore_policy=True)
        self.assertFalse(allowed)
        self.assertIn("blocked by block entry", reason)


if __name__ == "__main__":
    unittest.main()
