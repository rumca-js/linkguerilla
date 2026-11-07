"""
Search Expression Parser and Lexer for YAFR.

Parses raw user query strings into structured clauses, handling operators
('=' for substring LIKE, '==' for exact match), negation ('!', '-'),
quoted phrases, field-specific targets, and ordering directives.
"""

from dataclasses import dataclass, field
import logging
import re
import shlex
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

# Canonical field name mappings for user-friendly aliases
FIELD_ALIASES = {
    "title": "title",
    "desc": "description",
    "description": "description",
    "link": "link",
    "url": "link",
    "author": "author",
    "channel": "author",
    "lang": "language",
    "language": "language",
    "tag": "tag",
    "tags": "tag",
    "status": "status",
    "bookmark": "bookmarked",
    "bookmarked": "bookmarked",
    "bookmarks": "bookmarked",
    "votes": "page_rating_votes",
    "page_rating_votes": "page_rating_votes",
    "rating": "page_rating",
    "page_rating": "page_rating",
    "visits": "page_rating_visits",
    "page_rating_visits": "page_rating_visits",
    "age": "age",
    "age_limit": "age",
    "followers_count": "followers_count",
    "followers": "followers_count",
    "socialdata_followers": "followers_count",
    "socialdata_followers_count": "followers_count",
    "view_count": "view_count",
    "views": "view_count",
    "socialdata_views": "view_count",
    "stars": "stars",
    "socialdata_stars": "stars",
    "thumbs_up": "thumbs_up",
    "thumbs_down": "thumbs_down",
}

ORDER_DIRECTIVES = ("order:", "sort:")


@dataclass
class SearchClause:
    """
    Represents a single query predicate.

    :param field: Field to target (None for free-text search matching title/description)
    :param operator: Operator ('=' for substring LIKE, '==' for exact equality)
    :param value: Searched string value
    :param negated: Whether the predicate is inverted (NOT LIKE / !=)
    """

    field: Optional[str]
    operator: str
    value: str
    negated: bool = False


@dataclass
class ParsedQuery:
    """
    Represents the full parsed search query AST.

    :param raw_query: Original user input string
    :param clauses: List of parsed SearchClause filters
    :param order_by: Explicit sort criterion requested in query (e.g. 'published', 'votes')
    """

    raw_query: str
    clauses: List[SearchClause] = field(default_factory=list)
    order_by: Optional[str] = None

    @property
    def is_empty(self) -> bool:
        """Returns True if the query has no search predicates."""
        return len(self.clauses) == 0


class SearchParser:
    """
    Lexer and parser that translates user search syntax into a structured AST.
    """

    OPERATORS = (">=", "<=", "==", ">", "<", "=", ":")
    COMPARISON_OPERATORS = (">=", "<=", "==", ">", "<")

    @classmethod
    def parse(cls, raw_query: Optional[str]) -> ParsedQuery:
        """
        Parses a user input query string.

        :param raw_query: Raw user input text
        :return: ParsedQuery AST
        """
        if not raw_query or not raw_query.strip():
            return ParsedQuery(raw_query="")

        cleaned = raw_query.strip()
        tokens = cls._tokenize(cleaned)
        merged_tokens = cls._merge_operator_tokens(tokens)

        clauses: List[SearchClause] = []
        explicit_order: Optional[str] = None

        for token in merged_tokens:
            if not token:
                continue

            order = cls._extract_order_directive(token)
            if order is not None:
                explicit_order = order
                continue

            clause = cls._parse_token(token)
            if clause is not None:
                clauses.append(clause)

        return ParsedQuery(
            raw_query=cleaned,
            clauses=clauses,
            order_by=explicit_order,
        )

    @classmethod
    def _merge_operator_tokens(cls, tokens: List[str]) -> List[str]:
        """
        Merges comparison operator tokens that were split by whitespace
        (e.g. ['page_rating_votes', '>', '0'] -> 'page_rating_votes>0').
        """
        merged: List[str] = []
        i = 0
        while i < len(tokens):
            tok = tokens[i]
            # Case 1: [field, op, val]
            if i + 2 < len(tokens) and tokens[i + 1] in cls.OPERATORS:
                merged.append(f"{tok}{tokens[i + 1]}{tokens[i + 2]}")
                i += 3
            # Case 2: [field, op+val]
            elif i + 1 < len(tokens) and any(
                tokens[i + 1].startswith(op) for op in cls.OPERATORS
            ):
                merged.append(f"{tok}{tokens[i + 1]}")
                i += 2
            # Case 3: [field+op, val]
            elif any(tok.endswith(op) for op in cls.OPERATORS) and i + 1 < len(tokens):
                merged.append(f"{tok}{tokens[i + 1]}")
                i += 2
            else:
                merged.append(tok)
                i += 1
        return merged

    @classmethod
    def _extract_order_directive(cls, token: str) -> Optional[str]:
        """
        Extracts an ordering directive (e.g. 'order:votes', 'sort:published'), or None.
        """
        lower = token.lower()
        for prefix in ORDER_DIRECTIVES:
            if lower.startswith(prefix):
                return token[len(prefix) :].strip().lower()
        return None

    @classmethod
    def _strip_negation(cls, token: str) -> Tuple[bool, str]:
        """
        Checks for and strips leading '-' or '!' negation prefixes.
        """
        if (token.startswith("-") or token.startswith("!")) and len(token) > 1:
            return True, token[1:]
        return False, token

    @classmethod
    def _parse_comparison(cls, token: str, negated: bool) -> Optional[SearchClause]:
        """
        Attempts to parse comparison operators (>=, <=, ==, >, <).
        """
        for op in cls.COMPARISON_OPERATORS:
            if op in token:
                parts = token.split(op, 1)
                cand_field = parts[0].strip().lower()
                if cand_field and (cand_field in FIELD_ALIASES or "_" in cand_field):
                    val = parts[1].strip()
                    canonical_field = FIELD_ALIASES.get(cand_field, cand_field)
                    return SearchClause(
                        field=canonical_field,
                        operator=op,
                        value=val,
                        negated=negated,
                    )
        return None

    @classmethod
    def _parse_equality(cls, token: str, negated: bool) -> Optional[SearchClause]:
        """
        Attempts to parse substring/exact match operators ('=' or ':').
        """
        has_single_eq = "=" in token
        has_colon = (
            ":" in token
            and not token.startswith("http://")
            and not token.startswith("https://")
        )
        if not (has_single_eq or has_colon):
            return None

        separator = "=" if has_single_eq else ":"
        parts = token.split(separator, 1)
        field_name = parts[0].strip().lower()
        val = parts[1].strip()

        if field_name in FIELD_ALIASES or "_" in field_name:
            canonical_field = FIELD_ALIASES.get(field_name, field_name)
            return SearchClause(
                field=canonical_field,
                operator="=",
                value=val,
                negated=negated,
            )
        return None

    @classmethod
    def _parse_token(cls, token: str) -> Optional[SearchClause]:
        """
        Parses a single token into a SearchClause.
        """
        negated, core_token = cls._strip_negation(token)

        # 1. Try comparison operators (>=, <=, ==, >, <)
        comp_clause = cls._parse_comparison(core_token, negated)
        if comp_clause is not None:
            return comp_clause

        # 2. Try equality/LIKE operators (=, :)
        eq_clause = cls._parse_equality(core_token, negated)
        if eq_clause is not None:
            return eq_clause

        # 3. Fallback to free-text search token
        return SearchClause(
            field=None,
            operator="=",
            value=core_token,
            negated=negated,
        )

    @classmethod
    def _tokenize(cls, query_str: str) -> List[str]:
        """
        Tokenizes query string respecting quoted strings.
        Gracefully handles unclosed quotes.
        """
        try:
            return shlex.split(query_str, posix=True)
        except ValueError:
            # Handle unclosed quotes by attempting to close them or regex fallback
            try:
                return shlex.split(query_str + '"', posix=True)
            except ValueError:
                return re.findall(r'[^\s"]+|"[^"]*"', query_str)
