"""
Block Entry and Block Entry List Repository Implementation for YAFR.

Manages block lists (e.g. EasyList, adblock, hosts files, plain text lists)
in the blockentrylist table and individual block entries in the blockentry table.
Supports reading plain text files, splitting them into clean BlockEntry records,
and persistent database operations.
"""

from io import StringIO
import logging
from pathlib import Path
import re
from typing import Any, Iterable, List, Optional, Sequence, Set, TextIO, Union

from sqlalchemy import delete, func, or_, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session
from linkarchivetools.model.definitions import BlockEntry, BlockEntryList

from yafr.db.base_repository import BaseRepository

logger = logging.getLogger(__name__)


def split_block_list_text(text: str) -> List[str]:
    """
    Parses plain text block list content (such as EasyList, hosts files,
    or plain URL/domain lists) and splits it into a list of block entry strings.

    - Ignores comment lines starting with '!', '#', or '['.
    - Parses hosts file entries (e.g., '0.0.0.0 ad.example.com' or '127.0.0.1 tracker.com').
    - Strips whitespace and trailing comments.
    - Deduplicates entries while preserving original discovery order.
    - Ensures entries fit within column constraints (1 to 1000 characters).

    :param text: Raw plain text content
    :return: List of clean block entry URLs / patterns
    """
    entries: List[str] = []
    seen: Set[str] = set()

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("!", "[", "#")):
            continue

        # Check for hosts file format: 127.0.0.1, 0.0.0.0, ::1
        if line.startswith(("127.0.0.1", "0.0.0.0", "::1")):
            line = line.split("#", 1)[0].strip()
            parts = line.split()
            if len(parts) >= 2:
                for domain in parts[1:]:
                    d = domain.strip().lower()
                    if (
                        d
                        and d
                        not in ("localhost", "localhost.localdomain", "broadcasthost")
                        and d not in seen
                    ):
                        if 1 <= len(d) <= 1000:
                            seen.add(d)
                            entries.append(d)
                continue

        # Strip trailing inline comments for domain/URL entries
        if " #" in line or "\t#" in line:
            line = line.split("#", 1)[0].strip()

        if 1 <= len(line) <= 1000 and line not in seen:
            seen.add(line)
            entries.append(line)

    return entries


def read_and_split_block_list_file(
    file_path_or_obj: Union[str, Path, TextIO],
    encoding: str = "utf-8",
) -> List[str]:
    """
    Reads a plain text block list from a file path or file-like object
    and splits it into BlockEntry strings.

    :param file_path_or_obj: File path (str/Path) or open text file object
    :param encoding: File text encoding (default 'utf-8')
    :return: List of clean block entry URLs / patterns
    """
    if hasattr(file_path_or_obj, "read"):
        content = file_path_or_obj.read()  # type: ignore[union-attr]
    else:
        path = Path(file_path_or_obj)
        content = path.read_text(encoding=encoding, errors="replace")

    return split_block_list_text(content)


def fetch_and_split_block_list_url(url: str, timeout: int = 15) -> List[str]:
    """
    Fetches a plain text block list from a URL and splits it into BlockEntry strings.

    Tries WebToolsWrapper first if available; falls back to urllib.request.

    :param url: URL of the plain text block list
    :param timeout: Network request timeout in seconds
    :return: List of clean block entry URLs / patterns
    """
    content: Optional[str] = None

    try:
        from yafr.services.webtools_service import WebToolsWrapper

        content = WebToolsWrapper.fetch_text(url=url)
    except Exception as exc:
        logger.debug(
            "WebToolsWrapper.fetch_text failed for %s: %s; falling back to urllib",
            url,
            exc,
        )

    if not content:
        import urllib.request

        req = urllib.request.Request(
            url,
            headers={"User-Agent": "YAFR-BlockList-Fetcher/1.0"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw_bytes = resp.read()
            content = raw_bytes.decode("utf-8", errors="replace")

    return split_block_list_text(content or "")


class BlockEntryListRepository(BaseRepository[BlockEntryList]):
    """
    Data access repository for BlockEntryList (urls to plain text block list files).
    """

    def __init__(self, session: Optional[Session] = None) -> None:
        super().__init__(session=session)

    def list_lists(
        self,
        processed: Optional[bool] = None,
        order_by: str = "id",
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> List[BlockEntryList]:
        """
        Lists block entry lists with optional processed filter.

        :param processed: If specified, filter by processed status (True/False)
        :param order_by: Sorting field ('id' or 'url')
        :param limit: Maximum rows to return
        :param offset: Number of rows to skip
        :return: List of BlockEntryList instances
        """
        stmt = select(BlockEntryList)
        if processed is not None:
            stmt = stmt.where(BlockEntryList.processed == processed)

        if order_by == "url":
            stmt = stmt.order_by(BlockEntryList.url.asc())
        else:
            stmt = stmt.order_by(BlockEntryList.id.asc())

        if offset is not None:
            stmt = stmt.offset(offset)
        if limit is not None:
            stmt = stmt.limit(limit)

        return list(self.session.execute(stmt).scalars().all())

    def get_list(self, list_id: int) -> Optional[BlockEntryList]:
        """
        Retrieves a block entry list by primary key ID.

        :param list_id: Primary key ID
        :return: BlockEntryList instance or None
        """
        return self.get_by_id(BlockEntryList, list_id)

    def get_list_by_url(self, url: str) -> Optional[BlockEntryList]:
        """
        Retrieves a block entry list by URL.

        :param url: URL string
        :return: BlockEntryList instance or None
        """
        stmt = select(BlockEntryList).where(BlockEntryList.url == url.strip()).limit(1)
        return self.session.execute(stmt).scalar_one_or_none()

    def add_list(self, url: str, processed: bool = False) -> BlockEntryList:
        """
        Creates and persists a new BlockEntryList record.

        :param url: URL pointing to a plain text block list
        :param processed: Initial processed flag (default False)
        :return: Persisted BlockEntryList instance
        """
        cleaned_url = url.strip()
        obj = BlockEntryList(url=cleaned_url, processed=processed)
        self.add(obj)
        self.commit()
        return obj

    def update_list(
        self,
        list_id: int,
        url: Optional[str] = None,
        processed: Optional[bool] = None,
    ) -> Optional[BlockEntryList]:
        """
        Updates an existing BlockEntryList record.

        :param list_id: Primary key ID
        :param url: Optional new URL
        :param processed: Optional new processed flag
        :return: Updated BlockEntryList instance or None
        """
        obj = self.get_list(list_id)
        if not obj:
            return None

        if url is not None:
            obj.url = url.strip()
        if processed is not None:
            obj.processed = processed

        self.commit()
        return obj

    def mark_processed(
        self, list_id: int, processed: bool = True
    ) -> Optional[BlockEntryList]:
        """
        Marks a block entry list as processed (or unprocessed).

        :param list_id: Primary key ID
        :param processed: Target boolean state
        :return: Updated BlockEntryList or None
        """
        return self.update_list(list_id, processed=processed)

    def delete_list(self, list_id: int, delete_entries: bool = True) -> bool:
        """
        Deletes a block entry list and optionally deletes all associated BlockEntry items.

        :param list_id: Primary key ID
        :param delete_entries: If True, deletes child BlockEntry records referencing this list
        :return: True if deleted, False if not found
        """
        obj = self.get_list(list_id)
        if not obj:
            return False

        if delete_entries:
            del_stmt = delete(BlockEntry).where(BlockEntry.block_list_id == list_id)
            self.session.execute(del_stmt)

        self.delete(obj)
        self.commit()
        return True

    def delete_lists(self, list_ids: Iterable[int], delete_entries: bool = True) -> int:
        """
        Deletes multiple BlockEntryList records by ID and optionally deletes child BlockEntry items.

        :param list_ids: Iterable of primary key IDs
        :param delete_entries: If True, deletes child BlockEntry records referencing these lists
        :return: Count of deleted lists
        """
        ids = [int(i) for i in list_ids if i is not None]
        if not ids:
            return 0

        if delete_entries:
            del_entries_stmt = delete(BlockEntry).where(
                BlockEntry.block_list_id.in_(ids)
            )
            self.session.execute(del_entries_stmt)

        del_lists_stmt = delete(BlockEntryList).where(BlockEntryList.id.in_(ids))
        res = self.session.execute(del_lists_stmt)
        self.commit()
        return max(0, res.rowcount)

    def count_lists(self, processed: Optional[bool] = None) -> int:
        """
        Counts block entry lists matching optional processed filter.

        :param processed: Optional processed state filter
        :return: Count of lists
        """
        clauses = []
        if processed is not None:
            clauses.append(BlockEntryList.processed == processed)
        return self.count(BlockEntryList, *clauses)


class BlockEntryRepository(BaseRepository[BlockEntry]):
    """
    Data access repository for BlockEntry items (blocked URLs, domains, and patterns).
    """

    def __init__(self, session: Optional[Session] = None) -> None:
        super().__init__(session=session)

    def list_entries(
        self,
        block_list_id: Optional[int] = None,
        search: Optional[str] = None,
        order_by: str = "id",
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> List[BlockEntry]:
        """
        Lists block entries with optional filtering by block list ID or search substring.

        :param block_list_id: Optional filtering by origin block_list_id
        :param search: Substring search within entry url
        :param order_by: Sorting field ('id' or 'url')
        :param limit: Maximum rows to return
        :param offset: Number of rows to skip
        :return: List of BlockEntry instances
        """
        stmt = select(BlockEntry)
        if block_list_id is not None:
            stmt = stmt.where(BlockEntry.block_list_id == block_list_id)
        if search:
            stmt = stmt.where(BlockEntry.url.contains(search.strip()))

        if order_by == "url":
            stmt = stmt.order_by(BlockEntry.url.asc())
        else:
            stmt = stmt.order_by(BlockEntry.id.asc())

        if offset is not None:
            stmt = stmt.offset(offset)
        if limit is not None:
            stmt = stmt.limit(limit)

        return list(self.session.execute(stmt).scalars().all())

    def get_entry(self, entry_id: int) -> Optional[BlockEntry]:
        """
        Retrieves a block entry by primary key ID.

        :param entry_id: Primary key ID
        :return: BlockEntry instance or None
        """
        return self.get_by_id(BlockEntry, entry_id)

    def get_entry_by_url(self, url: str) -> Optional[BlockEntry]:
        """
        Retrieves a block entry by exact URL.

        :param url: URL to look up
        :return: BlockEntry instance or None
        """
        stmt = select(BlockEntry).where(BlockEntry.url == url.strip()).limit(1)
        return self.session.execute(stmt).scalar_one_or_none()

    def get_matching_entry(
        self,
        url: str,
        raw_url: Optional[str] = None,
    ) -> Optional[BlockEntry]:
        """
        Retrieves the first BlockEntry whose url matches any part of the given URL.

        Performs a case-insensitive substring search: if any BlockEntry.url matches
        any part of url (or raw_url), returns the matching BlockEntry.

        :param url: Candidate URL string
        :param raw_url: Optional raw URL string before sanitization
        :return: Matching BlockEntry instance or None
        """
        cleaned = (url or "").strip()
        raw = (raw_url or "").strip()
        if not cleaned and not raw:
            return None

        cleaned_lower = cleaned.lower()
        raw_lower = raw.lower()

        conditions = []
        if cleaned_lower:
            conditions.append(func.instr(cleaned_lower, func.lower(BlockEntry.url)) > 0)
        if raw_lower and raw_lower != cleaned_lower:
            conditions.append(func.instr(raw_lower, func.lower(BlockEntry.url)) > 0)

        if not conditions:
            return None

        stmt = (
            select(BlockEntry)
            .where(
                func.length(func.trim(BlockEntry.url)) > 0,
                or_(*conditions) if len(conditions) > 1 else conditions[0],
            )
            .limit(1)
        )

        try:
            return self.session.execute(stmt).scalar_one_or_none()
        except Exception as err:
            logger.debug(
                "Database instr query failed (%s); falling back to iteration", err
            )
            stmt_all = select(BlockEntry).where(
                func.length(func.trim(BlockEntry.url)) > 0
            )
            entries = self.session.execute(stmt_all).scalars().all()
            for entry in entries:
                pattern = (entry.url or "").strip().lower()
                if not pattern:
                    continue
                if (cleaned_lower and pattern in cleaned_lower) or (
                    raw_lower and pattern in raw_lower
                ):
                    return entry
            return None

    def is_blocked(self, url: str) -> bool:
        """
        Checks whether a URL is blocked (either exact match or if any BlockEntry.url matches any part of url).

        :param url: URL to check
        :return: True if blocked, False otherwise
        """
        return self.get_matching_entry(url) is not None

    def add_entry(self, url: str, block_list_id: Optional[int] = None) -> BlockEntry:
        """
        Creates and persists a single BlockEntry record.

        :param url: Blocked URL or pattern
        :param block_list_id: Optional originating BlockEntryList ID
        :return: Persisted BlockEntry instance
        """
        cleaned_url = url.strip()
        obj = BlockEntry(url=cleaned_url, block_list_id=block_list_id)
        self.add(obj)
        self.commit()
        return obj

    def add_entries(
        self,
        urls: Iterable[str],
        block_list_id: Optional[int] = None,
        batch_size: int = 500,
    ) -> int:
        """
        Batch-inserts multiple URLs into the BlockEntry table, ignoring duplicate entries.

        Uses SQLite ON CONFLICT DO NOTHING for high throughput and safety.

        :param urls: Iterable of URL strings to insert
        :param block_list_id: Optional origin block list ID
        :param batch_size: Chunk size for bulk insertions (default 500)
        :return: Count of newly inserted records
        """
        inserted_total = 0
        batch: List[dict] = []
        seen_in_batch: Set[str] = set()

        for u in urls:
            cleaned = (u or "").strip()
            if not cleaned or len(cleaned) > 1000 or cleaned in seen_in_batch:
                continue
            seen_in_batch.add(cleaned)
            batch.append({"url": cleaned, "block_list_id": block_list_id})

            if len(batch) >= batch_size:
                inserted_total += self._insert_batch(batch)
                batch.clear()
                seen_in_batch.clear()

        if batch:
            inserted_total += self._insert_batch(batch)
            batch.clear()

        self.commit()
        return inserted_total

    def _insert_batch(self, records: List[dict]) -> int:
        """Executes a single batch insertion with conflict resolution."""
        if not records:
            return 0
        try:
            stmt = sqlite_insert(BlockEntry).values(records).on_conflict_do_nothing()
            result = self.session.execute(stmt)
            return max(0, result.rowcount)
        except Exception:
            # Fallback for non-sqlite or unexpected errors: insert item-by-item
            count = 0
            for r in records:
                try:
                    existing = self.get_entry_by_url(r["url"])
                    if not existing:
                        self.session.add(BlockEntry(**r))
                        self.session.flush()
                        count += 1
                except Exception as err:
                    logger.debug("Failed inserting entry %s: %s", r.get("url"), err)
                    self.session.rollback()
            return count

    def delete_entry(self, entry_id: int) -> bool:
        """
        Deletes a single BlockEntry by primary key ID.

        :param entry_id: Primary key ID
        :return: True if deleted, False if not found
        """
        obj = self.get_entry(entry_id)
        if not obj:
            return False
        self.delete(obj)
        self.commit()
        return True

    def delete_entries(self, entry_ids: Iterable[int]) -> int:
        """
        Deletes multiple BlockEntry records by ID.

        :param entry_ids: Iterable of primary key IDs
        :return: Count of deleted entries
        """
        ids = [int(i) for i in entry_ids if i is not None]
        if not ids:
            return 0
        stmt = delete(BlockEntry).where(BlockEntry.id.in_(ids))
        res = self.session.execute(stmt)
        self.commit()
        return max(0, res.rowcount)

    def delete_by_list_id(self, block_list_id: int) -> int:
        """
        Deletes all BlockEntry records belonging to a given BlockEntryList ID.

        :param block_list_id: Originating block list ID
        :return: Count of deleted rows
        """
        stmt = delete(BlockEntry).where(BlockEntry.block_list_id == block_list_id)
        result = self.session.execute(stmt)
        self.commit()
        return max(0, result.rowcount)

    def count_entries(
        self,
        block_list_id: Optional[int] = None,
        search: Optional[str] = None,
    ) -> int:
        """
        Counts block entries, optionally filtered by block_list_id and search string.

        :param block_list_id: Optional origin block list ID filter
        :param search: Optional search substring within entry url
        :return: Count of entries
        """
        stmt = select(func.count(BlockEntry.id))
        if block_list_id is not None:
            stmt = stmt.where(BlockEntry.block_list_id == block_list_id)
        if search:
            stmt = stmt.where(BlockEntry.url.contains(search.strip()))
        return self.session.execute(stmt).scalar() or 0

    def clear_all(self) -> int:
        """
        Deletes all BlockEntry records.

        :return: Count of deleted rows
        """
        stmt = delete(BlockEntry)
        result = self.session.execute(stmt)
        self.commit()
        return max(0, result.rowcount)


class BlockRepository(BaseRepository[BlockEntryList]):
    """
    Unified repository providing high-level management for both BlockEntryList
    and BlockEntry, including reading plain text files, splitting them into
    BlockEntry records, and synchronizing lists.
    """

    def __init__(self, session: Optional[Session] = None) -> None:
        super().__init__(session=session)
        self.list_repo = BlockEntryListRepository(self.session)
        self.entry_repo = BlockEntryRepository(self.session)

    # ------------------------------------------------------------------
    # BlockEntryList operations
    # ------------------------------------------------------------------

    def list_lists(
        self,
        processed: Optional[bool] = None,
        order_by: str = "id",
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> List[BlockEntryList]:
        return self.list_repo.list_lists(
            processed=processed, order_by=order_by, limit=limit, offset=offset
        )

    def get_list(self, list_id: int) -> Optional[BlockEntryList]:
        return self.list_repo.get_list(list_id)

    def get_list_by_url(self, url: str) -> Optional[BlockEntryList]:
        return self.list_repo.get_list_by_url(url)

    def add_list(self, url: str, processed: bool = False) -> BlockEntryList:
        return self.list_repo.add_list(url=url, processed=processed)

    def update_list(
        self,
        list_id: int,
        url: Optional[str] = None,
        processed: Optional[bool] = None,
    ) -> Optional[BlockEntryList]:
        return self.list_repo.update_list(list_id=list_id, url=url, processed=processed)

    def mark_processed(
        self, list_id: int, processed: bool = True
    ) -> Optional[BlockEntryList]:
        return self.list_repo.mark_processed(list_id=list_id, processed=processed)

    def delete_list(self, list_id: int, delete_entries: bool = True) -> bool:
        return self.list_repo.delete_list(
            list_id=list_id, delete_entries=delete_entries
        )

    def delete_lists(self, list_ids: Iterable[int], delete_entries: bool = True) -> int:
        return self.list_repo.delete_lists(list_ids, delete_entries=delete_entries)

    def count_lists(self, processed: Optional[bool] = None) -> int:
        return self.list_repo.count_lists(processed=processed)

    # ------------------------------------------------------------------
    # BlockEntry operations
    # ------------------------------------------------------------------

    def list_entries(
        self,
        block_list_id: Optional[int] = None,
        search: Optional[str] = None,
        order_by: str = "id",
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> List[BlockEntry]:
        return self.entry_repo.list_entries(
            block_list_id=block_list_id,
            search=search,
            order_by=order_by,
            limit=limit,
            offset=offset,
        )

    def get_entry(self, entry_id: int) -> Optional[BlockEntry]:
        return self.entry_repo.get_entry(entry_id)

    def get_entry_by_url(self, url: str) -> Optional[BlockEntry]:
        return self.entry_repo.get_entry_by_url(url)

    def get_matching_entry(
        self, url: str, raw_url: Optional[str] = None
    ) -> Optional[BlockEntry]:
        return self.entry_repo.get_matching_entry(url, raw_url=raw_url)

    def is_blocked(self, url: str) -> bool:
        return self.entry_repo.is_blocked(url)

    def add_entry(self, url: str, block_list_id: Optional[int] = None) -> BlockEntry:
        return self.entry_repo.add_entry(url=url, block_list_id=block_list_id)

    def add_entries(
        self,
        urls: Iterable[str],
        block_list_id: Optional[int] = None,
        batch_size: int = 500,
    ) -> int:
        return self.entry_repo.add_entries(
            urls=urls, block_list_id=block_list_id, batch_size=batch_size
        )

    def delete_entry(self, entry_id: int) -> bool:
        return self.entry_repo.delete_entry(entry_id)

    def delete_entries(self, entry_ids: Iterable[int]) -> int:
        return self.entry_repo.delete_entries(entry_ids)

    def delete_entries_by_list(self, block_list_id: int) -> int:
        return self.entry_repo.delete_by_list_id(block_list_id)

    def count_entries(self, block_list_id: Optional[int] = None) -> int:
        return self.entry_repo.count_entries(block_list_id=block_list_id)

    def clear_entries(self) -> int:
        return self.entry_repo.clear_all()

    # ------------------------------------------------------------------
    # Parsing, Reading, and Processing Block Lists
    # ------------------------------------------------------------------

    def parse_text(self, text: str) -> List[str]:
        """
        Splits plain text block list content into individual clean entry URLs / patterns.
        """
        return split_block_list_text(text)

    def read_file(
        self,
        file_path_or_obj: Union[str, Path, TextIO],
        encoding: str = "utf-8",
    ) -> List[str]:
        """
        Reads a plain text file and splits into block entries.
        """
        return read_and_split_block_list_file(file_path_or_obj, encoding=encoding)

    def fetch_url(self, url: str, timeout: int = 15) -> List[str]:
        """
        Fetches a remote plain text block list and splits into block entries.
        """
        return fetch_and_split_block_list_url(url, timeout=timeout)

    def process_block_list(
        self,
        list_id: int,
        content: Optional[str] = None,
        batch_size: int = 500,
    ) -> int:
        """
        Processes a BlockEntryList:
        1. Retrieves the BlockEntryList record by list_id.
        2. Obtains plain text content (either from `content` parameter or by fetching `url`).
        3. Splits content into clean entries.
        4. Ingests all entries into BlockEntry associated with list_id.
        5. Sets `processed = True` on the BlockEntryList record.
        6. Commits and returns the count of newly inserted entries.

        :param list_id: BlockEntryList primary key ID
        :param content: Optional plain text content to avoid network fetch
        :param batch_size: Chunk size for bulk insertions
        :return: Count of newly inserted entries
        """
        block_list = self.get_list(list_id)
        if not block_list:
            raise ValueError(f"BlockEntryList with ID {list_id} does not exist.")

        if content is None:
            entries = self.fetch_url(block_list.url)
        else:
            entries = self.parse_text(content)

        inserted_count = self.add_entries(
            urls=entries,
            block_list_id=list_id,
            batch_size=batch_size,
        )

        block_list.processed = True
        self.commit()
        return inserted_count
