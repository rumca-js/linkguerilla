"""
History Repository Implementation for YAFR.

Manages browsing history, search query history (with FIFO storage limits),
entry visit tracking, transition paths, and Read Later bookmarks.
"""

from datetime import datetime, timezone
import logging
from typing import List, Optional, Set
from sqlalchemy import delete, distinct, func, select, update
from sqlalchemy.orm import Session
from linkarchivetools.model.definitions import (
    EntryTransitionHistory,
    EntryVisitHistory,
    LinkDataModel,
    ReadLater,
    SearchHistory,
)
from yafr.db.base_repository import BaseRepository

logger = logging.getLogger(__name__)


class HistoryRepository(BaseRepository[SearchHistory]):
    """
    Data access repository for search history, visits, transitions, and read later entries.
    """

    def __init__(self, session: Optional[Session] = None) -> None:
        super().__init__(session=session)

    # -------------------------------------------------------------------------
    # Search History
    # -------------------------------------------------------------------------

    def add_search(
        self, search_query: str, max_limit: int = 300
    ) -> Optional[SearchHistory]:
        """
        Records a search query and enforces the FIFO storage limit.

        :param search_query: Search expression string
        :param max_limit: Maximum allowed search history entries (default: 300)
        :return: Created SearchHistory instance or None if query empty
        """
        cleaned = search_query.strip()
        if not cleaned:
            return None

        entry = SearchHistory(
            search_query=cleaned,
            date=datetime.now(timezone.utc),
        )
        self.session.add(entry)
        self.session.commit()

        # Enforce rolling retention limit
        self.apply_storage_limit(SearchHistory, SearchHistory.id, max_limit)
        return entry

    def get_recent_searches(
        self, query_prefix: Optional[str] = None, limit: int = 10
    ) -> List[str]:
        """
        Retrieves recent distinct search queries for autocomplete assistance.

        :param query_prefix: Optional search text to filter by
        :param limit: Maximum suggestions to return
        :return: List of query strings ordered by recency
        """
        stmt = (
            select(SearchHistory.search_query)
            .distinct()
            .order_by(SearchHistory.id.desc())
        )
        if query_prefix:
            stmt = stmt.where(SearchHistory.search_query.ilike(f"{query_prefix}%"))

        stmt = stmt.limit(limit)
        return list(self.session.execute(stmt).scalars().all())

    def clear_search_history(self) -> int:
        """
        Clears all user search history entries.

        :return: Count of deleted rows
        """
        stmt = delete(SearchHistory)
        result = self.session.execute(stmt)
        self.session.commit()
        return result.rowcount or 0

    def delete_search(self, search_query: str) -> int:
        """Delete every stored occurrence of one exact search expression."""
        cleaned = search_query.strip()
        if not cleaned:
            return 0
        result = self.session.execute(
            delete(SearchHistory).where(SearchHistory.search_query == cleaned)
        )
        self.session.commit()
        return result.rowcount or 0

    # -------------------------------------------------------------------------
    # Entry Visit History
    # -------------------------------------------------------------------------

    def record_visit(self, entry_id: int, max_limit: int = 5000) -> EntryVisitHistory:
        """
        Records an entry visit, incrementing the visit counter and updating timestamp.
        Also updates linkdatamodel.page_rating_visits for sorting.

        :param entry_id: LinkDataModel ID
        :param max_limit: Maximum visit history records to retain (default: 5000)
        :return: Updated EntryVisitHistory instance
        """
        stmt = (
            select(EntryVisitHistory)
            .where(EntryVisitHistory.entry_id == entry_id)
            .limit(1)
        )
        visit_record = self.session.execute(stmt).scalar_one_or_none()

        now = datetime.now(timezone.utc)
        if visit_record is None:
            visit_record = EntryVisitHistory(
                entry_id=entry_id,
                visits=1,
                date_last_visit=now,
            )
            self.session.add(visit_record)
        else:
            visit_record.visits = (visit_record.visits or 0) + 1
            visit_record.date_last_visit = now

        # Synchronize visits counter on LinkDataModel
        entry_stmt = (
            update(LinkDataModel)
            .where(LinkDataModel.id == entry_id)
            .values(page_rating_visits=LinkDataModel.page_rating_visits + 1)
        )
        self.session.execute(entry_stmt)
        self.session.commit()

        # Enforce storage cap
        self.apply_storage_limit(EntryVisitHistory, EntryVisitHistory.id, max_limit)
        return visit_record

    def is_visited(self, entry_id: int) -> bool:
        """
        Checks whether an entry has been visited by the user.

        :param entry_id: LinkDataModel ID
        :return: True if visited, False otherwise
        """
        stmt = (
            select(func.count(EntryVisitHistory.id))
            .where(EntryVisitHistory.entry_id == entry_id)
            .where(EntryVisitHistory.visits > 0)
        )
        count = self.session.execute(stmt).scalar()
        return bool(count and count > 0)

    def get_visited_entry_ids(self) -> Set[int]:
        """
        Returns the set of all visited entry IDs.

        :return: Set of integer entry IDs
        """
        stmt = select(EntryVisitHistory.entry_id).where(EntryVisitHistory.visits > 0)
        return set(self.session.execute(stmt).scalars().all())

    def get_last_visited_entry_id(self) -> Optional[int]:
        """
        Returns the entry ID of the most recently visited entry.

        :return: Entry ID of the last visit, or None if no visits recorded
        """
        stmt = (
            select(EntryVisitHistory.entry_id)
            .order_by(EntryVisitHistory.date_last_visit.desc())
            .limit(1)
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def clear_visit_history(self) -> int:
        """
        Clears all visit history records.

        :return: Count of deleted rows
        """
        stmt = delete(EntryVisitHistory)
        result = self.session.execute(stmt)
        self.session.commit()
        return result.rowcount or 0

    # -------------------------------------------------------------------------
    # Entry Transition History
    # -------------------------------------------------------------------------

    def record_transition(
        self, entry_from_id: int, entry_to_id: int
    ) -> EntryTransitionHistory:
        """
        Logs a user navigation transition from one entry to another.

        :param entry_from_id: Source entry ID
        :param entry_to_id: Destination entry ID
        :return: Updated EntryTransitionHistory instance
        """
        stmt = (
            select(EntryTransitionHistory)
            .where(
                (EntryTransitionHistory.entry_from_id == entry_from_id)
                & (EntryTransitionHistory.entry_to_id == entry_to_id)
            )
            .limit(1)
        )
        transition = self.session.execute(stmt).scalar_one_or_none()

        if transition is None:
            transition = EntryTransitionHistory(
                entry_from_id=entry_from_id,
                entry_to_id=entry_to_id,
                counter=1,
            )
            self.session.add(transition)
        else:
            transition.counter = (transition.counter or 0) + 1

        self.session.commit()
        return transition

    def get_transitions_from(
        self, entry_id: int, limit: int = 10
    ) -> List[EntryTransitionHistory]:
        """
        Retrieves top navigation transitions from a given entry.

        :param entry_id: Originating entry ID
        :param limit: Maximum related transitions to return
        :return: List of EntryTransitionHistory records ordered by transition frequency
        """
        stmt = (
            select(EntryTransitionHistory)
            .where(EntryTransitionHistory.entry_from_id == entry_id)
            .order_by(EntryTransitionHistory.counter.desc())
            .limit(limit)
        )
        return list(self.session.execute(stmt).scalars().all())

    def clear_transition_history(self) -> int:
        """
        Clears all entry transition history records.

        :return: Count of deleted rows
        """
        stmt = delete(EntryTransitionHistory)
        result = self.session.execute(stmt)
        self.session.commit()
        return result.rowcount or 0

    # -------------------------------------------------------------------------
    # Read Later
    # -------------------------------------------------------------------------

    def toggle_read_later(self, entry_id: int) -> bool:
        """
        Toggles the Read Later bookmark state for an entry.

        :param entry_id: LinkDataModel ID
        :return: True if added to Read Later, False if removed
        """
        stmt = select(ReadLater).where(ReadLater.entry_id == entry_id).limit(1)
        existing = self.session.execute(stmt).scalar_one_or_none()

        if existing is not None:
            self.session.delete(existing)
            self.session.commit()
            return False
        else:
            new_item = ReadLater(entry_id=entry_id)
            self.session.add(new_item)
            self.session.commit()
            return True

    def is_read_later(self, entry_id: int) -> bool:
        """
        Checks whether an entry is bookmarked in Read Later.

        :param entry_id: LinkDataModel ID
        :return: True if in Read Later, False otherwise
        """
        stmt = select(func.count(ReadLater.id)).where(ReadLater.entry_id == entry_id)
        count = self.session.execute(stmt).scalar()
        return bool(count and count > 0)

    def get_read_later_entry_ids(self) -> Set[int]:
        """
        Returns the set of all entry IDs marked for reading later.

        :return: Set of integer entry IDs
        """
        stmt = select(ReadLater.entry_id)
        return set(self.session.execute(stmt).scalars().all())

    def clear_read_later(self) -> int:
        """
        Clears all entries marked for Read Later.

        :return: Count of deleted rows
        """
        stmt = delete(ReadLater)
        result = self.session.execute(stmt)
        self.session.commit()
        return result.rowcount or 0
