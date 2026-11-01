"""
Source Service Implementation for YAFR.

Coordinates source lifecycle operations, single and batch fetching,
operational hash checking (page_hash, body_hash), feed entry extraction
into linkdatamodel, consecutive error tracking, and progress polling status.
"""

from datetime import datetime, timedelta, timezone
import hashlib
import logging
import re
import sys
import threading
from typing import Any, Dict, List, Optional, Tuple
import warnings
from bs4 import MarkupResemblesLocatorWarning
from sqlalchemy import func, select
from sqlalchemy.orm import Session
import webtoolkit
from webtoolkit.utils.emailreader import EmailReader
from linkarchivetools.model.definitions import (
    LinkDataModel,
    SourceOperationalData,
    SourcesTable,
)
from linkarchivetools.model.sources import Sources
from yafr.db.block_repository import BlockEntryRepository
from yafr.db.credentials_repository import CredentialsRepository
from yafr.db.logging_repository import LoggingRepository
from yafr.db.rules_repository import RulesRepository
from yafr.db.session import get_session, session_scope
from yafr.db.source_repository import SourceRepository
from yafr.services.entry_builder import EntryBuilder
from yafr.services.webtools_service import WebToolsWrapper

logger = logging.getLogger(__name__)

# Suppress BeautifulSoup markup locator warning
warnings.filterwarnings("ignore", category=MarkupResemblesLocatorWarning)


class SourceService:
    """
    Service coordinating source operations, feed fetching, and background batch updates.
    """

    _lock = threading.Lock()
    _refresh_state: Dict[str, Any] = {
        "is_running": False,
        "total_sources": 0,
        "completed_sources": 0,
        "current_source_title": "",
        "percentage": 0.0,
        "errors_encountered": 0,
    }

    @classmethod
    def get_refresh_status(cls) -> Dict[str, Any]:
        """
        Returns a thread-safe snapshot of the current batch refresh progress.
        """
        with cls._lock:
            return dict(cls._refresh_state)

    @classmethod
    def start_batch_refresh(
        cls,
        source_ids: Optional[List[int]] = None,
        include_errors: bool = True,
    ) -> int:
        """
        Initiates a background thread to refresh outdated or error sources.

        :param source_ids: Specific list of source IDs (if None, all outdated)
        :param include_errors: Whether to also include sources with consecutive errors
        :return: Count of queued sources
        """
        with cls._lock:
            if cls._refresh_state["is_running"]:
                return cls._refresh_state["total_sources"]

        session = get_session()
        source_repo = SourceRepository(session)

        target_ids: List[int] = []
        if source_ids:
            target_ids = list(source_ids)
        else:
            # Query enabled outdated sources
            outdated = source_repo.get_outdated_sources(max_age_seconds=3600)
            target_ids = [s.id for s in outdated]

            if include_errors:
                # Add sources with consecutive errors
                stmt = (
                    select(SourcesTable.id)
                    .join(
                        SourceOperationalData,
                        SourcesTable.id == SourceOperationalData.source_id,
                    )
                    .where(SourcesTable.enabled == True)
                    .where(SourceOperationalData.consecutive_errors > 0)
                )
                error_ids = list(session.execute(stmt).scalars().all())
                for eid in error_ids:
                    if eid not in target_ids:
                        target_ids.append(eid)

        if not target_ids:
            return 0

        with cls._lock:
            cls._refresh_state = {
                "is_running": True,
                "total_sources": len(target_ids),
                "completed_sources": 0,
                "current_source_title": "Starting batch refresh...",
                "percentage": 0.0,
                "errors_encountered": 0,
            }

        worker_thread = threading.Thread(
            target=cls._run_batch_worker,
            args=(target_ids,),
            daemon=True,
            name="SourceBatchRefresher",
        )
        worker_thread.start()
        return len(target_ids)

    @classmethod
    def _run_batch_worker(cls, target_ids: List[int]) -> None:
        """
        Background worker thread executing sequential source fetches.
        """
        total = len(target_ids)
        completed = 0
        errors = 0

        for s_id in target_ids:
            source_title = f"Source #{s_id}"
            try:
                with session_scope() as session:
                    source = session.get(SourcesTable, s_id)
                    if source:
                        source_title = source.title or source.url

                with cls._lock:
                    cls._refresh_state["current_source_title"] = source_title

                res = cls.fetch_source(s_id)
                if not res.get("success"):
                    errors += 1
            except Exception as err:
                logger.error("Batch worker error fetching source %s: %s", s_id, err)
                errors += 1

            completed += 1
            with cls._lock:
                cls._refresh_state["completed_sources"] = completed
                cls._refresh_state["errors_encountered"] = errors
                cls._refresh_state["percentage"] = round((completed / total) * 100.0, 1)

        with cls._lock:
            cls._refresh_state["is_running"] = False
            cls._refresh_state["current_source_title"] = "Batch refresh finished."

    @classmethod
    def fetch_source(
        cls,
        source_id: int,
        session: Optional[Session] = None,
    ) -> Dict[str, Any]:
        """
        Fetches a single source from the internet, verifies hashes, extracts feed entries,
        and persists new LinkDataModel records.

        :param source_id: ID of the source to refresh
        :param session: Optional active database session
        :return: Result dictionary with success, message, status, entries_added
        """
        if session is not None:
            return cls._execute_fetch(source_id, session)
        else:
            with session_scope() as scoped_session:
                return cls._execute_fetch(source_id, scoped_session)

    @classmethod
    def is_source_blocked(
        cls,
        source: SourcesTable,
        session: Session,
    ) -> Tuple[bool, Optional[str]]:
        """
        Evaluates whether a source's URL matches any blocking EntryRules or BlockEntry patterns.

        :param source: SourcesTable instance
        :param session: Active database session
        :return: Tuple of (is_blocked: bool, reason: Optional[str])
        """
        if not source or not source.url:
            return False, None

        raw_url = (source.url or "").strip()
        builder = EntryBuilder(session=session)
        cleaned_url = builder.sanitize_url(raw_url)

        # 1. Check EntryRules with block=True
        matching_rules = builder._get_matching_rules(
            cleaned_url,
            source=source,
            title=source.title,
            description=getattr(source, "description", None),
        )
        for rule in matching_rules:
            if rule.block:
                return True, f"URL blocked by entry rule '{rule.rule_name}'."

        # If raw_url differs, also check against raw_url
        if raw_url and raw_url != cleaned_url:
            raw_matching_rules = builder._get_matching_rules(
                raw_url,
                source=source,
                title=source.title,
                description=getattr(source, "description", None),
            )
            for rule in raw_matching_rules:
                if rule.block:
                    return True, f"URL blocked by entry rule '{rule.rule_name}'."

        # 2. Check BlockEntry repository
        block_repo = BlockEntryRepository(session=session)
        matching_block = block_repo.get_matching_entry(cleaned_url, raw_url=raw_url)
        if matching_block:
            return True, f"URL blocked by block entry '{matching_block.url}'."

        return False, None

    @classmethod
    def _execute_fetch(cls, source_id: int, session: Session) -> Dict[str, Any]:
        source = session.get(SourcesTable, source_id)
        if not source:
            return {
                "success": False,
                "source_id": source_id,
                "error": "Source not found",
                "status": "error",
            }

        # Check if source.url matches entry rules (block), or blockentry
        blocked, reason = cls.is_source_blocked(source, session)
        if blocked:
            source_title = source.title or source.url
            source_url = source.url
            logger.info(
                "Removing source #%d (%s) because it is blocked: %s",
                source_id,
                source_url,
                reason,
            )

            # Record in applogging
            try:
                log_repo = LoggingRepository(session=session)
                log_repo.log(
                    info_text=f"Source #{source_id} removed (blocked)",
                    detail_text=f"Source '{source_title}' ({source_url}) was removed during fetch: {reason}",
                    level=LoggingRepository.WARNING,
                )
            except Exception as log_err:
                logger.warning(
                    "Failed to record source removal in applogging: %s", log_err
                )

            # Remove source and unlink its entries
            source_repo = SourceRepository(session=session)
            source_repo.delete_source(source_id)

            return {
                "success": True,
                "source_id": source_id,
                "status": "removed",
                "message": f"Source #{source_id} removed: {reason}",
                "reason": reason,
            }

        op_data = (
            session.execute(
                select(SourceOperationalData).where(
                    SourceOperationalData.source_id == source_id
                )
            )
            .scalars()
            .first()
        )

        if op_data is None:
            op_data = SourceOperationalData(
                source_id=source_id,
                consecutive_errors=0,
                number_of_entries=0,
            )
            session.add(op_data)
            session.flush()

        if source.source_type == Sources.SOURCE_TYPE_EMAIL:
            return cls._execute_fetch_email(source, op_data, session)
        elif source.source_type == Sources.SOURCE_TYPE_PARSE:
            return cls._execute_fetch_parse(source, op_data, session)
        else:
            return cls._execute_fetch_rss(source, op_data, session)

    @classmethod
    def _record_fetch_error(
        cls,
        source: SourcesTable,
        op_data: SourceOperationalData,
        session: Session,
        error_msg: str,
        status: str = "error",
    ) -> Dict[str, Any]:
        """
        Records a fetch failure on source operational data and commits the error state.

        :param source: SourcesTable instance
        :param op_data: SourceOperationalData record
        :param session: Active database session
        :param error_msg: Descriptive failure message
        :param status: Result status code
        :return: Standard error result dictionary
        """
        op_data.consecutive_errors = (op_data.consecutive_errors or 0) + 1
        op_data.date_fetched = datetime.now(timezone.utc)
        session.commit()
        return {
            "success": False,
            "source_id": source.id,
            "error": error_msg,
            "status": status,
        }

    @classmethod
    def _record_operational_unchanged(
        cls,
        source: SourcesTable,
        op_data: SourceOperationalData,
        session: Session,
    ) -> Dict[str, Any]:
        """
        Updates source operational tracking data when payload hash matches existing hash.

        :param source: SourcesTable instance
        :param op_data: SourceOperationalData record
        :param session: Active database session
        :return: Standard unchanged result dictionary
        """
        logger.info(
            "Source %s (%s) hash unchanged, skipping entry parse",
            source.id,
            source.title,
        )
        now_utc = datetime.now(timezone.utc)
        op_data.date_fetched = now_utc
        op_data.date_successful_fetch = now_utc
        op_data.consecutive_errors = 0
        session.commit()
        return {
            "success": True,
            "source_id": source.id,
            "status": "unchanged",
            "message": "Content unchanged (hash match).",
            "entries_added": 0,
        }

    @classmethod
    def _save_entries(
        cls,
        raw_entries: List[Dict[str, Any]],
        source: SourcesTable,
        session: Session,
    ) -> int:
        """
        Builds and saves LinkDataModel records from extracted raw feed/email entries.

        :param raw_entries: List of dictionaries containing entry metadata
        :param source: SourcesTable instance
        :param session: Active database session
        :return: Number of newly added entries
        """
        builder = EntryBuilder(session=session)
        entries_added = 0

        for item in raw_entries:
            link = (item.get("link") or "").strip()
            if not link:
                continue

            if source and source.xpath and source.xpath.strip():
                try:
                    if not re.match(source.xpath.strip(), link):
                        continue
                except re.error as err:
                    logger.warning(
                        "Invalid re.match pattern '%s' for source #%s: %s",
                        source.xpath,
                        source.id,
                        err,
                    )

            entry_age = item.get("age")
            if entry_age is None and source is not None:
                entry_age = source.age if source.age is not None else 0

            created_entry = builder.build_and_save(
                link=link,
                title=item.get("title"),
                description=item.get("description"),
                source=source,
                thumbnail=item.get("thumbnail"),
                author=item.get("author"),
                album=item.get("album"),
                language=item.get("language"),
                age=entry_age,
                date_published=item.get("date_published"),
                tags=item.get("tags") if isinstance(item.get("tags"), list) else None,
                commit=False,
            )
            if created_entry is not None:
                entries_added += 1

        session.flush()
        return entries_added

    @classmethod
    def _update_operational_success(
        cls,
        source: SourcesTable,
        op_data: SourceOperationalData,
        session: Session,
        page_hash: Optional[bytes] = None,
        body_hash: Optional[bytes] = None,
        entries_added: int = 0,
    ) -> Dict[str, Any]:
        """
        Updates source operational tracking data after a successful fetch cycle.

        :param source: SourcesTable instance
        :param op_data: SourceOperationalData record
        :param session: Active database session
        :param page_hash: Optional SHA-256 payload hash (bytes)
        :param body_hash: Optional SHA-256 body hash (bytes)
        :param entries_added: Number of newly inserted entries
        :return: Standard success result dictionary
        """
        total_source_entries = (
            session.execute(
                select(func.count(LinkDataModel.id)).where(
                    LinkDataModel.source_id == source.id
                )
            ).scalar()
            or 0
        )

        now_utc = datetime.now(timezone.utc)
        op_data.page_hash = page_hash
        op_data.body_hash = body_hash
        op_data.number_of_entries = total_source_entries
        op_data.consecutive_errors = 0
        op_data.date_fetched = now_utc
        op_data.date_successful_fetch = now_utc

        session.commit()

        return {
            "success": True,
            "source_id": source.id,
            "status": "completed",
            "message": f"Successfully refreshed {source.title}: {entries_added} new entries added.",
            "entries_added": entries_added,
        }

    @classmethod
    def _execute_source_pipeline(
        cls,
        source: SourcesTable,
        op_data: SourceOperationalData,
        session: Session,
        extractor: Any,
    ) -> Dict[str, Any]:
        """
        Unified fetch pipeline coordinating protocol-specific extraction, change detection,
        entry persistence via EntryBuilder, and operational data tracking.

        :param source: SourcesTable record
        :param op_data: SourceOperationalData record
        :param session: Active database session
        :param extractor: Extractor class implementing extract(source, op_data, session)
        :return: Standard result dictionary
        """
        result = extractor.extract(source, op_data, session)
        if result.error:
            return cls._record_fetch_error(source, op_data, session, result.error)

        if result.is_unchanged:
            return cls._record_operational_unchanged(source, op_data, session)

        entries_added = cls._save_entries(result.raw_entries, source, session)
        return cls._update_operational_success(
            source=source,
            op_data=op_data,
            session=session,
            page_hash=result.page_hash,
            body_hash=result.body_hash,
            entries_added=entries_added,
        )

    @classmethod
    def _execute_fetch_rss(cls, source, op_data, session: Session) -> Dict[str, Any]:
        """
        Executes fetch pipeline for RSS and web feeds.
        """
        return cls._execute_source_pipeline(
            source, op_data, session, RssSourceExtractor
        )

    @classmethod
    def get_email_link(cls, source, creds, email):
        """
        Constructs standard internal URI for email messages.
        """
        return "email://{}/{}/{}".format(source.url, creds.username, email.id)

    @classmethod
    def _execute_fetch_email(cls, source, op_data, session: Session) -> Dict[str, Any]:
        """
        Executes fetch pipeline for email sources.
        """
        return cls._execute_source_pipeline(
            source, op_data, session, EmailSourceExtractor
        )

    @classmethod
    def _execute_fetch_parse(cls, source, op_data, session: Session) -> Dict[str, Any]:
        """
        Executes fetch pipeline for email sources.
        """
        return cls._execute_source_pipeline(
            source, op_data, session, ParseSourceExtractor
        )


class FetchExtractionResult:
    """
    Data container holding the result of a source extraction operation.
    """

    def __init__(
        self,
        raw_entries: Optional[List[Dict[str, Any]]] = None,
        page_hash: Optional[bytes] = None,
        body_hash: Optional[bytes] = None,
        is_unchanged: bool = False,
        error: Optional[str] = None,
    ) -> None:
        self.raw_entries = raw_entries or []
        self.page_hash = page_hash
        self.body_hash = body_hash
        self.is_unchanged = is_unchanged
        self.error = error


class RssSourceExtractor:
    """
    Extractor strategy for RSS / Atom / Web feeds using WebToolsWrapper.
    Handles network download, hash calculation, and feed entry parsing.
    """

    @classmethod
    def extract(
        cls,
        source: SourcesTable,
        op_data: SourceOperationalData,
        session: Session,
    ) -> FetchExtractionResult:
        try:
            web_client = WebToolsWrapper(url=source.url, session=session, timeout_s=15)
            response = web_client.get_response()
            if response is None:
                raise ConnectionError(
                    f"Failed to fetch content from {source.url} (no response received)"
                )

            if not response.is_valid():
                status = response.get_status_code()
                err_detail = (
                    "; ".join(response.errors)
                    if getattr(response, "errors", None)
                    else ""
                )
                raise ConnectionError(
                    f"HTTP status {status} when fetching {source.url}"
                    + (f": {err_detail}" if err_detail else "")
                )

            content_str = web_client.get_text()
            if content_str is None:
                raise ValueError(f"No text content returned for source {source.url}")

            content_binary = response.get_binary()
            if content_binary is not None:
                content_bytes = content_binary
            else:
                content_bytes = content_str.encode("utf-8", errors="replace")

        except Exception as err:
            logger.warning(
                "Failed to fetch source %s (%s): %s", source.id, source.url, err
            )
            return FetchExtractionResult(error=f"Network download error: {err}")

        # Calculate hashes
        page_hash = hashlib.sha256(content_bytes).digest()
        body_hash = page_hash

        # Check for operational hash equality
        if op_data.page_hash and op_data.page_hash == page_hash:
            return FetchExtractionResult(
                page_hash=page_hash,
                body_hash=body_hash,
                is_unchanged=True,
            )

        # Parse RSS / Feed entries
        try:
            raw_entries = web_client.get_entries() or []
            if source.xpath and source.xpath.strip():
                pattern = source.xpath.strip()
                filtered = []
                for entry in raw_entries:
                    link = (entry.get("link") or "").strip()
                    try:
                        if re.match(pattern, link):
                            filtered.append(entry)
                    except re.error as err:
                        logger.warning(
                            "Invalid re.match pattern '%s' for source %s: %s",
                            pattern,
                            source.id,
                            err,
                        )
                        filtered.append(entry)
                raw_entries = filtered
        except Exception as err:
            logger.warning("Error parsing RSS feed for source %s: %s", source.id, err)
            return FetchExtractionResult(error=f"Feed parsing error: {err}")

        return FetchExtractionResult(
            raw_entries=raw_entries,
            page_hash=page_hash,
            body_hash=body_hash,
            is_unchanged=False,
        )


class EmailSourceExtractor:
    """
    Extractor strategy for email sources using EmailReader.
    Handles credentials lookup, IMAP connection, and email retrieval.
    Does not compute content hashes.
    """

    @classmethod
    def extract(
        cls,
        source: SourcesTable,
        op_data: SourceOperationalData,
        session: Session,
    ) -> FetchExtractionResult:
        try:
            creds_repo = CredentialsRepository(session=session)
            creds = creds_repo.get_credential(source.credentials_id)
            if not creds:
                raise ValueError(
                    f"Credentials not found for email source {source.id} (credentials_id={source.credentials_id})"
                )

            web_client = EmailReader(server=source.url)
            connect_status = web_client.connect(
                username=creds.username, password=creds.password
            )

            if not connect_status:
                raise ConnectionError(
                    f"Email connection error when fetching {source.url}"
                )

        except Exception as err:
            logger.warning(
                "Failed to fetch source %s (%s): %s", source.id, source.url, err
            )
            return FetchExtractionResult(error=f"Network download error: {err}")

        # Retrieve emails and convert to raw entry dictionaries
        try:
            raw_entries = []
            emails = web_client.get_emails()
            for email in emails:
                raw_entries.append(
                    {
                        "title": email.title,
                        "date_published": email.date_published,
                        "description": email.body,
                        "author": email.author,
                        "link": SourceService.get_email_link(source, creds, email),
                    }
                )
        except Exception as err:
            logger.warning("Error reading emails for source %s: %s", source.id, err)
            return FetchExtractionResult(error=f"Email reading error: {err}")

        return FetchExtractionResult(
            raw_entries=raw_entries,
            page_hash=None,
            body_hash=None,
            is_unchanged=False,
        )


class ParseSourceExtractor:
    """
    Extractor strategy for email sources using EmailReader.
    Handles credentials lookup, IMAP connection, and email retrieval.
    Does not compute content hashes.
    """

    @classmethod
    def extract(
        cls,
        source: SourcesTable,
        op_data: SourceOperationalData,
        session: Session,
    ) -> FetchExtractionResult:
        try:
            web_client = WebToolsWrapper(url=source.url, session=session, timeout_s=15)
            response = web_client.get_response()
            if response is None:
                raise ConnectionError(
                    f"Failed to fetch content from {source.url} (no response received)"
                )

            if not response.is_valid():
                status = response.get_status_code()
                err_detail = (
                    "; ".join(response.errors)
                    if getattr(response, "errors", None)
                    else ""
                )
                raise ConnectionError(
                    f"HTTP status {status} when fetching {source.url}"
                    + (f": {err_detail}" if err_detail else "")
                )

        except Exception as err:
            logger.warning(
                "Failed to fetch source %s (%s): %s", source.id, source.url, err
            )
            return FetchExtractionResult(error=f"Network download error: {err}")

        page_hash = web_client.get_hash()
        body_hash = web_client.get_body_hash()

        # Check for operational hash equality
        if op_data.page_hash and op_data.page_hash == page_hash:
            return FetchExtractionResult(
                page_hash=page_hash,
                body_hash=body_hash,
                is_unchanged=True,
            )

        try:
            links = web_client.get_content_links()
            raw_entries = []
            pattern = (
                source.xpath.strip() if source.xpath and source.xpath.strip() else None
            )
            for link in links:
                if pattern:
                    try:
                        if not re.match(pattern, link):
                            continue
                    except re.error as err:
                        logger.warning(
                            "Invalid re.match pattern '%s' for source %s: %s",
                            pattern,
                            source.id,
                            err,
                        )
                builder = EntryBuilder(session=session)
                if builder.can_build(url=link):
                    raw_entries.append({"link": link})
                    # TODO add background job to update link

        except Exception as err:
            logger.warning("Error extracting links for source %s: %s", source.id, err)
            return FetchExtractionResult(error=f"Link extraction error: {err}")

        return FetchExtractionResult(
            raw_entries=raw_entries,
            page_hash=page_hash,
            body_hash=body_hash,
            is_unchanged=False,
        )
