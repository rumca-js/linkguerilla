"""Repository operations for the linkarchivetools ``gateway`` table."""

from collections import OrderedDict
from typing import Iterable, Optional

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from linkarchivetools.model.definitions import Gateway

from yafr.db.base_repository import BaseRepository


class GatewayRepository(BaseRepository[Gateway]):
    """Persists and queries curated gateway links."""

    TYPE_GATEWAY = "gateway"
    TYPE_SEARCH_ENGINE = "search-engine"
    TYPE_AI_BOT = "ai-bot"
    TYPE_POPULAR = "popular"
    TYPE_SOCIAL_MEDIA = "social-media"
    TYPE_FAVOURITE = "favourite"
    TYPE_AUDIO_STREAMING = "audio-streaming"
    TYPE_VIDEO_STREAMING = "video-streaming"
    TYPE_FILE_SHARING = "file-sharing"
    TYPE_BANKING = "banking"
    TYPE_DIGITAL_LIBRARY = "digital-library"
    TYPE_MARKETPLACE = "marketplace"
    TYPE_APP_STORE = "app-store"
    TYPE_OTHER = "other"

    GATEWAYS_TYPES = [
        TYPE_GATEWAY,
        TYPE_SEARCH_ENGINE,
        TYPE_AI_BOT,
        TYPE_POPULAR,
        TYPE_SOCIAL_MEDIA,
        TYPE_FAVOURITE,
        TYPE_AUDIO_STREAMING,
        TYPE_VIDEO_STREAMING,
        TYPE_FILE_SHARING,
        TYPE_BANKING,
        TYPE_DIGITAL_LIBRARY,
        TYPE_MARKETPLACE,
        TYPE_APP_STORE,
        TYPE_OTHER,
    ]
    GATEWAYS_CHOICES = [[gateway_type, gateway_type] for gateway_type in GATEWAYS_TYPES]

    _SEED_DATA = {
        TYPE_SEARCH_ENGINE: "google.com bing.com kagi.com yahoo.com yandex.com duckduckgo.com searxng.site 4get.ca search.brave.com startpage.com wolframalpha.com mwmbl.org whoogle.io search.marginalia.nu baidu.com mojeek.com morphic.sh shodan.io sogou.com stract.com wiby.me cse.google.com anoox.com greppr.org letsearch.ru presearch.io".split(),
        TYPE_DIGITAL_LIBRARY: "wikipedia.org github.com archive.org archive.ph annas-archive.org".split(),
        TYPE_VIDEO_STREAMING: "youtube.com tiktok.com netflix.com disneyplus.com rumble.com odysee.com yewtu.be twitch.tv dailymotion.com vimeo.com".split(),
        TYPE_FILE_SHARING: ["drive.google.com", "icloud.com"],
        TYPE_BANKING: ["paypal.com", "wallet.google", "apple.com/pl/apple-pay"],
        TYPE_AUDIO_STREAMING: ["open.spotify.com", "music.youtube.com"],
        TYPE_SOCIAL_MEDIA: "meta.com reddit.com facebook.com stackoverflow.com linkedin.com discord.com messanger.com whatsapp.com instagram.com quora.com wechat.com hn.algolia.com news.ycombinator.com".split(),
        TYPE_AI_BOT: "chatgpt.com copilot.microsoft.com gemini.google.com chat.deepseek.com perplexity.ai claude.ai x.ai".split(),
        TYPE_MARKETPLACE: [
            "amazon.com",
            "aliexpress.com",
            "ebay.com",
            "facebook.com/marketplace",
            "vinted.com",
        ],
        TYPE_APP_STORE: [
            "play.google.com",
            "store.steampowered.com",
            "apps.apple.com",
            "store.playstation.com",
            "shop.battle.net",
        ],
        TYPE_OTHER: [
            "gmail.com",
            "maps.google.com",
            "chrome.google.com",
            "office.com/",
            "apple.com",
            "microsoft.com",
            "microsoft.com/microsoft-teams",
            "suno.com",
        ],
    }

    _GROUP_NAMES = OrderedDict(
        [
            (TYPE_SEARCH_ENGINE, "search_engines"),
            (TYPE_AI_BOT, "ai_search_engines"),
            (TYPE_DIGITAL_LIBRARY, "digital_library"),
            (TYPE_GATEWAY, "gateways"),
            (TYPE_APP_STORE, "app_store"),
            (TYPE_POPULAR, "popular"),
            (TYPE_FAVOURITE, "favourite"),
            (TYPE_SOCIAL_MEDIA, "social_media"),
            (TYPE_AUDIO_STREAMING, "audio_streaming"),
            (TYPE_VIDEO_STREAMING, "video_streaming"),
            (TYPE_MARKETPLACE, "marketplace"),
            (TYPE_FILE_SHARING, "file_sharing"),
            (TYPE_BANKING, "banking"),
            (TYPE_OTHER, "other"),
        ]
    )

    def __init__(self, session: Optional[Session] = None) -> None:
        super().__init__(session=session)

    def add_gateway(
        self,
        link: str,
        gateway_type: Optional[str] = None,
        title: Optional[str] = None,
        description: Optional[str] = None,
    ) -> Gateway:
        """Add or update a gateway, keyed by its unique link."""
        link = link.strip()
        gateway = self.get_by_link(link)
        if gateway is None:
            gateway = Gateway(link=link)
            self.session.add(gateway)
        gateway.gateway_type = gateway_type
        gateway.title = title
        gateway.description = description
        self.commit()
        return gateway

    def get_by_link(self, link: str) -> Optional[Gateway]:
        """Return a gateway matching ``link`` exactly after trimming whitespace."""
        stmt = select(Gateway).where(Gateway.link == link.strip()).limit(1)
        return self.session.execute(stmt).scalar_one_or_none()

    def list_by_type(self, gateway_type: str) -> list[Gateway]:
        """Return gateways of the requested type ordered by link."""
        stmt = (
            select(Gateway)
            .where(Gateway.gateway_type == gateway_type)
            .order_by(Gateway.link)
        )
        return list(self.session.execute(stmt).scalars().all())

    def cleanup(self, cfg=None) -> None:
        """Rebuild default data only when ``cfg`` requests a full cleanup."""
        if cfg and "full" in cfg:
            self.session.execute(delete(Gateway))
            self.populate()

    def check_init(self) -> None:
        """Populate default gateways when the table is empty."""
        if self.count(Gateway) == 0:
            self.populate()

    def populate(self) -> None:
        """Insert the curated default gateway links without duplicating existing rows."""
        for gateway_type, links in self._SEED_DATA.items():
            for link in links:
                normalized_link = "https://" + link
                existing = self.get_by_link(normalized_link)
                if existing is None:
                    self.session.add(
                        Gateway(link=normalized_link, gateway_type=gateway_type)
                    )
                elif existing.gateway_type is None:
                    existing.gateway_type = gateway_type
        self.commit()

    def get_types_mapping(self, gateway_types: Iterable[str]) -> OrderedDict:
        """Return selected gateway types using the legacy template group names."""
        selected = set(gateway_types)
        data = OrderedDict()
        for gateway_type, group_name in self._GROUP_NAMES.items():
            if gateway_type in selected:
                data[group_name] = self.list_by_type(gateway_type)
        return data
