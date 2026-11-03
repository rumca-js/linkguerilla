"""
Entry routes and search views controller.
"""

from datetime import datetime, timezone
import logging
import math
import re
from urllib.parse import urlparse
from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from sqlalchemy import select
from linkarchivetools.model.definitions import LinkDataModel, SocialData, SourcesTable
from yafr.db import ConfigRepository, EntryRepository, HistoryRepository, get_session
from yafr.search import FilterRegistry, SearchParser, SearchQueryBuilder
from yafr.services.entry_builder import EntryBuilder

logger = logging.getLogger(__name__)
entries_bp = Blueprint("entries", __name__)


@entries_bp.route("/")
@entries_bp.route("/entries")
def search_view():
    """
    Renders EntriesListView (Google-like search page).

    - If query parameter 'q' is empty/missing: displays large centered search input.
    - If 'q' is provided: displays search widget at top with search results container.
    """
    query = request.args.get("q", "").strip()
    session = get_session()
    config_repo = ConfigRepository(session)
    history_repo = HistoryRepository(session)
    entry_repo = EntryRepository(session)

    filters = FilterRegistry.get_available_filters(session)
    active_filter = request.args.get("filter")
    if not active_filter:
        active_filter = filters[0].id if filters else "date_published"

    page = max(1, request.args.get("page", 1, type=int))
    # When user enters a query OR performs search with no input ("q" in request.args, page, or filter)
    has_query = (
        ("q" in request.args)
        or ("page" in request.args)
        or ("filter" in request.args)
        or bool(query)
    )

    config = config_repo.get_config()
    display_type = request.args.get("display", config.display_type or "gallery")
    per_page = int(config.links_per_page or 25)
    offset = (page - 1) * per_page

    entries = []
    total_results = 0

    if has_query:
        # Save query to user search history for autocomplete only if non-empty
        if query:
            history_repo.add_search(
                query, max_limit=int(config.max_number_of_user_search or 300)
            )

        # Parse user query using AST grammar
        parsed_query = SearchParser.parse(query)

        # Execute search with filters and sorting
        entries, total_results = SearchQueryBuilder.execute_search(
            session=session,
            parsed_query=parsed_query,
            filter_id=active_filter,
            limit=per_page,
            offset=offset,
        )

    total_pages = (
        max(1, math.ceil(total_results / per_page)) if total_results > 0 else 1
    )

    # Attach sources, social metrics, tags, and status mappings for template rendering
    entry_ids = [e.id for e in entries]
    read_later_ids = set()
    visited_ids = set()
    tags_map = {}
    sources_map = {}
    social_map = {}

    if entry_ids:
        read_later_ids = history_repo.get_read_later_entry_ids()
        visited_ids = history_repo.get_visited_entry_ids()

        for e in entries:
            tags_map[e.id] = entry_repo.get_tags(e.id)

        source_ids = {e.source_id for e in entries if e.source_id}
        if source_ids:
            sources = (
                session.execute(
                    select(SourcesTable).where(SourcesTable.id.in_(source_ids))
                )
                .scalars()
                .all()
            )
            sources_map = {s.id: s for s in sources}

        social_records = (
            session.execute(
                select(SocialData).where(SocialData.entry_id.in_(entry_ids))
            )
            .scalars()
            .all()
        )
        social_map = {s.entry_id: s for s in social_records}

    return render_template(
        "entries/list.html",
        query=query,
        has_query=has_query,
        active_filter=active_filter,
        filters=filters,
        entries=entries,
        total_results=total_results,
        page=page,
        total_pages=total_pages,
        per_page=per_page,
        display_type=display_type,
        read_later_ids=read_later_ids,
        visited_ids=visited_ids,
        tags_map=tags_map,
        sources_map=sources_map,
        social_map=social_map,
        config=config,
        show_icons=(
            bool(config.show_icons)
            if config and config.show_icons is not None
            else True
        ),
    )


@entries_bp.route("/entries/<int:id>")
def entry_detail_view(id: int):
    """
    Renders EntryDetailView for a single entry.

    Displays complete metadata, video playback frame (if YouTube/video),
    vote widget, tags with edit controls, read-later toggle, status controls,
    comments, and entry navigation transition pane.
    """
    session = get_session()
    entry_repo = EntryRepository(session)
    history_repo = HistoryRepository(session)
    config_repo = ConfigRepository(session)

    entry = entry_repo.get_by_id(id)
    if not entry:
        abort(404)

    config = config_repo.get_config()

    # Track navigation transition from the last visited entry before recording new visit.
    # The from_entry_id query parameter takes precedence; otherwise we infer the
    # transition from the most recent entry in EntryVisitHistory.
    from_entry_id = request.args.get("from_entry_id") or request.args.get("from")
    if from_entry_id:
        try:
            from_id = int(from_entry_id)
            if from_id != entry.id and entry_repo.get_by_id(from_id):
                history_repo.record_transition(from_id, entry.id)
        except (ValueError, TypeError) as err:
            logger.debug("Ignored invalid from_entry_id transition parameter: %s", err)
    else:
        last_visited_id = history_repo.get_last_visited_entry_id()
        if last_visited_id and last_visited_id != entry.id:
            history_repo.record_transition(last_visited_id, entry.id)

    # Record user visit (after transition check so we compare against the previous visit)
    history_repo.record_visit(entry.id)

    # Retrieve source information if linked
    source = None
    if entry.source_id:
        source = session.execute(
            select(SourcesTable).where(SourcesTable.id == entry.source_id)
        ).scalar_one_or_none()

    # Associated tags
    tags = entry_repo.get_tags(entry.id)

    # Social data
    social = entry_repo.get_social_data(entry.id)

    # Read later and bookmarked state
    is_read_later = history_repo.is_read_later(entry.id)
    is_bookmarked = bool(entry.bookmarked)
    is_dead = entry.manual_status_code == 400 or (
        entry.status_code and entry.status_code >= 400
    )

    # Entry transition pane: entries previously navigated to from this entry
    transitions_data = []
    transitions_raw = history_repo.get_transitions_from(entry.id, limit=10)
    if transitions_raw:
        target_ids = [t.entry_to_id for t in transitions_raw]
        target_records = (
            session.execute(
                select(LinkDataModel).where(LinkDataModel.id.in_(target_ids))
            )
            .scalars()
            .all()
        )
        target_map = {e.id: e for e in target_records}

        for t in transitions_raw:
            t_entry = target_map.get(t.entry_to_id)
            if t_entry:
                transitions_data.append(
                    {
                        "entry": t_entry,
                        "counter": t.counter or 1,
                    }
                )

    # Rich media embed detection: YouTube and Odysee.
    # Build a full iframe HTML string so the template only needs to check embed_iframe.
    embed_url = None
    embed_title = entry.title or "Video Player"
    try:
        from webtoolkit import UrlLocation, YouTubeVideoHandler
        from webtoolkit.handlers.handlervideoodysee import OdyseeVideoHandler

        url_loc = UrlLocation(entry.link)
        if url_loc.is_youtube():
            yt_handler = YouTubeVideoHandler(entry.link)
            embed_url = yt_handler.get_link_embed()
        else:
            odysee_handler = OdyseeVideoHandler(entry.link)
            if odysee_handler.is_handled_by():
                embed_url = odysee_handler.get_link_embed()
    except Exception as err:
        logger.debug("Webtoolkit embed detection exception: %s", err)

    # Fallback regex for YouTube embed URL
    if not embed_url:
        yt_match = re.search(
            r"(?:v=|youtu\.be\/|embed\/)([A-Za-z0-9_-]{11})", entry.link
        )
        if yt_match:
            embed_url = f"https://www.youtube.com/embed/{yt_match.group(1)}"

    # Build the iframe element if an embed URL was resolved
    embed_iframe = None
    if embed_url:
        embed_iframe = (
            f"<iframe"
            f' src="{embed_url}"'
            f' title="{embed_title}"'
            f' allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"'
            f" allowfullscreen"
            f"></iframe>"
        )

    # Parse domain for external research tools (Wayback Machine, Schema, Whois)
    parsed_url = urlparse(entry.link)
    domain = parsed_url.netloc or ""

    return render_template(
        "entries/detail.html",
        entry=entry,
        source=source,
        tags=tags,
        social=social,
        is_read_later=is_read_later,
        is_bookmarked=is_bookmarked,
        is_dead=is_dead,
        transitions=transitions_data,
        embed_iframe=embed_iframe,
        domain=domain,
        config=config,
    )


@entries_bp.route("/entries/<int:id>/edit", methods=["GET", "POST"])
def entry_edit_screen(id: int):
    """
    Renders EntryEditScreen to modify an existing entry's metadata.
    """
    session = get_session()
    entry_repo = EntryRepository(session)
    entry = entry_repo.get_by_id(id)
    if not entry:
        abort(404)

    if request.method == "POST":
        title = request.form.get("title", "").strip() or None
        link = request.form.get("link", "").strip()
        description = request.form.get("description", "").strip() or None
        author = request.form.get("author", "").strip() or None
        language = request.form.get("language", "").strip() or None
        thumbnail = request.form.get("thumbnail", "").strip() or None
        tags_str = request.form.get("tags", "")
        tags = [t.strip().lstrip("#") for t in tags_str.split(",") if t.strip()]

        date_published_str = request.form.get("date_published", "").strip()
        date_published = None
        if date_published_str:
            try:
                date_published = datetime.fromisoformat(date_published_str)
            except ValueError:
                pass

        age_str = request.form.get("age", "").strip()
        age = 0
        if age_str:
            try:
                age = max(0, int(age_str))
            except ValueError:
                age = 0

        entry_repo.update_entry(
            id,
            title=title,
            link=link or entry.link,
            description=description,
            author=author,
            language=language,
            thumbnail=thumbnail,
            date_published=date_published or entry.date_published,
            age=age,
        )
        entry_repo.set_tags(id, tags)
        flash("Entry metadata updated successfully.", "success")
        return redirect(url_for("entries.entry_detail_view", id=id))

    tags = entry_repo.get_tags(id)
    return render_template("entries/edit.html", entry=entry, tags=tags, is_new=False)


@entries_bp.route("/entries/new", methods=["GET", "POST"])
def entry_create_screen():
    """
    Renders EntryEditScreen to create a new entry manually.
    """
    session = get_session()
    entry_repo = EntryRepository(session)

    if request.method == "POST":
        link = request.form.get("link", "").strip()
        if not link:
            flash("URL Link is required.", "danger")
            return render_template(
                "entries/edit.html", entry=None, tags=[], is_new=True
            )

        title = request.form.get("title", "").strip() or None
        description = request.form.get("description", "").strip() or None
        author = request.form.get("author", "").strip() or None
        language = request.form.get("language", "").strip() or None
        thumbnail = request.form.get("thumbnail", "").strip() or None
        tags_str = request.form.get("tags", "")
        tags = [t.strip().lstrip("#") for t in tags_str.split(",") if t.strip()]

        date_published_str = request.form.get("date_published", "").strip()
        date_published = None
        if date_published_str:
            try:
                date_published = datetime.fromisoformat(date_published_str)
            except ValueError:
                pass

        try:
            builder = EntryBuilder(session=session)
            new_entry = builder.build_and_save(
                link=link,
                title=title,
                description=description,
                author=author,
                language=language,
                thumbnail=thumbnail,
                date_published=date_published,
                tags=tags,
                ignore_policy=True,
                enqueue_update_job=True,
                commit=True,
            )
            if not new_entry:
                flash(
                    builder.last_rejection_reason or "Failed to create entry.", "danger"
                )
                return render_template(
                    "entries/edit.html", entry=None, tags=tags, is_new=True
                )
        except Exception as exc:
            session.rollback()
            flash(f"Database error: {exc}", "danger")
            return render_template(
                "entries/edit.html", entry=None, tags=tags, is_new=True
            )

        flash("Entry created successfully.", "success")
        return redirect(url_for("entries.entry_detail_view", id=new_entry.id))

    return render_template("entries/edit.html", entry=None, tags=[], is_new=True)
