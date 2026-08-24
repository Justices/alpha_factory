"""Infrastructure-only database operations used by maintenance commands."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import make_url

from alpha_operator_framework.infrastructure.runtime_factory import load_runtime_config, storage_config


def storage_path(config_path: Path) -> Path | None:
    """Return a filesystem path only for file-backed storage."""
    storage = storage_config(config_path)
    if storage.driver != "sqlite":
        return None
    database = make_url(storage.url).database
    return Path(database).resolve() if database else None


def open_alpha_database(config_path: Path):
    from alpha_operator_framework.database.repository import AlphaDatabase

    return AlphaDatabase(db_path=storage_config(config_path))


def initialize_storage(config_path: Path, *, reset: bool) -> bool:
    from alpha_operator_framework.database.init_db import init_database

    success, _ = init_database(db_path=storage_config(config_path), reset=reset)
    return success


def verify_storage(config_path: Path) -> bool:
    from alpha_operator_framework.database.init_db import verify_database

    return verify_database(storage_config(config_path))


def clean_storage(config_path: Path, *, mode: str, dry_run: bool, vacuum: bool) -> None:
    from alpha_operator_framework.database.cleaner import clean_alpha_research_db

    clean_alpha_research_db(db_path=storage_config(config_path), mode=mode, dry_run=dry_run, vacuum=vacuum)
