"""
Configuration Service for YAFR.

Provides business logic for retrieving, updating, and resetting application settings,
applying UI presets, and modifying display preferences.
"""

import logging
from typing import Any, Dict, Optional, Tuple
from sqlalchemy.orm import Session
from linkarchivetools.model.definitions import ConfigurationEntry
from yafr.db import ConfigRepository, get_session

logger = logging.getLogger(__name__)


class ConfigService:
    """
    Domain service for application configuration operations.
    """

    @staticmethod
    def get_config_model(session: Optional[Session] = None) -> ConfigurationEntry:
        """
        Retrieves the active ConfigurationEntry ORM instance.
        """
        repo = ConfigRepository(session=session)
        return repo.get_config()

    @staticmethod
    def get_config_dict(session: Optional[Session] = None) -> Dict[str, Any]:
        """
        Returns all configuration attributes as a key-value dictionary.
        """
        repo = ConfigRepository(session=session)
        return repo.to_dict()

    @staticmethod
    def update_config(
        data: Dict[str, Any], session: Optional[Session] = None
    ) -> ConfigurationEntry:
        """
        Updates multiple configuration attributes on the active configuration.

        :param data: Key-value dictionary of settings to update
        :param session: Optional SQLAlchemy session
        :return: Updated ConfigurationEntry instance
        """
        repo = ConfigRepository(session=session)
        logger.info("Updating configuration with %d attributes", len(data))
        return repo.update_config(**data)

    @staticmethod
    def set_display_style(
        style: str, session: Optional[Session] = None
    ) -> ConfigurationEntry:
        """
        Sets the active display style theme ('style-dark' or 'style-light').
        """
        if style not in ("style-dark", "style-light"):
            raise ValueError(f"Invalid display style: '{style}'")
        repo = ConfigRepository(session=session)
        return repo.update_config(display_style=style)

    @staticmethod
    def set_display_type(
        display_type: str, session: Optional[Session] = None
    ) -> ConfigurationEntry:
        """
        Sets the active card layout type (gallery, standard, search-engine, etc.).
        """
        valid_types = (
            "gallery",
            "standard",
            "search-engine",
            "content-centric",
            "links-only",
        )
        if display_type not in valid_types:
            raise ValueError(f"Invalid display type: '{display_type}'")
        repo = ConfigRepository(session=session)
        return repo.update_config(display_type=display_type)

    @staticmethod
    def apply_preset(
        preset_name: str, session: Optional[Session] = None
    ) -> ConfigurationEntry:
        """
        Applies a predefined UI preset (Search Engine, Gallery, News).
        """
        repo = ConfigRepository(session=session)
        return repo.apply_preset(preset_name)

    @staticmethod
    def reset_defaults(session: Optional[Session] = None) -> ConfigurationEntry:
        """
        Resets all configurable options to application defaults.
        """
        repo = ConfigRepository(session=session)
        return repo.reset_defaults()

    FEATURE_FLAG_KEYS = (
        "enable_background_jobs",
        "enable_social_data",
        "enable_crawling",
        "enable_keyword_support",
        "enable_domain_support",
        "enable_file_support",
        "enable_link_archiving",
        "enable_source_archiving",
    )

    @classmethod
    def get_feature_flags(cls, session: Optional[Session] = None) -> Dict[str, bool]:
        """
        Returns a dictionary of all supported enable_* feature flags and their boolean status.
        """
        config = cls.get_config_model(session=session)
        return {key: bool(getattr(config, key, False)) for key in cls.FEATURE_FLAG_KEYS}

    @classmethod
    def set_feature_flag(
        cls,
        feature_name: str,
        enabled: Optional[bool] = None,
        session: Optional[Session] = None,
    ) -> Tuple[str, bool]:
        """
        Sets or toggles an enable_* feature flag.

        :param feature_name: Feature flag name (e.g. 'background_jobs', 'enable_crawling')
        :param enabled: Optional boolean state. If None, toggles current value.
        :param session: Optional database session
        :return: Tuple of (canonical_feature_name, new_state)
        """
        canonical = feature_name.lower().replace("-", "_")
        if not canonical.startswith("enable_"):
            canonical = f"enable_{canonical}"

        if canonical not in cls.FEATURE_FLAG_KEYS:
            raise ValueError(f"Unknown feature flag: '{feature_name}'")

        repo = ConfigRepository(session=session)
        config = repo.get_config()

        if enabled is None:
            current_val = bool(getattr(config, canonical, False))
            target_val = not current_val
        else:
            target_val = bool(enabled)

        repo.update_config(**{canonical: target_val})
        return canonical, target_val
