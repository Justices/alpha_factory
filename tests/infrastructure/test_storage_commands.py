from __future__ import annotations

from types import SimpleNamespace

from alpha_operator_framework.cli.maintenance import command_storage_backup, command_storage_restore
from alpha_operator_framework.infrastructure.runtime_factory import storage_config
from alpha_operator_framework.infrastructure.storage import create_storage_engine


def test_storage_backup_and_restore_commands_use_yaml_storage(tmp_path) -> None:
    config = tmp_path / "alpha-factory.yaml"
    database = tmp_path / "research.db"
    backup = tmp_path / "backup.db"
    config.write_text(f"storage:\n  driver: sqlite\n  path: {database}\n", encoding="utf-8")
    engine = create_storage_engine(storage_config(config))
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE sample (value INTEGER)")
        connection.exec_driver_sql("INSERT INTO sample VALUES (7)")
    engine.dispose()

    command_storage_backup(SimpleNamespace(config=str(config), destination=str(backup)))
    command_storage_restore(SimpleNamespace(config=str(config), backup=str(backup)))

    with create_storage_engine(storage_config(config)).connect() as connection:
        assert connection.exec_driver_sql("SELECT value FROM sample").scalar_one() == 7
