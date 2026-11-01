"""
Entry Rules routes and view controller for YAFR.

Implements EntryRulesScreen: listing, creating, editing, toggling,
and deleting URL-based processing rules stored in the entryrules table.
"""

import math
from flask import Blueprint, flash, redirect, render_template, request, url_for
from yafr.db import (
    BlockEntryListRepository,
    BlockEntryRepository,
    BlockRepository,
    RulesRepository,
    get_session,
)

rules_bp = Blueprint("rules", __name__)


@rules_bp.route("/rules")
def rules_list():
    """
    Renders EntryRulesScreen — a full list of all configured entry rules.

    Rules are displayed ordered by priority (ascending), then ID.
    """
    session = get_session()
    repo = RulesRepository(session)
    rules = repo.list_rules()
    block_repo = BlockEntryRepository(session)
    blocked_urls_count = block_repo.count_entries()
    list_repo = BlockEntryListRepository(session)
    block_lists_count = list_repo.count_lists()
    return render_template(
        "rules/list.html",
        rules=rules,
        blocked_urls_count=blocked_urls_count,
        block_lists_count=block_lists_count,
    )


@rules_bp.route("/rules/block-entries")
@rules_bp.route("/rules/blocked-urls")
def blocked_urls_view():
    """
    Renders the Blocked URLs (BlockEntry items) screen.

    Displays BlockEntry items (blocked URLs, domains, and patterns)
    with server-side pagination, search, and per-entry deletion.
    """
    query = request.args.get("q", "").strip()
    order = request.args.get("order", "id")
    page = max(1, request.args.get("page", 1, type=int))
    per_page = 50
    offset = (page - 1) * per_page

    session = get_session()
    block_repo = BlockEntryRepository(session)
    list_repo = BlockEntryListRepository(session)

    total_count = block_repo.count_entries(search=query if query else None)
    total_all_count = block_repo.count_entries()
    block_lists_count = list_repo.count_lists()

    entries = block_repo.list_entries(
        search=query if query else None,
        order_by=order,
        limit=per_page,
        offset=offset,
    )
    total_pages = max(1, math.ceil(total_count / per_page)) if total_count > 0 else 1

    return render_template(
        "rules/blocked_urls.html",
        entries=entries,
        query=query,
        order=order,
        page=page,
        per_page=per_page,
        total_count=total_count,
        total_all_count=total_all_count,
        total_pages=total_pages,
        block_lists_count=block_lists_count,
    )


@rules_bp.route("/rules/blocked-urls/batch-delete", methods=["POST"])
def blocked_urls_batch_delete():
    """
    Batch-deletes multiple BlockEntry records selected via checkboxes in the UI.
    """
    raw_ids = request.form.getlist("selected_ids")
    if not raw_ids:
        flash("No blocked URLs selected for deletion.", "warning")
        return redirect(url_for("rules.blocked_urls_view"))

    try:
        ids = [int(i) for i in raw_ids if str(i).strip().isdigit()]
    except Exception:
        ids = []

    if not ids:
        flash("Invalid selection.", "warning")
        return redirect(url_for("rules.blocked_urls_view"))

    session = get_session()
    block_repo = BlockEntryRepository(session)
    count = block_repo.delete_entries(ids)
    flash(f"Successfully removed {count} blocked URL(s).", "success")
    return redirect(url_for("rules.blocked_urls_view"))


@rules_bp.route("/rules/block-lists")
def block_lists_view():
    """
    Renders the Block Entry Lists management screen.
    Displays all BlockEntryList records with their processed status,
    entry counts, deletion, processing, and multi-selection checkboxes.
    """
    session = get_session()
    list_repo = BlockEntryListRepository(session)
    entry_repo = BlockEntryRepository(session)
    lists = list_repo.list_lists(order_by="id")
    counts = {l.id: entry_repo.count_entries(block_list_id=l.id) for l in lists}
    return render_template(
        "rules/block_lists.html",
        lists=lists,
        counts=counts,
    )


@rules_bp.route("/rules/block-lists/add", methods=["POST"])
def block_list_add():
    """
    Adds a new BlockEntryList record and optionally processes it immediately.
    """
    url = request.form.get("url", "").strip()
    process_now = bool(request.form.get("process_now"))
    if not url:
        flash("Block list URL cannot be empty.", "warning")
        return redirect(url_for("rules.block_lists_view"))

    session = get_session()
    repo = BlockRepository(session)
    try:
        new_list = repo.add_list(url=url, processed=False)
        if process_now:
            count = repo.process_block_list(new_list.id)
            flash(
                f"Block list added and processed: {count} entries ingested.",
                "success",
            )
        else:
            flash(f"Block list added successfully.", "success")
    except Exception as exc:
        flash(f"Error adding block list: {exc}", "danger")

    return redirect(url_for("rules.block_lists_view"))


@rules_bp.route("/rules/block-lists/<int:id>/process", methods=["POST"])
def block_list_process(id: int):
    """
    Processes an existing BlockEntryList, downloading its contents and splitting into BlockEntry items.
    """
    session = get_session()
    repo = BlockRepository(session)
    try:
        count = repo.process_block_list(id)
        flash(
            f"Block list #{id} processed successfully: {count} entries ingested.",
            "success",
        )
    except Exception as exc:
        flash(f"Failed to process block list #{id}: {exc}", "danger")
    return redirect(url_for("rules.block_lists_view"))


@rules_bp.route("/rules/block-lists/<int:id>/delete", methods=["POST"])
def block_list_delete(id: int):
    """
    Deletes a single BlockEntryList record and its child BlockEntry items.
    """
    session = get_session()
    list_repo = BlockEntryListRepository(session)
    deleted = list_repo.delete_list(id, delete_entries=True)
    if deleted:
        flash(f"Block list #{id} deleted successfully.", "success")
    else:
        flash(f"Block list #{id} not found.", "warning")
    return redirect(url_for("rules.block_lists_view"))


@rules_bp.route("/rules/block-lists/batch-delete", methods=["POST"])
def block_lists_batch_delete():
    """
    Batch-deletes multiple BlockEntryList records selected via checkboxes in the UI layout.
    """
    raw_ids = request.form.getlist("selected_ids")
    if not raw_ids:
        flash("No block lists selected for deletion.", "warning")
        return redirect(url_for("rules.block_lists_view"))

    try:
        ids = [int(i) for i in raw_ids if str(i).strip().isdigit()]
    except Exception:
        ids = []

    if not ids:
        flash("Invalid list selection.", "warning")
        return redirect(url_for("rules.block_lists_view"))

    session = get_session()
    list_repo = BlockEntryListRepository(session)
    count = list_repo.delete_lists(ids, delete_entries=True)
    flash(f"Successfully deleted {count} block list(s).", "success")
    return redirect(url_for("rules.block_lists_view"))


@rules_bp.route("/rules/block-url", methods=["GET", "POST"])
def block_url_add():
    """
    Adds a single BlockEntry record (GET renders standalone form, POST persists).
    """
    if request.method == "POST":
        raw_url = request.form.get("url", "").strip()
        next_url = request.form.get("next") or request.referrer
        if not raw_url:
            flash("URL or pattern cannot be empty.", "warning")
            return redirect(next_url or url_for("rules.blocked_urls_view"))

        session = get_session()
        block_repo = BlockEntryRepository(session)
        try:
            entry = block_repo.add_entry(url=raw_url)
            flash(f"Blocked URL '{entry.url}' added successfully.", "success")
        except Exception as exc:
            flash(f"Failed to add block entry: {exc}", "danger")
        return redirect(next_url or url_for("rules.blocked_urls_view"))

    return render_template(
        "rules/block_url.html",
        action_url=url_for("rules.block_url_add"),
    )


@rules_bp.route("/rules/block-entry/<int:id>/delete", methods=["POST"])
def block_entry_delete(id: int):
    """
    Deletes a single BlockEntry by primary key ID and redirects back to Blocked URLs view.
    """
    next_url = (
        request.form.get("next")
        or request.referrer
        or url_for("rules.blocked_urls_view")
    )
    session = get_session()
    block_repo = BlockEntryRepository(session)
    deleted = block_repo.delete_entry(id)
    if deleted:
        flash("Blocked URL removed.", "success")
    else:
        flash("Block entry not found.", "warning")
    return redirect(next_url)


@rules_bp.route("/rules/add", methods=["GET", "POST"])
def rule_add():
    """
    Renders the add-rule form (GET) and persists a new rule (POST).
    """
    if request.method == "POST":
        session = get_session()
        repo = RulesRepository(session)
        try:
            repo.add_rule(
                rule_name=request.form.get("rule_name", "").strip(),
                trigger_rule_url=request.form.get("trigger_rule_url", "").strip(),
                enabled=bool(request.form.get("enabled")),
                priority=int(request.form.get("priority") or 0),
                block=bool(request.form.get("block")),
                trust=bool(request.form.get("trust")),
                auto_tag=request.form.get("auto_tag", "").strip(),
                apply_age_limit=int(request.form.get("apply_age_limit") or 0),
            )
            flash("Rule created successfully.", "success")
        except Exception as exc:
            flash(f"Failed to create rule: {exc}", "danger")
        return redirect(url_for("rules.rules_list"))

    return render_template(
        "rules/edit.html", rule=None, action_url=url_for("rules.rule_add")
    )


@rules_bp.route("/rules/<int:id>/edit", methods=["GET", "POST"])
def rule_edit(id: int):
    """
    Renders the edit-rule form (GET) and saves changes to an existing rule (POST).
    """
    session = get_session()
    repo = RulesRepository(session)
    rule = repo.get_rule(id)
    if not rule:
        flash("Rule not found.", "warning")
        return redirect(url_for("rules.rules_list"))

    if request.method == "POST":
        try:
            repo.update_rule(
                id,
                rule_name=request.form.get("rule_name", "").strip(),
                trigger_rule_url=request.form.get("trigger_rule_url", "").strip(),
                enabled=bool(request.form.get("enabled")),
                priority=int(request.form.get("priority") or 0),
                block=bool(request.form.get("block")),
                trust=bool(request.form.get("trust")),
                auto_tag=request.form.get("auto_tag", "").strip(),
                apply_age_limit=int(request.form.get("apply_age_limit") or 0),
            )
            flash("Rule updated successfully.", "success")
        except Exception as exc:
            flash(f"Failed to update rule: {exc}", "danger")
        return redirect(url_for("rules.rules_list"))

    return render_template(
        "rules/edit.html",
        rule=rule,
        action_url=url_for("rules.rule_edit", id=id),
    )


@rules_bp.route("/rules/<int:id>/toggle", methods=["POST"])
def rule_toggle(id: int):
    """
    Toggles the enabled state of a rule via AJAX POST.

    Returns JSON: {"success": true, "enabled": <new state>}
    """
    from flask import jsonify

    session = get_session()
    repo = RulesRepository(session)
    new_state = repo.toggle_rule(id)
    if new_state is None:
        return jsonify({"success": False, "error": "Rule not found"}), 404
    return jsonify({"success": True, "enabled": new_state})


@rules_bp.route("/rules/<int:id>/delete", methods=["POST"])
def rule_delete(id: int):
    """
    Deletes a rule and redirects back to EntryRulesScreen.
    """
    session = get_session()
    repo = RulesRepository(session)
    deleted = repo.delete_rule(id)
    if deleted:
        flash("Rule deleted.", "success")
    else:
        flash("Rule not found.", "warning")
    return redirect(url_for("rules.rules_list"))
