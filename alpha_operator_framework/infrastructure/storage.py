"""Database-driver-neutral SQLAlchemy engine composition."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from sqlalchemy import Engine, create_engine


@dataclass(frozen=True)
class StorageConfig:
    driver: str
    url: str
    connect_args: Mapping[str, Any] | None = None

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any], *, base_path: Path | None = None) -> "StorageConfig":
        driver = str(data.get("driver", "")).lower()
        if driver not in {"sqlite", "mysql", "postgresql"}:
            raise ValueError("storage.driver must be sqlite, mysql, or postgresql")
        explicit_url = data.get("url")
        if explicit_url:
            connect_args = data.get("connect_args")
            if connect_args is not None and not isinstance(connect_args, Mapping):
                raise ValueError("storage.connect_args must be a mapping")
            return cls(driver, str(explicit_url), dict(connect_args) if connect_args is not None else None)
        if driver != "sqlite":
            raise ValueError(f"storage.url is required for {driver}")
        path = data.get("path")
        if not path:
            raise ValueError("storage.path is required for sqlite")
        database_path = Path(str(path))
        if not database_path.is_absolute() and base_path is not None:
            database_path = (base_path / database_path).resolve()
        return cls(driver, f"sqlite:///{database_path.as_posix()}")


def create_storage_engine(config: StorageConfig) -> Engine:
    """Create an engine without issuing a connection; credentials stay in the URL/config."""
    return create_engine(config.url, pool_pre_ping=config.driver != "sqlite", connect_args=dict(config.connect_args or {}))
