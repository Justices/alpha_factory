"""Database package with a backward-compatible public API."""

from .config import (
    DEFAULT_SQLITE_PATH,
    DatabaseConfig,
    get_database_config,
    get_database_path,
    set_database_config,
)
from .models import (
    WF_STAGES,
    AlphaCheck,
    AlphaDetail,
    AlphaExpression,
    DataField,
    OptimizationQueueItem,
    SimulationBatch,
    SimulationResult,
    SubmissionCandidate,
    Template,
)
from .cleaner import CleanReport, DatabaseCleaner, clean_alpha_research_db, vacuum_database
from .repositories import (
    AlphaRepository,
    DatafieldRepository,
    EventLedgerRepository,
    QueueRepository,
    SimulationRepository,
    TemplateRepository,
)
from .repository import AlphaDatabase, persist_workflow_row

__all__ = [
    "AlphaCheck",
    "AlphaDatabase",
    "AlphaDetail",
    "AlphaExpression",
    "AlphaRepository",
    "CleanReport",
    "DataField",
    "DatafieldRepository",
    "DatabaseCleaner",
    "DatabaseConfig",
    "DatabaseConnectionManager",
    "DEFAULT_SQLITE_PATH",
    "EventLedgerRepository",
    "OptimizationQueueItem",
    "QueueRepository",
    "SimulationBatch",
    "SimulationRepository",
    "SimulationResult",
    "SubmissionCandidate",
    "Template",
    "TemplateRepository",
    "WF_STAGES",
    "clean_alpha_research_db",
    "get_database_config",
    "get_database_path",
    "persist_workflow_row",
    "set_database_config",
    "vacuum_database",
]
