"""
Credentials Repository Implementation for YAFR.

Manages stored credential records (name, username, password, etc.)
in the credentials SQLite table.
"""

import logging
from typing import Any, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session
from linkarchivetools.model.definitions import Credentials

from yafr.db.base_repository import BaseRepository

logger = logging.getLogger(__name__)


class CredentialsRepository(BaseRepository[Credentials]):
    """
    Data access repository for credential records.

    Supports listing, retrieving, creating, updating, and deleting
    entries in the credentials table.
    """

    def __init__(self, session: Optional[Session] = None) -> None:
        super().__init__(session=session)

    def list_credentials(
        self,
        order_by: str = "name",
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> List[Credentials]:
        """
        Lists all credential records.

        :param order_by: Sorting field ('name' or 'id')
        :param limit: Maximum rows to return
        :param offset: Number of rows to skip
        :return: List of Credentials instances
        """
        stmt = select(Credentials)

        if order_by == "id":
            stmt = stmt.order_by(Credentials.id.asc())
        else:
            stmt = stmt.order_by(Credentials.name.asc())

        if offset is not None:
            stmt = stmt.offset(offset)
        if limit is not None:
            stmt = stmt.limit(limit)

        return list(self.session.execute(stmt).scalars().all())

    def get_credential(self, credential_id: int) -> Optional[Credentials]:
        """
        Retrieves a credential by primary key ID.

        :param credential_id: Credential ID
        :return: Credentials instance or None
        """
        return self.get_by_id(Credentials, credential_id)

    def get_by_name(self, name: str) -> Optional[Credentials]:
        """
        Retrieves a credential by its unique name.

        :param name: Credential name (e.g. 'github', 'reddit')
        :return: Credentials instance or None
        """
        stmt = select(Credentials).where(Credentials.name == name)
        return self.session.execute(stmt).scalar_one_or_none()

    def add_credential(
        self,
        name: str,
        username: Optional[str] = None,
        password: Optional[str] = None,
        credential_type: Optional[str] = None,
        secret: Optional[str] = None,
        token: Optional[str] = None,
    ) -> Credentials:
        """
        Creates a new credential record.

        :param name: Unique credential name (e.g. 'github')
        :param username: Account username
        :param password: Account password
        :param credential_type: Credential type label (e.g. 'refresh_token')
        :param secret: Optional secret field
        :param token: Optional token field
        :return: Persisted Credentials instance
        """
        credential = Credentials(
            name=name,
            username=username or "",
            password=password or "",
            credential_type=credential_type or "",
            secret=secret or "",
            token=token or "",
            user_id=1,
        )
        self.session.add(credential)
        self.session.commit()
        logger.info("Created credential '%s' (id=%s)", name, credential.id)
        return credential

    def update_credential(
        self, credential_id: int, **kwargs: Any
    ) -> Optional[Credentials]:
        """
        Updates fields on an existing credential record.

        :param credential_id: Credential ID
        :param kwargs: Field values to update
        :return: Updated Credentials instance or None if not found
        """
        credential = self.get_credential(credential_id)
        if not credential:
            return None

        for key, val in kwargs.items():
            if hasattr(credential, key):
                setattr(credential, key, val)

        self.session.commit()
        logger.info("Updated credential id=%d", credential_id)
        return credential

    def delete_credential(self, credential_id: int) -> bool:
        """
        Deletes a credential record by ID.

        :param credential_id: Credential ID
        :return: True if deleted, False if not found
        """
        credential = self.get_credential(credential_id)
        if not credential:
            return False
        self.session.delete(credential)
        self.session.commit()
        logger.info("Deleted credential id=%d", credential_id)
        return True
