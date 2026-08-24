"""Database-driver-neutral SQLAlchemy engine composition."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from sqlalchemy import Engine, create_engine, make_url


@dataclass(frozen=True)
class StorageConfig:
    driver: str
    url: str
    connect_args: Mapping[str, Any] | None = None

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any], *, base_path: Path | None = None) -> "StorageConfig":
        database_type = str(data.get("database_type") or data.get("driver", "")).lower()
        connection_type = str(data.get("connection_type") or "url").lower()
        dialect_driver = str(data.get("driver", "")).lower() if data.get("database_type") else None
        if not database_type:
            raise ValueError("storage.database_type is required")
        if connection_type not in {"file", "url"}:
            raise ValueError("storage.connection_type must be file or url")
        if connection_type == "file":
            if database_type != "sqlite":
                raise ValueError("storage.connection_type=file is only supported for sqlite")
            if dialect_driver not in {None, "sqlite"}:
                raise ValueError("storage.driver must be sqlite for file connections")
            location = data.get("url") or data.get("path")
            if not location:
                raise ValueError("storage.url is required for file connections")
            database_path = Path(str(location))
            if not database_path.is_absolute() and base_path is not None:
                database_path = (base_path / database_path).resolve()
            return cls("sqlite", f"sqlite:///{database_path.as_posix()}")
        explicit_url = data.get("url")
        if explicit_url:
            url = os.path.expandvars(str(explicit_url))
            if re.search(r"\$(?:\{[^}]+\}|\w+)|%[^%]+%", url):
                raise ValueError("storage.url contains an unresolved environment variable")
            parsed_url = make_url(url)
            if database_type != parsed_url.get_backend_name():
                raise ValueError("storage.database_type must match storage.url")
            url_driver = parsed_url.drivername.partition("+")[2] or parsed_url.get_backend_name()
            if dialect_driver and dialect_driver != url_driver:
                raise ValueError("storage.driver must match storage.url")
            if database_type == "sqlite" and parsed_url.database and parsed_url.database != ":memory:" and not Path(parsed_url.database).is_absolute() and base_path is not None:
                url = str(parsed_url.set(database=str((base_path / parsed_url.database).resolve())))
            connect_args = data.get("connect_args")
            if connect_args is not None and not isinstance(connect_args, Mapping):
                raise ValueError("storage.connect_args must be a mapping")
            return cls(database_type, url, dict(connect_args) if connect_args is not None else None)
        if database_type != "sqlite":
            raise ValueError(f"storage.url is required for {database_type}")
        path = data.get("path")
        if not path:
            raise ValueError("storage.path is required for sqlite")
        database_path = Path(str(path))
        if not database_path.is_absolute() and base_path is not None:
            database_path = (base_path / database_path).resolve()
        return cls(database_type, f"sqlite:///{database_path.as_posix()}")


def create_storage_engine(config: StorageConfig) -> Engine:
    """Create an engine without issuing a connection; credentials stay in the URL/config."""
    return create_engine(config.url, pool_pre_ping=config.driver != "sqlite", connect_args=dict(config.connect_args or {}))
