"""
Link Background Jobs Handlers for YAFR.

Contains handlers for link-related tasks, including JOB_LINK_UPDATE_DATA ('link-update-data').
"""

from datetime import datetime, timezone
import logging
from typing import Any, Dict, Optional
from sqlalchemy.orm import Session

from linkarchivetools.model.definitions import BackgroundJob, LinkDataModel
from webtoolkit import UrlLocation

from yafr.db.entry_repository import EntryRepository
from yafr.services.job_service import (
    JOB_LINK_DOWNLOAD_SOCIAL,
    JOB_LINK_UPDATE_DATA,
)
from yafr.services.webtools_service import WebToolsWrapper
from yafr.workers.jobs.base import BaseJobHandler

logger = logging.getLogger(__name__)


class LinkUpdateDataJobHandler(BaseJobHandler):
    """
    Handler for JOB_LINK_UPDATE_DATA ('link-update-data').

    Refreshes link metadata by obtaining a webtoolkit URL handler (BaseUrl or RemoteUrl)
    via WebToolsWrapper, extracting get_title(), get_description(), get_date_published(),
    get_author(), get_language(), get_thumbnail(), etc. directly via webtoolkit without
    raw response or BeautifulSoup HTML parsing fallbacks.
    """

    job_types = (JOB_LINK_UPDATE_DATA, "JOB_LINK_UPDATE_DATA")

    def execute(self, job: BackgroundJob, session: Session) -> Dict[str, Any]:
        """
        Executes link metadata update for the target entry.

        :param job: BackgroundJob record
        :param session: Active database session
        :return: Execution result dictionary
        """
        subject = (job.subject or "").strip()
        entry_repo = EntryRepository(session)
        entry: Optional[LinkDataModel] = None

        if subject.isdigit():
            entry = entry_repo.get_by_id(int(subject))
        elif subject:
            entry = entry_repo.get_by_link(subject)

        if not entry:
            return {
                "success": False,
                "consume": True,
                "status": "error",
                "error": f"Entry not found for subject: '{subject}'",
            }

        if not entry.link:
            return {
                "success": False,
                "consume": True,
                "status": "error",
                "error": f"Entry #{entry.id} has no link URL",
            }

        location = UrlLocation(url=entry.link)
        if not location.is_web_link():
            return {
                "success": False,
                "consume": True,
                "status": "error",
                "error": f"Cannot update non web links: '{subject}'",
            }

        try:
            # Obtain Url handler via WebToolsWrapper (either BaseUrl or RemoteUrl)
            web_client = WebToolsWrapper(url=entry.link, session=session, timeout_s=15)

            response = web_client.get_response()
            is_active = web_client.is_active()

            if response is None or not response.is_valid():
                # Response is not valid (failed fetch or HTTP error) — mark dead, log error
                status_code = None
                if response is not None and hasattr(response, "get_status_code"):
                    try:
                        sc = response.get_status_code()
                        if isinstance(sc, int):
                            status_code = sc
                        elif isinstance(sc, str) and sc.isdigit():
                            status_code = int(sc)
                    except Exception:
                        status_code = None
                if status_code is None and hasattr(web_client, "get_status_code"):
                    try:
                        sc = web_client.get_status_code()
                        if isinstance(sc, int):
                            status_code = sc
                        elif isinstance(sc, str) and sc.isdigit():
                            status_code = int(sc)
                    except Exception:
                        status_code = None

                if status_code is not None:
                    entry.status_code = status_code
                if not entry.date_dead_since:
                    entry.date_dead_since = datetime.now(timezone.utc)
                entry.date_update_last = datetime.now(timezone.utc)
                session.commit()

                err_msg = (
                    f"HTTP error {status_code} fetching {entry.link}"
                    if status_code
                    else f"Failed to fetch content from {entry.link}"
                )
                logger.error(
                    "Invalid response for entry #%s (%s): %s",
                    entry.id,
                    entry.link,
                    err_msg,
                )

                try:
                    from yafr.db.logging_repository import LoggingRepository

                    log_repo = LoggingRepository(session)
                    log_repo.log(
                        info_text=err_msg,
                        detail_text=f"Entry #{entry.id} marked as dead. Job #{getattr(job, 'id', '?')}.",
                        level=LoggingRepository.ERROR,
                    )
                except Exception as log_err:
                    logger.debug(
                        "Failed to record error log in applogging: %s", log_err
                    )

                return {
                    "success": False,
                    "consume": is_active,
                    "status": "error",
                    "error": err_msg,
                    "message": err_msg,
                }

            # Response is valid — clear dead marker and update metadata
            entry.date_dead_since = None

            # Fetch BaseUrl / RemoteUrl metadata directly via webtoolkit
            title = web_client.get_title()
            description = web_client.get_description()
            date_published = web_client.get_date_published()
            author = web_client.get_author()
            album = web_client.get_album()
            language = web_client.get_language()
            thumbnail = web_client.get_thumbnail()

            # Update entry properties only when webtoolkit returns a value
            if title and str(title).strip():
                entry.title = str(title).strip()
            if description and str(description).strip():
                entry.description = str(description).strip()
            if date_published:
                if isinstance(date_published, str) and date_published.strip():
                    try:
                        entry.date_published = datetime.fromisoformat(
                            date_published.strip()
                        )
                    except Exception:
                        pass
                elif isinstance(date_published, datetime):
                    entry.date_published = date_published
            if author and str(author).strip():
                entry.author = str(author).strip()
            if album and isinstance(album, str) and album.strip():
                entry.album = album.strip()
            if language and isinstance(language, str) and language.strip():
                entry.language = language.strip()
            if thumbnail and isinstance(thumbnail, str) and thumbnail.strip():
                entry.thumbnail = thumbnail.strip()

            status_code = None
            if hasattr(web_client, "get_status_code"):
                try:
                    sc = web_client.get_status_code()
                    if isinstance(sc, int):
                        status_code = sc
                except Exception:
                    pass
            if status_code is None and hasattr(response, "get_status_code"):
                try:
                    sc = response.get_status_code()
                    if isinstance(sc, int):
                        status_code = sc
                except Exception:
                    pass

            if status_code is not None:
                entry.status_code = status_code

            # Check if link is acceptable using EntryRules and BlockRules; if blocked, remove it
            try:
                from yafr.services.entry_builder import EntryBuilder
                from yafr.db.block_repository import BlockEntryRepository

                builder = EntryBuilder(session=session)
                acceptable, reason = builder.can_build(
                    entry.link,
                    status_code=entry.status_code or 200,
                    check_duplicates=False,
                    title=entry.title,
                    description=entry.description,
                )
                if not acceptable:
                    logger.info(
                        "Removing entry #%s (%s) because it is blocked or no longer acceptable: %s",
                        entry.id,
                        entry.link,
                        reason,
                    )
                    entry_repo.delete_entry(entry.id)
                    return {
                        "success": True,
                        "consume": True,
                        "status": "removed",
                        "message": f"Entry #{entry.id} removed: {reason}",
                    }

                # Also verify directly against BlockEntry repository (BlockRules)
                block_repo = BlockEntryRepository(session=session)
                matching_block = block_repo.get_matching_entry(entry.link)
                if matching_block:
                    reason = f"URL blocked by block entry '{matching_block.url}'."
                    logger.info(
                        "Removing entry #%s (%s) matching block entry: %s",
                        entry.id,
                        entry.link,
                        reason,
                    )
                    entry_repo.delete_entry(entry.id)
                    return {
                        "success": True,
                        "consume": True,
                        "status": "removed",
                        "message": f"Entry #{entry.id} removed: {reason}",
                    }
            except Exception as rule_err:
                logger.warning(
                    "Entry rule or block rule evaluation failed: %s", rule_err
                )

            # Enqueue JOB_LINK_DOWNLOAD_SOCIAL
            try:
                from yafr.db.job_repository import JobRepository

                job_repo = JobRepository(session=session)
                job_repo.enqueue_job(
                    job=JOB_LINK_DOWNLOAD_SOCIAL,
                    subject=str(entry.id),
                    priority=1,
                    enabled=True,
                )
            except Exception as job_err:
                logger.debug(
                    "Failed to enqueue %s job: %s", JOB_LINK_DOWNLOAD_SOCIAL, job_err
                )

            entry.date_update_last = datetime.now(timezone.utc)
            session.commit()

            return {
                "success": True,
                "consume": True,
                "status": "completed",
                "message": f"Updated entry #{entry.id} metadata (title='{entry.title}').",
                "entry_id": entry.id,
                "title": entry.title,
                "description": entry.description,
            }

        except Exception as err:
            logger.warning(
                "Error updating data for entry #%s (%s): %s",
                getattr(entry, "id", "?"),
                getattr(entry, "link", "?"),
                err,
            )
            try:
                if entry:
                    entry.date_update_last = datetime.now(timezone.utc)
                    session.commit()
            except Exception:
                pass
            is_active = WebToolsWrapper.is_status_active(session)
            return {
                "success": False,
                "consume": is_active,
                "status": "error",
                "error": f"Error updating link data: {err}",
            }


class LinkDownloadSocialJobHandler(BaseJobHandler):
    """
    Handler for JOB_LINK_DOWNLOAD_SOCIAL ('link-social-data').

    Downloads social metadata via WebToolsWrapper.get_social_properties() and upserts
    the result into the socialdata table (linked by entry_id). Fields mapped:
    followers_count, thumbs_up, thumbs_down, view_count, rating, upvote_ratio,
    upvote_diff, upvote_view_ratio, stars, date_updated.
    """

    job_types = (JOB_LINK_DOWNLOAD_SOCIAL, "JOB_LINK_DOWNLOAD_SOCIAL")

    def execute(self, job: BackgroundJob, session: Session) -> Dict[str, Any]:
        """
        Executes social metadata download for the target entry.

        :param job: BackgroundJob record
        :param session: Active database session
        :return: Execution result dictionary
        """
        subject = (job.subject or "").strip()
        entry_repo = EntryRepository(session)
        entry: Optional[LinkDataModel] = None

        if subject.isdigit():
            entry = entry_repo.get_by_id(int(subject))
        elif subject:
            entry = entry_repo.get_by_link(subject)

        if not entry or not entry.link:
            return {
                "success": False,
                "consume": True,
                "status": "error",
                "error": f"Entry not found or has no URL for subject: '{subject}'",
            }

        try:
            web_client = WebToolsWrapper(url=entry.link, session=session, timeout_s=15)
            social_data = (
                web_client.get_social_properties()
                if hasattr(web_client, "get_social_properties")
                else {}
            ) or {}

            if social_data:
                # Upsert social data into the socialdata table
                social_record = entry_repo.get_social_data(entry.id)
                if social_record is None:
                    from linkarchivetools.model.definitions import SocialData

                    social_record = SocialData(entry_id=entry.id)
                    session.add(social_record)

                def _to_int(val: Any) -> Optional[int]:
                    try:
                        return int(val) if val is not None else None
                    except (ValueError, TypeError):
                        return None

                def _to_float(val: Any) -> Optional[float]:
                    try:
                        return float(val) if val is not None else None
                    except (ValueError, TypeError):
                        return None

                thumbs_up = _to_int(social_data.get("thumbs_up"))
                thumbs_down = _to_int(social_data.get("thumbs_down"))
                view_count = _to_int(social_data.get("view_count"))
                rating = _to_float(social_data.get("rating"))
                upvote_ratio = _to_float(social_data.get("upvote_ratio"))
                upvote_diff = _to_int(social_data.get("upvote_diff"))
                upvote_view_ratio = _to_float(social_data.get("upvote_view_ratio"))
                stars = _to_float(social_data.get("stars"))
                followers_count = _to_int(social_data.get("followers_count"))

                if thumbs_up is not None:
                    social_record.thumbs_up = thumbs_up
                if thumbs_down is not None:
                    social_record.thumbs_down = thumbs_down
                if view_count is not None:
                    social_record.view_count = view_count
                if rating is not None:
                    social_record.rating = rating
                if upvote_ratio is not None:
                    social_record.upvote_ratio = upvote_ratio
                if upvote_diff is not None:
                    social_record.upvote_diff = upvote_diff
                if upvote_view_ratio is not None:
                    social_record.upvote_view_ratio = upvote_view_ratio
                if stars is not None:
                    social_record.stars = stars
                if followers_count is not None:
                    social_record.followers_count = followers_count

                social_record.date_updated = datetime.now(timezone.utc)
                session.commit()

            return {
                "success": True,
                "consume": True,
                "status": "completed",
                "message": f"Updated social metadata for entry #{entry.id}.",
                "entry_id": entry.id,
            }
        except Exception as err:
            logger.warning(
                "Error downloading social data for entry #%s (%s): %s",
                entry.id,
                entry.link,
                err,
            )
            is_active = WebToolsWrapper.is_status_active(session)
            return {
                "success": False,
                "consume": is_active,
                "status": "error",
                "error": str(err),
            }
