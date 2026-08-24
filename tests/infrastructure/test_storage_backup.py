from sqlalchemy import text

from alpha_operator_framework.infrastructure.storage import StorageConfig, create_storage_engine
from alpha_operator_framework.infrastructure.storage_backup import backup_sqlite_storage, restore_sqlite_storage


def test_sqlite_backup_and_restore_are_consistent(tmp_path) -> None:
    source = StorageConfig.from_mapping({"driver": "sqlite", "path": "source.db"}, base_path=tmp_path)
    engine = create_storage_engine(source)
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE sample (value INTEGER)"))
        connection.execute(text("INSERT INTO sample VALUES (7)"))
    backup = tmp_path / "backup.db"

    backup_sqlite_storage(source, backup)
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM sample"))
    restore_sqlite_storage(backup, source)

    with create_storage_engine(source).connect() as connection:
        assert connection.execute(text("SELECT value FROM sample")).scalar_one() == 7
