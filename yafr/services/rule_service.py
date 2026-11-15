"""
RuleService - Business logic for evaluating, matching, and testing URLs
against EntryRules and BlockEntry definitions.
"""

import logging
import re
from typing import Any, Dict, List, Optional
from sqlalchemy.orm import Session
from linkarchivetools.model.definitions import EntryRules
from yafr.db import BlockEntryRepository, RulesRepository, get_session

logger = logging.getLogger(__name__)


class RuleService:
    """
    Evaluates candidate URLs against configured EntryRules and BlockEntry records.
    """

    @staticmethod
    def match_url_patterns(pattern_str: Optional[str], url: str) -> Optional[str]:
        """
        Tests whether candidate URL matches any comma-separated regex in pattern_str.

        :param pattern_str: Comma-separated regex patterns (e.g. '.*reddit\\.com.*, .*github\\.com.*')
        :param url: Candidate URL string to test
        :return: First matching pattern string or None
        """
        if not pattern_str or not url:
            return None

        patterns = [p.strip() for p in pattern_str.split(",") if p.strip()]
        for pattern in patterns:
            try:
                if re.search(pattern, url, re.IGNORECASE):
                    return pattern
            except re.error as err:
                logger.warning("Invalid regex pattern '%s': %s", pattern, err)
        return None

    @staticmethod
    def to_rule_dict(
        rule: EntryRules, matched_pattern: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Serializes an EntryRules record into a JSON-compatible dictionary.

        :param rule: EntryRules model instance
        :param matched_pattern: Specific regex pattern that matched
        :return: Dictionary representation of rule with actions summary
        """
        actions = []
        if rule.block:
            actions.append("Block link")
        if rule.trust:
            actions.append("Trust link (mark active)")
        if rule.auto_tag:
            actions.append(f"Add tags: {rule.auto_tag}")
        if rule.apply_age_limit and rule.apply_age_limit > 0:
            actions.append(f"Apply age limit: {rule.apply_age_limit}")
        if not actions:
            actions.append("No action")

        return {
            "id": rule.id,
            "rule_name": rule.rule_name or f"Rule #{rule.id}",
            "priority": rule.priority if rule.priority is not None else 0,
            "enabled": bool(rule.enabled),
            "block": bool(rule.block),
            "trust": bool(rule.trust),
            "auto_tag": rule.auto_tag or "",
            "apply_age_limit": int(rule.apply_age_limit or 0),
            "trigger_rule_url": rule.trigger_rule_url or "",
            "matched_pattern": matched_pattern,
            "actions_summary": "; ".join(actions),
        }

    @classmethod
    def test_url(cls, url: str, session: Optional[Session] = None) -> Dict[str, Any]:
        """
        Evaluates a candidate URL against all EntryRules and BlockEntry records.

        Reports:
        - Whether the link is blocked (overall, by rule, and/or by block entry).
        - What actions are taken (block, trust, auto-tags, age limit).
        - Which specific rules and block entries affect the URL.

        :param url: Candidate URL string
        :param session: Optional active SQLAlchemy session
        :return: Dictionary with evaluation verdict, action flags, and matching items
        """
        raw = (url or "").strip()
        if not raw:
            return {
                "success": False,
                "error": "URL is empty or undefined.",
                "url": "",
                "cleaned_url": "",
                "is_blocked": False,
                "is_blocked_by_rule": False,
                "is_blocked_by_block_entry": False,
                "is_trusted": False,
                "auto_tags": [],
                "age_limit": 0,
                "matched_rule_id": None,
                "rule_name": None,
                "matching_rules": [],
                "matching_block_entries": [],
                "verdict": "URL is empty.",
            }

        sess = session or get_session()
        from yafr.services.entry_builder import EntryBuilder

        builder = EntryBuilder(session=sess)
        cleaned_url = builder.sanitize_url(raw) or raw

        rules_repo = RulesRepository(sess)
        all_rules = rules_repo.list_rules(enabled_only=False, order_by="priority")

        matching_rules: List[Dict[str, Any]] = []
        is_blocked_by_rule = False
        is_trusted = False
        auto_tags: List[str] = []
        age_limit = 0
        first_rule_id: Optional[int] = None
        first_rule_name: Optional[str] = None

        for rule in all_rules:
            matched_pattern = cls.match_url_patterns(
                rule.trigger_rule_url, cleaned_url
            ) or cls.match_url_patterns(rule.trigger_rule_url, raw)

            if matched_pattern:
                rule_dict = cls.to_rule_dict(rule, matched_pattern=matched_pattern)
                matching_rules.append(rule_dict)

                if first_rule_id is None:
                    first_rule_id = rule.id
                    first_rule_name = rule.rule_name or f"Rule #{rule.id}"

                # Only enabled rules affect the actual execution verdict
                if rule.enabled:
                    if rule.block:
                        is_blocked_by_rule = True
                    if rule.trust:
                        is_trusted = True
                    if rule.auto_tag:
                        for t in re.split(r"[,\s]+", rule.auto_tag):
                            clean_t = t.strip().lstrip("#")
                            if clean_t and clean_t not in auto_tags:
                                auto_tags.append(clean_t)
                    if rule.apply_age_limit and rule.apply_age_limit > age_limit:
                        age_limit = int(rule.apply_age_limit)

        # Evaluate BlockEntry matches
        block_repo = BlockEntryRepository(sess)
        block_entries = block_repo.get_matching_entries(cleaned_url, raw_url=raw)
        matching_block_entries = [
            {
                "id": b.id,
                "url": b.url,
                "block_list_id": b.block_list_id,
            }
            for b in block_entries
        ]
        is_blocked_by_block_entry = len(matching_block_entries) > 0

        is_blocked = is_blocked_by_rule or is_blocked_by_block_entry

        # Build human-readable verdict
        if is_blocked_by_rule and is_blocked_by_block_entry:
            verdict = "Blocked by rule and block entry"
        elif is_blocked_by_rule:
            verdict = f"Blocked by rule '{first_rule_name}'"
        elif is_blocked_by_block_entry:
            pattern_str = matching_block_entries[0]["url"]
            verdict = f"Blocked by block entry '{pattern_str}'"
        else:
            extras = []
            if is_trusted:
                extras.append("trusted")
            if auto_tags:
                extras.append(f"tags: {', '.join(auto_tags)}")
            if age_limit > 0:
                extras.append(f"age limit: {age_limit}")
            if extras:
                verdict = f"Allowed ({'; '.join(extras)})"
            elif matching_rules:
                verdict = "Allowed (matching disabled rules only)"
            else:
                verdict = "Allowed (no matching rules or blocks)"

        return {
            "success": True,
            "url": raw,
            "cleaned_url": cleaned_url,
            "is_blocked": is_blocked,
            "is_blocked_by_rule": is_blocked_by_rule,
            "is_blocked_by_block_entry": is_blocked_by_block_entry,
            "is_trusted": is_trusted,
            "auto_tags": auto_tags,
            "age_limit": age_limit,
            "matched_rule_id": first_rule_id,
            "rule_name": first_rule_name,
            "matching_rules": matching_rules,
            "matching_block_entries": matching_block_entries,
            "verdict": verdict,
        }
