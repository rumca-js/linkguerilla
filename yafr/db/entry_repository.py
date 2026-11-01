"""
Entry Repository Implementation for YAFR.

Handles database operations for LinkDataModel entries, associated tags,
social metrics, manual status codes, voting, and dependent cascade deletions.
"""

from datetime import datetime, timezone
import logging
from typing import Any, Dict, Iterable, List, Optional, Set
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.orm import Session
from linkarchivetools.model.definitions import (
    CompactedTags,
    EntryCompactedTags,
    EntryTransitionHistory,
    EntryVisitHistory,
    LinkDataModel,
    ReadLater,
    SocialData,
    SourceOperationalData,
    UserBookmarks,
    UserEntryTransitionHistory,
    UserEntryVisitHistory,
    UserTags,
    UserVotes,
)
from yafr.db.base_repository import BaseRepository

logger = logging.getLogger(__name__)


class EntryRepository(BaseRepository[LinkDataModel]):
    """
    Data access repository for link archive entries (linkdatamodel).
    """

    def __init__(self, session: Optional[Session] = None) -> None:
        super().__init__(session=session)

    def get_by_id(self, entry_id: int) -> Optional[LinkDataModel]:
        """
        Retrieves a LinkDataModel entry by primary key ID.

        :param entry_id: Entry ID
        :return: LinkDataModel or None
        """
        return self.session.get(LinkDataModel, entry_id)

    def get_by_link(self, link: str) -> Optional[LinkDataModel]:
        """
        Retrieves an entry by its unique canonical URL/link.

        :param link: Web link URL
        :return: LinkDataModel or None
        """
        stmt = select(LinkDataModel).where(LinkDataModel.link == link).limit(1)
        return self.session.execute(stmt).scalar_one_or_none()

    def add_entry(
        self,
        link: str,
        title: Optional[str] = None,
        description: Optional[str] = None,
        source_id: Optional[int] = None,
        source_url: Optional[str] = None,
        thumbnail: Optional[str] = None,
        author: Optional[str] = None,
        language: Optional[str] = None,
        date_published: Optional[datetime] = None,
        **kwargs: Any,
    ) -> LinkDataModel:
        """
        Persists a new entry into the linkdatamodel table.

        :param link: Canonical entry URL
        :param title: Page or video title
        :param description: Entry summary or text description
        :param source_id: Foreign key to source
        :param source_url: Source feed URL
        :param thumbnail: Thumbnail image URL
        :param author: Entry author or channel name
        :param language: Language code
        :param date_published: Publication timestamp
        :return: Created LinkDataModel instance
        """
        now = datetime.now(timezone.utc)
        bookmarked = kwargs.pop("bookmarked", False)
        entry = LinkDataModel(
            link=link,
            title=title,
            description=description,
            source_id=source_id,
            source_url=source_url,
            thumbnail=thumbnail,
            author=author,
            language=language,
            bookmarked=bookmarked,
            date_created=now,
            date_published=date_published or now,
            **kwargs,
        )
        self.session.add(entry)
        self.session.commit()
        return entry

    def update_entry(self, entry_id: int, **kwargs: Any) -> Optional[LinkDataModel]:
        """
        Updates metadata fields on an existing entry.

        :param entry_id: Entry ID to update
        :param kwargs: Fields and new values
        :return: Updated LinkDataModel or None
        """
        entry = self.get_by_id(entry_id)
        if not entry:
            return None

        for key, val in kwargs.items():
            if hasattr(entry, key):
                setattr(entry, key, val)

        entry.date_last_modified = datetime.now(timezone.utc)
        self.session.commit()
        return entry

    def delete_entry(self, entry_id: int) -> bool:
        """
        Deletes an entry along with all dependent foreign records across related tables:
        - entrycompactedtags
        - socialdata
        - readlater
        - entryvisithistory
        - entrytransitionhistory (both incoming and outgoing)
        - usertags, userbookmarks, uservotes, userentryvisithistory, userentrytransitionhistory

        :param entry_id: Entry ID to delete
        :return: True if entry was deleted, False if not found
        """
        entry = self.get_by_id(entry_id)
        if not entry:
            return False

        # Cascade dependent records
        self._cascade_delete_dependencies([entry_id])

        # Delete parent entry
        self.session.delete(entry)
        self.session.commit()
        logger.info("Deleted entry id=%d and dependent records", entry_id)
        return True

    def delete_entries(self, entry_ids: Iterable[int]) -> int:
        """
        Batch deletes multiple entries and their dependent records.

        :param entry_ids: Collection of entry IDs to delete
        :return: Count of deleted entries
        """
        id_list = list(entry_ids)
        if not id_list:
            return 0

        self._cascade_delete_dependencies(id_list)

        stmt = delete(LinkDataModel).where(LinkDataModel.id.in_(id_list))
        result = self.session.execute(stmt)
        self.session.commit()
        return result.rowcount or 0

    def _cascade_delete_dependencies(self, entry_ids: List[int]) -> None:
        """
        Removes all dependent rows linked to entry_ids across all satellite tables.
        """
        if not entry_ids:
            return

        self.session.execute(
            delete(EntryCompactedTags).where(EntryCompactedTags.entry_id.in_(entry_ids))
        )
        self.session.execute(
            delete(SocialData).where(SocialData.entry_id.in_(entry_ids))
        )
        self.session.execute(delete(ReadLater).where(ReadLater.entry_id.in_(entry_ids)))
        self.session.execute(
            delete(EntryVisitHistory).where(EntryVisitHistory.entry_id.in_(entry_ids))
        )
        self.session.execute(
            delete(EntryTransitionHistory).where(
                EntryTransitionHistory.entry_from_id.in_(entry_ids)
                | EntryTransitionHistory.entry_to_id.in_(entry_ids)
            )
        )
        self.session.execute(delete(UserTags).where(UserTags.entry_id.in_(entry_ids)))
        self.session.execute(
            delete(UserBookmarks).where(UserBookmarks.entry_object.in_(entry_ids))
        )
        self.session.execute(
            delete(UserVotes).where(UserVotes.entry_object.in_(entry_ids))
        )
        self.session.execute(
            delete(UserEntryVisitHistory).where(
                UserEntryVisitHistory.entry_id.in_(entry_ids)
            )
        )
        self.session.execute(
            delete(UserEntryTransitionHistory).where(
                UserEntryTransitionHistory.entry_from_id.in_(entry_ids)
                | UserEntryTransitionHistory.entry_to_id.in_(entry_ids)
            )
        )

    def set_manual_status(self, entry_id: int, status_code: int) -> bool:
        """
        Sets manual status code for entry:
        - 200: Active / alive
        - 400: Dead link

        :param entry_id: Entry ID
        :param status_code: Integer status code (e.g. 200 or 400)
        :return: True if updated, False if entry not found
        """
        entry = self.get_by_id(entry_id)
        if not entry:
            return False

        entry.manual_status_code = status_code
        if status_code == 400:
            entry.date_dead_since = datetime.now(timezone.utc)
        elif status_code == 200:
            entry.date_dead_since = None

        self.session.commit()
        return True

    def vote_entry(self, entry_id: int, vote: int) -> Optional[int]:
        """
        Records a user rating vote for an entry, clamped to [-100, 100].

        :param entry_id: Entry ID
        :param vote: Integer vote value (-100 to 100)
        :return: Updated page_rating_votes or None if entry not found
        """
        clamped_vote = max(-100, min(100, vote))
        entry = self.get_by_id(entry_id)
        if not entry:
            return None

        entry.page_rating_votes = clamped_vote
        self.session.commit()
        return entry.page_rating_votes

    def toggle_bookmark(self, entry_id: int) -> Optional[bool]:
        """
        Toggles bookmarked status for an entry.

        :param entry_id: Entry ID
        :return: New bookmark state (True/False) or None if entry not found
        """
        entry = self.get_by_id(entry_id)
        if not entry:
            return None

        entry.bookmarked = not bool(entry.bookmarked)
        self.session.commit()
        return entry.bookmarked

    def get_tags(self, entry_id: int) -> List[str]:
        """
        Retrieves all tag strings associated with an entry.

        :param entry_id: Entry ID
        :return: List of tag strings
        """
        stmt = (
            select(EntryCompactedTags.tag)
            .where(EntryCompactedTags.entry_id == entry_id)
            .order_by(EntryCompactedTags.tag.asc())
        )
        tags = list(self.session.execute(stmt).scalars().all())
        all_tags = []
        for tag in tags:
            split = tag.split(",")
            for item in split:
                if item.strip():
                    all_tags.append(item)

        return all_tags

    def set_tags(self, entry_id: int, tags: List[str]) -> List[str]:
        """
        Replaces the set of tags associated with an entry.

        Updates entrycompactedtags and adjusts compactedtags counters.

        :param entry_id: Entry ID
        :param tags: New list of tag strings
        :return: Updated list of tags
        """
        clean_tags = sorted(
            list({t.strip().lstrip("#").lower() for t in tags if t.strip()})
        )

        # Remove existing entry tags
        self.session.execute(
            delete(EntryCompactedTags).where(EntryCompactedTags.entry_id == entry_id)
        )

        for tag_str in clean_tags:
            self.session.add(EntryCompactedTags(entry_id=entry_id, tag=tag_str))

        self.session.commit()
        return clean_tags

    def get_social_data(self, entry_id: int) -> Optional[SocialData]:
        """
        Retrieves social metrics for an entry.

        :param entry_id: Entry ID
        :return: SocialData instance or None
        """
        stmt = select(SocialData).where(SocialData.entry_id == entry_id).limit(1)
        return self.session.execute(stmt).scalar_one_or_none()

    def clear_all_social_data(self) -> int:
        """
        Clears all records in the socialdata table.

        :return: Count of deleted rows
        """
        stmt = delete(SocialData)
        result = self.session.execute(stmt)
        self.session.commit()
        return result.rowcount or 0

    def clear_all_entries(self) -> Dict[str, int]:
        """
        Clears all records from linkdatamodel and all tables that depend on it:
        - entrycompactedtags
        - compactedtags
        - socialdata
        - readlater
        - entryvisithistory
        - entrytransitionhistory
        - usertags
        - userbookmarks
        - uservotes
        - userentryvisithistory
        - userentrytransitionhistory
        - usercomments (if table exists)
        - usercompactedtags (if table exists)
        Also resets number_of_entries on sourceoperationaldata.

        :return: Dict mapping table names to deleted row counts
        """
        counts: Dict[str, int] = {}

        # 1. Dependent satellite tables
        satellite_models = [
            (EntryCompactedTags, "entrycompactedtags"),
            (CompactedTags, "compactedtags"),
            (SocialData, "socialdata"),
            (ReadLater, "readlater"),
            (EntryVisitHistory, "entryvisithistory"),
            (EntryTransitionHistory, "entrytransitionhistory"),
            (UserTags, "usertags"),
            (UserBookmarks, "userbookmarks"),
            (UserVotes, "uservotes"),
            (UserEntryVisitHistory, "userentryvisithistory"),
            (UserEntryTransitionHistory, "userentrytransitionhistory"),
        ]

        for model, name in satellite_models:
            res = self.session.execute(delete(model))
            counts[name] = res.rowcount or 0

        # Optional raw tables without direct ORM definitions
        for raw_table in ["usercomments", "usercompactedtags"]:
            try:
                res = self.session.execute(text(f"DELETE FROM {raw_table}"))
                counts[raw_table] = res.rowcount or 0
            except Exception:
                counts[raw_table] = 0

        # 2. Reset sourceoperationaldata.number_of_entries to 0
        try:
            self.session.execute(
                update(SourceOperationalData).values(number_of_entries=0)
            )
        except Exception:
            pass

        # 3. Delete parent linkdatamodel entries
        res = self.session.execute(delete(LinkDataModel))
        counts["linkdatamodel"] = res.rowcount or 0

        self.session.commit()
        logger.info("Cleared all entries and dependent records: %s", counts)
        return counts
