"""
Configuration Repository for YAFR.

Manages application-wide settings persisted in the configurationentry table,
such as themes, display styles, alpha transparencies, and storage caps.
"""

import logging
from typing import Optional, Tuple
from sqlalchemy import select
from sqlalchemy.orm import Session
from linkarchivetools.model.definitions import ConfigurationEntry
from yafr.db.base_repository import BaseRepository

logger = logging.getLogger(__name__)

DEFAULT_TITLE = "LinkGuerilla"
DEFAULT_DESCRIPTION = "Link manager and aggregator"


class ConfigRepository(BaseRepository[ConfigurationEntry]):
    """
    Data access repository for application configuration entries.
    """

    DEFAULT_TITLE = DEFAULT_TITLE
    DEFAULT_DESCRIPTION = DEFAULT_DESCRIPTION

    def __init__(self, session: Optional[Session] = None) -> None:
        super().__init__(session=session)

    def get_config(self) -> ConfigurationEntry:
        """
        Retrieves the primary active ConfigurationEntry record.

        If no configuration row exists, initializes a default entry.

        :return: Active ConfigurationEntry instance
        """
        stmt = select(ConfigurationEntry).order_by(ConfigurationEntry.id.asc()).limit(1)
        config = self.session.execute(stmt).scalar_one_or_none()

        if config is None:
            config = ConfigurationEntry(
                instance_title=DEFAULT_TITLE,
                instance_description=DEFAULT_DESCRIPTION,
                display_style="style-dark",
                display_type="gallery",
                show_icons=True,
                thumbnails_as_icons=True,
                entries_visit_alpha=0.6,
                entries_dead_alpha=0.4,
                number_of_update_entries=10,
                max_number_of_user_search=300,
                max_user_entry_visit_history=5000,
                links_per_page=25,
                sources_per_page=25,
                vote_min=-100,
                vote_max=100,
                initialized=True,
            )
            self.session.add(config)
            self.session.commit()
            logger.info("Initialized default ConfigurationEntry (id=%s)", config.id)

        return config

    def to_dict(self) -> dict:
        """
        Serializes active ConfigurationEntry attributes into a dictionary.

        :return: Dict representation of configuration attributes
        """
        config = self.get_config()
        return {
            col.name: getattr(config, col.name)
            for col in ConfigurationEntry.__table__.columns
        }

    def update_config(self, **kwargs) -> ConfigurationEntry:
        """
        Updates fields on the active ConfigurationEntry with automatic type coercion.

        :param kwargs: Key-value attributes to update
        :return: Updated ConfigurationEntry instance
        """
        config = self.get_config()
        columns = ConfigurationEntry.__table__.columns
        for key, value in kwargs.items():
            if key in columns:
                col_type = str(columns[key].type)
                if "BOOLEAN" in col_type:
                    if isinstance(value, str):
                        converted_val = value.lower() in ("true", "1", "yes", "on", "t")
                    else:
                        converted_val = bool(value)
                elif "INTEGER" in col_type:
                    try:
                        converted_val = int(value)
                    except (ValueError, TypeError):
                        continue
                elif "FLOAT" in col_type:
                    try:
                        converted_val = float(value)
                    except (ValueError, TypeError):
                        continue
                else:
                    converted_val = str(value) if value is not None else ""
                setattr(config, key, converted_val)
            elif hasattr(config, key):
                setattr(config, key, value)
            else:
                logger.warning("ConfigurationEntry has no attribute '%s'", key)

        self.session.commit()
        return config

    def apply_preset(self, preset_name: str) -> ConfigurationEntry:
        """
        Applies a predefined UI display preset (Search Engine, Gallery, News).

        :param preset_name: 'search-engine', 'gallery', or 'news'
        :return: Updated ConfigurationEntry instance
        """
        preset_key = preset_name.lower().replace(" ", "-").replace("_", "-")
        if preset_key in ("search-engine", "search"):
            return self.update_config(
                display_type="search-engine",
                show_icons=False,
                thumbnails_as_icons=False,
                small_icons=True,
                click_behavior_modal_window=False,
            )
        elif preset_key in ("gallery",):
            return self.update_config(
                display_type="gallery",
                show_icons=True,
                thumbnails_as_icons=True,
                small_icons=False,
                click_behavior_modal_window=True,
            )
        elif preset_key in ("news", "content-centric"):
            return self.update_config(
                display_type="content-centric",
                show_icons=True,
                thumbnails_as_icons=True,
                small_icons=True,
                click_behavior_modal_window=False,
            )
        else:
            raise ValueError(f"Unknown preset name: '{preset_name}'")

    def reset_defaults(self) -> ConfigurationEntry:
        """
        Resets all configurable options to application defaults.

        :return: Reset ConfigurationEntry instance
        """
        defaults = {
            "instance_title": "YAFR",
            "instance_description": "Yet Another Feed Reader",
            "display_style": "style-dark",
            "display_type": "gallery",
            "show_icons": True,
            "thumbnails_as_icons": True,
            "small_icons": False,
            "local_icons": False,
            "highlight_bookmarks": True,
            "click_behavior_modal_window": True,
            "entries_visit_alpha": 0.6,
            "entries_dead_alpha": 0.4,
            "max_number_of_user_search": 300,
            "max_user_entry_visit_history": 5000,
            "links_per_page": 25,
            "sources_per_page": 25,
            "vote_min": -100,
            "vote_max": 100,
            "track_user_searches": True,
            "track_user_navigation": True,
            "prefer_https_links": True,
            "prefer_non_www_links": False,
            "accept_dead_links": False,
            "accept_domain_links": True,
            "accept_ip_links": True,
            "accept_onion_links": False,
            "accept_same_hashes": False,
            "sources_refresh_period": 3600,
            "enable_social_data": True,
            "debug_mode": False,
        }
        return self.update_config(**defaults)

    def get_display_style(self) -> str:
        """
        Returns the active display theme style (e.g., 'style-dark', 'style-light').
        """
        config = self.get_config()
        return config.display_style or "style-dark"

    def get_display_type(self) -> str:
        """
        Returns the active layout card type (e.g., 'gallery', 'standard', 'search-engine').
        """
        config = self.get_config()
        return config.display_type or "gallery"

    def get_alphas(self) -> Tuple[float, float]:
        """
        Returns the configured transparency alphas for visited and dead entries.

        :return: Tuple of (entries_visit_alpha, entries_dead_alpha)
        """
        config = self.get_config()
        visit_alpha = float(
            config.entries_visit_alpha
            if config.entries_visit_alpha is not None
            else 0.6
        )
        dead_alpha = float(
            config.entries_dead_alpha if config.entries_dead_alpha is not None else 0.4
        )
        return visit_alpha, dead_alpha
