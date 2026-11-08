"""
Base Job Handler Interface for YAFR Background Jobs.

Defines the abstract interface implemented by all discrete job handlers.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict
from sqlalchemy.orm import Session
from linkarchivetools.model.definitions import BackgroundJob


class BaseJobHandler(ABC):
    """
    Abstract base class for all background job execution handlers.
    """

    job_types: tuple[str, ...] = ()

    def can_handle(self, job_type: str) -> bool:
        """
        Determines whether this handler can process the given job type.

        :param job_type: Job type string from BackgroundJob.job
        :return: True if this handler matches
        """
        return job_type in self.job_types

    @abstractmethod
    def execute(self, job: BackgroundJob, session: Session) -> Dict[str, Any]:
        """
        Executes the background job logic.

        :param job: BackgroundJob database model instance
        :param session: Active SQLAlchemy session
        :return: Dictionary containing 'success' (bool), and optional 'consume' (bool indicating
                 whether the job should be consumed and removed from queue upon reaching max retries or success),
                 'status' (str), 'message' (str), and 'error' (str).
        """
        raise NotImplementedError
