"""
Unit and integration tests for WebToolsWrapper and SourceService integration.
"""

from datetime import datetime, timezone
import hashlib
import unittest
from unittest.mock import MagicMock, patch
from sqlalchemy import select
from webtoolkit import BaseUrl, RemoteUrl
from webtoolkit.response import PageResponseObject
from linkarchivetools.model.definitions import (
    AppLogging,
    BackgroundJob,
    ConfigurationEntry,
    LinkDataModel,
    SourceOperationalData,
    SourcesTable,
)
from yafr.app import create_app
from yafr.db import (
    BlockEntryRepository,
    ConfigRepository,
    LoggingRepository,
    RulesRepository,
    SourceRepository,
    close_session,
    get_session,
)
from yafr.services.source_service import SourceService
from yafr.services.webtools_service import (
    WebToolkitWrapper,
    WebToolsService,
    WebToolsWrapper,
    create_url,
    fetch_response,
    fetch_text,
)


class TestWebToolsWrapper(unittest.TestCase):
    """
    Test suite for WebToolsWrapper class and helpers.
    """

    def setUp(self):
        self.app = create_app(
            {
                "TESTING": True,
                "DATABASE_PATH": ":memory:",
                "SECRET_KEY": "test-key-webtools",
            }
        )
        self.session = get_session()
        self.config_repo = ConfigRepository(self.session)
        # Ensure clean config
        self.config = self.config_repo.get_config()
        self.config.remote_webtools_server_location = None
        self.session.commit()

    def tearDown(self):
        close_session()

    def test_default_uses_base_url_when_remote_not_configured(self):
        """
        When remote_webtools_server_location is None/empty, WebToolsWrapper uses BaseUrl.
        """
        wrapper = WebToolsWrapper(url="https://example.com/rss", session=self.session)
        self.assertFalse(wrapper.is_remote)
        self.assertIsNone(wrapper.remote_server_location)
        self.assertIsInstance(wrapper.url_handler, BaseUrl)

    def test_uses_remote_url_when_remote_configured_in_database(self):
        """
        When remote_webtools_server_location is set in DB, WebToolsWrapper uses RemoteUrl.
        """
        self.config.remote_webtools_server_location = "http://192.168.0.200:3000"
        self.session.commit()

        wrapper = WebToolsWrapper(url="https://example.com/rss", session=self.session)
        self.assertTrue(wrapper.is_remote)
        self.assertEqual(wrapper.remote_server_location, "http://192.168.0.200:3000")
        self.assertIsInstance(wrapper.url_handler, RemoteUrl)
        self.assertEqual(
            wrapper.url_handler.remote_server_location, "http://192.168.0.200:3000"
        )

    def test_explicit_remote_server_location_parameter(self):
        """
        Explicit remote_server_location parameter overrides DB configuration.
        """
        self.config.remote_webtools_server_location = "http://db-server:3000"
        self.session.commit()

        wrapper = WebToolsWrapper(
            url="https://example.com/rss",
            remote_server_location="http://custom-server:8080",
            session=self.session,
        )
        self.assertTrue(wrapper.is_remote)
        self.assertEqual(wrapper.remote_server_location, "http://custom-server:8080")
        self.assertIsInstance(wrapper.url_handler, RemoteUrl)

    def test_explicit_use_remote_false_forces_base_url(self):
        """
        Setting use_remote=False forces BaseUrl even when remote is configured.
        """
        self.config.remote_webtools_server_location = "http://192.168.0.200:3000"
        self.session.commit()

        wrapper = WebToolsWrapper(
            url="https://example.com/rss",
            use_remote=False,
            session=self.session,
        )
        self.assertFalse(wrapper.is_remote)
        self.assertIsNone(wrapper.remote_server_location)
        self.assertIsInstance(wrapper.url_handler, BaseUrl)

    def test_explicit_empty_remote_server_location_forces_base_url(self):
        """
        Passing remote_server_location='' disables remote and uses BaseUrl.
        """
        wrapper = WebToolsWrapper(
            url="https://example.com/rss",
            remote_server_location="",
            session=self.session,
        )
        self.assertFalse(wrapper.is_remote)
        self.assertIsNone(wrapper.remote_server_location)
        self.assertIsInstance(wrapper.url_handler, BaseUrl)

    def test_create_url_factory_returns_base_or_remote_url(self):
        """
        create_url helper returns BaseUrl or RemoteUrl instance.
        """
        # BaseUrl case
        h1 = create_url("https://example.com/feed", session=self.session)
        self.assertIsInstance(h1, BaseUrl)

        # RemoteUrl case
        h2 = create_url(
            "https://example.com/feed",
            remote_server_location="http://127.0.0.1:3000",
            session=self.session,
        )
        self.assertIsInstance(h2, RemoteUrl)

    def test_get_response_and_get_text_with_base_url(self):
        """
        Tests BaseUrl get_response and get_text logic using mock response.
        """
        wrapper = WebToolsWrapper(url="https://example.com/rss", session=self.session)
        sample_rss = "<rss><channel><title>Example</title></channel></rss>"
        mock_response = PageResponseObject(
            url="https://example.com/rss",
            status_code=200,
            text=sample_rss,
            binary=sample_rss.encode("utf-8"),
        )

        with patch.object(
            wrapper.url_handler, "get_response", return_value=mock_response
        ):
            resp = wrapper.get_response()
            self.assertIsNotNone(resp)
            self.assertEqual(resp.get_status_code(), 200)
            self.assertTrue(wrapper.is_valid())
            self.assertEqual(wrapper.get_status_code(), 200)
            self.assertEqual(wrapper.get_text(), sample_rss)
            self.assertEqual(wrapper.get_binary(), sample_rss.encode("utf-8"))

    def test_get_response_and_get_text_with_remote_url(self):
        """
        Tests RemoteUrl get_response and get_text logic using mock response.
        """
        wrapper = WebToolsWrapper(
            url="https://example.com/rss",
            remote_server_location="http://192.168.0.200:3000",
            session=self.session,
        )
        sample_rss = "<rss><channel><title>Remote Feed</title></channel></rss>"
        mock_response = PageResponseObject(
            url="https://example.com/rss",
            status_code=200,
            text=sample_rss,
            binary=sample_rss.encode("utf-8"),
        )

        with patch.object(
            wrapper.url_handler, "get_response", return_value=mock_response
        ):
            self.assertTrue(wrapper.is_remote)
            resp = wrapper.get_response()
            self.assertIsNotNone(resp)
            self.assertEqual(wrapper.get_text(), sample_rss)

    def test_convenience_functions(self):
        """
        Tests fetch_text and fetch_response convenience helpers.
        """
        sample_text = "Feed Content Here"
        mock_response = PageResponseObject(
            url="https://example.com/test",
            status_code=200,
            text=sample_text,
        )

        with patch.object(BaseUrl, "get_response", return_value=mock_response):
            text = fetch_text("https://example.com/test", session=self.session)
            self.assertEqual(text, sample_text)

            resp = fetch_response("https://example.com/test", session=self.session)
            self.assertIsNotNone(resp)
            self.assertEqual(resp.get_status_code(), 200)

    def test_aliases_are_identical(self):
        """
        WebToolkitWrapper and WebToolsService are aliases to WebToolsWrapper.
        """
        self.assertIs(WebToolkitWrapper, WebToolsWrapper)
        self.assertIs(WebToolsService, WebToolsWrapper)


class TestSourceServiceWithWrapper(unittest.TestCase):
    """
    Integration tests verifying SourceService uses WebToolsWrapper.
    """

    def setUp(self):
        self.app = create_app(
            {
                "TESTING": True,
                "DATABASE_PATH": ":memory:",
                "SECRET_KEY": "test-key-source-service",
            }
        )
        self.session = get_session()
        self.source_repo = SourceRepository(self.session)
        self.rules_repo = RulesRepository(self.session)
        self.block_repo = BlockEntryRepository(self.session)
        self.log_repo = LoggingRepository(self.session)
        self.source = self.source_repo.add_source(
            url="https://example.com/feed.xml",
            title="Test Feed",
            source_type="RSS",
            enabled=True,
        )

    def tearDown(self):
        close_session()

    def test_fetch_source_success_creates_entries(self):
        """
        SourceService._execute_fetch downloads through WebToolsWrapper and creates LinkDataModel rows.
        """
        sample_rss = """<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0">
          <channel>
            <title>Test Feed</title>
            <link>https://example.com</link>
            <item>
              <title>Entry Number One</title>
              <link>https://example.com/entry-1</link>
              <description>First description</description>
            </item>
            <item>
              <title>Entry Number Two</title>
              <link>https://example.com/entry-2</link>
              <description>Second description</description>
            </item>
          </channel>
        </rss>"""

        mock_resp = PageResponseObject(
            url=self.source.url,
            status_code=200,
            text=sample_rss,
            binary=sample_rss.encode("utf-8"),
        )

        with patch.object(BaseUrl, "get_response", return_value=mock_resp):
            res = SourceService.fetch_source(self.source.id, session=self.session)
            self.assertTrue(res.get("success"))
            self.assertEqual(res.get("entries_added"), 2)

            # Verify in DB
            entries = (
                self.session.execute(
                    select(LinkDataModel).where(
                        LinkDataModel.source_id == self.source.id
                    )
                )
                .scalars()
                .all()
            )
            self.assertEqual(len(entries), 2)
            links = [e.link for e in entries]
            self.assertIn("https://example.com/entry-1", links)
            self.assertIn("https://example.com/entry-2", links)

            # Verify operational data
            op_data = self.session.execute(
                select(SourceOperationalData).where(
                    SourceOperationalData.source_id == self.source.id
                )
            ).scalar_one()
            self.assertEqual(op_data.number_of_entries, 2)
            self.assertEqual(op_data.consecutive_errors, 0)
            self.assertIsNotNone(op_data.page_hash)

    def test_fetch_rss_source_with_regex_match_filter(self):
        """
        When source.xpath regex match pattern is specified on RSS source,
        only entries matching re.match(source.xpath, link) are ingested.
        """
        filtered_source = self.source_repo.add_source(
            url="https://filtered.example.com/feed.xml",
            title="Filtered RSS",
            source_type="RSS",
            xpath=r"https://filtered\.example\.com/allowed/.*",
            enabled=True,
        )
        sample_rss = """<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0">
          <channel>
            <title>Filtered RSS</title>
            <link>https://filtered.example.com</link>
            <item>
              <title>Allowed Entry</title>
              <link>https://filtered.example.com/allowed/item-1</link>
            </item>
            <item>
              <title>Ignored Entry</title>
              <link>https://filtered.example.com/ignored/item-2</link>
            </item>
          </channel>
        </rss>"""

        mock_resp = PageResponseObject(
            url=filtered_source.url,
            status_code=200,
            text=sample_rss,
            binary=sample_rss.encode("utf-8"),
        )

        with patch.object(BaseUrl, "get_response", return_value=mock_resp):
            res = SourceService.fetch_source(filtered_source.id, session=self.session)
            self.assertTrue(res.get("success"))
            self.assertEqual(res.get("entries_added"), 1)

            entries = (
                self.session.execute(
                    select(LinkDataModel).where(
                        LinkDataModel.source_id == filtered_source.id
                    )
                )
                .scalars()
                .all()
            )
            self.assertEqual(len(entries), 1)
            self.assertEqual(
                entries[0].link, "https://filtered.example.com/allowed/item-1"
            )

    def test_fetch_parse_source_with_regex_match_filter(self):
        """
        When source.xpath regex match pattern is specified on PARSE source,
        only links matching re.match(source.xpath, link) are ingested.
        """
        parse_source = self.source_repo.add_source(
            url="https://parse.example.com/index.html",
            title="Parse Source Test",
            source_type="PARSE",
            xpath=r"https://parse\.example\.com/posts/\d+",
            enabled=True,
        )

        mock_resp = PageResponseObject(
            url=parse_source.url,
            status_code=200,
            text="<html><body>mock</body></html>",
            binary=b"<html><body>mock</body></html>",
        )

        discovered_links = [
            "https://parse.example.com/posts/101",
            "https://parse.example.com/posts/102",
            "https://parse.example.com/about",
            "https://other.com/external",
        ]

        with patch.object(
            BaseUrl, "get_response", return_value=mock_resp
        ), patch.object(BaseUrl, "get_content_links", return_value=discovered_links):
            res = SourceService.fetch_source(parse_source.id, session=self.session)
            self.assertTrue(res.get("success"))
            self.assertEqual(res.get("entries_added"), 2)

            entries = (
                self.session.execute(
                    select(LinkDataModel).where(
                        LinkDataModel.source_id == parse_source.id
                    )
                )
                .scalars()
                .all()
            )
            self.assertEqual(len(entries), 2)
            links = {e.link for e in entries}
            self.assertEqual(
                links,
                {
                    "https://parse.example.com/posts/101",
                    "https://parse.example.com/posts/102",
                },
            )

            # Verify background link-update-data jobs were enqueued for each extracted link
            jobs = (
                self.session.execute(
                    select(BackgroundJob).where(BackgroundJob.job == "link-update-data")
                )
                .scalars()
                .all()
            )
            job_subjects = {j.subject for j in jobs}
            self.assertEqual(
                job_subjects,
                {
                    "https://parse.example.com/posts/101",
                    "https://parse.example.com/posts/102",
                },
            )

    def test_fetch_source_unchanged_hash_skips_parsing(self):
        """
        When hash matches previous fetch, SourceService returns status='unchanged'.
        """
        sample_rss = """<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0">
          <channel>
            <title>Unchanged Feed</title>
            <item>
              <title>Static Item</title>
              <link>https://example.com/static</link>
            </item>
          </channel>
        </rss>"""

        content_bytes = sample_rss.encode("utf-8")
        page_hash = hashlib.sha256(content_bytes).digest()

        # Update existing op_data with this page_hash
        op_data = (
            self.session.execute(
                select(SourceOperationalData).where(
                    SourceOperationalData.source_id == self.source.id
                )
            )
            .scalars()
            .first()
        )
        if op_data is None:
            op_data = SourceOperationalData(source_id=self.source.id)
            self.session.add(op_data)
        op_data.page_hash = page_hash
        op_data.body_hash = page_hash
        op_data.consecutive_errors = 0
        op_data.number_of_entries = 1
        self.session.commit()

        mock_resp = PageResponseObject(
            url=self.source.url,
            status_code=200,
            text=sample_rss,
            binary=content_bytes,
        )

        with patch.object(BaseUrl, "get_response", return_value=mock_resp):
            res = SourceService.fetch_source(self.source.id, session=self.session)
            self.assertTrue(res.get("success"))
            self.assertEqual(res.get("status"), "unchanged")
            self.assertEqual(res.get("entries_added"), 0)

    def test_fetch_source_network_error_tracks_consecutive_errors(self):
        """
        When WebToolsWrapper returns invalid response, consecutive_errors increments.
        """
        mock_resp = PageResponseObject(
            url=self.source.url,
            status_code=500,
            text=None,
        )
        mock_resp.add_error("Internal Server Error")

        with patch.object(BaseUrl, "get_response", return_value=mock_resp):
            res = SourceService.fetch_source(self.source.id, session=self.session)
            self.assertFalse(res.get("success"))
            self.assertEqual(res.get("status"), "error")

            op_data = self.session.execute(
                select(SourceOperationalData).where(
                    SourceOperationalData.source_id == self.source.id
                )
            ).scalar_one()
            self.assertEqual(op_data.consecutive_errors, 1)

    def test_fetch_email_source_success(self):
        """
        SourceService._execute_fetch_email extracts emails via EmailReader and creates LinkDataModel rows.
        """
        from linkarchivetools.model.definitions import Credentials, User

        user = self.session.execute(select(User).limit(1)).scalar_one_or_none()
        if not user:
            user = User(
                username="testuser",
                password="",
                first_name="",
                last_name="",
                email="",
                is_superuser=True,
                is_active=True,
                is_staff=True,
            )
            self.session.add(user)
            self.session.flush()

        creds = Credentials(
            name="Test Mail Creds",
            credential_type="email",
            username="reader@example.com",
            password="secretpassword",
            user_id=user.id,
        )
        self.session.add(creds)
        self.session.flush()

        email_source = self.source_repo.add_source(
            url="imap.example.com",
            title="Tech Newsletter",
            source_type="EMAIL",
            credentials_id=creds.id,
            enabled=True,
        )

        mock_email = MagicMock()
        mock_email.id = "msg123"
        mock_email.title = "Weekly Digest #42"
        mock_email.date_published = datetime(2026, 5, 1, 12, 0, 0, tzinfo=timezone.utc)
        mock_email.body = "Here are the top stories of the week."
        mock_email.author = "Weekly Editor"

        with patch("yafr.services.source_service.EmailReader") as MockEmailReader:
            instance = MockEmailReader.return_value
            instance.connect.return_value = True
            instance.get_emails.return_value = [mock_email]

            res = SourceService.fetch_source(email_source.id, session=self.session)
            self.assertTrue(res.get("success"))
            self.assertEqual(res.get("entries_added"), 1)

            # Verify in DB
            entries = (
                self.session.execute(
                    select(LinkDataModel).where(
                        LinkDataModel.source_id == email_source.id
                    )
                )
                .scalars()
                .all()
            )
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0].title, "Weekly Digest #42")
            self.assertEqual(
                entries[0].link, "email://imap.example.com/reader@example.com/msg123"
            )
            self.assertEqual(
                entries[0].description, "Here are the top stories of the week."
            )

            # Operational data: email sources do not store page_hash / body_hash
            op_data = self.session.execute(
                select(SourceOperationalData).where(
                    SourceOperationalData.source_id == email_source.id
                )
            ).scalar_one()
            self.assertEqual(op_data.number_of_entries, 1)
            self.assertIsNone(op_data.page_hash)
            self.assertIsNone(op_data.body_hash)
            self.assertEqual(op_data.consecutive_errors, 0)

    def test_fetch_source_removed_when_blocked_by_entry_rule(self):
        """When source.url matches an EntryRule with block=True, source is removed and applogging records it."""
        blocked_source = self.source_repo.add_source(
            url="https://spam-feed.example.com/rss",
            title="Spammy Feed",
            source_type="RSS",
            enabled=True,
        )
        source_id = blocked_source.id

        # Add EntryRule with block=True
        self.rules_repo.add_rule(
            rule_name="Block Spam Feed",
            trigger_rule_url=r".*spam-feed\.example\.com.*",
            block=True,
            priority=1,
            enabled=True,
        )

        res = SourceService.fetch_source(source_id, session=self.session)

        # Status is removed
        self.assertEqual(res.get("status"), "removed")
        self.assertTrue(res.get("success"))

        # Source is removed from database
        self.assertIsNone(self.source_repo.get_by_id(source_id))

        # AppLogging contains notification
        logs = self.log_repo.list_logs(limit=10)
        self.assertTrue(
            any("removed (blocked)" in (log.info_text or "") for log in logs)
        )
        self.assertTrue(
            any("Block Spam Feed" in (log.detail_text or "") for log in logs)
        )

    def test_fetch_source_removed_when_blocked_by_block_entry(self):
        """When source.url matches a BlockEntry pattern, source is removed and applogging records it."""
        blocked_source = self.source_repo.add_source(
            url="https://tracker-ads.net/syndication/rss",
            title="Tracker Feed",
            source_type="RSS",
            enabled=True,
        )
        source_id = blocked_source.id

        # Add BlockEntry whose url matches part of the source link
        self.block_repo.add_entry("tracker-ads.net")

        res = SourceService.fetch_source(source_id, session=self.session)

        # Status is removed
        self.assertEqual(res.get("status"), "removed")
        self.assertTrue(res.get("success"))

        # Source is removed from database
        self.assertIsNone(self.source_repo.get_by_id(source_id))

        # AppLogging contains notification
        logs = self.log_repo.list_logs(limit=10)
        self.assertTrue(
            any("removed (blocked)" in (log.info_text or "") for log in logs)
        )
        self.assertTrue(
            any("tracker-ads.net" in (log.detail_text or "") for log in logs)
        )


class TestWebToolsStatusApi(unittest.TestCase):
    """
    Test suite for WebTools reachability and API status endpoints.
    """

    def setUp(self):
        self.app = create_app(
            {
                "TESTING": True,
                "DATABASE_PATH": ":memory:",
                "SECRET_KEY": "test-key-webtools-api",
            }
        )
        self.client = self.app.test_client()
        self.session = get_session()
        self.config_repo = ConfigRepository(self.session)
        self.config = self.config_repo.get_config()
        self.config.remote_webtools_server_location = None
        self.session.commit()

    def tearDown(self):
        close_session()

    def test_check_remote_status_not_configured(self):
        """
        When not configured, check_remote_status returns configured=False.
        """
        status = WebToolsWrapper.check_remote_status(session=self.session)
        self.assertFalse(status["configured"])
        self.assertFalse(status["online"])
        self.assertIsNone(status["url"])

    def test_check_remote_status_online(self):
        """
        When remote server responds with 200, check_remote_status returns online=True.
        """
        mock_resp = MagicMock(status_code=200)
        with patch("requests.get", return_value=mock_resp):
            status = WebToolsWrapper.check_remote_status(
                remote_server_location="http://192.168.0.200:3000",
                session=self.session,
            )
            self.assertTrue(status["configured"])
            self.assertTrue(status["online"])
            self.assertEqual(status["status_code"], 200)

    def test_check_remote_status_offline(self):
        """
        When remote server connection fails, check_remote_status returns online=False.
        """
        with patch("requests.get", side_effect=ConnectionError("Connection refused")):
            status = WebToolsWrapper.check_remote_status(
                remote_server_location="http://127.0.0.1:9999",
                session=self.session,
            )
            self.assertTrue(status["configured"])
            self.assertFalse(status["online"])
            self.assertIn("Connection refused", status.get("error", ""))

    def test_api_webtools_status_endpoint(self):
        """
        GET /api/config/webtools-status returns current configured status.
        """
        self.config.remote_webtools_server_location = "http://192.168.0.200:3000"
        self.session.commit()

        mock_resp = MagicMock(status_code=200)
        with patch("requests.get", return_value=mock_resp):
            resp = self.client.get("/api/config/webtools-status")
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertTrue(data.get("success"))
            self.assertTrue(data.get("configured"))
            self.assertTrue(data.get("online"))

    def test_api_test_webtools_endpoint(self):
        """
        POST /api/config/test-webtools tests reachability of submitted URL.
        """
        mock_resp = MagicMock(status_code=200)
        with patch("requests.get", return_value=mock_resp):
            resp = self.client.post(
                "/api/config/test-webtools",
                json={"url": "http://192.168.0.200:3000"},
            )
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertTrue(data.get("success"))
            self.assertTrue(data.get("online"))

    def test_get_title_and_description_from_handler(self):
        """WebToolsWrapper.get_title and get_description delegates to url_handler."""
        wrapper = WebToolsWrapper(
            url="https://example.com/test-page", session=self.session
        )
        wrapper.url_handler = MagicMock()
        wrapper.url_handler.get_title.return_value = "Mocked Page Title"
        wrapper.url_handler.get_description.return_value = "Mocked Page Description"
        wrapper._response = MagicMock(is_valid=lambda: True)

        self.assertEqual(wrapper.get_title(), "Mocked Page Title")
        self.assertEqual(wrapper.get_description(), "Mocked Page Description")

    def test_no_fallback_to_response_or_beautifulsoup(self):
        """
        WebToolsWrapper does NOT fall back on response object or BeautifulSoup HTML parsing.
        Either BaseUrl/RemoteUrl works, or not.
        """
        html_doc = """
        <html>
            <head>
                <title>HTML Fallback Title</title>
                <meta name="description" content="HTML Fallback Description" />
            </head>
            <body>Content</body>
        </html>
        """
        wrapper = WebToolsWrapper(
            url="https://example.com/html-fallback", session=self.session
        )
        wrapper.url_handler = MagicMock(spec=[])  # No get_title / get_description
        mock_resp = MagicMock()
        mock_resp.get_text.return_value = html_doc
        mock_resp.get_title.return_value = "Response Title Fallback"
        mock_resp.get_description.return_value = "Response Description Fallback"
        wrapper._response = mock_resp

        # Must return None because handler does not provide them; no fallback allowed
        self.assertIsNone(wrapper.get_title())
        self.assertIsNone(wrapper.get_description())

    def test_all_metadata_getters_delegate_to_handler(self):
        """
        WebToolsWrapper delegates title, description, date_published, author, album,
        language, thumbnail, tags, canonical_url, and social_properties to url_handler.
        """
        wrapper = WebToolsWrapper(
            url="https://example.com/meta-page", session=self.session
        )
        mock_handler = MagicMock()
        pub_date = datetime(2026, 5, 10, 12, 0, tzinfo=timezone.utc)
        mock_handler.get_title.return_value = "Sample Title"
        mock_handler.get_description.return_value = "Sample Description"
        mock_handler.get_date_published.return_value = pub_date
        mock_handler.get_author.return_value = "Sample Author"
        mock_handler.get_language.return_value = "en"
        mock_handler.get_thumbnail.return_value = "https://example.com/thumb.png"
        mock_handler.get_album.return_value = "Sample Album"
        mock_handler.get_tags.return_value = ["tech", "python"]
        mock_handler.get_canonical_url.return_value = "https://example.com/canonical"
        mock_handler.get_social_properties.return_value = {
            "rating": 4.5,
            "thumbs_up": 100,
        }
        mock_handler.get_content_links.return_value = [
            "https://example.com/link1",
            "https://example.com/link2",
        ]

        wrapper.url_handler = mock_handler
        wrapper._response = MagicMock(is_valid=lambda: True)

        self.assertEqual(wrapper.get_title(), "Sample Title")
        self.assertEqual(wrapper.get_description(), "Sample Description")
        self.assertEqual(wrapper.get_date_published(), pub_date)
        self.assertEqual(wrapper.get_author(), "Sample Author")
        self.assertEqual(wrapper.get_language(), "en")
        self.assertEqual(wrapper.get_thumbnail(), "https://example.com/thumb.png")
        self.assertEqual(wrapper.get_album(), "Sample Album")
        self.assertEqual(wrapper.get_tags(), ["tech", "python"])
        self.assertEqual(wrapper.get_canonical_url(), "https://example.com/canonical")
        self.assertEqual(
            wrapper.get_social_properties(), {"rating": 4.5, "thumbs_up": 100}
        )
        self.assertEqual(
            wrapper.get_content_links(),
            ["https://example.com/link1", "https://example.com/link2"],
        )

    def test_get_content_links_handling(self):
        """
        WebToolsWrapper.get_content_links always returns a list and handles
        various formats and handler errors gracefully.
        """
        wrapper = WebToolsWrapper(url="https://example.com/page", session=self.session)
        mock_handler = MagicMock()
        wrapper.url_handler = mock_handler
        wrapper._response = MagicMock(is_valid=lambda: True)

        # 1. Normal list
        mock_handler.get_content_links.return_value = ["https://a.com", "https://b.com"]
        self.assertEqual(
            wrapper.get_content_links(), ["https://a.com", "https://b.com"]
        )

        # 2. Set / tuple conversion to list
        mock_handler.get_content_links.return_value = ("https://c.com",)
        self.assertEqual(wrapper.get_content_links(), ["https://c.com"])

        # 3. None returns empty list
        mock_handler.get_content_links.return_value = None
        self.assertEqual(wrapper.get_content_links(), [])

        # 4. Exception handled gracefully returning empty list
        mock_handler.get_content_links.side_effect = RuntimeError(
            "Parser error in webtoolkit"
        )
        self.assertEqual(wrapper.get_content_links(), [])

    def test_convenience_fetch_metadata_helpers(self):
        """
        WebToolsWrapper.fetch_title, fetch_description, fetch_date_published,
        fetch_author, and fetch_content_links work correctly.
        """
        pub_date = datetime(2026, 1, 1, tzinfo=timezone.utc)
        mock_handler = MagicMock()
        mock_handler.get_title.return_value = "Fetched Title"
        mock_handler.get_description.return_value = "Fetched Description"
        mock_handler.get_date_published.return_value = pub_date
        mock_handler.get_author.return_value = "Fetched Author"
        mock_handler.get_content_links.return_value = ["https://example.com/out1"]

        with patch.object(
            WebToolsWrapper, "_create_handler", return_value=mock_handler
        ):
            self.assertEqual(
                WebToolsWrapper.fetch_title(
                    "https://example.com/f", session=self.session
                ),
                "Fetched Title",
            )
            self.assertEqual(
                WebToolsWrapper.fetch_description(
                    "https://example.com/f", session=self.session
                ),
                "Fetched Description",
            )
            self.assertEqual(
                WebToolsWrapper.fetch_date_published(
                    "https://example.com/f", session=self.session
                ),
                pub_date,
            )
            self.assertEqual(
                WebToolsWrapper.fetch_author(
                    "https://example.com/f", session=self.session
                ),
                "Fetched Author",
            )
            self.assertEqual(
                WebToolsWrapper.fetch_content_links(
                    "https://example.com/f", session=self.session
                ),
                ["https://example.com/out1"],
            )


if __name__ == "__main__":
    unittest.main()
