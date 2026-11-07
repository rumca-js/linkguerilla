"""
Unit tests for Search Parser, Query Builder, and Filters in YAFR.
"""

from datetime import datetime, timezone
import unittest
from yafr.db import (
    EntryRepository,
    HistoryRepository,
    close_session,
    get_session,
    init_db,
)
from yafr.search import (
    FilterRegistry,
    SearchClause,
    SearchFilter,
    SearchParser,
    SearchQueryBuilder,
)


class TestSearchParser(unittest.TestCase):
    """
    Test suite for SearchParser tokenizer and AST builder.
    """

    def test_free_text_parsing(self):
        """Verifies that free-text words are parsed as individual SearchClauses."""
        query = SearchParser.parse("python programming")
        self.assertEqual(len(query.clauses), 2)
        self.assertIsNone(query.clauses[0].field)
        self.assertEqual(query.clauses[0].value, "python")
        self.assertEqual(query.clauses[0].operator, "=")
        self.assertFalse(query.clauses[0].negated)

        self.assertIsNone(query.clauses[1].field)
        self.assertEqual(query.clauses[1].value, "programming")

    def test_quoted_phrases(self):
        """Verifies that double quotes preserve spaces in phrases."""
        query = SearchParser.parse('title="machine learning" "deep learning"')
        self.assertEqual(len(query.clauses), 2)
        self.assertEqual(query.clauses[0].field, "title")
        self.assertEqual(query.clauses[0].value, "machine learning")
        self.assertEqual(query.clauses[0].operator, "=")

        self.assertIsNone(query.clauses[1].field)
        self.assertEqual(query.clauses[1].value, "deep learning")

    def test_operator_single_equal_like(self):
        """Verifies that single equal represents substring LIKE matching."""
        query = SearchParser.parse("title=youtube desc=tutorial")
        self.assertEqual(len(query.clauses), 2)
        self.assertEqual(query.clauses[0].field, "title")
        self.assertEqual(query.clauses[0].operator, "=")
        self.assertEqual(query.clauses[0].value, "youtube")

        self.assertEqual(query.clauses[1].field, "description")
        self.assertEqual(query.clauses[1].operator, "=")
        self.assertEqual(query.clauses[1].value, "tutorial")

    def test_operator_double_equal_exact(self):
        """Verifies that double equal represents exact equality matching."""
        query = SearchParser.parse("title==linux author==Linus")
        self.assertEqual(len(query.clauses), 2)
        self.assertEqual(query.clauses[0].field, "title")
        self.assertEqual(query.clauses[0].operator, "==")
        self.assertEqual(query.clauses[0].value, "linux")

        self.assertEqual(query.clauses[1].field, "author")
        self.assertEqual(query.clauses[1].operator, "==")
        self.assertEqual(query.clauses[1].value, "Linus")

    def test_negation_operators(self):
        """Verifies that '-' and '!' set the negated flag."""
        query = SearchParser.parse("-tag=nsfw !spam -title==Draft")
        self.assertEqual(len(query.clauses), 3)

        self.assertEqual(query.clauses[0].field, "tag")
        self.assertEqual(query.clauses[0].value, "nsfw")
        self.assertTrue(query.clauses[0].negated)

        self.assertIsNone(query.clauses[1].field)
        self.assertEqual(query.clauses[1].value, "spam")
        self.assertTrue(query.clauses[1].negated)

        self.assertEqual(query.clauses[2].field, "title")
        self.assertEqual(query.clauses[2].operator, "==")
        self.assertEqual(query.clauses[2].value, "Draft")
        self.assertTrue(query.clauses[2].negated)

    def test_order_directive(self):
        """Verifies parsing of order: directive."""
        query = SearchParser.parse("title=python order:votes")
        self.assertEqual(len(query.clauses), 1)
        self.assertEqual(query.order_by, "votes")

        query2 = SearchParser.parse("sort:published tag=ai")
        self.assertEqual(len(query2.clauses), 1)
        self.assertEqual(query2.order_by, "published")

    def test_unclosed_quotes_resilience(self):
        """Verifies that an unclosed quote does not crash the parser."""
        query = SearchParser.parse('title="unclosed quote test')
        self.assertFalse(query.is_empty)
        self.assertEqual(query.clauses[0].field, "title")


class TestSearchQueryBuilder(unittest.TestCase):
    """
    Test suite for SearchQueryBuilder execution against SQLite.
    """

    def setUp(self):
        self.engine = init_db(":memory:", sync_schema=True)
        self.session = get_session()
        self.entry_repo = EntryRepository(self.session)
        self.history_repo = HistoryRepository(self.session)

        # Seed test data
        self.e1 = self.entry_repo.add_entry(
            link="https://youtube.com/watch?v=1",
            title="Python Tutorial For Beginners",
            description="Learn Python 3 programming language fundamentals",
            author="TechMaster",
            language="en",
        )
        self.entry_repo.set_tags(self.e1.id, ["python", "tutorial"])
        self.entry_repo.vote_entry(self.e1.id, 50)

        self.e2 = self.entry_repo.add_entry(
            link="https://youtube.com/watch?v=2",
            title="Linux Kernel Deep Dive",
            description="Understanding the core architecture of the operating system",
            author="LinusFan",
            language="en",
        )
        self.entry_repo.set_tags(self.e2.id, ["linux", "kernel"])
        self.entry_repo.vote_entry(self.e2.id, 90)

        self.e3 = self.entry_repo.add_entry(
            link="https://github.com/project",
            title="Python",  # Exact title 'Python'
            description="Official source code repository",
            author="DevOrg",
            language="en",
        )
        self.entry_repo.set_manual_status(self.e3.id, 400)  # Dead status

    def tearDown(self):
        close_session()

    def test_search_free_text(self):
        """Verifies free-text terms match title, description, link, or tags by default."""
        pq = SearchParser.parse("Tutorial")
        entries, count = SearchQueryBuilder.execute_search(self.session, pq)
        self.assertEqual(count, 1)
        self.assertEqual(entries[0].id, self.e1.id)

        # Term in description
        pq2 = SearchParser.parse("architecture")
        entries2, count2 = SearchQueryBuilder.execute_search(self.session, pq2)
        self.assertEqual(count2, 1)
        self.assertEqual(entries2[0].id, self.e2.id)

        # Term in link URL
        pq3 = SearchParser.parse("github.com")
        entries3, count3 = SearchQueryBuilder.execute_search(self.session, pq3)
        self.assertEqual(count3, 1)
        self.assertEqual(entries3[0].id, self.e3.id)

        # Term in tags by default
        self.entry_repo.set_tags(self.e3.id, ["github-source", "devtools"])
        pq4 = SearchParser.parse("devtools")
        entries4, count4 = SearchQueryBuilder.execute_search(self.session, pq4)
        self.assertEqual(count4, 1)
        self.assertEqual(entries4[0].id, self.e3.id)

        # Hash-prefixed term matching tag by default
        pq5 = SearchParser.parse("#devtools")
        entries5, count5 = SearchQueryBuilder.execute_search(self.session, pq5)
        self.assertEqual(count5, 1)
        self.assertEqual(entries5[0].id, self.e3.id)

    def test_search_exact_vs_like(self):
        """Verifies '=' (LIKE) vs '==' (exact match)."""
        # LIKE title=Python matches e1 ("Python Tutorial...") and e3 ("Python")
        pq_like = SearchParser.parse("title=Python")
        entries_like, count_like = SearchQueryBuilder.execute_search(
            self.session, pq_like
        )
        self.assertEqual(count_like, 2)

        # Exact title==Python matches only e3
        pq_exact = SearchParser.parse("title==Python")
        entries_exact, count_exact = SearchQueryBuilder.execute_search(
            self.session, pq_exact
        )
        self.assertEqual(count_exact, 1)
        self.assertEqual(entries_exact[0].id, self.e3.id)

    def test_search_tag(self):
        """Verifies searching by tag."""
        pq = SearchParser.parse("tag=tutorial")
        entries, count = SearchQueryBuilder.execute_search(self.session, pq)
        self.assertEqual(count, 1)
        self.assertEqual(entries[0].id, self.e1.id)

        pq_linux = SearchParser.parse("tag:linux")
        entries_linux, count_linux = SearchQueryBuilder.execute_search(
            self.session, pq_linux
        )
        self.assertEqual(count_linux, 1)
        self.assertEqual(entries_linux[0].id, self.e2.id)

    def test_search_status_filter(self):
        """Verifies filtering by status=active or status=dead."""
        pq_dead = SearchParser.parse("status=dead")
        entries, count = SearchQueryBuilder.execute_search(self.session, pq_dead)
        self.assertEqual(count, 1)
        self.assertEqual(entries[0].id, self.e3.id)

    def test_system_filter_read_later(self):
        """Verifies the Read Later filter restricts results to marked entries."""
        self.history_repo.toggle_read_later(self.e2.id)

        pq = SearchParser.parse("")
        entries, count = SearchQueryBuilder.execute_search(
            self.session, pq, filter_id="read_later"
        )
        self.assertEqual(count, 1)
        self.assertEqual(entries[0].id, self.e2.id)

    def test_system_filter_visited(self):
        """Verifies the Visited filter restricts results to visited entries."""
        self.history_repo.record_visit(self.e1.id)

        pq = SearchParser.parse("")
        entries, count = SearchQueryBuilder.execute_search(
            self.session, pq, filter_id="visited"
        )
        self.assertEqual(count, 1)
        self.assertEqual(entries[0].id, self.e1.id)

    def test_system_filter_votes_ordering(self):
        """Verifies 'by Votes' orders entries by highest votes first."""
        pq = SearchParser.parse("")
        entries, count = SearchQueryBuilder.execute_search(
            self.session, pq, filter_id="votes"
        )
        self.assertEqual(count, 3)
        self.assertEqual(entries[0].id, self.e2.id)  # votes=90
        self.assertEqual(entries[1].id, self.e1.id)  # votes=50

    def test_explicit_ordering_override(self):
        """Verifies query order:votes overrides the default filter order."""
        pq = SearchParser.parse("order:votes")
        entries, count = SearchQueryBuilder.execute_search(
            self.session, pq, filter_id="date_published"
        )
        self.assertEqual(entries[0].id, self.e2.id)  # votes=90 first


class TestFilterRegistry(unittest.TestCase):
    """
    Test suite for FilterRegistry.
    """

    def test_system_filters_list(self):
        filters = FilterRegistry.get_system_filters()
        ids = [f.id for f in filters]
        self.assertIn("date_published", ids)
        self.assertIn("read_later", ids)
        self.assertIn("visited", ids)
        self.assertIn("votes", ids)
        self.assertIn("visits", ids)

    def test_get_filter_fallback(self):
        f = FilterRegistry.get_filter("non_existent")
        self.assertEqual(f.id, "date_published")


if __name__ == "__main__":
    unittest.main()
