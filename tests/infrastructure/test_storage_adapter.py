"""Driver-neutral infrastructure storage tests."""

from pathlib import Path

from alpha_operator_framework.infrastructure.storage import StorageConfig, create_storage_engine
from alpha_operator_framework.database.connection import DatabaseConnectionManager, _Cursor, translate_sql
from alpha_operator_framework.database.repository import AlphaDatabase


def test_storage_engine_selects_sqlite_from_relative_yaml_path(tmp_path: Path) -> None:
    config = StorageConfig.from_mapping({"driver": "sqlite", "path": "research.db"}, base_path=tmp_path)

    engine = create_storage_engine(config)

    assert engine.url.drivername == "sqlite"
    assert Path(engine.url.database) == tmp_path / "research.db"


def test_storage_engine_selects_mysql_without_connecting() -> None:
    config = StorageConfig.from_mapping({"driver": "mysql", "url": "mysql+pymysql://user:pass@db:3306/alpha"})

    engine = create_storage_engine(config)

    assert engine.url.drivername == "mysql+pymysql"
    assert engine.url.database == "alpha"


def test_storage_config_preserves_driver_connect_options() -> None:
    config = StorageConfig.from_mapping({"driver": "mysql", "url": "mysql+pymysql://user:pass@db/alpha", "connect_args": {"ssl": {"ca": "ca.pem"}}})

    assert config.connect_args == {"ssl": {"ca": "ca.pem"}}


def test_legacy_connection_manager_uses_shared_storage_config_without_connecting() -> None:
    manager = DatabaseConnectionManager(StorageConfig("mysql", "mysql+pymysql://user:pass@db/alpha"))

    assert manager.engine.url.drivername == "mysql+pymysql"


def test_legacy_database_accepts_the_shared_sqlite_storage_config(tmp_path: Path) -> None:
    db = AlphaDatabase(StorageConfig.from_mapping({"driver": "sqlite", "path": "legacy.db"}, base_path=tmp_path))
    try:
        assert db.manager.engine.url.database.endswith("legacy.db")
    finally:
        db.close()


def test_database_package_has_no_direct_sqlite_driver_dependency() -> None:
    database_root = Path(__file__).parents[2] / "alpha_operator_framework" / "database"

    assert all("import sqlite3" not in source.read_text(encoding="utf-8") for source in database_root.rglob("*.py"))


def test_legacy_sql_is_translated_at_the_connection_boundary_for_mysql() -> None:
    statement = "INSERT INTO templates (name) VALUES (?) ON CONFLICT(name) DO UPDATE SET name=excluded.name"

    assert translate_sql(statement, "mysql") == "INSERT INTO templates (name) VALUES (%s) ON DUPLICATE KEY UPDATE name=VALUES(name)"


def test_mysql_tuple_rows_are_exposed_as_mapping_rows_to_legacy_repositories() -> None:
    class TupleCursor:
        description = (("id",), ("name",))

        def fetchone(self):
            return (7, "template")

        def fetchall(self):
            return [(8, "next")]

    cursor = _Cursor(TupleCursor(), "mysql")

    assert cursor.fetchone()["name"] == "template"
    assert dict(cursor.fetchall()[0]) == {"id": 8, "name": "next"}
