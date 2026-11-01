"""
Credentials Service for YAFR.

Provides business logic for managing stored credentials (name, username, password)
used by email sources and other integrations.
"""

import logging
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session
from linkarchivetools.model.definitions import Credentials

from yafr.db.credentials_repository import CredentialsRepository

logger = logging.getLogger(__name__)


class CredentialsService:
    """
    Domain service for credential management operations.
    """

    @staticmethod
    def list_credentials(session: Optional[Session] = None) -> List[Credentials]:
        """
        Returns all credential records ordered by name.

        :param session: Optional SQLAlchemy session
        :return: List of Credentials instances
        """
        repo = CredentialsRepository(session=session)
        return repo.list_credentials()

    @staticmethod
    def get_credential(
        credential_id: int, session: Optional[Session] = None
    ) -> Optional[Credentials]:
        """
        Retrieves a single credential by ID.

        :param credential_id: Credential primary key
        :param session: Optional SQLAlchemy session
        :return: Credentials instance or None
        """
        repo = CredentialsRepository(session=session)
        return repo.get_credential(credential_id)

    @staticmethod
    def create_credential(
        data: Dict[str, Any], session: Optional[Session] = None
    ) -> Credentials:
        """
        Validates and creates a new credential.

        :param data: Dictionary with 'name', 'username', 'password', etc.
        :param session: Optional SQLAlchemy session
        :return: Persisted Credentials instance
        :raises ValueError: If name is missing or already taken
        """
        repo = CredentialsRepository(session=session)

        name = (data.get("name") or "").strip()
        if not name:
            raise ValueError("Credential name is required.")

        if repo.get_by_name(name):
            raise ValueError(f"A credential named '{name}' already exists.")

        return repo.add_credential(
            name=name,
            username=(data.get("username") or "").strip(),
            password=data.get("password") or "",
            credential_type=(data.get("credential_type") or "").strip(),
            secret=data.get("secret") or "",
            token=data.get("token") or "",
        )

    @staticmethod
    def update_credential(
        credential_id: int, data: Dict[str, Any], session: Optional[Session] = None
    ) -> Credentials:
        """
        Validates and applies updates to an existing credential.

        :param credential_id: Credential primary key
        :param data: Dictionary of fields to update
        :param session: Optional SQLAlchemy session
        :return: Updated Credentials instance
        :raises ValueError: If credential not found or name conflict
        """
        repo = CredentialsRepository(session=session)

        credential = repo.get_credential(credential_id)
        if not credential:
            raise ValueError(f"Credential with id={credential_id} not found.")

        name = (data.get("name") or "").strip()
        if not name:
            raise ValueError("Credential name is required.")

        # Check for name conflicts with other credentials
        existing = repo.get_by_name(name)
        if existing and existing.id != credential_id:
            raise ValueError(f"A credential named '{name}' already exists.")

        update_fields: Dict[str, Any] = {
            "name": name,
            "username": (data.get("username") or "").strip(),
            "credential_type": (data.get("credential_type") or "").strip(),
        }
        # Only update password if a new value was supplied
        if data.get("password"):
            update_fields["password"] = data["password"]

        return repo.update_credential(credential_id, **update_fields)

    @staticmethod
    def delete_credential(
        credential_id: int, session: Optional[Session] = None
    ) -> bool:
        """
        Deletes a credential by ID.

        :param credential_id: Credential primary key
        :param session: Optional SQLAlchemy session
        :return: True if deleted, False if not found
        """
        repo = CredentialsRepository(session=session)
        return repo.delete_credential(credential_id)
