"""
Integration tests for YAFR web routes and search views.
"""

import unittest
from yafr.app import create_app
from yafr.db import (
    ConfigRepository,
    EntryRepository,
    HistoryRepository,
    close_session,
    get_session,
    init_db,
)


class TestEntryRoutes(unittest.TestCase):
    """
    Test suite for EntriesListView and search routes.
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
        self.session = get_session()

        # Seed sample entries
        entry_repo = EntryRepository(self.session)
        self.e1 = entry_repo.add_entry(
            link="https://example.com/py1",
            title="Advanced Python Programming",
            description="Deep dive into Python internals and metaclasses",
        )
        entry_repo.set_tags(self.e1.id, ["python", "advanced"])

        self.e2 = entry_repo.add_entry(
            link="https://example.com/flask",
            title="Flask Web Development",
            description="Building web applications using Python and Flask",
        )
        entry_repo.set_tags(self.e2.id, ["flask", "web"])

    def tearDown(self):
        close_session()

    def test_search_view_empty_query(self):
        """GET / without query renders centered search input."""
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("main-search-input", html)
        self.assertIn("Search entries", html)
        self.assertIn("filter-select", html)

    def test_search_view_no_input_returns_all_data(self):
        """GET /?q= (search with no input text) returns all entries."""
        response = self.client.get("/?q=")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        # Should return both seeded entries
        self.assertIn("Advanced Python Programming", html)
        self.assertIn("Flask Web Development", html)
        self.assertIn("Showing all", html)

    def test_search_view_with_query(self):
        """GET / with query executes search and returns matching entries."""
        response = self.client.get("/?q=Python")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Advanced Python Programming", html)
        self.assertIn("Found", html)

        # Check search query was recorded in history
        history_repo = HistoryRepository(self.session)
        recent = history_repo.get_recent_searches()
        self.assertIn("Python", recent)

    def test_search_view_with_operator_and_filter(self):
        """GET /?q=title=Flask&filter=date_published works properly."""
        response = self.client.get("/?q=title=Flask&filter=date_published")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Flask Web Development", html)
        self.assertNotIn("Advanced Python Programming", html)

    def test_search_view_tag_search(self):
        """GET /?q=tag:flask matches tagged entry."""
        response = self.client.get("/?q=tag:flask")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Flask Web Development", html)

    def test_display_gallery_layout(self):
        """GET /?q=Python&display=gallery renders gallery-grid container."""
        response = self.client.get("/?q=Python&display=gallery")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("gallery-grid", html)
        self.assertIn("gallery-card", html)

    def test_display_standard_layout(self):
        """GET /?q=Python&display=standard renders standard-list container."""
        response = self.client.get("/?q=Python&display=standard")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("standard-list", html)
        self.assertIn("standard-card", html)

    def test_display_search_engine_layout(self):
        """GET /?q=Python&display=search-engine renders search-engine-list with votes and social data."""
        # Add social data to e1
        from linkarchivetools.model.definitions import SocialData

        self.session.add(SocialData(entry_id=self.e1.id, stars=42, view_count=1337))
        self.session.commit()

        response = self.client.get("/?q=Python&display=search-engine")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("search-engine-list", html)
        self.assertIn("search-engine-item", html)
        self.assertIn("btn-set-vote", html)
        self.assertIn("Vote:", html)
        self.assertIn("score-badge", html)
        self.assertIn("42", html)  # stars count
        self.assertIn("1,337", html)  # views count

    def test_display_content_centric_layout(self):
        """GET /?q=Python&display=content-centric renders Reddit-style layout."""
        response = self.client.get("/?q=Python&display=content-centric")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("content-centric-list", html)
        self.assertIn("content-centric-card", html)

    def test_display_links_only_layout(self):
        """GET /?q=Python&display=links-only renders high-density tabular view."""
        response = self.client.get("/?q=Python&display=links-only")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("links-only-table", html)
        self.assertIn("links-only-row", html)

    def test_entry_item_click_links_to_detail_view(self):
        """Entry items in search results contain data-detail-url and links to EntryDetailView."""
        response = self.client.get("/?q=Python")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn(f'data-detail-url="/entries/{self.e1.id}"', html)
        self.assertIn(f'href="/entries/{self.e1.id}"', html)

    def test_entry_detail_view_success(self):
        """GET /entries/<id> renders complete EntryDetailView metadata and controls."""
        response = self.client.get(f"/entries/{self.e1.id}")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Advanced Python Programming", html)
        self.assertIn("https://example.com/py1", html)
        self.assertIn("#python", html)
        self.assertIn("btn-copy-link", html)
        self.assertIn("btn-mark-active", html)
        self.assertIn("btn-mark-dead", html)
        self.assertIn("btn-update-data", html)
        self.assertIn("btn-reset-data", html)
        self.assertIn("btn-back-history", html)

    def test_entry_detail_view_records_visit(self):
        """Visiting /entries/<id> records a visit in HistoryRepository."""
        history_repo = HistoryRepository(self.session)
        self.assertFalse(history_repo.is_visited(self.e1.id))

        response = self.client.get(f"/entries/{self.e1.id}")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(history_repo.is_visited(self.e1.id))

    def test_entry_detail_view_transitions(self):
        """Visiting with from_entry_id records transition and displays it in transition pane."""
        # Navigate from e1 to e2
        res = self.client.get(f"/entries/{self.e2.id}?from_entry_id={self.e1.id}")
        self.assertEqual(res.status_code, 200)

        # Loading e1 detail view should now show e2 in the transition pane
        res_e1 = self.client.get(f"/entries/{self.e1.id}")
        self.assertEqual(res_e1.status_code, 200)
        html_e1 = res_e1.get_data(as_text=True)
        self.assertIn("Navigation Transitions", html_e1)
        self.assertIn("Flask Web Development", html_e1)

    def test_entry_detail_view_youtube_embed(self):
        """Entry with YouTube URL displays responsive video player iframe."""
        entry_repo = EntryRepository(self.session)
        yt_entry = entry_repo.add_entry(
            link="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            title="Rick Astley - Never Gonna Give You Up",
        )
        response = self.client.get(f"/entries/{yt_entry.id}")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("iframe", html)
        self.assertIn("https://www.youtube.com/embed/dQw4w9WgXcQ", html)

    def test_entry_detail_view_not_found(self):
        """GET /entries/99999 returns 404 for non-existent entry."""
        response = self.client.get("/entries/99999")
        self.assertEqual(response.status_code, 404)

    def test_entry_edit_screen_get_and_post(self):
        """GET /entries/<id>/edit loads form, and POST updates metadata."""
        # 1. GET form
        res_get = self.client.get(f"/entries/{self.e1.id}/edit")
        self.assertEqual(res_get.status_code, 200)
        self.assertIn("Edit Entry Metadata", res_get.get_data(as_text=True))

        # 2. POST updates
        res_post = self.client.post(
            f"/entries/{self.e1.id}/edit",
            data={
                "link": "https://example.com/py1-updated",
                "title": "Python Internals Updated",
                "description": "Updated deep dive",
                "author": "Guido",
                "language": "en",
                "tags": "python, advanced, internals",
            },
            follow_redirects=True,
        )
        self.assertEqual(res_post.status_code, 200)
        html = res_post.get_data(as_text=True)
        self.assertIn("Python Internals Updated", html)
        self.assertIn("#internals", html)

    def test_show_icons_enabled_by_default(self):
        """When show_icons is enabled, thumbnails, container class, and icon table headers render."""
        response = self.client.get("/?q=Python&display=gallery")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('data-show-icons="true"', html)
        self.assertIn("gallery-grid show-icons", html)
        self.assertIn("gallery-thumb-wrap", html)

        res_table = self.client.get("/?q=Python&display=links-only")
        self.assertEqual(res_table.status_code, 200)
        html_table = res_table.get_data(as_text=True)
        self.assertIn('<th style="width: 40px;"></th>', html_table)
        self.assertIn('data-show-icons="true"', html_table)

    def test_show_icons_disabled_via_configurationentry(self):
        """When configurationentry.show_icons is False, thumbnails and icon table cells are suppressed."""
        config_repo = ConfigRepository(self.session)
        config_repo.update_config(show_icons=False)

        # 1. Gallery
        res_gallery = self.client.get("/?q=Python&display=gallery")
        self.assertEqual(res_gallery.status_code, 200)
        html_gallery = res_gallery.get_data(as_text=True)
        self.assertIn('data-show-icons="false"', html_gallery)
        self.assertIn("gallery-grid no-icons", html_gallery)
        self.assertNotIn("gallery-thumb-wrap", html_gallery)

        # 2. Standard
        res_standard = self.client.get("/?q=Python&display=standard")
        self.assertEqual(res_standard.status_code, 200)
        html_standard = res_standard.get_data(as_text=True)
        self.assertIn('data-show-icons="false"', html_standard)
        self.assertIn("standard-list no-icons", html_standard)
        self.assertNotIn("standard-thumb-col", html_standard)

        # 3. Links-only
        res_table = self.client.get("/?q=Python&display=links-only")
        self.assertEqual(res_table.status_code, 200)
        html_table = res_table.get_data(as_text=True)
        self.assertIn('data-show-icons="false"', html_table)
        self.assertNotIn('<th style="width: 40px;"></th>', html_table)

    def test_list_template_directly_accepts_config_show_icons(self):
        """Verifies render_template('entries/list.html') accepts config object directly."""
        from flask import render_template

        class MockConfig:
            show_icons = False

        with self.app.test_request_context("/?q=test"):
            html = render_template(
                "entries/list.html",
                config=MockConfig(),
                has_query=True,
                query="test",
                display_type="gallery",
                entries=[self.e1],
                total_results=1,
                page=1,
                total_pages=1,
                visited_ids=set(),
                read_later_ids=set(),
                tags_map={},
                sources_map={},
                social_map={},
            )
            self.assertIn('data-show-icons="false"', html)
            self.assertNotIn("gallery-thumb-wrap", html)



if __name__ == "__main__":
    unittest.main()
