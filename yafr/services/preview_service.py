"""
PreviewService - Domain service for dynamic link preview and inspection.

Obtains page and feed metadata dynamically via WebToolsWrapper (BaseUrl / RemoteUrl)
including title, description, thumbnail, author, language, publication date,
HTTP status code, media embed, feed entries, and content links, while evaluating
blocking entry rules and block entries.
"""

from datetime import datetime
import logging
import re
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlparse
from sqlalchemy.orm import Session
from yafr.db import get_session
from yafr.services.entry_builder import EntryBuilder
from yafr.services.rule_service import RuleService
from yafr.services.webtools_service import WebToolsWrapper

logger = logging.getLogger(__name__)


class PreviewService:
    """
    Service responsible for dynamic link metadata resolution and preview inspection.
    """

    @staticmethod
    def extract_youtube_video_id(url: str) -> Optional[str]:
        """
        Extracts YouTube video ID from various URL formats:
        - https://www.youtube.com/watch?v=VIDEO_ID
        - https://youtu.be/VIDEO_ID
        - https://www.youtube.com/embed/VIDEO_ID
        - https://www.youtube.com/shorts/VIDEO_ID
        - https://www.youtube.com/v/VIDEO_ID

        :param url: Candidate web URL
        :return: Extracted video ID or None
        """
        if not url:
            return None

        clean = url.strip()
        parsed = urlparse(clean)
        netloc = parsed.netloc.lower()

        # youtu.be/VIDEO_ID
        if "youtu.be" in netloc:
            path_parts = parsed.path.strip("/").split("/")
            if path_parts and path_parts[0]:
                return path_parts[0].split("?")[0].split("&")[0]

        # youtube.com or m.youtube.com
        if "youtube.com" in netloc:
            # Query param ?v=
            if parsed.query:
                qs = parse_qs(parsed.query)
                if "v" in qs and qs["v"]:
                    return qs["v"][0]

            # Path formats: /embed/ID, /v/ID, /shorts/ID
            path_parts = parsed.path.strip("/").split("/")
            if len(path_parts) >= 2 and path_parts[0] in ("embed", "v", "shorts"):
                return path_parts[1]

        return None

    @classmethod
    def inspect_url(
        cls,
        url: str,
        session: Optional[Session] = None,
        timeout_s: Optional[int] = 10,
    ) -> Dict[str, Any]:
        """
        Dynamically inspects a URL via WebToolsWrapper and RuleService.

        :param url: Web URL to inspect
        :param session: Optional active database session
        :param timeout_s: Network request timeout in seconds
        :return: Dictionary containing resolved metadata, entries, embed info, and rule verdicts
        """
        raw = (url or "").strip()
        if not raw:
            return {
                "success": False,
                "error": "URL is empty or undefined.",
                "url": "",
                "canonical_url": "",
                "is_blocked": False,
                "is_blocked_by_rule": False,
                "is_blocked_by_block_entry": False,
                "blocking_rule": None,
                "blocking_block_entry": None,
                "media_type": "unknown",
                "embed_url": None,
                "title": None,
                "description": None,
                "author": None,
                "language": None,
                "album": None,
                "thumbnail": None,
                "status_code": None,
                "date_published": None,
                "entries": [],
                "content_links": [],
                "social": {},
                "is_valid": False,
            }

        sess = session or get_session()
        builder = EntryBuilder(session=sess)
        cleaned_url = builder.sanitize_url(raw) or raw

        # 1. Rule & Block Entry Evaluation
        rule_res = RuleService.test_url(cleaned_url, session=sess)
        is_blocked = rule_res.get("is_blocked", False)
        is_blocked_by_rule = rule_res.get("is_blocked_by_rule", False)
        is_blocked_by_block_entry = rule_res.get("is_blocked_by_block_entry", False)

        blocking_rule = rule_res.get("rule_name") if is_blocked_by_rule else None
        blocking_block_entry = None
        if is_blocked_by_block_entry and rule_res.get("matching_block_entries"):
            blocking_block_entry = rule_res["matching_block_entries"][0].get("url")

        # 2. Media Type & Embed Player Detection
        media_type = "webpage"
        embed_url = None
        video_id = cls.extract_youtube_video_id(cleaned_url) or cls.extract_youtube_video_id(raw)

        if video_id:
            media_type = "video"
            embed_url = f"https://www.youtube-nocookie.com/embed/{video_id}"
        elif re.search(r"\.(mp3|ogg|wav|m4a|aac)(\?.*)?$", cleaned_url, re.IGNORECASE):
            media_type = "audio"
        elif re.search(r"\.(mp4|webm|ogv|mov)(\?.*)?$", cleaned_url, re.IGNORECASE):
            media_type = "video"

        # 3. Dynamic Metadata Extraction via WebToolsWrapper
        title = None
        description = None
        author = None
        language = None
        album = None
        thumbnail = None
        status_code = None
        is_valid = False
        date_published = None
        canonical_url = cleaned_url
        raw_entries: List[Any] = []
        content_links: List[str] = []
        social: Dict[str, Any] = {}

        try:
            wrapper = WebToolsWrapper(url=cleaned_url, session=sess, timeout_s=timeout_s)
            title = wrapper.get_title()
            description = wrapper.get_description()
            author = wrapper.get_author()
            language = wrapper.get_language()
            album = wrapper.get_album()
            thumbnail = wrapper.get_thumbnail()
            status_code = wrapper.get_status_code()
            is_valid = wrapper.is_valid()
            raw_entries = wrapper.get_entries() or []
            content_links = wrapper.get_content_links() or []
            canonical_url = wrapper.get_canonical_url() or cleaned_url
            social = wrapper.get_social_properties() or {}

            raw_date = wrapper.get_date_published()
            if isinstance(raw_date, datetime):
                date_published = raw_date.isoformat()
            elif raw_date:
                date_published = str(raw_date)

        except Exception as exc:
            logger.warning("WebTools dynamic metadata fetch failed for '%s': %s", cleaned_url, exc)

        # Fallback thumbnail for YouTube
        if not thumbnail and video_id:
            thumbnail = f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"

        # 4. Normalize Feed / Page Child Entries
        normalized_entries: List[Dict[str, Any]] = []
        for item in raw_entries:
            if isinstance(item, dict):
                e_title = item.get("title") or item.get("name")
                e_link = item.get("link") or item.get("url")
                e_date = item.get("date") or item.get("date_published") or item.get("pubDate")
                e_desc = item.get("description") or item.get("summary")
                e_author = item.get("author")
                normalized_entries.append(
                    {
                        "title": str(e_title).strip() if e_title else "Untitled Entry",
                        "link": str(e_link).strip() if e_link else "",
                        "date": str(e_date).strip() if e_date else None,
                        "description": str(e_desc).strip() if e_desc else None,
                        "author": str(e_author).strip() if e_author else None,
                    }
                )
            elif hasattr(item, "title") or hasattr(item, "link"):
                e_title = getattr(item, "title", None)
                e_link = getattr(item, "link", None)
                e_date = getattr(item, "date", None) or getattr(item, "date_published", None)
                e_desc = getattr(item, "description", None)
                normalized_entries.append(
                    {
                        "title": str(e_title).strip() if e_title else "Untitled Entry",
                        "link": str(e_link).strip() if e_link else "",
                        "date": str(e_date).strip() if e_date else None,
                        "description": str(e_desc).strip() if e_desc else None,
                        "author": None,
                    }
                )

        if normalized_entries and media_type == "webpage":
            media_type = "feed"

        return {
            "success": True,
            "url": raw,
            "cleaned_url": cleaned_url,
            "canonical_url": canonical_url,
            "is_blocked": is_blocked,
            "is_blocked_by_rule": is_blocked_by_rule,
            "is_blocked_by_block_entry": is_blocked_by_block_entry,
            "blocking_rule": blocking_rule,
            "blocking_block_entry": blocking_block_entry,
            "media_type": media_type,
            "embed_url": embed_url,
            "title": title,
            "description": description,
            "author": author,
            "language": language,
            "album": album,
            "thumbnail": thumbnail,
            "status_code": status_code,
            "is_valid": is_valid,
            "date_published": date_published,
            "entries": normalized_entries,
            "content_links": content_links,
            "social": social,
            "matching_rules": rule_res.get("matching_rules", []),
            "matching_block_entries": rule_res.get("matching_block_entries", []),
        }
