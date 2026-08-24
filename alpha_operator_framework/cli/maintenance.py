"""CLI adapters for storage maintenance; all storage comes from YAML."""

from __future__ import annotations

import sys
from argparse import Namespace
from pathlib import Path

from alpha_operator_framework.cli.research import DEFAULT_CONFIG_PATH


def _config_path(args: Namespace) -> Path:
    return Path(getattr(args, "config", DEFAULT_CONFIG_PATH))


def command_init_db(args: Namespace) -> None:
    from alpha_operator_framework.infrastructure.maintenance import initialize_storage, storage_path, verify_storage

    config_path = _config_path(args)
    db_file = storage_path(config_path)
    if args.verify:
        if db_file is not None and not db_file.exists() and not initialize_storage(config_path, reset=False):
            raise SystemExit(1)
        success = verify_storage(config_path)
        print("storage verification passed" if success else "storage verification failed")
        raise SystemExit(0 if success else 1)
    success = initialize_storage(config_path, reset=args.reset)
    print("storage migration completed" if success else "storage migration failed")
    raise SystemExit(0 if success else 1)


def command_storage_backup(args: Namespace) -> None:
    from alpha_operator_framework.infrastructure.runtime_factory import storage_config
    from alpha_operator_framework.infrastructure.storage_backup import backup_sqlite_storage

    destination = backup_sqlite_storage(storage_config(_config_path(args)), Path(args.destination))
    print(f"storage backup created: {destination}")


def command_storage_restore(args: Namespace) -> None:
    from alpha_operator_framework.infrastructure.runtime_factory import storage_config
    from alpha_operator_framework.infrastructure.storage_backup import restore_sqlite_storage

    restore_sqlite_storage(Path(args.backup), storage_config(_config_path(args)))
    print(f"storage restore completed: {args.backup}")


def command_clean_db(args: Namespace) -> None:
    from alpha_operator_framework.infrastructure.maintenance import clean_storage

    clean_storage(_config_path(args), mode=args.mode, dry_run=args.dry_run, vacuum=not args.no_vacuum)
