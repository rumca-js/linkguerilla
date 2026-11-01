"""
Sources routes and view controller for YAFR.

Implements SourcesListView, SourceDetailScreen, SourceRssEditScreen,
SourceEmailEditScreen, and SourceParseEditScreen.
"""

from datetime import datetime, timedelta, timezone
import math
from typing import Any, Optional
from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from sqlalchemy import func, select
from linkarchivetools.model.definitions import (
    Credentials,
    LinkDataModel,
    SourceOperationalData,
    SourcesTable,
    User,
)
from linkarchivetools.model.sources import Sources
from yafr.db import ConfigRepository, SourceRepository, get_session
from yafr.search import SOURCE_FILTERS, SearchParser, SourceSearchQueryBuilder

sources_bp = Blueprint("sources", __name__)
default_source_refresh = 3600


@sources_bp.route("/sources")
def sources_list():
    """
    Renders SourcesListView.

    Displays compact search bar at top with sources list, badges, and controls.
    """
    query = request.args.get("q", "").strip()
    active_filter = request.args.get("order", "url")
    show_all = request.args.get("all") == "1"
    page = max(1, request.args.get("page", 1, type=int))
    has_query = bool(query)

    session = get_session()
    config_repo = ConfigRepository(session)
    source_repo = SourceRepository(session)

    config = config_repo.get_config()
    _, dead_alpha = config_repo.get_alphas()
    per_page = int(config.sources_per_page or 25)
    offset = (page - 1) * per_page

    parsed_query = SearchParser.parse(query)
    sources_with_op, total_results = SourceSearchQueryBuilder.execute_search(
        session=session,
        parsed_query=parsed_query,
        filter_id=active_filter,
        limit=per_page,
        offset=offset,
    )

    total_pages = (
        max(1, math.ceil(total_results / per_page)) if total_results > 0 else 1
    )

    # Calculate outdated and error source IDs for red dot and error badges
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=3600)
    outdated_count = source_repo.count_outdated_sources(max_age_seconds=3600)
    error_count = source_repo.count_error_sources()

    # Check whether any sources exist at all (to skip the search UI when empty)
    total_sources_in_db = session.execute(
        select(func.count(SourcesTable.id))
    ).scalar_one()

    # Get set of all currently outdated source IDs
    outdated_stmt = (
        select(SourcesTable.id)
        .outerjoin(
            SourceOperationalData,
            SourcesTable.id == SourceOperationalData.source_id,
        )
        .where(SourcesTable.enabled == True)
        .where(
            (SourceOperationalData.date_fetched == None)
            | (SourceOperationalData.date_fetched < cutoff)
        )
    )
    outdated_ids = set(session.execute(outdated_stmt).scalars().all())

    # Map sources and their operational tracking data
    sources_list_data = []
    for row in sources_with_op:
        src, op = row
        sources_list_data.append((src, op))

    return render_template(
        "sources/list.html",
        query=query,
        has_query=has_query,
        show_all=show_all,
        active_filter=active_filter,
        filters=SOURCE_FILTERS,
        sources=sources_list_data,
        outdated_ids=outdated_ids,
        outdated_count=outdated_count,
        error_count=error_count,
        total_results=total_results,
        page=page,
        total_pages=total_pages,
        per_page=per_page,
        dead_alpha=dead_alpha,
        total_sources_in_db=total_sources_in_db,
    )


def _parse_fetch_period(raw_value: Any) -> Optional[int]:
    """
    Parses fetch_period input from request form data.

    Returns positive integer seconds, or None if omitted, empty, or non-positive.
    """
    if raw_value is None:
        return None
    val_str = str(raw_value).strip()
    if not val_str:
        return None
    try:
        val = int(val_str)
        return val if val > 0 else None
    except (ValueError, TypeError):
        return None


def _parse_age(raw_value: Any) -> int:
    """
    Parses minimum age from request form data.
    Defaults to 0 (visible to anybody).
    """
    if raw_value is None:
        return 0
    val_str = str(raw_value).strip()
    if not val_str:
        return 0
    try:
        val = int(val_str)
        return max(0, val)
    except (ValueError, TypeError):
        return 0


@sources_bp.route("/sources/<int:id>")
def source_detail(id: int):
    """
    Renders SourceDetailScreen.

    Displays source metadata, operational metrics (date_fetched, page_hash, body_hash),
    and a preview list of entries extracted from this source.
    """
    session = get_session()
    source_repo = SourceRepository(session)
    source = source_repo.get_by_id(id)
    if not source:
        abort(404)

    op_data = source_repo.get_operational_data(id)

    # Fetch entries associated with this source
    entries = (
        session.execute(
            select(LinkDataModel)
            .where(LinkDataModel.source_id == id)
            .order_by(LinkDataModel.date_published.desc().nullslast())
            .limit(50)
        )
        .scalars()
        .all()
    )

    total_entries_count = (
        session.execute(
            select(func.count(LinkDataModel.id)).where(LinkDataModel.source_id == id)
        ).scalar()
        or 0
    )

    credentials = None
    if source.credentials_id:
        credentials = session.get(Credentials, source.credentials_id)

    # Format binary hashes as hex strings for display
    page_hash_hex = op_data.page_hash.hex() if op_data and op_data.page_hash else None
    body_hash_hex = op_data.body_hash.hex() if op_data and op_data.body_hash else None

    # Check if outdated
    is_outdated = False
    if source.enabled:
        if op_data is None or op_data.date_fetched is None:
            is_outdated = True
        else:
            df = op_data.date_fetched
            if isinstance(df, str):
                try:
                    df = datetime.fromisoformat(df)
                except Exception:
                    df = None
            if df:
                if df.tzinfo is not None:
                    df = df.astimezone(timezone.utc).replace(tzinfo=None)
                fetch_seconds = (
                    source.fetch_period
                    if (source.fetch_period and source.fetch_period > 0)
                    else default_source_refresh
                )
                cutoff_naive = datetime.now(timezone.utc).replace(
                    tzinfo=None
                ) - timedelta(seconds=fetch_seconds)
                is_outdated = df < cutoff_naive
            else:
                is_outdated = True

    return render_template(
        "sources/detail.html",
        source=source,
        op_data=op_data,
        entries=entries,
        total_entries_count=total_entries_count,
        credentials=credentials,
        page_hash_hex=page_hash_hex,
        body_hash_hex=body_hash_hex,
        is_outdated=is_outdated,
        fetch_period=source.fetch_period,
    )


@sources_bp.route("/sources/new/rss", methods=["GET", "POST"])
def source_add_rss():
    """
    Renders SourceRssEditScreen for adding a new RSS source.
    """
    session = get_session()
    source_repo = SourceRepository(session)

    if request.method == "POST":
        url = request.form.get("url", "").strip()
        title = request.form.get("title", "").strip() or url
        xpath = request.form.get("xpath", "").strip() or None
        enabled = "enabled" in request.form
        auto_tag = request.form.get("auto_tag", "").strip()
        favicon = request.form.get("favicon", "").strip() or None
        category_name = request.form.get("category_name", "").strip() or None
        language = request.form.get("language", "").strip() or None
        age = _parse_age(request.form.get("age"))
        fetch_period = _parse_fetch_period(request.form.get("fetch_period"))

        if not url:
            flash("Feed URL is required.", "danger")
            return render_template("sources/edit_rss.html", source=None, is_new=True)

        existing = source_repo.get_by_url(url)
        if existing:
            flash("A source with this URL already exists.", "warning")
            return redirect(url_for("sources.source_detail", id=existing.id))

        new_source = source_repo.add_source(
            url=url,
            title=title,
            source_type="RSS",
            xpath=xpath,
            enabled=enabled,
            auto_tag=auto_tag,
            favicon=favicon,
            category_name=category_name,
            language=language,
            age=age,
            fetch_period=fetch_period,
        )
        flash(f"RSS source '{new_source.title}' created successfully.", "success")
        return redirect(url_for("sources.source_detail", id=new_source.id))

    return render_template("sources/edit_rss.html", source=None, is_new=True)


@sources_bp.route("/sources/<int:id>/edit-rss", methods=["GET", "POST"])
def source_edit_rss(id: int):
    """
    Renders SourceRssEditScreen for editing an existing RSS source.
    """
    session = get_session()
    source_repo = SourceRepository(session)
    source = source_repo.get_by_id(id)
    if not source:
        abort(404)

    if request.method == "POST":
        title = request.form.get("title", "").strip() or source.url
        url = request.form.get("url", "").strip() or source.url
        xpath = request.form.get("xpath", "").strip() or None
        enabled = "enabled" in request.form
        auto_tag = request.form.get("auto_tag", "").strip()
        favicon = request.form.get("favicon", "").strip() or None
        category_name = request.form.get("category_name", "").strip() or None
        language = request.form.get("language", "").strip() or None
        age = _parse_age(request.form.get("age"))
        fetch_period = _parse_fetch_period(request.form.get("fetch_period"))

        source_repo.update_source(
            id,
            title=title,
            url=url,
            xpath=xpath,
            enabled=enabled,
            auto_tag=auto_tag,
            favicon=favicon,
            category_name=category_name,
            language=language,
            age=age,
            fetch_period=fetch_period,
        )
        flash(f"Source '{title}' updated successfully.", "success")
        return redirect(url_for("sources.source_detail", id=id))

    return render_template("sources/edit_rss.html", source=source, is_new=False)


@sources_bp.route("/sources/new/email", methods=["GET", "POST"])
def source_add_email():
    """
    Renders SourceEmailEditScreen for configuring an IMAP Email source.
    Persists credentials into the credentials table.
    """
    session = get_session()
    source_repo = SourceRepository(session)

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        url = request.form.get("url", "").strip()  # IMAP host / server URL
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        enabled = "enabled" in request.form
        auto_tag = request.form.get("auto_tag", "").strip()
        language = request.form.get("language", "").strip() or None
        age = _parse_age(request.form.get("age"))
        fetch_period = _parse_fetch_period(request.form.get("fetch_period"))

        if not url or not username:
            flash("Server URL and username are required.", "danger")
            return render_template(
                "sources/edit_email.html", source=None, credentials=None, is_new=True
            )

        user = session.execute(select(User).limit(1)).scalar_one_or_none()
        if not user:
            user = User(
                username="admin",
                password="",
                first_name="",
                last_name="",
                is_superuser=True,
                is_active=True,
                is_staff=True,
                email="",
            )
            session.add(user)
            session.flush()

        creds = Credentials(
            name=title or url,
            credential_type="email",
            username=username,
            password=password,
            user_id=user.id,
        )
        session.add(creds)
        session.flush()

        new_source = source_repo.add_source(
            url=url,
            title=title or url,
            source_type=Sources.SOURCE_TYPE_EMAIL,
            enabled=enabled,
            auto_tag=auto_tag,
            credentials_id=creds.id,
            language=language,
            age=age,
            fetch_period=fetch_period,
        )
        flash(f"Email source '{new_source.title}' configured successfully.", "success")
        return redirect(url_for("sources.source_detail", id=new_source.id))

    return render_template(
        "sources/edit_email.html", source=None, credentials=None, is_new=True
    )


@sources_bp.route("/sources/<int:id>/edit-email", methods=["GET", "POST"])
def source_edit_email(id: int):
    """
    Renders SourceEmailEditScreen for editing an existing IMAP Email source.
    """
    session = get_session()
    source_repo = SourceRepository(session)
    source = source_repo.get_by_id(id)
    if not source:
        abort(404)

    credentials = (
        session.get(Credentials, source.credentials_id)
        if source.credentials_id
        else None
    )

    if request.method == "POST":
        title = request.form.get("title", "").strip() or source.url
        url = request.form.get("url", "").strip() or source.url
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        enabled = "enabled" in request.form
        auto_tag = request.form.get("auto_tag", "").strip()
        language = request.form.get("language", "").strip() or None
        age = _parse_age(request.form.get("age"))
        fetch_period = _parse_fetch_period(request.form.get("fetch_period"))

        if credentials:
            credentials.name = title
            credentials.username = username
            if password:
                credentials.password = password
        else:
            user = session.execute(select(User).limit(1)).scalar_one_or_none()
            if not user:
                user = User(
                    username="admin",
                    password="",
                    first_name="",
                    last_name="",
                    is_superuser=True,
                    is_active=True,
                    is_staff=True,
                    email="",
                )
                session.add(user)
                session.flush()

            credentials = Credentials(
                name=title,
                credential_type="email",
                username=username,
                password=password,
                user_id=user.id,
            )
            session.add(credentials)
            session.flush()
            source.credentials_id = credentials.id

        source_repo.update_source(
            id,
            title=title,
            url=url,
            enabled=enabled,
            auto_tag=auto_tag,
            credentials_id=credentials.id,
            language=language,
            age=age,
            fetch_period=fetch_period,
        )
        flash(f"Email source '{title}' updated successfully.", "success")
        return redirect(url_for("sources.source_detail", id=id))

    return render_template(
        "sources/edit_email.html", source=source, credentials=credentials, is_new=False
    )


@sources_bp.route("/sources/new/parse", methods=["GET", "POST"])
def source_add_parse():
    """
    Renders SourceParseEditScreen for adding a custom XPath/HTML parsing source.
    """
    session = get_session()
    source_repo = SourceRepository(session)

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        url = request.form.get("url", "").strip()
        xpath = request.form.get("xpath", "").strip() or None
        enabled = "enabled" in request.form
        auto_tag = request.form.get("auto_tag", "").strip()
        language = request.form.get("language", "").strip() or None
        age = _parse_age(request.form.get("age"))
        fetch_period = _parse_fetch_period(request.form.get("fetch_period"))

        if not url:
            flash("Web page URL is required.", "danger")
            return render_template("sources/edit_parse.html", source=None, is_new=True)

        new_source = source_repo.add_source(
            url=url,
            title=title or url,
            source_type="PARSE",
            xpath=xpath,
            enabled=enabled,
            auto_tag=auto_tag,
            language=language,
            age=age,
            fetch_period=fetch_period,
        )
        flash(f"Parse source '{new_source.title}' configured successfully.", "success")
        return redirect(url_for("sources.source_detail", id=new_source.id))

    return render_template("sources/edit_parse.html", source=None, is_new=True)


@sources_bp.route("/sources/<int:id>/edit-parse", methods=["GET", "POST"])
def source_edit_parse(id: int):
    """
    Renders SourceParseEditScreen for editing an existing custom XPath parsing source.
    """
    session = get_session()
    source_repo = SourceRepository(session)
    source = source_repo.get_by_id(id)
    if not source:
        abort(404)

    if request.method == "POST":
        title = request.form.get("title", "").strip() or source.url
        url = request.form.get("url", "").strip() or source.url
        xpath = request.form.get("xpath", "").strip() or None
        enabled = "enabled" in request.form
        auto_tag = request.form.get("auto_tag", "").strip()
        language = request.form.get("language", "").strip() or None
        age = _parse_age(request.form.get("age"))
        fetch_period = _parse_fetch_period(request.form.get("fetch_period"))

        source_repo.update_source(
            id,
            title=title,
            url=url,
            xpath=xpath,
            enabled=enabled,
            auto_tag=auto_tag,
            language=language,
            age=age,
            fetch_period=fetch_period,
        )
        flash(f"Parse source '{title}' updated successfully.", "success")
        return redirect(url_for("sources.source_detail", id=id))

    return render_template("sources/edit_parse.html", source=source, is_new=False)
