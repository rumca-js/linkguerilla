"""Gateway directory management views."""

import re
from urllib.parse import urlsplit

from flask import Blueprint, flash, redirect, render_template, request, url_for

from yafr.db import GatewayRepository, get_session

gateways_bp = Blueprint("gateways", __name__)


@gateways_bp.route("/gateways", methods=["GET", "POST"])
def gateways_list():
    """Display and manage gateway links in the active database."""
    session = get_session()
    repo = GatewayRepository(session)

    if request.method == "POST":
        action = request.form.get("action", "").strip()
        try:
            if action == "add":
                link = request.form.get("link", "").strip()
                title = request.form.get("title", "").strip() or None
                gateway_type = request.form.get("gateway_type", "").strip()
                if not link:
                    raise ValueError("A gateway URL is required.")
                if len(link) > 2048:
                    raise ValueError("Gateway URLs must be 2048 characters or fewer.")
                if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", link):
                    link = "https://" + link
                parsed = urlsplit(link)
                if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
                    raise ValueError("Enter a valid HTTP or HTTPS gateway URL.")
                if gateway_type not in GatewayRepository.GATEWAYS_TYPES:
                    raise ValueError("Select a valid gateway category.")
                if title and len(title) > 200:
                    raise ValueError("Gateway titles must be 200 characters or fewer.")
                existing = repo.get_by_link(link)
                if existing:
                    raise ValueError("That gateway URL already exists.")
                repo.add_gateway(link, gateway_type, title)
                flash("Gateway added.", "success")
            elif action == "delete":
                gateway_id = request.form.get("gateway_id", type=int)
                if gateway_id is None or not repo.delete_gateway(gateway_id):
                    flash("Gateway was not found.", "warning")
                else:
                    flash("Gateway removed.", "success")
            elif action == "reset":
                repo.reset_to_defaults()
                flash("Gateway directory reset to defaults.", "success")
            else:
                flash("Unknown gateway action.", "danger")
        except ValueError as err:
            session.rollback()
            flash(str(err), "warning")
        except Exception:
            session.rollback()
            flash("Could not save gateway changes. Check the database and try again.", "danger")
        return redirect(url_for("gateways.gateways_list"))

    return render_template(
        "gateways/list.html",
        gateways=repo.list_all_gateways(),
        gateway_types=GatewayRepository.GATEWAYS_TYPES,
    )
