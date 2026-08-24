"""Consistent file backup and restore for SQLite storage."""

from __future__ import annotations

import shutil
from pathlib import Path

from sqlalchemy import make_url, text

from .storage import StorageConfig, create_storage_engine


def backup_sqlite_storage(storage: StorageConfig, destination: Path) -> Path:
    if storage.driver != "sqlite":
        raise ValueError("file backup is only available for sqlite storage")
    if destination.exists():
        raise FileExistsError(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    engine = create_storage_engine(storage)
    try:
        escaped = str(destination.resolve()).replace("'", "''")
        with engine.begin() as connection:
            connection.execute(text(f"VACUUM INTO '{escaped}'"))
    finally:
        engine.dispose()
    return destination


def restore_sqlite_storage(backup: Path, storage: StorageConfig) -> None:
    if storage.driver != "sqlite":
        raise ValueError("file restore is only available for sqlite storage")
    if not backup.is_file():
        raise FileNotFoundError(backup)
    target = Path(make_url(storage.url).database)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(backup, target)
