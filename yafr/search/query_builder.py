"""
SQLAlchemy Query Builder for YAFR Search Engine.

Translates ParsedQuery AST tokens into indexed SQLAlchemy expressions,
applying operators ('=', '=='), joins for tags and social metrics,
system filters, explicit ordering, and pagination.
"""

import logging
from typing import List, Optional, Tuple
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql import Select
from linkarchivetools.model.definitions import (
    EntryCompactedTags,
    EntryVisitHistory,
    LinkDataModel,
    ReadLater,
    SocialData,
)
from yafr.search.parser import ParsedQuery, SearchClause

logger = logging.getLogger(__name__)


class SearchQueryBuilder:
    """
    Compiles search AST tokens into executable SQLAlchemy statements.
    """

    # Mapping of user-facing aliases to SocialData model column names.
    # Keys are normalized (lowercase, stripped) tokens from order: directives.
    SOCIAL_ORDER_ALIASES = {
        "thumbs_up": "thumbs_up",
        "socialdata__thumbs_up": "thumbs_up",
        "socialdata_thumbs_up": "thumbs_up",
        "thumbs_down": "thumbs_down",
        "socialdata__thumbs_down": "thumbs_down",
        "socialdata_thumbs_down": "thumbs_down",
        "view_count": "view_count",
        "views": "view_count",
        "socialdata__view_count": "view_count",
        "socialdata_view_count": "view_count",
        "socialdata__views": "view_count",
        "socialdata_views": "view_count",
        "socialdata__rating": "rating",
        "socialdata_rating": "rating",
        "rating": "rating",
        "upvote_ratio": "upvote_ratio",
        "socialdata__upvote_ratio": "upvote_ratio",
        "socialdata_upvote_ratio": "upvote_ratio",
        "upvote_diff": "upvote_diff",
        "socialdata__upvote_diff": "upvote_diff",
        "socialdata_upvote_diff": "upvote_diff",
        "upvote_view_ratio": "upvote_view_ratio",
        "socialdata__upvote_view_ratio": "upvote_view_ratio",
        "socialdata_upvote_view_ratio": "upvote_view_ratio",
        "stars": "stars",
        "socialdata__stars": "stars",
        "socialdata_stars": "stars",
        "followers_count": "followers_count",
        "followers": "followers_count",
        "socialdata__followers_count": "followers_count",
        "socialdata_followers_count": "followers_count",
        "socialdata__followers": "followers_count",
        "socialdata_followers": "followers_count",
        "date_updated": "date_updated",
        "socialdata__date_updated": "date_updated",
        "socialdata_date_updated": "date_updated",
    }

    @classmethod
    def build_select(
        cls,
        parsed_query: ParsedQuery,
        filter_id: Optional[str] = "date_published",
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> Select:
        """
        Builds the primary SELECT statement for matching LinkDataModel entries.

        :param parsed_query: Parsed query AST
        :param filter_id: Active system filter ID ('date_published', 'read_later', etc.)
        :param limit: Maximum rows to return (pagination)
        :param offset: Number of rows to skip (pagination)
        :return: Compiled SQLAlchemy Select statement
        """
        stmt = select(LinkDataModel)
        stmt = cls._apply_clauses(stmt, parsed_query.clauses)
        stmt, applied_order = cls._apply_filter(stmt, filter_id)
        stmt = cls._apply_ordering(stmt, parsed_query.order_by, applied_order)

        if offset is not None and offset > 0:
            stmt = stmt.offset(offset)
        if limit is not None and limit > 0:
            stmt = stmt.limit(limit)

        return stmt

    @classmethod
    def build_count(
        cls,
        parsed_query: ParsedQuery,
        filter_id: Optional[str] = "date_published",
    ) -> Select:
        """
        Builds the COUNT statement to calculate total matching results for pagination.

        :param parsed_query: Parsed query AST
        :param filter_id: Active system filter ID
        :return: Compiled SQLAlchemy Select statement returning integer count
        """
        stmt = select(func.count(LinkDataModel.id))
        stmt = cls._apply_clauses(stmt, parsed_query.clauses)
        stmt, _ = cls._apply_filter(stmt, filter_id)
        return stmt

    @classmethod
    def execute_search(
        cls,
        session: Session,
        parsed_query: ParsedQuery,
        filter_id: Optional[str] = "date_published",
        limit: int = 25,
        offset: int = 0,
    ) -> Tuple[List[LinkDataModel], int]:
        """
        Executes search and returns matching entries along with total count.

        :param session: Active database session
        :param parsed_query: Parsed query AST
        :param filter_id: Active filter ID
        :param limit: Results per page
        :param offset: Pagination offset
        :return: Tuple of (list of LinkDataModel entries, total count)
        """
        count_stmt = cls.build_count(parsed_query, filter_id)
        total_count = session.execute(count_stmt).scalar() or 0

        if total_count == 0:
            return [], 0

        select_stmt = cls.build_select(
            parsed_query, filter_id, limit=limit, offset=offset
        )
        entries = list(session.execute(select_stmt).scalars().all())
        return entries, total_count

    @classmethod
    def _apply_clauses(cls, stmt: Select, clauses: List[SearchClause]) -> Select:
        """
        Applies search token predicates to the query statement.
        """
        joined_social = False
        for clause in clauses:
            stmt, joined_social = cls._apply_single_clause(stmt, clause, joined_social)
        return stmt

    @classmethod
    def _apply_single_clause(
        cls, stmt: Select, clause: SearchClause, joined_social: bool
    ) -> Tuple[Select, bool]:
        """
        Routes and applies a single SearchClause to the Select statement.
        """
        field_name = clause.field
        val = clause.value.strip()
        if not val:
            return stmt, joined_social

        # Free-text search: matches title, description, link, or associated tags by default
        if field_name is None:
            return (
                cls._apply_free_text_clause(stmt, val, clause.negated),
                joined_social,
            )

        # Tag search (subquery on EntryCompactedTags)
        if field_name == "tag":
            return (
                cls._apply_tag_clause(stmt, val, clause.operator, clause.negated),
                joined_social,
            )

        # Status search
        if field_name == "status":
            cond = cls._build_status_condition(val)
            if cond is not None:
                if clause.negated:
                    cond = ~cond
                stmt = stmt.where(cond)
            return stmt, joined_social

        # Bookmarked search
        if field_name == "bookmarked":
            cond = cls._build_bookmarked_condition(val)
            if clause.negated:
                cond = ~cond
            return stmt.where(cond), joined_social

        # Standard columns on LinkDataModel
        if hasattr(LinkDataModel, field_name):
            column = getattr(LinkDataModel, field_name)
            cond = cls._build_comparison_condition(
                column, clause.operator, val, fallback_ilike=True
            )
            if clause.negated:
                cond = ~cond
            return stmt.where(cond), joined_social

        # SocialData columns
        if (social_col := cls._resolve_social_column(field_name)) is not None:
            if not joined_social:
                stmt = stmt.outerjoin(
                    SocialData, SocialData.entry_id == LinkDataModel.id
                )
                joined_social = True

            cond = cls._build_comparison_condition(
                social_col, clause.operator, val, fallback_ilike=False
            )
            if clause.negated:
                cond = ~cond
            return stmt.where(cond), joined_social

        return stmt, joined_social

    @classmethod
    def _apply_free_text_clause(cls, stmt: Select, val: str, negated: bool) -> Select:
        """
        Applies a free-text search clause matching title, description, link, or tag.
        """
        clean_tag_val = val.lstrip("#").lower()
        tag_subquery = select(EntryCompactedTags.entry_id).where(
            EntryCompactedTags.tag.ilike(f"%{clean_tag_val}%")
        )
        condition = or_(
            LinkDataModel.title.ilike(f"%{val}%"),
            LinkDataModel.description.ilike(f"%{val}%"),
            LinkDataModel.link.ilike(f"%{val}%"),
            LinkDataModel.id.in_(tag_subquery),
        )
        if negated:
            condition = ~condition
        return stmt.where(condition)

    @classmethod
    def _apply_tag_clause(
        cls, stmt: Select, val: str, operator: str, negated: bool
    ) -> Select:
        """
        Applies a tag search clause using EntryCompactedTags subquery.
        """
        clean_tag = val.lstrip("#").lower()
        if operator == "==":
            tag_stmt = select(EntryCompactedTags.entry_id).where(
                EntryCompactedTags.tag == clean_tag
            )
        else:
            tag_stmt = select(EntryCompactedTags.entry_id).where(
                EntryCompactedTags.tag.ilike(f"%{clean_tag}%")
            )

        if negated:
            return stmt.where(LinkDataModel.id.not_in(tag_stmt))
        return stmt.where(LinkDataModel.id.in_(tag_stmt))

    @classmethod
    def _build_status_condition(cls, val: str):
        """
        Builds a condition for HTTP or manual status codes ('active', 'dead', or integer code).
        """
        val_lower = val.lower()
        if val_lower == "active":
            return LinkDataModel.manual_status_code == 200
        if val_lower == "dead":
            return or_(
                LinkDataModel.manual_status_code == 400,
                LinkDataModel.status_code >= 400,
            )
        try:
            code = int(val)
            return or_(
                LinkDataModel.manual_status_code == code,
                LinkDataModel.status_code == code,
            )
        except ValueError:
            return None

    @classmethod
    def _build_bookmarked_condition(cls, val: str):
        """
        Builds a boolean condition for the bookmarked flag.
        """
        is_true = val.lower() in ("true", "1", "yes")
        return LinkDataModel.bookmarked == is_true

    @classmethod
    def _build_comparison_condition(
        cls, column, operator: str, val: str, fallback_ilike: bool = True
    ):
        """
        Builds a column comparison condition supporting relational operators (>, <, >=, <=, ==)
        and substring/exact fallback.
        """
        if operator in (">", "<", ">=", "<="):
            try:
                num_val = float(val) if "." in val else int(val)
            except ValueError:
                num_val = val

            if operator == ">":
                return column > num_val
            elif operator == "<":
                return column < num_val
            elif operator == ">=":
                return column >= num_val
            elif operator == "<=":
                return column <= num_val
        elif operator == "==":
            return column == val
        elif fallback_ilike:
            return column.ilike(f"%{val}%")
        else:
            return column == val

        return stmt

    @classmethod
    def _apply_filter(
        cls, stmt: Select, filter_id: Optional[str]
    ) -> Tuple[Select, bool]:
        """
        Applies system filter joins and default sort.
        Returns modified Select and whether an order was applied.
        """
        order_applied = False

        if filter_id == "read_later":
            stmt = stmt.join(ReadLater, ReadLater.entry_id == LinkDataModel.id)
            stmt = stmt.order_by(ReadLater.id.desc())
            order_applied = True

        elif filter_id == "visited":
            stmt = stmt.join(
                EntryVisitHistory,
                (EntryVisitHistory.entry_id == LinkDataModel.id)
                & (EntryVisitHistory.visits > 0),
            )
            stmt = stmt.order_by(
                EntryVisitHistory.date_last_visit.desc().nullslast(),
                EntryVisitHistory.id.desc(),
            )
            order_applied = True

        elif filter_id == "votes":
            stmt = stmt.order_by(
                LinkDataModel.page_rating_votes.desc(),
                LinkDataModel.id.desc(),
            )
            order_applied = True

        elif filter_id == "visits":
            stmt = stmt.order_by(
                LinkDataModel.page_rating_visits.desc(),
                LinkDataModel.id.desc(),
            )
            order_applied = True

        elif filter_id and filter_id.startswith("custom_"):
            from yafr.search.filters import FilterRegistry
            from yafr.search.parser import SearchParser

            view = FilterRegistry.get_search_view(filter_id)
            if view:
                if view.filter_statement:
                    parsed_custom = SearchParser.parse(view.filter_statement)
                    stmt = cls._apply_clauses(stmt, parsed_custom.clauses)
                if view.order_by:
                    stmt = cls._apply_ordering(
                        stmt, view.order_by, filter_order_applied=False
                    )
                    order_applied = True

        elif filter_id == "date_published" or not filter_id:
            stmt = stmt.order_by(
                LinkDataModel.date_published.desc().nullslast(),
                LinkDataModel.id.desc(),
            )
            order_applied = True

        return stmt, order_applied

    @classmethod
    def _resolve_social_column(cls, clean_token: str):
        """
        Resolves a cleaned order token to a SocialData column, or None if not a social field.

        :param clean_token: Lowered, stripped order token
        :return: SocialData mapped column attribute, or None
        """
        normalized = clean_token
        if normalized.startswith("socialdata__"):
            normalized = normalized[12:]
        elif normalized.startswith("socialdata_"):
            normalized = normalized[11:]

        col_name = cls.SOCIAL_ORDER_ALIASES.get(
            normalized
        ) or cls.SOCIAL_ORDER_ALIASES.get(clean_token)
        if col_name is not None and hasattr(SocialData, col_name):
            return getattr(SocialData, col_name)
        return None

    @classmethod
    def _apply_ordering(
        cls,
        stmt: Select,
        order_by: Optional[str],
        filter_order_applied: bool,
    ) -> Select:
        """
        Applies explicit ordering directives from search query or custom search view.
        Overrides system filter ordering when specified.
        """
        if not order_by or not order_by.strip():
            if not filter_order_applied:
                # Fallback ordering
                stmt = stmt.order_by(
                    LinkDataModel.date_published.desc().nullslast(),
                    LinkDataModel.id.desc(),
                )
            return stmt

        tokens = [t.strip() for t in order_by.split(",") if t.strip()]
        if not tokens:
            return stmt

        # Clear existing filter ordering if explicit order is specified
        stmt = stmt.order_by(None)
        order_clauses = []
        joined_social = False

        for token in tokens:
            is_asc = token.startswith("+")
            is_explicit_desc = token.startswith("-")
            clean = token.lstrip("-+").strip().lower()

            if clean in ("published", "date_published"):
                order_clauses.append(
                    LinkDataModel.date_published.asc().nullsfirst()
                    if is_asc
                    else LinkDataModel.date_published.desc().nullslast()
                )
            elif clean in ("created", "date_created"):
                order_clauses.append(
                    LinkDataModel.date_created.asc().nullsfirst()
                    if is_asc
                    else LinkDataModel.date_created.desc().nullslast()
                )
            elif clean in ("votes", "page_rating_votes"):
                order_clauses.append(
                    LinkDataModel.page_rating_votes.asc()
                    if is_asc
                    else LinkDataModel.page_rating_votes.desc()
                )
            elif clean in ("rating", "page_rating"):
                order_clauses.append(
                    LinkDataModel.page_rating.asc()
                    if is_asc
                    else LinkDataModel.page_rating.desc()
                )
            elif clean in ("visits", "page_rating_visits", "visit_count"):
                order_clauses.append(
                    LinkDataModel.page_rating_visits.asc()
                    if is_asc
                    else LinkDataModel.page_rating_visits.desc()
                )
            elif clean == "link":
                order_clauses.append(
                    LinkDataModel.link.desc()
                    if is_explicit_desc
                    else LinkDataModel.link.asc()
                )
            elif (social_col := cls._resolve_social_column(clean)) is not None:
                if not joined_social:
                    stmt = stmt.outerjoin(
                        SocialData, SocialData.entry_id == LinkDataModel.id
                    )
                    joined_social = True
                order_clauses.append(
                    social_col.asc().nullsfirst()
                    if is_asc
                    else social_col.desc().nullslast()
                )

        if order_clauses:
            order_clauses.append(LinkDataModel.id.desc())
            return stmt.order_by(*order_clauses)

        # Fallback to date_published
        return stmt.order_by(
            LinkDataModel.date_published.desc().nullslast(),
            LinkDataModel.id.desc(),
        )
