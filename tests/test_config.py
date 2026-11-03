"""
Unit and integration tests for ConfigurationView, /api/config endpoints,
and enable_* feature flag toggles (enable_background_jobs, enable_crawling, enable_social_data).
"""

import json
import unittest
from yafr.app import create_app
from yafr.db import ConfigRepository, close_session, get_session
from yafr.services import ConfigService
from yafr.workers.job_executor import JobExecutor


class TestConfigurationFeatures(unittest.TestCase):
    """
    Test suite for enable_* feature toggles in ConfigService and ConfigRepository.
    """

    def setUp(self):
        self.app = create_app(
            {
                "TESTING": True,
                "DATABASE_PATH": ":memory:",
                "SECRET_KEY": "test-key-config",
            }
        )
        self.session = get_session()
        self.config_repo = ConfigRepository(self.session)

    def tearDown(self):
        close_session()

    def test_default_feature_flags(self):
        """Verifies default values for enable_* flags."""
        features = ConfigService.get_feature_flags(session=self.session)
        self.assertIn("enable_background_jobs", features)
        self.assertIn("enable_crawling", features)
        self.assertIn("enable_social_data", features)
        self.assertTrue(features["enable_background_jobs"])
        self.assertTrue(features["enable_social_data"])
        self.assertFalse(features["enable_crawling"])

    def test_set_feature_flag_explicit(self):
        """Verifies setting feature flag to specific boolean values."""
        canonical, state = ConfigService.set_feature_flag(
            "enable_crawling", enabled=True, session=self.session
        )
        self.assertEqual(canonical, "enable_crawling")
        self.assertTrue(state)

        config = self.config_repo.get_config()
        self.assertTrue(config.enable_crawling)

        canonical, state = ConfigService.set_feature_flag(
            "crawling", enabled=False, session=self.session
        )
        self.assertEqual(canonical, "enable_crawling")
        self.assertFalse(state)

        config = self.config_repo.get_config()
        self.assertFalse(config.enable_crawling)

    def test_set_feature_flag_toggle(self):
        """Verifies toggling feature flag when enabled argument is omitted."""
        config = self.config_repo.get_config()
        initial_bg = config.enable_background_jobs

        canonical, new_state = ConfigService.set_feature_flag(
            "background-jobs", enabled=None, session=self.session
        )
        self.assertEqual(canonical, "enable_background_jobs")
        self.assertEqual(new_state, not initial_bg)

        # Toggle again
        _, toggled_back = ConfigService.set_feature_flag(
            "enable_background_jobs", enabled=None, session=self.session
        )
        self.assertEqual(toggled_back, initial_bg)

    def test_unknown_feature_flag_raises_error(self):
        """Verifies that setting an unknown feature flag raises ValueError."""
        with self.assertRaises(ValueError):
            ConfigService.set_feature_flag("non_existent_feature", session=self.session)


class TestConfigurationWebAndApi(unittest.TestCase):
    """
    Test suite for Configuration HTML views and /api/config endpoints.
    """

    def setUp(self):
        self.app = create_app(
            {
                "TESTING": True,
                "DATABASE_PATH": ":memory:",
                "SECRET_KEY": "test-key-config-web",
            }
        )
        self.client = self.app.test_client()
        self.session = get_session()
        self.config_repo = ConfigRepository(self.session)

    def tearDown(self):
        close_session()

    def test_configuration_view_renders_enable_fields(self):
        """GET /configuration renders switches for enable_background_jobs, enable_crawling, enable_social_data, and accept_* links."""
        res = self.client.get("/configuration")
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)

        self.assertIn("enable_background_jobs", html)
        self.assertIn("enable_crawling", html)
        self.assertIn("enable_social_data", html)
        self.assertIn("Enable Background Jobs", html)
        self.assertIn("Enable Crawling", html)
        self.assertIn("Enable Social Data", html)
        self.assertIn("accept_domain_links", html)
        self.assertIn("accept_non_domain_links", html)
        self.assertIn("Accept Domain Links", html)
        self.assertIn("Accept Non-Domain Links", html)

    def test_post_configuration_updates_enable_fields(self):
        """POST /configuration persists updated enable_* and accept_* checkbox states."""
        # Uncheck enable_background_jobs, check enable_crawling and accept_non_domain_links
        res = self.client.post(
            "/configuration",
            data={
                "instance_title": "Custom YAFR",
                "enable_crawling": "on",
                "enable_social_data": "on",
                "accept_non_domain_links": "on",
                # enable_background_jobs omitted -> should become False
            },
            follow_redirects=True,
        )
        self.assertEqual(res.status_code, 200)

        config = self.config_repo.get_config()
        self.assertFalse(config.enable_background_jobs)
        self.assertTrue(config.enable_crawling)
        self.assertTrue(config.enable_social_data)
        self.assertTrue(config.accept_non_domain_links)

    def test_api_get_features(self):
        """GET /api/config/features returns full dictionary of feature flags."""
        res = self.client.get("/api/config/features")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertIn("features", data)
        self.assertIn("enable_background_jobs", data["features"])
        self.assertIn("enable_crawling", data["features"])
        self.assertIn("enable_social_data", data["features"])

    def test_api_manage_feature_get(self):
        """GET /api/config/enable/<feature> returns single feature state."""
        res = self.client.get("/api/config/enable/background_jobs")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["feature"], "enable_background_jobs")
        self.assertTrue(data["enabled"])

    def test_api_manage_feature_post_explicit(self):
        """POST /api/config/enable/<feature> with payload updates feature state."""
        res = self.client.post(
            "/api/config/enable/crawling",
            json={"enabled": True},
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["feature"], "enable_crawling")
        self.assertTrue(data["enabled"])

        config = self.config_repo.get_config()
        self.assertTrue(config.enable_crawling)

    def test_api_manage_feature_post_toggle(self):
        """POST /api/config/enable/<feature> without payload toggles current state."""
        config = self.config_repo.get_config()
        current = config.enable_background_jobs

        res = self.client.post("/api/config/enable/enable_background_jobs")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["enabled"], not current)

    def test_api_convenience_endpoints(self):
        """POST convenience endpoints for background-jobs, social-data, and crawling."""
        # 1. Background jobs
        res1 = self.client.post(
            "/api/config/enable-background-jobs", json={"enabled": False}
        )
        self.assertEqual(res1.status_code, 200)
        self.assertFalse(res1.get_json()["enabled"])

        # 2. Social data
        res2 = self.client.post(
            "/api/config/enable-social-data", json={"enabled": False}
        )
        self.assertEqual(res2.status_code, 200)
        self.assertFalse(res2.get_json()["enabled"])

        # 3. Crawling
        res3 = self.client.post("/api/config/enable-crawling", json={"enabled": True})
        self.assertEqual(res3.status_code, 200)
        self.assertTrue(res3.get_json()["enabled"])


class TestInstanceConfigAndConsoleTitles(unittest.TestCase):
    """
    Test suite for centralized instance title, description, and console titles.
    """

    def test_default_config_constants(self):
        """Verifies default values and aliases in yafr.config."""
        import yafr.config as config_mod
        from yafr.config import Config

        self.assertEqual(Config.INSTANCE_TITLE, "LinkGuerilla")
        self.assertEqual(Config.INSTANCE_DESCRIPTION, "Link manager and aggregator")
        self.assertEqual(Config.APP_NAME, "LinkGuerilla")
        self.assertEqual(Config.APP_DESCRIPTION, "Link manager and aggregator")
        self.assertEqual(
            Config.APP_CONSOLE_TITLE,
            "LinkGuerilla - Link manager and aggregator",
        )
        self.assertEqual(
            Config.WORKER_CONSOLE_TITLE,
            "LinkGuerilla - Background Task Processor",
        )

        # Module-level exported constants
        self.assertEqual(config_mod.INSTANCE_TITLE, Config.INSTANCE_TITLE)
        self.assertEqual(config_mod.INSTANCE_DESCRIPTION, Config.INSTANCE_DESCRIPTION)
        self.assertEqual(config_mod.APP_NAME, Config.APP_NAME)
        self.assertEqual(config_mod.APP_DESCRIPTION, Config.APP_DESCRIPTION)
        self.assertEqual(config_mod.APP_CONSOLE_TITLE, Config.APP_CONSOLE_TITLE)
        self.assertEqual(config_mod.WORKER_CONSOLE_TITLE, Config.WORKER_CONSOLE_TITLE)

    def test_set_console_title_runs_safely(self):
        """Verifies set_console_title executes cleanly without raising exceptions."""
        from yafr.config import set_console_title

        # Should execute safely in both TTY and non-TTY test environments
        set_console_title("Test Title")
        set_console_title("")

    def test_shared_context_defaults(self):
        """Verifies get_shared_context provides app_name and app_tagline from Config."""
        from yafr.app import create_app
        from yafr.config import Config
        from yafr.web.shared import get_shared_context

        app = create_app({"TESTING": True, "DATABASE_PATH": ":memory:"})
        with app.app_context():
            context = get_shared_context()
            self.assertEqual(context["app_name"], Config.INSTANCE_TITLE)
            self.assertEqual(context["app_tagline"], Config.INSTANCE_DESCRIPTION)


if __name__ == "__main__":
    unittest.main()
