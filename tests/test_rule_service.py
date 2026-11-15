"""
Unit tests for RuleService and URL testing against EntryRules and BlockEntry records.
"""

import unittest
from yafr.app import create_app
from yafr.db import (
    BlockEntryListRepository,
    BlockEntryRepository,
    RulesRepository,
    close_session,
    get_session,
)
from yafr.services.rule_service import RuleService


class TestRuleService(unittest.TestCase):
    """
    Test suite for RuleService.test_url evaluation logic.
    """

    def setUp(self):
        self.app = create_app(
            {
                "TESTING": True,
                "DATABASE_PATH": ":memory:",
                "SECRET_KEY": "test-rule-service-key",
            }
        )
        self.session = get_session()
        self.rules_repo = RulesRepository(self.session)
        self.block_repo = BlockEntryRepository(self.session)
        self.list_repo = BlockEntryListRepository(self.session)

    def tearDown(self):
        close_session()

    def test_test_url_empty_input(self):
        """Testing an empty URL returns not allowed / error result."""
        result = RuleService.test_url("", session=self.session)
        self.assertFalse(result["success"])
        self.assertIn("empty", result["error"].lower())

    def test_test_url_no_rules_no_blocks(self):
        """Testing a clean URL when no rules or blocks exist reports allowed with no actions."""
        result = RuleService.test_url(
            "https://clean-example.com/page", session=self.session
        )
        self.assertTrue(result["success"])
        self.assertFalse(result["is_blocked"])
        self.assertFalse(result["is_blocked_by_rule"])
        self.assertFalse(result["is_blocked_by_block_entry"])
        self.assertFalse(result["is_trusted"])
        self.assertEqual(result["auto_tags"], [])
        self.assertEqual(result["age_limit"], 0)
        self.assertEqual(result["matching_rules"], [])
        self.assertEqual(result["matching_block_entries"], [])

    def test_test_url_blocked_by_block_entry(self):
        """URL matching a BlockEntry record is reported as blocked by block entry."""
        b = self.block_repo.add_entry("malicious-tracker.org")

        result = RuleService.test_url(
            "https://sub.malicious-tracker.org/click?id=123", session=self.session
        )
        self.assertTrue(result["success"])
        self.assertTrue(result["is_blocked"])
        self.assertFalse(result["is_blocked_by_rule"])
        self.assertTrue(result["is_blocked_by_block_entry"])
        self.assertEqual(len(result["matching_block_entries"]), 1)
        self.assertEqual(result["matching_block_entries"][0]["id"], b.id)
        self.assertEqual(
            result["matching_block_entries"][0]["url"], "malicious-tracker.org"
        )

    def test_test_url_blocked_by_rule(self):
        """URL matching an enabled blocking EntryRule is reported as blocked by rule."""
        rule = self.rules_repo.add_rule(
            rule_name="Block Phishing",
            trigger_rule_url=r".*bad-login\.(com|net).*",
            enabled=True,
            block=True,
        )

        result = RuleService.test_url(
            "https://secure.bad-login.com/account", session=self.session
        )
        self.assertTrue(result["success"])
        self.assertTrue(result["is_blocked"])
        self.assertTrue(result["is_blocked_by_rule"])
        self.assertFalse(result["is_blocked_by_block_entry"])
        self.assertEqual(result["matched_rule_id"], rule.id)
        self.assertEqual(result["rule_name"], "Block Phishing")
        self.assertEqual(len(result["matching_rules"]), 1)
        self.assertTrue(result["matching_rules"][0]["block"])

    def test_test_url_rule_actions_trust_tags_age_limit(self):
        """URL matching rule with actions reports trust, tags, and age limit."""
        rule = self.rules_repo.add_rule(
            rule_name="Reddit Discussion",
            trigger_rule_url=r".*reddit\.com/r/.*",
            enabled=True,
            trust=True,
            auto_tag="reddit, social, community",
            apply_age_limit=18,
        )

        result = RuleService.test_url(
            "https://www.reddit.com/r/technology/comments/123", session=self.session
        )
        self.assertTrue(result["success"])
        self.assertFalse(result["is_blocked"])
        self.assertTrue(result["is_trusted"])
        self.assertIn("reddit", result["auto_tags"])
        self.assertIn("social", result["auto_tags"])
        self.assertEqual(result["age_limit"], 18)
        self.assertEqual(len(result["matching_rules"]), 1)
        self.assertEqual(result["matching_rules"][0]["id"], rule.id)

    def test_test_url_disabled_rule_not_affecting_verdict(self):
        """A disabled blocking rule should match but not cause is_blocked=True in the active verdict."""
        rule = self.rules_repo.add_rule(
            rule_name="Disabled Block",
            trigger_rule_url=r".*blocked-site\.org.*",
            enabled=False,
            block=True,
        )

        result = RuleService.test_url(
            "https://blocked-site.org/home", session=self.session
        )
        self.assertTrue(result["success"])
        # Verdict should not be blocked because the rule is disabled
        self.assertFalse(result["is_blocked"])
        self.assertFalse(result["is_blocked_by_rule"])
        # But matching_rules should include the rule and indicate enabled=False
        self.assertEqual(len(result["matching_rules"]), 1)
        self.assertEqual(result["matching_rules"][0]["id"], rule.id)
        self.assertFalse(result["matching_rules"][0]["enabled"])

    def test_test_url_both_rule_and_block_entry(self):
        """URL affected by both a block entry and a rule reports both accurately."""
        self.block_repo.add_entry("spamdomain.com")
        self.rules_repo.add_rule(
            rule_name="Spam Rule",
            trigger_rule_url=r".*spamdomain\.com.*",
            enabled=True,
            block=True,
            auto_tag="spam",
        )

        result = RuleService.test_url(
            "https://spamdomain.com/buy", session=self.session
        )
        self.assertTrue(result["success"])
        self.assertTrue(result["is_blocked"])
        self.assertTrue(result["is_blocked_by_rule"])
        self.assertTrue(result["is_blocked_by_block_entry"])
        self.assertEqual(len(result["matching_block_entries"]), 1)
        self.assertEqual(len(result["matching_rules"]), 1)
