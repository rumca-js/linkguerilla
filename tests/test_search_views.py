"""
Unit tests for SearchView Repository, Service, REST API, and Search Integration.
"""

import unittest
from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker
from linkarchivetools.model.definitions import (
    Base,
    ConfigurationEntry,
    EntryCompactedTags,
    LinkDataModel,
    SearchView,
)
from yafr.app import create_app
from yafr.db.search_view_repository import SearchViewRepository
from yafr.db.session import close_session
from yafr.search import FilterRegistry, SearchParser, SearchQueryBuilder
from yafr.services.search_view_service import SearchViewService


class TestSearchViewRepository(unittest.TestCase):
    """
    Tests for SearchViewRepository CRUD operations.
    """

    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine)
        self.Session = scoped_session(self.session_factory)
        self.session = self.Session()
        self.repo = SearchViewRepository(self.session)

    def tearDown(self):
        self.session.close()
        self.Session.remove()
        Base.metadata.drop_all(self.engine)

    def test_create_and_get_view(self):
        view = self.repo.create_view(
            name="Test View",
            default=True,
            priority=10,
            filter_statement="tag=news",
            order_by="-date_published",
        )
        self.assertIsNotNone(view.id)
        self.assertEqual(view.name, "Test View")
        self.assertTrue(view.default)
        self.assertEqual(view.priority, 10)
        self.assertEqual(view.filter_statement, "tag=news")
        self.assertEqual(view.order_by, "-date_published")

        fetched = self.repo.get_view(view.id)
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.name, "Test View")

        by_name = self.repo.get_by_name("Test View")
        self.assertIsNotNone(by_name)
        self.assertEqual(by_name.id, view.id)

    def test_list_views_ordered_by_priority(self):
        self.repo.create_view(name="High Priority", priority=1)
        self.repo.create_view(name="Low Priority", priority=100)
        self.repo.create_view(name="Medium Priority", priority=50)

        views = self.repo.list_views(order_by="priority")
        self.assertEqual(len(views), 3)
        self.assertEqual(views[0].name, "High Priority")
        self.assertEqual(views[1].name, "Medium Priority")
        self.assertEqual(views[2].name, "Low Priority")

    def test_update_view(self):
        view = self.repo.create_view(name="Initial Name", priority=5)
        updated = self.repo.update_view(
            view.id,
            name="Updated Name",
            priority=2,
            filter_statement="status=active",
            order_by="votes",
        )
        self.assertIsNotNone(updated)
        self.assertEqual(updated.name, "Updated Name")
        self.assertEqual(updated.priority, 2)
        self.assertEqual(updated.filter_statement, "status=active")
        self.assertEqual(updated.order_by, "votes")

    def test_delete_view(self):
        view = self.repo.create_view(name="To Delete")
        self.assertTrue(self.repo.delete_view(view.id))
        self.assertIsNone(self.repo.get_view(view.id))
        self.assertFalse(self.repo.delete_view(99999))

    def test_set_default_unsets_other_defaults(self):
        v1 = self.repo.create_view(name="View 1", default=True)
        v2 = self.repo.create_view(name="View 2", default=False)

        self.assertTrue(v1.default)
        self.assertFalse(v2.default)

        self.repo.set_default(v2.id)
        self.session.refresh(v1)
        self.session.refresh(v2)

        self.assertFalse(v1.default)
        self.assertTrue(v2.default)

    def test_only_one_filter_can_be_default_repo(self):
        # Creating multiple default views sequentially leaves only the latest default
        v1 = self.repo.create_view(name="Default 1", default=True)
        self.assertTrue(v1.default)

        v2 = self.repo.create_view(name="Default 2", default=True)
        self.session.refresh(v1)
        self.assertFalse(v1.default)
        self.assertTrue(v2.default)

        # Updating v1 back to default unsets v2
        self.repo.update_view(v1.id, default=True)
        self.session.refresh(v1)
        self.session.refresh(v2)
        self.assertTrue(v1.default)
        self.assertFalse(v2.default)

        # Test ensure_single_default clears multiple if present
        v2.default = True
        self.session.commit()
        self.repo.ensure_single_default()
        self.session.refresh(v1)
        self.session.refresh(v2)
        defaults = [v for v in (v1, v2) if v.default]
        self.assertEqual(len(defaults), 1)


class TestSearchViewService(unittest.TestCase):
    """
    Tests for SearchViewService business validation and operations.
    """

    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine)
        self.Session = scoped_session(self.session_factory)
        self.session = self.Session()

    def tearDown(self):
        self.session.close()
        self.Session.remove()
        Base.metadata.drop_all(self.engine)

    def test_create_view_validation(self):
        # Empty name should raise ValueError
        with self.assertRaises(ValueError):
            SearchViewService.create_view({"name": "   "}, session=self.session)

        # Valid creation
        view = SearchViewService.create_view(
            {
                "name": "Python Articles",
                "default": "true",
                "priority": "5",
                "filter_statement": "tag=python",
                "order_by": "votes",
            },
            session=self.session,
        )
        self.assertEqual(view.name, "Python Articles")
        self.assertTrue(view.default)
        self.assertEqual(view.priority, 5)

        # Duplicate name should raise ValueError
        with self.assertRaises(ValueError):
            SearchViewService.create_view(
                {"name": "Python Articles"}, session=self.session
            )

    def test_update_view_validation(self):
        v1 = SearchViewService.create_view({"name": "View One"}, session=self.session)
        v2 = SearchViewService.create_view({"name": "View Two"}, session=self.session)

        # Renaming v2 to v1's name should raise ValueError
        with self.assertRaises(ValueError):
            SearchViewService.update_view(
                v2.id, {"name": "View One"}, session=self.session
            )

        # Valid update
        updated = SearchViewService.update_view(
            v2.id,
            {"priority": 10, "filter_statement": "tag=tech"},
            session=self.session,
        )
        self.assertEqual(updated.priority, 10)
        self.assertEqual(updated.filter_statement, "tag=tech")

    def test_to_dict_structure(self):
        view = SearchViewService.create_view(
            {
                "name": "Dict Test",
                "default": False,
                "priority": 3,
                "filter_statement": "title=test",
                "order_by": "date_published",
            },
            session=self.session,
        )
        d = SearchViewService.to_dict(view)
        self.assertEqual(d["id"], view.id)
        self.assertEqual(d["name"], "Dict Test")
        self.assertFalse(d["default"])
        self.assertEqual(d["priority"], 3)
        self.assertEqual(d["filter_statement"], "title=test")
        self.assertEqual(d["order_by"], "date_published")


class TestSearchViewAPIAndSearch(unittest.TestCase):
    """
    Tests for SearchView REST API endpoints, web routes, and search integration.
    """

    def setUp(self):
        self.app = create_app(
            {
                "TESTING": True,
                "DATABASE_PATH": ":memory:",
                "SECRET_KEY": "test-key",
            }
        )
        self.client = self.app.test_client()

        with self.app.app_context():
            from yafr.db.session import get_session

            self.session = get_session()
            Base.metadata.create_all(self.session.get_bind())

            # Seed config
            cfg = ConfigurationEntry(id=1, links_per_page=25)
            self.session.merge(cfg)
            self.session.commit()

    def tearDown(self):
        with self.app.app_context():
            close_session()

    def test_api_list_and_create(self):
        # Initially empty
        res = self.client.get("/api/search-views")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["count"], 0)

        # Create new search view
        payload = {
            "name": "Bookmarks by Creation",
            "default": True,
            "priority": 1,
            "filter_statement": "bookmarked=True",
            "order_by": "-date_created, link",
        }
        res = self.client.post("/api/search-views", json=payload)
        self.assertEqual(res.status_code, 201)
        res_data = res.get_json()
        self.assertTrue(res_data["success"])
        self.assertEqual(res_data["search_view"]["name"], "Bookmarks by Creation")
        self.assertTrue(res_data["search_view"]["default"])
        view_id = res_data["search_view"]["id"]

        # Get single search view
        res = self.client.get(f"/api/search-views/{view_id}")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["search_view"]["id"], view_id)

    def test_api_update_and_delete(self):
        # Create view
        res = self.client.post(
            "/api/search-views",
            json={"name": "Temp View", "priority": 10},
        )
        self.assertEqual(res.status_code, 201)
        view_id = res.get_json()["search_view"]["id"]

        # Update view
        res = self.client.post(
            f"/api/search-views/{view_id}",
            json={"name": "Renamed View", "priority": 2},
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["search_view"]["name"], "Renamed View")
        self.assertEqual(res.get_json()["search_view"]["priority"], 2)

        # Delete view
        res = self.client.delete(f"/api/search-views/{view_id}")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()["success"])

        # Subsequent fetch returns 404
        res = self.client.get(f"/api/search-views/{view_id}")
        self.assertEqual(res.status_code, 404)

    def test_api_set_default(self):
        res1 = self.client.post(
            "/api/search-views", json={"name": "View A", "default": True}
        )
        self.assertEqual(res1.status_code, 201)
        id1 = res1.get_json()["search_view"]["id"]

        res2 = self.client.post(
            "/api/search-views", json={"name": "View B", "default": False}
        )
        self.assertEqual(res2.status_code, 201)
        id2 = res2.get_json()["search_view"]["id"]

        # Set View B as default
        res = self.client.post(f"/api/search-views/{id2}/set-default")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()["search_view"]["default"])

        # Check View A is no longer default
        res_a = self.client.get(f"/api/search-views/{id1}")
        self.assertFalse(res_a.get_json()["search_view"]["default"])

    def test_search_integration_with_custom_view(self):
        with self.app.app_context():
            from yafr.db.session import get_session

            session = get_session()

            # Insert sample entries
            e1 = LinkDataModel(
                title="Python Tutorial",
                link="https://example.com/py",
                source_url="https://example.com/py",
                description="Learn Python basics",
                page_rating_votes=10,
                bookmarked=True,
            )
            e2 = LinkDataModel(
                title="Rust Guide",
                link="https://example.com/rs",
                source_url="https://example.com/rs",
                description="Rust memory safety",
                page_rating_votes=50,
                bookmarked=False,
            )
            e3 = LinkDataModel(
                title="Advanced Python",
                link="https://example.com/py-adv",
                source_url="https://example.com/py-adv",
                description="Asyncio and meta-programming",
                page_rating_votes=100,
                bookmarked=True,
            )
            session.add_all([e1, e2, e3])
            session.commit()

            # Add tag to e1 and e3
            t1 = EntryCompactedTags(entry_id=e1.id, tag="python")
            t2 = EntryCompactedTags(entry_id=e3.id, tag="python")
            session.add_all([t1, t2])
            session.commit()

            # Create custom SearchView: filter_statement="tag=python", order_by="-page_rating_votes"
            view = SearchViewService.create_view(
                {
                    "name": "Top Python",
                    "priority": 1,
                    "filter_statement": "tag=python",
                    "order_by": "-page_rating_votes",
                },
                session=session,
            )

            # Test FilterRegistry exposes custom view
            filters = FilterRegistry.get_available_filters(session=session)
            custom_filter = next(
                (f for f in filters if f.id == f"custom_{view.id}"), None
            )
            self.assertIsNotNone(custom_filter)
            self.assertEqual(custom_filter.name, "Top Python")

            # Execute search through SearchQueryBuilder using custom filter
            parsed_query = SearchParser.parse("")
            entries, count = SearchQueryBuilder.execute_search(
                session=session,
                parsed_query=parsed_query,
                filter_id=f"custom_{view.id}",
            )
            self.assertEqual(count, 2)
            self.assertEqual(entries[0].title, "Advanced Python")  # 100 votes
            self.assertEqual(entries[1].title, "Python Tutorial")  # 10 votes

    def test_configuration_view_renders_search_views(self):
        # Create a view
        self.client.post(
            "/api/search-views",
            json={
                "name": "Config UI View",
                "default": True,
                "priority": 4,
                "filter_statement": "status=active",
                "order_by": "votes",
            },
        )

        res = self.client.get("/configuration")
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)
        self.assertIn("Search Views", html)
        self.assertIn("Config UI View", html)
        self.assertIn("status=active", html)
        self.assertIn("votes", html)

    def test_default_filter_always_on_top_in_combos(self):
        with self.app.app_context():
            from yafr.db.session import get_session

            session = get_session()

            # 1. No custom views: 'date_published' should be at index 0 and be the only default
            filters = FilterRegistry.get_available_filters(session=session)
            defaults = [f for f in filters if f.is_default]
            self.assertEqual(len(defaults), 1)
            self.assertEqual(defaults[0].id, "date_published")
            self.assertEqual(filters[0].id, "date_published")
            self.assertTrue(filters[0].is_default)

            # 2. Add non-default custom view
            v1 = SearchViewService.create_view(
                {"name": "Custom Non-Default", "default": False, "priority": 10},
                session=session,
            )
            filters = FilterRegistry.get_available_filters(session=session)
            defaults = [f for f in filters if f.is_default]
            self.assertEqual(len(defaults), 1)
            self.assertEqual(defaults[0].id, "date_published")
            self.assertEqual(filters[0].id, "date_published")

            # 3. Add custom view with default=True: should become the ONLY default and be at index 0
            v2 = SearchViewService.create_view(
                {"name": "Custom Default View", "default": True, "priority": 5},
                session=session,
            )
            filters = FilterRegistry.get_available_filters(session=session)
            defaults = [f for f in filters if f.is_default]
            self.assertEqual(len(defaults), 1)
            self.assertEqual(defaults[0].id, f"custom_{v2.id}")
            self.assertEqual(filters[0].id, f"custom_{v2.id}")
            self.assertEqual(filters[0].name, "Custom Default View")
            self.assertTrue(filters[0].is_default)

            # All system filters must have is_default=False
            for f in filters:
                if f.id != f"custom_{v2.id}":
                    self.assertFalse(
                        f.is_default, f"Filter {f.id} should not be default"
                    )

    def test_entries_search_combo_renders_default_on_top(self):
        # 1. Default system view on top
        res = self.client.get("/entries")
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)
        # Verify first option in #filter-select is date_published
        self.assertIn(
            '<select \n          name="filter" \n          id="filter-select"', html
        )
        opt_start = html.find('id="filter-select"')
        first_option_chunk = html[opt_start : opt_start + 600]
        self.assertIn('value="date_published"', first_option_chunk)
        self.assertIn("selected", first_option_chunk)

        # 2. Create custom default view
        res_create = self.client.post(
            "/api/search-views",
            json={
                "name": "Primary Custom Filter",
                "default": True,
                "priority": 1,
                "filter_statement": "bookmarked=True",
                "order_by": "votes",
            },
        )
        self.assertEqual(res_create.status_code, 201)
        custom_id = res_create.get_json()["search_view"]["id"]

        # 3. Request /entries with no ?filter= param: custom default is at index 0 and selected
        res2 = self.client.get("/entries")
        self.assertEqual(res2.status_code, 200)
        html2 = res2.get_data(as_text=True)
        opt_start2 = html2.find('id="filter-select"')
        first_option_chunk2 = html2[opt_start2 : opt_start2 + 600]
        self.assertIn(f'value="custom_{custom_id}"', first_option_chunk2)
        self.assertIn("Primary Custom Filter", first_option_chunk2)
        self.assertIn("selected", first_option_chunk2)

        # 4. Request /entries?q=test (compact search widget)
        res3 = self.client.get("/entries?q=test")
        self.assertEqual(res3.status_code, 200)
        html3 = res3.get_data(as_text=True)
        opt_start3 = html3.find('id="compact-filter-select"')
        compact_chunk = html3[opt_start3 : opt_start3 + 600]
        self.assertIn(f'value="custom_{custom_id}"', compact_chunk)
        self.assertIn("Primary Custom Filter", compact_chunk)
        self.assertIn("selected", compact_chunk)


if __name__ == "__main__":
    unittest.main()
