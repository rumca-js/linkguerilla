"""
SQLAlchemy Query Builder for Sources Search in YAFR.

Translates ParsedQuery AST tokens into indexed SQLAlchemy expressions,
applying operators ('=', '=='), joins with SourceOperationalData,
system filters ('url', 'title', 'fetch_time', 'errors'), explicit ordering, and pagination.
"""

import logging
from typing import List, Optional, Tuple
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql import Select
from linkarchivetools.model.definitions import (
    SourceOperationalData,
    SourcesTable,
)
from yafr.db.source_repository import DEFAULT_SOURCE_REFRESH_SECONDS, _outdated_condition
from yafr.search.parser import ParsedQuery, SearchClause

logger = logging.getLogger(__name__)

# Available Source Filters
SOURCE_FILTERS = [
    {"id": "url", "name": "by URL", "default": True},
    {"id": "title", "name": "by Title", "default": False},
    {"id": "fetch_time", "name": "by Fetch time", "default": False},
    {"id": "errors", "name": "by Errors", "default": False},
]


class SourceSearchQueryBuilder:
    """
    Compiles search AST tokens into executable SQLAlchemy statements for Sources.
    """

    @classmethod
    def build_select(
        cls,
        parsed_query: ParsedQuery,
        filter_id: Optional[str] = "url",
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        default_period: int = DEFAULT_SOURCE_REFRESH_SECONDS,
    ) -> Select:
        """
        Builds the primary SELECT statement for matching SourcesTable and SourceOperationalData.

        :param parsed_query: Parsed query AST
        :param filter_id: Active filter ID ('url', 'title', 'fetch_time')
        :param limit: Maximum rows to return
        :param offset: Number of rows to skip
        :param default_period: Default period in seconds for sources without explicit fetch_period
        :return: Compiled SQLAlchemy Select statement
        """
        stmt = select(SourcesTable, SourceOperationalData).outerjoin(
            SourceOperationalData,
            SourcesTable.id == SourceOperationalData.source_id,
        )

        stmt = cls._apply_clauses(stmt, parsed_query.clauses, default_period=default_period)
        stmt = cls._apply_ordering(stmt, filter_id, parsed_query.order_by)

        if offset is not None and offset > 0:
            stmt = stmt.offset(offset)
        if limit is not None and limit > 0:
            stmt = stmt.limit(limit)

        return stmt

    @classmethod
    def execute_search(
        cls,
        session: Session,
        parsed_query: ParsedQuery,
        filter_id: Optional[str] = "url",
        limit: Optional[int] = 25,
        offset: Optional[int] = 0,
        default_period: int = DEFAULT_SOURCE_REFRESH_SECONDS,
    ) -> Tuple[List[Tuple[SourcesTable, Optional[SourceOperationalData]]], int]:
        """
        Executes the search query and returns matched rows and total count.

        :param session: Active SQLAlchemy Session
        :param parsed_query: Parsed AST
        :param filter_id: System filter identifier ('url', 'title', 'fetch_time')
        :param limit: Pagination limit
        :param offset: Pagination offset
        :param default_period: Default period in seconds for sources without explicit fetch_period
        :return: Tuple of (list of (SourcesTable, SourceOperationalData), total_count)
        """
        count_stmt = select(func.count(SourcesTable.id)).outerjoin(
            SourceOperationalData,
            SourcesTable.id == SourceOperationalData.source_id,
        )
        count_stmt = cls._apply_clauses(count_stmt, parsed_query.clauses, default_period=default_period)
        total_count = session.execute(count_stmt).scalar() or 0

        query_stmt = cls.build_select(
            parsed_query=parsed_query,
            filter_id=filter_id,
            limit=limit,
            offset=offset,
            default_period=default_period,
        )
        results = list(session.execute(query_stmt).all())
        return results, total_count

    @classmethod
    def _apply_clauses(
        cls,
        stmt: Select,
        clauses: List[SearchClause],
        default_period: int = DEFAULT_SOURCE_REFRESH_SECONDS,
    ) -> Select:
        """
        Applies parsed predicates from search clauses onto the statement.
        """
        for clause in clauses:
            expr = cls._build_clause_expression(clause, default_period=default_period)
            if expr is not None:
                stmt = stmt.where(expr)
        return stmt

    @classmethod
    def _build_clause_expression(
        cls,
        clause: SearchClause,
        default_period: int = DEFAULT_SOURCE_REFRESH_SECONDS,
    ):
        """
        Builds a boolean SQLAlchemy expression for a single SearchClause.
        """
        field_target = clause.field
        op = clause.operator
        val = clause.value
        negated = clause.negated

        if field_target in ("link", "url"):
            col = SourcesTable.url
            if op == "==":
                expr = col != val if negated else col == val
            else:
                like_pattern = f"%{val}%"
                expr = (
                    col.notilike(like_pattern) if negated else col.ilike(like_pattern)
                )
            return expr

        if field_target == "title":
            col = SourcesTable.title
            if op == "==":
                expr = col != val if negated else col == val
            else:
                like_pattern = f"%{val}%"
                expr = (
                    col.notilike(like_pattern) if negated else col.ilike(like_pattern)
                )
            return expr

        if field_target in ("tag", "auto_tag"):
            col = SourcesTable.auto_tag
            if op == "==":
                expr = col != val if negated else col == val
            else:
                like_pattern = f"%{val}%"
                expr = (
                    col.notilike(like_pattern) if negated else col.ilike(like_pattern)
                )
            return expr

        if field_target in ("type", "source_type"):
            col = SourcesTable.source_type
            if op == "==":
                expr = col != val if negated else col == val
            else:
                like_pattern = f"%{val}%"
                expr = (
                    col.notilike(like_pattern) if negated else col.ilike(like_pattern)
                )
            return expr

        if field_target in ("status", "enabled"):
            is_enabled = val.lower() in ("enabled", "active", "true", "1")
            target_val = not is_enabled if negated else is_enabled
            return SourcesTable.enabled == target_val

        if field_target == "outdated":
            cond = _outdated_condition(default_period)
            return ~cond if negated else cond

        if field_target in ("error", "errors"):
            cond = SourceOperationalData.consecutive_errors > 0
            return ~cond if negated else cond

        # Free-text search matches title, url, or auto_tag
        like_pattern = f"%{val}%"
        free_expr = or_(
            SourcesTable.title.ilike(like_pattern),
            SourcesTable.url.ilike(like_pattern),
            SourcesTable.auto_tag.ilike(like_pattern),
        )
        return ~free_expr if negated else free_expr

    @classmethod
    def _apply_ordering(
        cls,
        stmt: Select,
        filter_id: Optional[str],
        order_directive: Optional[str],
    ) -> Select:
        """
        Orders sources by explicit directive or active filter.
        """
        # Explicit order overrides filter
        if order_directive:
            clean_order = order_directive.lower().strip()
            if clean_order in ("title", "name"):
                return stmt.order_by(SourcesTable.title.asc())
            if clean_order in ("url", "link"):
                return stmt.order_by(SourcesTable.url.asc())
            if clean_order in ("fetch", "fetch_time", "date"):
                return stmt.order_by(
                    SourceOperationalData.date_fetched.desc().nullslast()
                )
            if clean_order in ("errors", "consecutive_errors"):
                return stmt.order_by(
                    SourceOperationalData.consecutive_errors.desc().nullslast()
                )

        # Active filter ordering
        if filter_id == "title":
            return stmt.order_by(SourcesTable.title.asc())
        elif filter_id == "fetch_time":
            return stmt.order_by(SourceOperationalData.date_fetched.desc().nullslast())
        elif filter_id == "errors":
            return stmt.order_by(
                SourceOperationalData.consecutive_errors.desc().nullslast()
            )
        else:
            # Default by URL
            return stmt.order_by(SourcesTable.url.asc())
