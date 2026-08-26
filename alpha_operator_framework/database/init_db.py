"""Schema initialization and verification through the shared storage engine."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import List, Tuple

from sqlalchemy import inspect, make_url

from alpha_operator_framework.database.config import get_database_path
from alpha_operator_framework.database.schema import migrate_legacy_schema
from alpha_operator_framework.infrastructure.storage import StorageConfig, create_storage_engine


DEFAULT_DB_PATH = get_database_path()


def _storage(value: Path | StorageConfig) -> StorageConfig:
    return value if isinstance(value, StorageConfig) else StorageConfig.from_mapping({"driver": "sqlite", "path": str(value)})


def init_database(db_path: Path | StorageConfig = DEFAULT_DB_PATH, reset: bool = False, verbose: bool = True) -> Tuple[bool, List[str]]:
    storage = _storage(db_path)
    if reset and storage.driver == "sqlite":
        database = make_url(storage.url).database
        if database:
            target = Path(database)
            for candidate in (target, target.with_name(f"{target.name}-wal"), target.with_name(f"{target.name}-shm")):
                if candidate.exists():
                    candidate.unlink()
    engine = create_storage_engine(storage)
    try:
        if reset and storage.driver != "sqlite":
            # Reset is deliberately schema-level so it has identical semantics for every configured driver.
            from alpha_operator_framework.database.schema import metadata
            from alpha_operator_framework.infrastructure.sqlalchemy_migrations import metadata as runtime_metadata

            metadata.drop_all(engine)
            runtime_metadata.drop_all(engine)
        migrate_legacy_schema(engine)
        tables = sorted(inspect(engine).get_table_names())
        if verbose:
            print(f"initialized {engine.url.render_as_string(hide_password=True)}: {len(tables)} tables")
        return True, tables
    except Exception as error:
        if verbose:
            print(f"initialization failed: {type(error).__name__}: {error}")
        return False, []
    finally:
        engine.dispose()


def verify_database(db_path: Path | StorageConfig = DEFAULT_DB_PATH) -> bool:
    storage = _storage(db_path)
    engine = create_storage_engine(storage)
    try:
        tables = set(inspect(engine).get_table_names())
        return {"alpha_expressions", "event_log"} <= tables
    except Exception as error:
        print(f"verification failed: {type(error).__name__}: {error}")
        return False
    finally:
        engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Initialize or verify Alpha Factory storage")
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--reset", action="store_true")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    if args.verify:
        raise SystemExit(0 if verify_database(args.db_path) else 1)
    success, _ = init_database(args.db_path, reset=args.reset)
    raise SystemExit(0 if success else 1)


if __name__ == "__main__":
    main()
