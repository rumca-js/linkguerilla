"""
Database and Repository Layer Package Exports for YAFR.
"""

from yafr.db.base_repository import BaseRepository
from yafr.db.block_repository import (
    BlockEntryListRepository,
    BlockEntryRepository,
    BlockRepository,
    fetch_and_split_block_list_url,
    read_and_split_block_list_file,
    split_block_list_text,
)
from yafr.db.config_repository import ConfigRepository
from yafr.db.credentials_repository import CredentialsRepository
from yafr.db.entry_repository import EntryRepository
from yafr.db.gateway_repository import GatewayRepository
from yafr.db.history_repository import HistoryRepository
from yafr.db.job_repository import JobRepository
from yafr.db.logging_repository import (
    AppLoggingHandler,
    LoggingRepository,
    NOTIFICATION,
    setup_app_logging,
)
from yafr.db.rules_repository import RulesRepository
from yafr.db.search_view_repository import SearchViewRepository
from yafr.db.session import (
    close_session,
    get_engine,
    get_session,
    init_db,
    session_scope,
)
from yafr.db.source_repository import SourceRepository
from yafr.db.system_operation_repository import SystemOperationRepository

__all__ = [
    "init_db",
    "get_engine",
    "get_session",
    "close_session",
    "session_scope",
    "BaseRepository",
    "BlockRepository",
    "BlockEntryRepository",
    "BlockEntryListRepository",
    "split_block_list_text",
    "read_and_split_block_list_file",
    "fetch_and_split_block_list_url",
    "ConfigRepository",
    "CredentialsRepository",
    "EntryRepository",
    "GatewayRepository",
    "SourceRepository",
    "JobRepository",
    "HistoryRepository",
    "RulesRepository",
    "SearchViewRepository",
    "LoggingRepository",
    "AppLoggingHandler",
    "setup_app_logging",
    "NOTIFICATION",
    "SystemOperationRepository",
]
