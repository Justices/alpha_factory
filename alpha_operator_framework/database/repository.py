"""Unified aggregate facade for Alpha Factory's legacy simulation repositories."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional, Union

from alpha_operator_framework.infrastructure.storage import StorageConfig

from .base import submission_wf_stage
from .config import DEFAULT_SQLITE_PATH
from .connection import DatabaseConnectionManager
from .models import AlphaDetail, AlphaExpression, DataField, Template
from .repositories import AlphaRepository, DatafieldRepository, EventLedgerRepository, QueueRepository, SimulationRepository, TemplateRepository
from .schema import migrate_legacy_schema


def persist_workflow_row(db: "AlphaDatabase", row: Dict[str, Any], settings: Dict, stage: str = "", status: str = "pending") -> Optional[str]:
    if not isinstance(row, dict):
        return None
    alpha_id = row.get("alpha_id") or row.get("id")
    regular = row.get("regular")
    expression = (regular.get("code") if isinstance(regular, dict) else None) or row.get("expression") or ""
    if not alpha_id or not expression:
        return None
    db.insert_expression(expression, settings)
    db.save_result_with_checks(alpha_id, row, settings)
    return alpha_id


class AlphaDatabase(AlphaRepository, SimulationRepository, DatafieldRepository, TemplateRepository, QueueRepository, EventLedgerRepository):
    """The sole legacy database facade; all connections and DDL use SQLAlchemy."""

    DEFAULT_DB_PATH = DEFAULT_SQLITE_PATH

    def __init__(self, db_path: Optional[Union[str, Path, StorageConfig, DatabaseConnectionManager]] = None, timeout: float = 30.0, wal_mode: bool = True):
        super().__init__(db_path=db_path, timeout=timeout, wal_mode=wal_mode)
        migrate_legacy_schema(self.manager.engine)
        self.seed_template_library()


__all__ = [
    "AlphaDatabase", "AlphaRepository", "SimulationRepository", "DatafieldRepository", "TemplateRepository", "QueueRepository",
    "EventLedgerRepository", "AlphaExpression", "AlphaDetail", "DataField", "Template", "persist_workflow_row",
    "submission_wf_stage",
]
