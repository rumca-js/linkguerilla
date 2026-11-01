"""
SearchView Repository Implementation for YAFR.

Manages custom saved search views and filter presets configured in the
searchview SQLite table.
"""

import logging
from typing import Any, List, Optional
from sqlalchemy import select, update
from sqlalchemy.orm import Session
from linkarchivetools.model.definitions import SearchView
from yafr.db.base_repository import BaseRepository

logger = logging.getLogger(__name__)


class SearchViewRepository(BaseRepository[SearchView]):
    """
    Data access repository for custom SearchView configurations.
    """

    def __init__(self, session: Optional[Session] = None) -> None:
        super().__init__(session=session)

    def list_views(
        self,
        order_by: str = "priority",
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> List[SearchView]:
        """
        Lists configured search views.

        :param order_by: Sorting field ('priority', 'name', 'id')
        :param limit: Maximum rows to return
        :param offset: Number of rows to skip
        :return: List of SearchView instances
        """
        stmt = select(SearchView)
        if order_by == "name":
            stmt = stmt.order_by(SearchView.name.asc())
        elif order_by == "id":
            stmt = stmt.order_by(SearchView.id.asc())
        else:
            stmt = stmt.order_by(
                SearchView.default.desc(),
                SearchView.priority.asc(),
                SearchView.id.asc(),
            )

        if offset is not None:
            stmt = stmt.offset(offset)
        if limit is not None:
            stmt = stmt.limit(limit)

        return list(self.session.execute(stmt).scalars().all())

    def get_view(self, view_id: int) -> Optional[SearchView]:
        """
        Retrieves a search view by its primary key ID.

        :param view_id: SearchView ID
        :return: SearchView instance or None
        """
        return self.get_by_id(SearchView, view_id)

    def get_by_name(self, name: str) -> Optional[SearchView]:
        """
        Retrieves a search view by exact name.

        :param name: View name
        :return: SearchView instance or None
        """
        stmt = select(SearchView).where(SearchView.name == name)
        return self.session.execute(stmt).scalars().first()

    def create_view(
        self,
        name: str,
        default: bool = False,
        priority: int = 0,
        filter_statement: Optional[str] = None,
        order_by: Optional[str] = None,
        **kwargs: Any,
    ) -> SearchView:
        """
        Creates a new search view.

        :param name: Human-readable unique name
        :param default: Whether this search view is active by default
        :param priority: Integer priority for sequence/sorting
        :param filter_statement: Filter expression (same syntax as user search)
        :param order_by: Sort column expression
        :return: Persisted SearchView instance
        """
        if default:
            self._clear_defaults()

        view = SearchView(
            name=name.strip(),
            default=bool(default),
            priority=int(priority),
            filter_statement=(filter_statement.strip() if filter_statement else ""),
            order_by=(order_by.strip() if order_by else ""),
            hover_text=kwargs.get("hover_text"),
            icon=kwargs.get("icon"),
            entry_limit=kwargs.get("entry_limit", 0),
            auto_fetch=kwargs.get("auto_fetch", False),
            date_published_day_limit=kwargs.get("date_published_day_limit", 0),
            date_created_day_limit=kwargs.get("date_created_day_limit", 0),
            user=kwargs.get("user", False),
        )
        self.session.add(view)
        self.commit()
        self.session.refresh(view)
        logger.info("Created SearchView id=%d name='%s'", view.id, view.name)
        return view

    def update_view(
        self,
        view_id: int,
        **kwargs: Any,
    ) -> Optional[SearchView]:
        """
        Updates an existing search view.

        :param view_id: Primary key of view to update
        :param kwargs: Fields to update (name, default, priority, filter_statement, order_by)
        :return: Updated SearchView instance or None
        """
        view = self.get_view(view_id)
        if not view:
            return None

        if "default" in kwargs and kwargs["default"]:
            self._clear_defaults(exclude_id=view_id)

        for key, value in kwargs.items():
            if hasattr(view, key):
                if key in ("name", "filter_statement", "order_by") and isinstance(
                    value, str
                ):
                    setattr(view, key, value.strip())
                elif key == "priority" and value is not None:
                    setattr(view, key, int(value))
                elif key == "default" and value is not None:
                    setattr(view, key, bool(value))
                else:
                    setattr(view, key, value)

        self.commit()
        self.session.refresh(view)
        logger.info("Updated SearchView id=%d name='%s'", view.id, view.name)
        return view

    def delete_view(self, view_id: int) -> bool:
        """
        Deletes a search view.

        :param view_id: SearchView ID to delete
        :return: True if deleted, False if not found
        """
        view = self.get_view(view_id)
        if not view:
            return False

        self.session.delete(view)
        self.commit()
        logger.info("Deleted SearchView id=%d", view_id)
        return True

    def set_default(self, view_id: int) -> Optional[SearchView]:
        """
        Marks a specific view as default and unsets default on all others.

        :param view_id: SearchView ID
        :return: Updated SearchView instance or None
        """
        view = self.get_view(view_id)
        if not view:
            return None

        self._clear_defaults(exclude_id=view_id)
        view.default = True
        self.commit()
        self.session.refresh(view)
        logger.info("Set SearchView id=%d as default", view.id)
        return view

    def _clear_defaults(self, exclude_id: Optional[int] = None) -> None:
        """
        Clears default flag on all search views except exclude_id.
        """
        stmt = update(SearchView).values(default=False)
        if exclude_id is not None:
            stmt = stmt.where(SearchView.id != exclude_id)
        self.session.execute(stmt)

    def ensure_single_default(self) -> None:
        """
        Ensures that at most one SearchView has default=True in the database.
        If multiple have default=True, retains the primary one and clears the rest.
        """
        stmt = (
            select(SearchView)
            .where(SearchView.default == True)
            .order_by(SearchView.priority.asc(), SearchView.id.asc())
        )
        defaults = list(self.session.execute(stmt).scalars().all())
        if len(defaults) > 1:
            primary_default = defaults[0]
            self._clear_defaults(exclude_id=primary_default.id)
            self.commit()
            logger.info(
                "Enforced single default search view; retained id=%d name='%s'",
                primary_default.id,
                primary_default.name,
            )
