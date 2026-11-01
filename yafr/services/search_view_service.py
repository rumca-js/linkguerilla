"""
SearchView Service Implementation for YAFR.

Encapsulates business logic, validation, and CRUD coordination for
custom SearchViews and filter presets.
"""

import logging
from typing import Any, Dict, List, Optional
from sqlalchemy.orm import Session
from linkarchivetools.model.definitions import SearchView
from yafr.db.search_view_repository import SearchViewRepository

logger = logging.getLogger(__name__)


class SearchViewService:
    """
    Business service managing custom SearchView definitions.
    """

    @classmethod
    def list_views(
        cls,
        order_by: str = "priority",
        session: Optional[Session] = None,
    ) -> List[SearchView]:
        """
        Retrieves all configured search views ordered by priority.

        :param order_by: Sorting field ('priority', 'name', 'id')
        :param session: Optional active database session
        :return: List of SearchView models
        """
        repo = SearchViewRepository(session=session)
        return repo.list_views(order_by=order_by)

    @classmethod
    def get_view(
        cls,
        view_id: int,
        session: Optional[Session] = None,
    ) -> Optional[SearchView]:
        """
        Retrieves a single search view by primary key ID.

        :param view_id: SearchView ID
        :param session: Optional active database session
        :return: SearchView or None
        """
        repo = SearchViewRepository(session=session)
        return repo.get_view(view_id)

    @classmethod
    def create_view(
        cls,
        data: Dict[str, Any],
        session: Optional[Session] = None,
    ) -> SearchView:
        """
        Validates and creates a new search view.

        :param data: Input dictionary containing name, default, priority, filter_statement, order_by
        :param session: Optional active database session
        :return: Persisted SearchView
        :raises ValueError: On invalid or duplicate input
        """
        repo = SearchViewRepository(session=session)

        name = str(data.get("name", "")).strip()
        if not name:
            raise ValueError("Name is required and cannot be empty.")
        if len(name) > 500:
            raise ValueError("Name cannot exceed 500 characters.")

        existing = repo.get_by_name(name)
        if existing:
            raise ValueError(f"A search view with name '{name}' already exists.")

        default = cls._parse_bool(data.get("default", False))

        try:
            priority = int(data.get("priority", 0) or 0)
        except (ValueError, TypeError):
            priority = 0

        filter_statement = str(data.get("filter_statement", "") or "").strip()
        order_by = str(data.get("order_by", "") or "").strip()

        return repo.create_view(
            name=name,
            default=default,
            priority=priority,
            filter_statement=filter_statement,
            order_by=order_by,
        )

    @classmethod
    def update_view(
        cls,
        view_id: int,
        data: Dict[str, Any],
        session: Optional[Session] = None,
    ) -> SearchView:
        """
        Validates and updates an existing search view.

        :param view_id: ID of the search view to update
        :param data: Fields to update (name, default, priority, filter_statement, order_by)
        :param session: Optional active database session
        :return: Updated SearchView
        :raises ValueError: If not found or duplicate name
        """
        repo = SearchViewRepository(session=session)
        view = repo.get_view(view_id)
        if not view:
            raise ValueError(f"Search view with ID {view_id} not found.")

        update_payload: Dict[str, Any] = {}

        if "name" in data:
            name = str(data["name"]).strip()
            if not name:
                raise ValueError("Name cannot be empty.")
            if len(name) > 500:
                raise ValueError("Name cannot exceed 500 characters.")
            existing = repo.get_by_name(name)
            if existing and existing.id != view_id:
                raise ValueError(f"A search view with name '{name}' already exists.")
            update_payload["name"] = name

        if "default" in data:
            update_payload["default"] = cls._parse_bool(data["default"])

        if "priority" in data:
            try:
                update_payload["priority"] = int(data["priority"] or 0)
            except (ValueError, TypeError):
                update_payload["priority"] = 0

        if "filter_statement" in data:
            update_payload["filter_statement"] = str(
                data["filter_statement"] or ""
            ).strip()

        if "order_by" in data:
            update_payload["order_by"] = str(data["order_by"] or "").strip()

        updated = repo.update_view(view_id, **update_payload)
        if not updated:
            raise ValueError(f"Failed to update search view with ID {view_id}.")
        return updated

    @classmethod
    def delete_view(
        cls,
        view_id: int,
        session: Optional[Session] = None,
    ) -> bool:
        """
        Deletes a search view.

        :param view_id: SearchView ID
        :param session: Optional active database session
        :return: True if deleted
        :raises ValueError: If view not found
        """
        repo = SearchViewRepository(session=session)
        success = repo.delete_view(view_id)
        if not success:
            raise ValueError(f"Search view with ID {view_id} not found.")
        return True

    @classmethod
    def set_default(
        cls,
        view_id: int,
        session: Optional[Session] = None,
    ) -> SearchView:
        """
        Sets a search view as default.

        :param view_id: SearchView ID
        :param session: Optional active database session
        :return: Updated SearchView
        :raises ValueError: If view not found
        """
        repo = SearchViewRepository(session=session)
        updated = repo.set_default(view_id)
        if not updated:
            raise ValueError(f"Search view with ID {view_id} not found.")
        return updated

    @classmethod
    def to_dict(cls, view: SearchView) -> Dict[str, Any]:
        """
        Serializes a SearchView to a JSON-compatible dictionary.

        :param view: SearchView model
        :return: Dictionary of supported fields
        """
        return {
            "id": view.id,
            "name": view.name,
            "default": bool(view.default),
            "priority": view.priority,
            "filter_statement": view.filter_statement or "",
            "order_by": view.order_by or "",
        }

    @staticmethod
    def _parse_bool(val: Any) -> bool:
        """
        Helper to parse boolean values from forms or JSON.
        """
        if isinstance(val, bool):
            return val
        if isinstance(val, (int, float)):
            return val != 0
        if isinstance(val, str):
            return val.lower() in ("true", "1", "yes", "on", "t")
        return False
