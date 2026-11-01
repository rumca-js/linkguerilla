"""
Predefined and Dynamic Search Filters for YAFR.

Encapsulates system filters (by Date published, Read Later, Visited,
by Votes, by Visits) and manages custom search views from SQLite searchview table.
"""

from dataclasses import dataclass
import logging
from typing import List, Optional
from sqlalchemy import select
from sqlalchemy.orm import Session
from linkarchivetools.model.definitions import SearchView
from yafr.db import get_session

logger = logging.getLogger(__name__)


@dataclass
class SearchFilter:
    """
    Representation of a selectable search filter option.

    :param id: Unique filter identifier string
    :param name: Human-readable display label
    :param is_default: Whether this filter is the default selection
    :param hover_text: Optional tooltip description
    """

    id: str
    name: str
    is_default: bool = False
    hover_text: Optional[str] = None


SYSTEM_FILTERS = [
    SearchFilter(
        id="date_published",
        name="by Date published",
        is_default=True,
        hover_text="Order entries by publication date descending",
    ),
    SearchFilter(
        id="read_later",
        name="Read Later",
        is_default=False,
        hover_text="Show only entries saved for reading later",
    ),
    SearchFilter(
        id="visited",
        name="Visited",
        is_default=False,
        hover_text="Show only entries previously visited",
    ),
    SearchFilter(
        id="votes",
        name="by Votes",
        is_default=False,
        hover_text="Order entries by rating votes descending",
    ),
    SearchFilter(
        id="visits",
        name="by Visits",
        is_default=False,
        hover_text="Order entries by total visit count descending",
    ),
]


class FilterRegistry:
    """
    Registry providing system filters and custom views defined in SQLite.
    """

    @classmethod
    def get_system_filters(cls) -> List[SearchFilter]:
        """
        Returns the core system filters.
        """
        return list(SYSTEM_FILTERS)

    @classmethod
    def get_available_filters(
        cls, session: Optional[Session] = None
    ) -> List[SearchFilter]:
        """
        Retrieves all available filters: predefined system filters combined with
        any custom search views stored in the SQLite searchview table.

        :param session: Optional active database session
        :return: List of SearchFilter instances
        """
        filters = [
            SearchFilter(f.id, f.name, f.is_default, f.hover_text)
            for f in SYSTEM_FILTERS
        ]
        try:
            db_session = session or get_session()
            stmt = select(SearchView).order_by(
                SearchView.priority.asc(), SearchView.id.asc()
            )
            custom_views = db_session.execute(stmt).scalars().all()

            # Ensure ONLY ONE filter can be default across all system and custom filters
            custom_default = next((v for v in custom_views if v.default), None)
            if custom_default:
                for f in filters:
                    f.is_default = False
            else:
                for idx, f in enumerate(filters):
                    f.is_default = idx == 0

            for view in custom_views:
                if not any(f.id == f"custom_{view.id}" for f in filters):
                    is_this_default = bool(
                        custom_default and view.id == custom_default.id
                    )
                    filters.append(
                        SearchFilter(
                            id=f"custom_{view.id}",
                            name=view.name,
                            is_default=is_this_default,
                            hover_text=view.hover_text,
                        )
                    )
        except Exception as err:
            logger.debug("Failed to query custom SearchView records: %s", err)

        # "default" filter should be always on top in UI combos
        default_idx = next((i for i, f in enumerate(filters) if f.is_default), -1)
        if default_idx > 0:
            default_item = filters.pop(default_idx)
            filters.insert(0, default_item)

        return filters

    @classmethod
    def get_search_view(
        cls, filter_id: Optional[str], session: Optional[Session] = None
    ) -> Optional[SearchView]:
        """
        Retrieves a custom SearchView if the filter_id represents one (e.g. 'custom_42').

        :param filter_id: Filter ID string
        :param session: Optional active database session
        :return: SearchView instance or None
        """
        if not filter_id or not str(filter_id).startswith("custom_"):
            return None
        try:
            view_id = int(str(filter_id).replace("custom_", ""))
            db_session = session or get_session()
            return db_session.get(SearchView, view_id)
        except Exception as err:
            logger.debug(
                "Failed to retrieve SearchView for filter '%s': %s", filter_id, err
            )
            return None

    @classmethod
    def get_filter(
        cls, filter_id: Optional[str], session: Optional[Session] = None
    ) -> SearchFilter:
        """
        Resolves a filter by ID, falling back to 'date_published' default.

        :param filter_id: Filter ID string
        :param session: Optional active database session
        :return: Matching SearchFilter
        """
        all_filters = cls.get_available_filters(session=session)
        if filter_id:
            for f in all_filters:
                if f.id == filter_id:
                    return f
            return SYSTEM_FILTERS[0]

        # If filter_id is None or empty, return default filter if defined
        for f in all_filters:
            if f.is_default:
                return f

        return SYSTEM_FILTERS[0]
