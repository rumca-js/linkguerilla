"""
Entry Builder and Validation Pipeline for YAFR.

Centralized domain service responsible for validating, sanitizing, policy checking,
rule-matching, inheriting source attributes, and instantiating LinkDataModel records
prior to database persistence.
"""

from datetime import datetime, timezone
import logging
import re
from typing import Any, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session
import webtoolkit

from linkarchivetools.model.definitions import (
    BlockEntry,
    ConfigurationEntry,
    EntryCompactedTags,
    EntryRules,
    LinkDataModel,
    SourcesTable,
)
from yafr.db.block_repository import BlockEntryRepository
from yafr.db.config_repository import ConfigRepository
from yafr.db.rules_repository import RulesRepository
from yafr.db.session import get_session
from yafr.services.job_service import JOB_LINK_UPDATE_DATA

logger = logging.getLogger(__name__)


class EntryBuilder:
    """
    Builder and validation pipeline for candidate web entries.

    Ensures that raw candidate URLs from background workers, feeds, jobs,
    or manual user forms pass through a strict validation pipeline:
      1. URL sanitization and normalization (trim whitespace, clean trailing slashes,
         apply HTTPS and non-WWW preferences).
      2. Configuration policy verification (domain-only, IP addresses, Onion/Tor,
         dead links, non-domain links).
      3. EntryRules regex evaluation (blocking, trusting, auto-tagging, age restrictions).
      4. BlockEntry evaluation (blocking candidate URLs matching any BlockEntry pattern).
      5. Source property inheritance (language, age, auto-tags, favicon fallback).
      6. De-duplication check against existing LinkDataModel rows.
    """

    def __init__(
        self,
        session: Optional[Session] = None,
        config: Optional[ConfigurationEntry] = None,
    ) -> None:
        """
        Initializes the EntryBuilder.

        :param session: Optional active database session (falls back to scoped get_session())
        :param config: Optional ConfigurationEntry instance for link acceptance policies
        """
        self._session = session
        self._config = config
        self.last_rejection_reason: Optional[str] = None

    @property
    def session(self) -> Session:
        """Returns the active SQLAlchemy session."""
        if self._session is None:
            self._session = get_session()
        return self._session

    @property
    def config(self) -> ConfigurationEntry:
        """Returns the cached or queried active ConfigurationEntry."""
        if self._config is None:
            config_repo = ConfigRepository(self.session)
            self._config = config_repo.get_config()
        return self._config

    def _get_config_bool(self, key: str, default: bool = False) -> bool:
        """
        Safely retrieves a boolean policy flag from the active configuration.

        :param key: Attribute name on ConfigurationEntry
        :param default: Fallback value if attribute is None or unset
        :return: Boolean value of the flag
        """
        if self.config is not None:
            val = getattr(self.config, key, None)
            if val is not None:
                return bool(val)
        return default

    def sanitize_url(self, raw_url: Any) -> str:
        """
        Cleans and normalizes a candidate URL:
        - Strips leading and trailing whitespace.
        - Prepends HTTP/HTTPS scheme if missing.
        - Applies prefer_https_links (upgrades http:// to https://, except for Tor .onion).
        - Applies prefer_non_www_links (removes leading www.).
        - Cleans URL paths and superfluous trailing slashes using webtoolkit.UrlLocation.

        :param raw_url: Raw URL string or UrlLocation instance
        :return: Sanitized canonical URL string
        """
        if raw_url is None:
            return ""
        if hasattr(raw_url, "url"):
            url = str(raw_url.url or "").strip()
        else:
            url = str(raw_url).strip()
        if not url:
            return ""

        prefer_https = self._get_config_bool("prefer_https_links", default=False)
        prefer_non_www = self._get_config_bool("prefer_non_www_links", default=False)

        # Prepend scheme if missing or protocol-relative
        if url.startswith("//"):
            scheme = "https:" if prefer_https else "http:"
            url = f"{scheme}{url}"
        elif not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", url):
            scheme = "https://" if prefer_https else "http://"
            url = f"{scheme}{url}"

        # Prefer HTTPS link upgrade (preserve plain http for onion addresses)
        is_onion = url.lower().endswith(".onion") or ".onion/" in url.lower()
        if prefer_https and url.lower().startswith("http://") and not is_onion:
            url = "https://" + url[7:]

        # Prefer non-WWW link stripping
        if prefer_non_www:
            url = re.sub(r"^(https?://)www\.", r"\1", url, flags=re.IGNORECASE)

        # Use webtoolkit.UrlLocation for canonical path cleaning
        cleaned = webtoolkit.UrlLocation(url).get_clean()
        if cleaned:
            return str(cleaned.url if hasattr(cleaned, "url") else cleaned)
        return url

    def is_duplicate(self, url: str) -> bool:
        """
        Checks whether a candidate URL already exists in the linkdatamodel table.

        :param url: URL to check (will be sanitized prior to lookup)
        :return: True if duplicate found, False otherwise
        """
        cleaned = self.sanitize_url(url)
        raw = (url or "").strip()
        if not cleaned:
            return False
        stmt = (
            select(LinkDataModel.id)
            .where((LinkDataModel.link == cleaned) | (LinkDataModel.link == raw))
            .limit(1)
        )
        return self.session.execute(stmt).scalar_one_or_none() is not None

    def _get_matching_rules(
        self,
        url: str,
        source: Optional[SourcesTable] = None,
        title: Optional[str] = None,
        description: Optional[str] = None,
    ) -> List[EntryRules]:
        """
        Queries enabled EntryRules ordered by priority and returns rules matching the URL or text.

        :param url: Sanitized candidate URL
        :param source: Optional source to evaluate source_id scoping
        :param title: Optional candidate title for trigger_text matching
        :param description: Optional candidate description for trigger_text matching
        :return: List of matching EntryRules instances
        """
        try:
            rules_repo = RulesRepository(self.session)
            rules = rules_repo.list_rules(enabled_only=True, order_by="priority")
        except Exception as err:
            logger.warning("Error querying entry rules: %s", err)
            return []

        source_id = source.id if source else None
        matching: List[EntryRules] = []

        for rule in rules:
            # Source scoping check
            if rule.source_id is not None:
                if source_id is None or rule.source_id != source_id:
                    continue

            rule_matched = False

            # URL regex matching (supports comma-separated regex patterns)
            if rule.trigger_rule_url:
                patterns = [
                    p.strip() for p in rule.trigger_rule_url.split(",") if p.strip()
                ]
                for pattern in patterns:
                    try:
                        if re.search(pattern, url, re.IGNORECASE):
                            rule_matched = True
                            break
                    except re.error as err:
                        logger.warning(
                            "Invalid regex pattern '%s' in rule #%s: %s",
                            pattern,
                            rule.id,
                            err,
                        )

            # Optional trigger_text matching (supports comma-separated terms)
            if not rule_matched and rule.trigger_text:
                full_text = f"{title or ''} {description or ''}"
                patterns = [
                    p.strip() for p in rule.trigger_text.split(",") if p.strip()
                ]
                for pattern in patterns:
                    if pattern.lower() in full_text.lower():
                        rule_matched = True
                        break

            if rule_matched:
                matching.append(rule)

        return matching

    def _get_matching_block_entry(
        self,
        cleaned_url: str,
        raw_url: Optional[str] = None,
    ) -> Optional[BlockEntry]:
        """
        Queries BlockEntry table to check whether any BlockEntry.url matches any part of the candidate link.

        :param cleaned_url: Sanitized candidate URL
        :param raw_url: Optional raw candidate URL prior to sanitization
        :return: Matching BlockEntry instance or None
        """
        try:
            block_repo = BlockEntryRepository(self.session)
            return block_repo.get_matching_entry(cleaned_url, raw_url=raw_url)
        except Exception as err:
            logger.warning("Error querying block entries: %s", err)
            return None

    def can_build(
        self,
        url: str,
        source: Optional[SourcesTable] = None,
        status_code: int = 200,
        check_duplicates: bool = True,
        ignore_policy: bool = False,
        title: Optional[str] = None,
        description: Optional[str] = None,
    ) -> Tuple[bool, Optional[str]]:
        """
        Evaluates whether a candidate URL is permissible according to URL validity,
        ConfigurationEntry acceptance policies, EntryRules regex matching,
        BlockEntry substring matching, and de-duplication.

        :param url: Candidate URL string
        :param source: Optional originating SourcesTable source
        :param status_code: HTTP response status code for dead link evaluation
        :param check_duplicates: If True, rejects URLs already existing in database
        :param ignore_policy: If True, bypasses ConfigurationEntry accept_* flags (for explicit overrides)
        :param title: Optional candidate title for text-based rule triggers
        :param description: Optional candidate description for text-based rule triggers
        :return: Tuple of (allowed: bool, rejection_reason: Optional[str])
        """
        raw = (url or "").strip()
        if not raw:
            reason = "URL is empty or undefined."
            self.last_rejection_reason = reason
            return False, reason

        cleaned_url = self.sanitize_url(raw)
        loc = webtoolkit.UrlLocation(cleaned_url)

        # 1. Basic Web URL validation
        is_onion = loc.is_onion()
        is_web = loc.is_web_link()

        if not is_web and not is_onion:
            if not self._get_config_bool("accept_unknown_links", default=False):
                reason = (
                    "Invalid URL scheme: only web protocols (HTTP/HTTPS) are supported."
                )
                self.last_rejection_reason = reason
                return False, reason

        # 2. Configuration Policy Verification
        if not ignore_policy:
            # Tor / Onion check
            if is_onion and not self._get_config_bool(
                "accept_onion_links", default=False
            ):
                reason = "Tor/Onion links are not accepted by current configuration."
                self.last_rejection_reason = reason
                return False, reason

            # IP link check
            if loc.is_ip() and not self._get_config_bool(
                "accept_ip_links", default=True
            ):
                reason = "IP address links are not accepted by current configuration."
                self.last_rejection_reason = reason
                return False, reason

            if loc.is_domain() and not self._get_config_bool(
                "accept_domain_links", default=True
            ):
                reason = "Domain links are not accepted by current configuration."
                self.last_rejection_reason = reason
                return False, reason

            if not loc.is_domain() and not self._get_config_bool(
                "accept_non_domain_links", default=True
            ):
                reason = "Non domain links are not accepted by current configuration."
                self.last_rejection_reason = reason
                return False, reason

            # Dead link check
            if status_code >= 400 and not self._get_config_bool(
                "accept_dead_links", default=False
            ):
                reason = f"Dead links (status {status_code}) are not accepted by current configuration."
                self.last_rejection_reason = reason
                return False, reason

        # 3. EntryRules Evaluation (Blocking regex)
        matching_rules = self._get_matching_rules(
            cleaned_url, source=source, title=title, description=description
        )
        for rule in matching_rules:
            if rule.block:
                reason = f"URL blocked by entry rule '{rule.rule_name}'."
                self.last_rejection_reason = reason
                return False, reason

        # 4. BlockEntry Evaluation (Blocked URLs, domains, and substrings)
        matching_block = self._get_matching_block_entry(cleaned_url, raw_url=raw)
        if matching_block:
            reason = f"URL blocked by block entry '{matching_block.url}'."
            self.last_rejection_reason = reason
            return False, reason

        # 5. De-duplication Check
        if check_duplicates and self.is_duplicate(cleaned_url):
            reason = f"Duplicate entry: URL '{cleaned_url}' already exists."
            self.last_rejection_reason = reason
            return False, reason

        self.last_rejection_reason = None
        return True, None

    def is_link_acceptable(
        self,
        url: str,
        source: Optional[SourcesTable] = None,
        status_code: int = 200,
        check_duplicates: bool = True,
        ignore_policy: bool = False,
        title: Optional[str] = None,
        description: Optional[str] = None,
    ) -> Tuple[bool, Optional[str]]:
        """
        Evaluates whether a candidate link is acceptable according to URL validity,
        configuration policies, EntryRules regex matching, BlockEntry matching,
        and de-duplication.

        Alias and wrapper around can_build().

        :param url: Candidate URL string
        :param source: Optional parent source
        :param status_code: HTTP response status code
        :param check_duplicates: If True, rejects URLs already existing in database
        :param ignore_policy: If True, bypasses ConfigurationEntry accept_* flags
        :param title: Optional candidate title for text-based rule triggers
        :param description: Optional candidate description for text-based rule triggers
        :return: Tuple of (acceptable: bool, rejection_reason: Optional[str])
        """
        return self.can_build(
            url=url,
            source=source,
            status_code=status_code,
            check_duplicates=check_duplicates,
            ignore_policy=ignore_policy,
            title=title,
            description=description,
        )

    def build_entry(
        self,
        link: str,
        title: Optional[str] = None,
        description: Optional[str] = None,
        source: Optional[SourcesTable] = None,
        thumbnail: Optional[str] = None,
        author: Optional[str] = None,
        album: Optional[str] = None,
        language: Optional[str] = None,
        age: Optional[int] = None,
        date_published: Optional[datetime] = None,
        status_code: int = 200,
        tags: Optional[List[str]] = None,
        check_duplicates: bool = True,
        ignore_policy: bool = False,
        **kwargs: Any,
    ) -> Tuple[Optional[LinkDataModel], List[str]]:
        """
        Validates, applies source inheritance, matches rules, and instantiates a LinkDataModel instance
        along with its resolved tag list.

        :param link: Raw candidate web link
        :param title: Page or media title
        :param description: Summary or article description
        :param source: Optional parent SourcesTable row
        :param thumbnail: Thumbnail image URL
        :param author: Author, artist, or channel
        :param album: Album name
        :param language: Language code
        :param age: Age restriction rating (e.g. 18)
        :param date_published: Publication timestamp
        :param status_code: HTTP status code
        :param tags: Explicit tags to attach
        :param check_duplicates: If True, rejects existing links
        :param ignore_policy: If True, bypasses ConfigurationEntry accept_* flags
        :param kwargs: Additional fields passed to LinkDataModel
        :return: Tuple of (LinkDataModel instance or None, resolved list of tag strings)
        """
        allowed, reason = self.can_build(
            link,
            source=source,
            status_code=status_code,
            check_duplicates=check_duplicates,
            ignore_policy=ignore_policy,
            title=title,
            description=description,
        )
        if not allowed:
            logger.info("Entry candidate '%s' rejected: %s", link, reason)
            return None, []

        cleaned_url = self.sanitize_url(link)
        now_utc = datetime.now(timezone.utc)

        # 1. Evaluate matching EntryRules
        matching_rules = self._get_matching_rules(
            cleaned_url, source=source, title=title, description=description
        )
        manual_status_code = status_code
        rule_tags: List[str] = []
        rule_age_limit = 0

        for rule in matching_rules:
            if rule.trust:
                manual_status_code = 200
            if rule.auto_tag:
                for t in re.split(r"[,\s]+", rule.auto_tag):
                    clean_t = t.strip().lstrip("#")
                    if clean_t:
                        rule_tags.append(clean_t)
            if rule.apply_age_limit and rule.apply_age_limit > rule_age_limit:
                rule_age_limit = rule.apply_age_limit

        # 2. Source Property Inheritance
        final_source_url = source.url if source else kwargs.pop("source_url", None)
        final_source_id = source.id if source else kwargs.pop("source_id", None)
        final_language = language or (source.language if source else None) or ""
        final_thumbnail = thumbnail or (source.favicon if source else None) or None

        source_age = source.age if source and source.age else 0
        candidate_age = age or 0
        final_age = max(candidate_age, source_age, rule_age_limit)

        source_tags: List[str] = []
        if source and source.auto_tag:
            for t in re.split(r"[,]+", source.auto_tag):
                clean_t = t.strip().lstrip("#")
                if clean_t:
                    source_tags.append(clean_t)

        # 3. Tag Merging and De-duplication
        all_tags = (tags or []) + source_tags + rule_tags
        resolved_tags = sorted(
            list({t.strip().lstrip("#").lower() for t in all_tags if t.strip()})
        )

        # Resolve publication date
        now_utc = datetime.now(timezone.utc)
        resolved_date_published = date_published
        if isinstance(resolved_date_published, str) and resolved_date_published.strip():
            try:
                resolved_date_published = datetime.fromisoformat(
                    resolved_date_published
                )
            except Exception:
                try:
                    from email.utils import parsedate_to_datetime

                    resolved_date_published = parsedate_to_datetime(
                        resolved_date_published
                    )
                except Exception:
                    resolved_date_published = None
        if not resolved_date_published:
            resolved_date_published = now_utc

        # 4. LinkDataModel Instantiation
        bookmarked = kwargs.pop("bookmarked", False)
        permanent = kwargs.pop("permanent", False)

        entry = LinkDataModel(
            link=cleaned_url,
            source_url=final_source_url,
            source_id=final_source_id,
            title=title or cleaned_url,
            description=description or "",
            thumbnail=final_thumbnail,
            author=author or "",
            album=album or "",
            language=final_language,
            age=final_age,
            date_published=resolved_date_published,
            date_created=now_utc,
            date_update_last=now_utc,
            status_code=status_code,
            manual_status_code=manual_status_code,
            bookmarked=bookmarked,
            permanent=permanent,
            contents_type=0,
            page_rating_contents=0,
            page_rating_votes=0,
            page_rating_visits=0,
            page_rating=0,
            **kwargs,
        )

        return entry, resolved_tags

    def build_and_save(
        self,
        link: str,
        title: Optional[str] = None,
        description: Optional[str] = None,
        source: Optional[SourcesTable] = None,
        thumbnail: Optional[str] = None,
        author: Optional[str] = None,
        album: Optional[str] = None,
        language: Optional[str] = None,
        age: Optional[int] = None,
        date_published: Optional[datetime] = None,
        status_code: int = 200,
        tags: Optional[List[str]] = None,
        commit: bool = True,
        check_duplicates: bool = True,
        ignore_policy: bool = False,
        enqueue_update_job: bool = False,
        **kwargs: Any,
    ) -> Optional[LinkDataModel]:
        """
        Builds, persists to database, and associates tags with the newly created entry.

        :param link: Raw candidate web link
        :param title: Page or media title
        :param description: Summary or article description
        :param source: Optional parent SourcesTable row
        :param thumbnail: Thumbnail image URL
        :param author: Author, artist, or channel
        :param album: Album name
        :param language: Language code
        :param age: Age restriction rating (e.g. 18)
        :param date_published: Publication timestamp
        :param status_code: HTTP status code
        :param tags: Explicit tags to attach
        :param commit: If True, commits the transaction immediately; if False, flushes
        :param check_duplicates: If True, rejects existing links
        :param ignore_policy: If True, bypasses ConfigurationEntry accept_* flags
        :param enqueue_update_job: If True, enqueues JOB_LINK_UPDATE_DATA ('link-update-data') background job
        :param kwargs: Additional fields passed to LinkDataModel
        :return: Created LinkDataModel instance or None if rejected
        """
        entry, resolved_tags = self.build_entry(
            link=link,
            title=title,
            description=description,
            source=source,
            thumbnail=thumbnail,
            author=author,
            album=album,
            language=language,
            age=age,
            date_published=date_published,
            status_code=status_code,
            tags=tags,
            check_duplicates=check_duplicates,
            ignore_policy=ignore_policy,
            **kwargs,
        )

        if entry is None:
            return None

        try:
            self.session.add(entry)
            self.session.flush()

            # Persist associated tags
            if resolved_tags:
                for tag_str in resolved_tags:
                    self.session.add(EntryCompactedTags(entry_id=entry.id, tag=tag_str))
                self.session.flush()

            # Handle auto_add_to_read_later from source
            if source and getattr(source, "auto_add_to_read_later", False):
                from linkarchivetools.model.definitions import ReadLater

                self.session.add(ReadLater(entry_id=entry.id, user_id=1))
                self.session.flush()

            # Enqueue link-update-data job (when added by user or explicitly requested)
            if enqueue_update_job:
                from yafr.db.job_repository import JobRepository

                job_repo = JobRepository(self.session)
                job_repo.enqueue_job(
                    job="link-update-data",
                    subject=str(entry.id),
                    priority=2,
                    enabled=True,
                )
                self.session.flush()

            if commit:
                self.session.commit()

            return entry
        except Exception as err:
            self.session.rollback()
            err_msg = f"Database error: {err}"
            self.last_rejection_reason = err_msg
            logger.error("Failed to persist entry '%s': %s", link, err)
            return None

    @classmethod
    def create(
        cls,
        link: str,
        session: Optional[Session] = None,
        **kwargs: Any,
    ) -> Optional[LinkDataModel]:
        """
        Convenience factory method to build and persist an entry.

        :param link: URL of the entry
        :param session: Optional SQLAlchemy session
        :param kwargs: Additional builder arguments
        :return: Created LinkDataModel instance or None
        """
        builder = cls(session=session)
        return builder.build_and_save(link=link, **kwargs)


# Specification and architectural alias for backwards-compatibility
EntryLinkBuilder = EntryBuilder
