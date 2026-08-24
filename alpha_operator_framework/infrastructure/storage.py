"""Database-driver-neutral SQLAlchemy engine composition."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from sqlalchemy import Engine, create_engine

from alpha_operator_framework.infrastructure.storage_drivers import build_storage_url


@dataclass(frozen=True)
class StorageConfig:
    driver: str
    url: str
    connect_args: Mapping[str, Any] | None = None

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any], *, base_path: Path | None = None) -> "StorageConfig":
        database_type = str(data.get("database_type") or data.get("driver", "")).lower()
        connection_type = str(data.get("connection_type") or ("file" if data.get("path") else "url")).lower()
        dialect_driver = str(data.get("driver", "")).lower() if data.get("database_type") else None
        if not database_type:
            raise ValueError("storage.database_type is required")
        url = build_storage_url(database_type, dialect_driver, connection_type, data, base_path)
        connect_args = data.get("connect_args")
        if connect_args is not None and not isinstance(connect_args, Mapping):
            raise ValueError("storage.connect_args must be a mapping")
        return cls(database_type, url, dict(connect_args) if connect_args is not None else None)


def create_storage_engine(config: StorageConfig) -> Engine:
    """Create an engine without issuing a connection; credentials stay in the URL/config."""
    return create_engine(config.url, pool_pre_ping=config.driver != "sqlite", connect_args=dict(config.connect_args or {}))
