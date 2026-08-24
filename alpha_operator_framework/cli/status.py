"""Production status command adapter; it owns no database queries."""

from __future__ import annotations

from argparse import Namespace
from pathlib import Path

from alpha_operator_framework.application.status_dashboard import build_status_dashboard
from alpha_operator_framework.infrastructure.maintenance import open_alpha_database, storage_display_location, storage_path, verify_storage

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "configs" / "alpha-factory.yaml"


def command_status(args: Namespace) -> None:
    config_path = Path(getattr(args, "config", DEFAULT_CONFIG_PATH))
    database_file = storage_path(config_path)
    if database_file is not None and not database_file.exists():
        print(f"storage is not initialized: {database_file.resolve()}")
        return
    if not verify_storage(config_path):
        print("storage verification failed; run init-db first")
        return
    database = open_alpha_database(config_path)
    try:
        dashboard = build_status_dashboard(database)
    finally:
        database.close()
    simulation = dashboard["simulation"]
    expressions = dashboard["expression_status"]
    print(f"Database: {storage_display_location(config_path)}")
    print(f"expressions={sum(expressions.values())} completed={expressions.get('completed', 0)} pending={expressions.get('pending', 0)} failed={expressions.get('failed', 0)}")
    print(f"simulations={simulation['total']} max_sharpe={simulation['max_sharpe']:.2f} avg_sharpe={simulation['avg_sharpe']:.2f}")
    print(f"submission_ready={len(dashboard['submission_ready'])} templates={len(dashboard['templates'])}")
