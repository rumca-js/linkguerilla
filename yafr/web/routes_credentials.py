"""
Credentials routes and view controller for YAFR.

Implements CredentialsScreen: listing, creating, editing, and deleting
stored credentials (name, username, password) in the credentials table.
"""

import logging

from flask import Blueprint, flash, redirect, render_template, request, url_for
from yafr.db import get_session
from yafr.services.credentials_service import CredentialsService

logger = logging.getLogger(__name__)

credentials_bp = Blueprint("credentials", __name__)


@credentials_bp.route("/credentials")
def credentials_list():
    """
    Renders CredentialsScreen listing all configured credentials.
    """
    session = get_session()
    credentials = CredentialsService.list_credentials(session=session)
    return render_template("credentials/view.html", credentials=credentials)


@credentials_bp.route("/credentials/add", methods=["GET", "POST"])
def credential_add():
    """
    Renders the add-credential form (GET) and persists a new credential (POST).
    """
    if request.method == "POST":
        session = get_session()
        try:
            CredentialsService.create_credential(
                request.form.to_dict(), session=session
            )
            flash("Credential created successfully.", "success")
        except ValueError as exc:
            flash(str(exc), "danger")
        except Exception as exc:
            logger.error("Failed to create credential: %s", exc)
            flash(f"Failed to create credential: {exc}", "danger")
        return redirect(url_for("credentials.credentials_list"))

    return render_template(
        "credentials/edit.html",
        credential=None,
        action_url=url_for("credentials.credential_add"),
    )


@credentials_bp.route("/credentials/<int:credential_id>/edit", methods=["GET", "POST"])
def credential_edit(credential_id: int):
    """
    Renders the edit-credential form (GET) and saves changes (POST).
    """
    session = get_session()
    credential = CredentialsService.get_credential(credential_id, session=session)
    if not credential:
        flash("Credential not found.", "warning")
        return redirect(url_for("credentials.credentials_list"))

    if request.method == "POST":
        try:
            CredentialsService.update_credential(
                credential_id, request.form.to_dict(), session=session
            )
            flash("Credential updated successfully.", "success")
        except ValueError as exc:
            flash(str(exc), "danger")
        except Exception as exc:
            logger.error("Failed to update credential %d: %s", credential_id, exc)
            flash(f"Failed to update credential: {exc}", "danger")
        return redirect(url_for("credentials.credentials_list"))

    return render_template(
        "credentials/edit.html",
        credential=credential,
        action_url=url_for("credentials.credential_edit", credential_id=credential_id),
    )


@credentials_bp.route("/credentials/<int:credential_id>/delete", methods=["POST"])
def credential_delete(credential_id: int):
    """
    Deletes a credential after user confirmation (POST-only for safety).
    """
    session = get_session()
    try:
        deleted = CredentialsService.delete_credential(credential_id, session=session)
        if deleted:
            flash("Credential deleted.", "success")
        else:
            flash("Credential not found.", "warning")
    except Exception as exc:
        logger.error("Failed to delete credential %d: %s", credential_id, exc)
        flash(f"Failed to delete credential: {exc}", "danger")

    return redirect(url_for("credentials.credentials_list"))
