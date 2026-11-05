"""
Source Repository Implementation for YAFR.

Manages RSS, Email, and Parse sources (sourcedatamodel) and their
corresponding operational metrics (sourceoperationaldata).
"""

from datetime import datetime, timedelta, timezone
import logging
from typing import Any, Dict, List, Optional
from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session
from linkarchivetools.model.definitions import (
    LinkDataModel,
    SourceOperationalData,
    SourcesTable,
)
from yafr.db.base_repository import BaseRepository

logger = logging.getLogger(__name__)


class SourceRepository(BaseRepository[SourcesTable]):
    """
    Data access repository for sources and their operational tracking data.
    """

    def __init__(self, session: Optional[Session] = None) -> None:
        super().__init__(session=session)

    def get_by_id(self, source_id: int) -> Optional[SourcesTable]:
        """
        Retrieves a source by primary key ID.

        :param source_id: Source ID
        :return: SourcesTable instance or None
        """
        return self.session.get(SourcesTable, source_id)

    def get_by_url(self, url: str) -> Optional[SourcesTable]:
        """
        Retrieves a source by unique URL.

        :param url: Source feed or endpoint URL
        :return: SourcesTable instance or None
        """
        stmt = select(SourcesTable).where(SourcesTable.url == url).limit(1)
        return self.session.execute(stmt).scalar_one_or_none()

    def list_sources(
        self,
        enabled_only: bool = False,
        order_by: str = "url",
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> List[SourcesTable]:
        """
        Lists sources with optional filtering and ordering.

        :param enabled_only: If True, only returns enabled sources
        :param order_by: Ordering mode ('url', 'title', 'id')
        :param limit: Maximum rows to return
        :param offset: Number of rows to skip
        :return: List of SourcesTable instances
        """
        stmt = select(SourcesTable)
        if enabled_only:
            stmt = stmt.where(SourcesTable.enabled == True)

        if order_by == "title":
            stmt = stmt.order_by(SourcesTable.title.asc())
        elif order_by == "id":
            stmt = stmt.order_by(SourcesTable.id.asc())
        else:
            stmt = stmt.order_by(SourcesTable.url.asc())

        if offset is not None:
            stmt = stmt.offset(offset)
        if limit is not None:
            stmt = stmt.limit(limit)

        return list(self.session.execute(stmt).scalars().all())

    def add_source(
        self,
        url: str,
        title: Optional[str] = None,
        source_type: Optional[str] = "rss",
        enabled: bool = True,
        favicon: Optional[str] = None,
        credentials_id: Optional[int] = None,
        xpath: Optional[str] = None,
        fetch_period: Optional[int] = None,
        **kwargs: Any,
    ) -> SourcesTable:
        """
        Persists a new source and initializes its operational data record.

        :param url: Unique feed URL
        :param title: Display title
        :param source_type: 'rss', 'email', or 'parse'
        :param enabled: Enabled status
        :param favicon: Favicon URL
        :param credentials_id: Foreign key to credentials (for email sources)
        :param xpath: XPath parser expression (for parse sources)
        :param fetch_period: Custom refresh interval in seconds
        :return: Persisted SourcesTable instance
        """
        source = SourcesTable(
            url=url,
            title=title or url,
            source_type=source_type,
            enabled=enabled,
            favicon=favicon,
            credentials_id=credentials_id,
            xpath=xpath,
            fetch_period=fetch_period,
            **kwargs,
        )
        self.session.add(source)
        self.session.flush()

        # Initialize operational data record
        op_data = SourceOperationalData(
            source_id=source.id,
            consecutive_errors=0,
            number_of_entries=0,
        )
        self.session.add(op_data)
        self.session.commit()
        return source

    def update_source(self, source_id: int, **kwargs: Any) -> Optional[SourcesTable]:
        """
        Updates fields on a source.

        :param source_id: Source ID
        :param kwargs: Fields to update
        :return: Updated SourcesTable or None
        """
        source = self.get_by_id(source_id)
        if not source:
            return None

        for key, val in kwargs.items():
            if hasattr(source, key):
                setattr(source, key, val)

        self.session.commit()
        return source

    def delete_source(self, source_id: int) -> bool:
        """
        Deletes a source and its operational tracking data.
        Entries belonging to this source have their source_id unlinked.

        :param source_id: Source ID
        :return: True if deleted, False if not found
        """
        source = self.get_by_id(source_id)
        if not source:
            return False

        # Delete operational data
        self.session.execute(
            delete(SourceOperationalData).where(
                SourceOperationalData.source_id == source_id
            )
        )

        # Unlink entries associated with this source
        stmt = (
            LinkDataModel.__table__.update()
            .where(LinkDataModel.source_id == source_id)
            .values(source_id=None)
        )
        self.session.execute(stmt)

        self.session.delete(source)
        self.session.commit()
        return True

    def delete_sources(self, source_ids: List[int]) -> int:
        """
        Deletes multiple sources and their operational tracking data in batch.
        Entries belonging to these sources have their source_id unlinked.

        :param source_ids: List of source IDs to delete
        :return: Number of deleted sources
        """
        if not source_ids:
            return 0

        # Delete operational data
        self.session.execute(
            delete(SourceOperationalData).where(
                SourceOperationalData.source_id.in_(source_ids)
            )
        )

        # Unlink entries associated with these sources
        stmt = (
            LinkDataModel.__table__.update()
            .where(LinkDataModel.source_id.in_(source_ids))
            .values(source_id=None)
        )
        self.session.execute(stmt)

        res = self.session.execute(
            delete(SourcesTable).where(SourcesTable.id.in_(source_ids))
        )
        self.session.commit()
        return res.rowcount or 0

    def set_enabled(self, source_id: int, enabled: bool) -> bool:
        """
        Enables or disables a source.

        :param source_id: Source ID
        :param enabled: New enabled state
        :return: True if updated, False if not found
        """
        source = self.get_by_id(source_id)
        if not source:
            return False
        source.enabled = enabled
        self.session.commit()
        return True

    def get_operational_data(self, source_id: int) -> Optional[SourceOperationalData]:
        """
        Retrieves operational data for a given source.

        :param source_id: Source ID
        :return: SourceOperationalData or None
        """
        stmt = (
            select(SourceOperationalData)
            .where(SourceOperationalData.source_id == source_id)
            .limit(1)
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def update_operational_data(
        self, source_id: int, **kwargs: Any
    ) -> SourceOperationalData:
        """
        Updates or creates operational data for a source.

        :param source_id: Source ID
        :param kwargs: Operational fields (date_fetched, date_successful_fetch, consecutive_errors, etc.)
        :return: Updated SourceOperationalData instance
        """
        op_data = self.get_operational_data(source_id)
        if op_data is None:
            op_data = SourceOperationalData(source_id=source_id)
            self.session.add(op_data)
            self.session.flush()

        for key, val in kwargs.items():
            if hasattr(op_data, key):
                setattr(op_data, key, val)

        self.session.commit()
        return op_data

    def get_outdated_sources(
        self, max_age_seconds: int = 3600, limit: Optional[int] = None
    ) -> List[SourcesTable]:
        """
        Returns enabled sources that have not been refreshed within max_age_seconds.

        :param max_age_seconds: Maximum elapsed seconds since last fetch (default: 1 hour)
        :param limit: Optional maximum number of sources to return
        :return: List of SourcesTable instances requiring refresh
        """
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=max_age_seconds)
        stmt = (
            select(SourcesTable)
            .outerjoin(
                SourceOperationalData,
                SourcesTable.id == SourceOperationalData.source_id,
            )
            .where(SourcesTable.enabled == True)
            .where(
                (SourceOperationalData.date_fetched == None)
                | (SourceOperationalData.date_fetched < cutoff)
            )
            .order_by(SourceOperationalData.date_fetched.asc().nullsfirst())
        )
        if limit is not None and limit > 0:
            stmt = stmt.limit(limit)
        return list(self.session.execute(stmt).scalars().all())

    def count_outdated_sources(self, max_age_seconds: int = 3600) -> int:
        """
        Counts the number of enabled sources requiring refresh.

        :param max_age_seconds: Age limit in seconds (default: 3600)
        :return: Number of outdated sources
        """
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=max_age_seconds)
        stmt = (
            select(func.count(SourcesTable.id))
            .outerjoin(
                SourceOperationalData,
                SourcesTable.id == SourceOperationalData.source_id,
            )
            .where(SourcesTable.enabled == True)
            .where(
                (SourceOperationalData.date_fetched == None)
                | (SourceOperationalData.date_fetched < cutoff)
            )
        )
        return self.session.execute(stmt).scalar() or 0

    def count_error_sources(self) -> int:
        """
        Counts sources currently in consecutive error state.

        :return: Count of sources with consecutive_errors > 0
        """
        stmt = (
            select(func.count(SourcesTable.id))
            .join(
                SourceOperationalData,
                SourcesTable.id == SourceOperationalData.source_id,
            )
            .where(SourceOperationalData.consecutive_errors > 0)
        )
        return self.session.execute(stmt).scalar() or 0

    def clear_all_sources(self) -> Dict[str, int]:
        """
        Clears all source-related data: sourcedatamodel, sourceoperationaldata,
        sourcecategories, and sourcesubcategories tables.
        Also unlinks entries (sets source_id to NULL on linkdatamodel).

        :return: Dict mapping table names to deleted row counts
        """
        counts: Dict[str, int] = {}

        # Delete operational data first (depends on sourcedatamodel)
        res = self.session.execute(delete(SourceOperationalData))
        counts["sourceoperationaldata"] = res.rowcount or 0

        # Unlink entries associated with any source
        stmt = (
            LinkDataModel.__table__.update()
            .where(LinkDataModel.source_id != None)
            .values(source_id=None)
        )
        self.session.execute(stmt)

        # Delete all sources
        res = self.session.execute(delete(SourcesTable))
        counts["sourcedatamodel"] = res.rowcount or 0

        # Delete sourcecategories and sourcesubcategories (no ORM model, use raw SQL)
        try:
            res = self.session.execute(text("DELETE FROM sourcesubcategories"))
            counts["sourcesubcategories"] = res.rowcount or 0
        except Exception:
            counts["sourcesubcategories"] = 0

        try:
            res = self.session.execute(text("DELETE FROM sourcecategories"))
            counts["sourcecategories"] = res.rowcount or 0
        except Exception:
            counts["sourcecategories"] = 0

        self.session.commit()
        return counts
