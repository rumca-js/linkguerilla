"""
Unit tests for AppLoggingHandler and NOTIFICATION log level in YAFR.
"""

import logging
import unittest
from yafr.db import (
    LoggingRepository,
    init_db,
    close_session,
    get_session,
)
from yafr.db.logging_repository import (
    AppLoggingHandler,
    setup_app_logging,
    NOTIFICATION,
)


class TestAppLoggingHandler(unittest.TestCase):
    """
    Test suite for AppLoggingHandler and NOTIFICATION severity level.
    """

    @classmethod
    def setUpClass(cls):
        init_db(":memory:", sync_schema=True)

    @classmethod
    def tearDownClass(cls):
        close_session()

    def setUp(self):
        self.session = get_session()
        self.repo = LoggingRepository(self.session)
        self.repo.clear_logs()

    def tearDown(self):
        close_session()

    def test_notification_level_constants(self):
        """Verifies NOTIFICATION level constant on LoggingRepository and in logging module."""
        self.assertEqual(LoggingRepository.NOTIFICATION, 25)
        self.assertEqual(NOTIFICATION, 25)
        self.assertEqual(logging.getLevelName(25), "NOTIFICATION")
        self.assertEqual(logging.getLevelName("NOTIFICATION"), 25)

    def test_logger_has_notification_method(self):
        """Verifies logger.notification helper method exists and can be called."""
        test_logger = logging.getLogger("test_notification_logger")
        self.assertTrue(hasattr(test_logger, "notification"))
        self.assertTrue(callable(getattr(test_logger, "notification")))

    def test_handler_threshold_filters_debug_and_info(self):
        """Verifies handler ignores DEBUG and INFO by default (threshold NOTIFICATION 25)."""
        logger = logging.getLogger("test_handler_threshold")
        logger.propagate = False
        logger.setLevel(logging.DEBUG)
        handler = AppLoggingHandler(level=NOTIFICATION)
        logger.addHandler(handler)

        try:
            logger.debug("Debug event - should not be in db")
            logger.info("Info event - should not be in db")

            logs = self.repo.list_logs()
            self.assertEqual(len(logs), 0)
        finally:
            logger.removeHandler(handler)

    def test_handler_persists_notification_and_above(self):
        """Verifies handler captures NOTIFICATION, WARNING, ERROR, CRITICAL to SQLite."""
        logger = logging.getLogger("test_handler_persistence")
        logger.propagate = False
        logger.setLevel(logging.DEBUG)
        handler = AppLoggingHandler(level=NOTIFICATION)
        logger.addHandler(handler)

        try:
            logger.notification("Milestone: 10 new items fetched")
            logger.warning("Warning: slow response from feed")
            logger.error("Error: connection refused")
            logger.critical("Fatal: system out of memory")

            logs = self.repo.list_logs()
            self.assertEqual(len(logs), 4)

            # Ordered by id desc
            self.assertEqual(logs[0].level, logging.CRITICAL)
            self.assertEqual(logs[0].info_text, "Fatal: system out of memory")

            self.assertEqual(logs[1].level, logging.ERROR)
            self.assertEqual(logs[1].info_text, "Error: connection refused")
            self.assertIsNotNone(logs[1].detail_text)

            self.assertEqual(logs[2].level, logging.WARNING)
            self.assertEqual(logs[2].info_text, "Warning: slow response from feed")

            self.assertEqual(logs[3].level, NOTIFICATION)
            self.assertEqual(logs[3].info_text, "Milestone: 10 new items fetched")
        finally:
            logger.removeHandler(handler)

    def test_handler_captures_exception_traceback(self):
        """Verifies handler captures exception tracebacks into detail_text."""
        logger = logging.getLogger("test_handler_traceback")
        logger.propagate = False
        logger.setLevel(logging.DEBUG)
        handler = AppLoggingHandler(level=NOTIFICATION)
        logger.addHandler(handler)

        try:
            try:
                raise ValueError("Custom calculation error")
            except ValueError:
                logger.exception("Caught an exception")

            logs = self.repo.list_logs()
            self.assertEqual(len(logs), 1)
            self.assertEqual(logs[0].level, logging.ERROR)
            self.assertEqual(logs[0].info_text, "Caught an exception")
            self.assertIn("ValueError: Custom calculation error", logs[0].detail_text)
            self.assertIn("Traceback", logs[0].detail_text)
        finally:
            logger.removeHandler(handler)

    def test_setup_app_logging_idempotent(self):
        """Verifies setup_app_logging attaches the handler once without duplicates."""
        logger = logging.getLogger("yafr.test.idempotent")
        setup_app_logging(logger_name="yafr.test.idempotent", level=NOTIFICATION)
        handler_count_1 = sum(
            1 for h in logger.handlers if isinstance(h, AppLoggingHandler)
        )
        self.assertEqual(handler_count_1, 1)

        # Calling again should not add a second handler
        setup_app_logging(logger_name="yafr.test.idempotent", level=NOTIFICATION)
        handler_count_2 = sum(
            1 for h in logger.handlers if isinstance(h, AppLoggingHandler)
        )
        self.assertEqual(handler_count_2, 1)

        # Cleanup
        for h in list(logger.handlers):
            if isinstance(h, AppLoggingHandler):
                logger.removeHandler(h)


if __name__ == "__main__":
    unittest.main()
