"""
Unit tests for YAFR database connection and repository layer.

Can be run with Python's standard library test runner:
    poetry run python -m unittest tests/test_repositories.py
"""

from datetime import datetime, timezone
import unittest
from sqlalchemy import select
from linkarchivetools.model.definitions import (
    AppLogging,
    BackgroundJob,
    BackgroundJobHistory,
    EntryCompactedTags,
    EntryVisitHistory,
    ReadLater,
    SearchHistory,
    SocialData,
)
from yafr.db import (
    BaseRepository,
    ConfigRepository,
    EntryRepository,
    HistoryRepository,
    JobRepository,
    LoggingRepository,
    RulesRepository,
    SourceRepository,
    close_session,
    get_session,
    init_db,
    session_scope,
)


class TestRepositories(unittest.TestCase):
    """
    Test suite for database connection, scoped sessions, and repository classes.
    """

    def setUp(self):
        """Set up an isolated in-memory SQLite database before each test."""
        self.engine = init_db(db_path=":memory:", sync_schema=True)

    def tearDown(self):
        """Clean up and close scoped session after each test."""
        close_session()

    def test_session_scope(self):
        """Verifies that session_scope properly commits transactions."""
        with session_scope() as session:
            log = AppLogging(info_text="Scope test", level=20)
            session.add(log)

        session = get_session()
        saved = session.execute(
            select(AppLogging).where(AppLogging.info_text == "Scope test")
        ).scalar_one_or_none()
        self.assertIsNotNone(saved)
        self.assertEqual(saved.level, 20)

    def test_base_repository_fifo_limit(self):
        """Verifies that BaseRepository.apply_storage_limit evicts oldest records."""
        repo = BaseRepository()
        session = repo.session

        for i in range(10):
            session.add(SearchHistory(search_query=f"query_{i}"))
        session.commit()

        self.assertEqual(repo.count(SearchHistory), 10)
        evicted = repo.apply_storage_limit(SearchHistory, SearchHistory.id, max_limit=4)
        self.assertEqual(evicted, 6)
        self.assertEqual(repo.count(SearchHistory), 4)

        remaining = [
            r.search_query
            for r in repo.list_all(SearchHistory, order_by=SearchHistory.id.asc())
        ]
        self.assertEqual(remaining, ["query_6", "query_7", "query_8", "query_9"])

    def test_config_repository(self):
        """Verifies ConfigurationEntry initialization, querying, and updating."""
        repo = ConfigRepository()
        config = repo.get_config()
        self.assertIsNotNone(config)
        self.assertEqual(config.instance_title, repo.DEFAULT_TITLE)
        self.assertEqual(repo.get_display_style(), "style-dark")
        self.assertEqual(repo.get_display_type(), "gallery")

        repo.update_config(display_style="style-light", display_type="standard")
        self.assertEqual(repo.get_display_style(), "style-light")
        self.assertEqual(repo.get_display_type(), "standard")

        visit_alpha, dead_alpha = repo.get_alphas()
        self.assertIsInstance(visit_alpha, float)
        self.assertIsInstance(dead_alpha, float)

    def test_entry_repository_crud_and_status(self):
        """Verifies LinkDataModel creation, status updates, voting, and bookmarks."""
        repo = EntryRepository()
        entry = repo.add_entry(
            link="https://example.com/test",
            title="Test Entry",
            description="A sample test description",
        )
        self.assertIsNotNone(entry.id)
        self.assertEqual(entry.title, "Test Entry")

        # Status codes: 200 = active, 400 = dead
        self.assertTrue(repo.set_manual_status(entry.id, 400))
        updated = repo.get_by_id(entry.id)
        self.assertEqual(updated.manual_status_code, 400)
        self.assertIsNotNone(updated.date_dead_since)

        repo.set_manual_status(entry.id, 200)
        updated = repo.get_by_id(entry.id)
        self.assertEqual(updated.manual_status_code, 200)
        self.assertIsNone(updated.date_dead_since)

        # Voting clamped to [-100, 100]
        repo.vote_entry(entry.id, 150)
        self.assertEqual(repo.get_by_id(entry.id).page_rating_votes, 100)

        repo.vote_entry(entry.id, -200)
        self.assertEqual(repo.get_by_id(entry.id).page_rating_votes, -100)

        # Bookmarks toggle
        self.assertTrue(repo.toggle_bookmark(entry.id))
        self.assertTrue(repo.get_by_id(entry.id).bookmarked)
        self.assertFalse(repo.toggle_bookmark(entry.id))
        self.assertFalse(repo.get_by_id(entry.id).bookmarked)

    def test_entry_repository_tags(self):
        """Verifies adding and replacing tags on entries."""
        repo = EntryRepository()
        entry = repo.add_entry(link="https://example.com/tags", title="Tagged Entry")

        tags = repo.set_tags(entry.id, ["#python", "web", "SQLite"])
        self.assertEqual(tags, ["python", "sqlite", "web"])

        fetched_tags = repo.get_tags(entry.id)
        self.assertEqual(fetched_tags, ["python", "sqlite", "web"])

    def test_entry_repository_cascade_delete(self):
        """Verifies that deleting an entry cascades to dependent tables."""
        entry_repo = EntryRepository()
        history_repo = HistoryRepository()
        session = entry_repo.session

        entry = entry_repo.add_entry(
            link="https://example.com/cascade", title="Cascade Entry"
        )
        entry_id = entry.id

        entry_repo.set_tags(entry_id, ["tag1", "tag2"])
        history_repo.toggle_read_later(entry_id)
        history_repo.record_visit(entry_id)
        session.add(SocialData(entry_id=entry_id, view_count=100))
        session.commit()

        # Confirm related rows exist
        self.assertTrue(
            session.execute(
                select(EntryCompactedTags).where(
                    EntryCompactedTags.entry_id == entry_id
                )
            )
            .scalars()
            .all()
        )
        self.assertIsNotNone(
            session.execute(
                select(ReadLater).where(ReadLater.entry_id == entry_id)
            ).scalar_one_or_none()
        )
        self.assertIsNotNone(
            session.execute(
                select(EntryVisitHistory).where(EntryVisitHistory.entry_id == entry_id)
            ).scalar_one_or_none()
        )
        self.assertIsNotNone(
            session.execute(
                select(SocialData).where(SocialData.entry_id == entry_id)
            ).scalar_one_or_none()
        )

        # Delete parent entry
        self.assertTrue(entry_repo.delete_entry(entry_id))
        self.assertIsNone(entry_repo.get_by_id(entry_id))

        # Verify dependent rows are deleted
        self.assertFalse(
            session.execute(
                select(EntryCompactedTags).where(
                    EntryCompactedTags.entry_id == entry_id
                )
            )
            .scalars()
            .all()
        )
        self.assertIsNone(
            session.execute(
                select(ReadLater).where(ReadLater.entry_id == entry_id)
            ).scalar_one_or_none()
        )
        self.assertIsNone(
            session.execute(
                select(EntryVisitHistory).where(EntryVisitHistory.entry_id == entry_id)
            ).scalar_one_or_none()
        )
        self.assertIsNone(
            session.execute(
                select(SocialData).where(SocialData.entry_id == entry_id)
            ).scalar_one_or_none()
        )

    def test_source_repository(self):
        """Verifies source creation, operational data tracking, and outdated detection."""
        repo = SourceRepository()
        source = repo.add_source(
            url="https://news.ycombinator.com/rss",
            title="Hacker News",
            source_type="rss",
        )
        self.assertIsNotNone(source.id)
        self.assertEqual(source.title, "Hacker News")

        # Operational data initialized automatically
        op_data = repo.get_operational_data(source.id)
        self.assertIsNotNone(op_data)
        self.assertEqual(op_data.consecutive_errors, 0)

        # Outdated source check (no fetch date yet -> considered outdated)
        outdated = repo.get_outdated_sources(max_age_seconds=3600)
        self.assertEqual(len(outdated), 1)
        self.assertEqual(outdated[0].id, source.id)

        # Update fetch date to now
        repo.update_operational_data(
            source.id,
            date_fetched=datetime.now(timezone.utc),
            date_successful_fetch=datetime.now(timezone.utc),
            consecutive_errors=0,
        )
        self.assertEqual(len(repo.get_outdated_sources(max_age_seconds=3600)), 0)

        # Error tracking
        repo.update_operational_data(source.id, consecutive_errors=2)
        self.assertEqual(repo.count_error_sources(), 1)

    def test_job_repository(self):
        """Verifies job enqueueing, priority dispatch, retry disablement, and archiving."""
        repo = JobRepository()

        job1 = repo.enqueue_job(job="PROCESS_FEED", subject="feed1", priority=10)
        job2 = repo.enqueue_job(job="HIGH_PRIORITY", subject="feed2", priority=1)

        # Next job must be highest priority (lowest number)
        next_job = repo.get_next_pending_job()
        self.assertIsNotNone(next_job)
        self.assertEqual(next_job.id, job2.id)
        self.assertEqual(next_job.job, "HIGH_PRIORITY")

        # Error threshold disabling (3 retries)
        repo.record_job_error(job2.id, max_retries=3)
        repo.record_job_error(job2.id, max_retries=3)
        repo.record_job_error(job2.id, max_retries=3)
        updated_job2 = repo.get_by_id(BackgroundJob, job2.id)
        self.assertFalse(updated_job2.enabled)

        # Now next pending job is job1
        self.assertEqual(repo.get_next_pending_job().id, job1.id)

        # Complete job archives to history
        self.assertTrue(repo.complete_job(job1.id))
        self.assertIsNone(repo.get_by_id(BackgroundJob, job1.id))
        history_entry = repo.session.execute(
            select(BackgroundJobHistory).where(BackgroundJobHistory.subject == "feed1")
        ).scalar_one_or_none()
        self.assertIsNotNone(history_entry)

    def test_history_repository(self):
        """Verifies search history, visit tracking, transitions, and read later."""
        repo = HistoryRepository()

        # Search history with limit
        for q in ["apple", "banana", "cherry", "date"]:
            repo.add_search(q, max_limit=3)

        recent = repo.get_recent_searches()
        self.assertEqual(len(recent), 3)
        self.assertNotIn("apple", recent)
        self.assertIn("date", recent)

        # Autocomplete prefix
        repo.add_search("carrot")
        matches = repo.get_recent_searches(query_prefix="ch")
        self.assertIn("cherry", matches)

        # Visit tracking
        visit = repo.record_visit(entry_id=99)
        self.assertEqual(visit.visits, 1)
        self.assertTrue(repo.is_visited(99))
        repo.record_visit(entry_id=99)
        self.assertEqual(repo.get_by_id(EntryVisitHistory, visit.id).visits, 2)

        # Transitions
        t = repo.record_transition(entry_from_id=1, entry_to_id=2)
        self.assertEqual(t.counter, 1)
        repo.record_transition(entry_from_id=1, entry_to_id=2)
        transitions = repo.get_transitions_from(entry_id=1)
        self.assertEqual(len(transitions), 1)
        self.assertEqual(transitions[0].counter, 2)

        # Read later toggle
        self.assertTrue(repo.toggle_read_later(entry_id=42))
        self.assertTrue(repo.is_read_later(42))
        self.assertFalse(repo.toggle_read_later(entry_id=42))
        self.assertFalse(repo.is_read_later(42))

    def test_rules_repository(self):
        """Verifies regex rule CRUD and priority order."""
        repo = RulesRepository()

        r1 = repo.add_rule(
            rule_name="Block Reddit",
            trigger_rule_url=r".*reddit\.com.*",
            block=True,
            priority=10,
        )
        r2 = repo.add_rule(
            rule_name="Trust GitHub",
            trigger_rule_url=r".*github\.com.*",
            trust=True,
            priority=1,
        )

        rules = repo.list_rules(enabled_only=True)
        self.assertEqual(len(rules), 2)
        self.assertEqual(rules[0].id, r2.id)
        self.assertEqual(rules[1].id, r1.id)

        self.assertFalse(repo.toggle_rule(r1.id))
        enabled_rules = repo.list_rules(enabled_only=True)
        self.assertEqual(len(enabled_rules), 1)
        self.assertEqual(enabled_rules[0].id, r2.id)

    def test_logging_repository(self):
        """Verifies structured logging and severity filtering."""
        repo = LoggingRepository()

        repo.log(info_text="Debug message", level=LoggingRepository.DEBUG)
        repo.log(info_text="Info message", level=LoggingRepository.INFO)
        repo.log(info_text="Error message", level=LoggingRepository.ERROR)

        all_logs = repo.list_logs()
        self.assertEqual(len(all_logs), 3)

        error_logs = repo.list_logs(min_level=LoggingRepository.ERROR)
        self.assertEqual(len(error_logs), 1)
        self.assertEqual(error_logs[0].info_text, "Error message")


if __name__ == "__main__":
    unittest.main()
