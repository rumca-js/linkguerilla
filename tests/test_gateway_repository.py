"""Tests for gateway seed data and query operations."""

import unittest

from linkarchivetools.model.definitions import Gateway
from yafr.db import GatewayRepository, close_session, get_session, init_db


class TestGatewayRepository(unittest.TestCase):
    def setUp(self):
        init_db(db_path=":memory:", sync_schema=True)
        self.session = get_session()
        self.repo = GatewayRepository(self.session)

    def tearDown(self):
        close_session()

    def test_type_constants_match_supported_gateway_types(self):
        self.assertEqual(
            set(self.repo.GATEWAYS_TYPES),
            {
                self.repo.TYPE_GATEWAY,
                self.repo.TYPE_SEARCH_ENGINE,
                self.repo.TYPE_AI_BOT,
                self.repo.TYPE_POPULAR,
                self.repo.TYPE_SOCIAL_MEDIA,
                self.repo.TYPE_FAVOURITE,
                self.repo.TYPE_AUDIO_STREAMING,
                self.repo.TYPE_VIDEO_STREAMING,
                self.repo.TYPE_FILE_SHARING,
                self.repo.TYPE_BANKING,
                self.repo.TYPE_DIGITAL_LIBRARY,
                self.repo.TYPE_MARKETPLACE,
                self.repo.TYPE_APP_STORE,
                self.repo.TYPE_OTHER,
            },
        )

    def test_populate_is_idempotent(self):
        self.repo.populate()
        count = self.repo.count(Gateway)
        self.assertGreater(count, 0)
        self.assertIsNotNone(self.repo.get_by_link("https://google.com"))

        self.repo.populate()
        self.assertEqual(self.repo.count(Gateway), count)

    def test_get_types_mapping_returns_requested_named_groups(self):
        self.repo.add_gateway(
            "https://example.com", self.repo.TYPE_GATEWAY, title="Example"
        )
        self.repo.add_gateway("https://search.example", self.repo.TYPE_SEARCH_ENGINE)

        grouped = self.repo.get_types_mapping(
            [self.repo.TYPE_GATEWAY, self.repo.TYPE_SEARCH_ENGINE]
        )

        self.assertEqual(list(grouped), ["search_engines", "gateways"])
        self.assertEqual(
            [row.link for row in grouped["gateways"]], ["https://example.com"]
        )
        self.assertEqual(
            [row.link for row in grouped["search_engines"]], ["https://search.example"]
        )

    def test_cleanup_full_repopulates_defaults(self):
        self.repo.add_gateway("https://custom.example", self.repo.TYPE_OTHER)

        self.repo.cleanup({"full": True})

        self.assertIsNone(self.repo.get_by_link("https://custom.example"))
        self.assertIsNotNone(self.repo.get_by_link("https://google.com"))

    def test_cleanup_without_full_leaves_rows_unchanged(self):
        row = self.repo.add_gateway("https://custom.example", self.repo.TYPE_OTHER)

        self.repo.cleanup()

        self.assertEqual(self.repo.count(Gateway), 1)
        self.assertIsNotNone(self.repo.get_by_id(Gateway, row.id))


if __name__ == "__main__":
    unittest.main()
