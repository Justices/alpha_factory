"""Portable schema migration tests for the research runtime."""

from sqlalchemy import create_mock_engine, inspect

from alpha_operator_framework.infrastructure.sqlalchemy_migrations import migrate
from alpha_operator_framework.infrastructure.storage import StorageConfig, create_storage_engine


def test_migrate_creates_portable_research_tables(tmp_path) -> None:
    engine = create_storage_engine(StorageConfig.from_mapping({"driver": "sqlite", "path": "research.db"}, base_path=tmp_path))

    migrate(engine)

    tables = set(inspect(engine).get_table_names())
    assert {"schema_migrations", "event_log", "research_round_snapshots", "experiment_batch_snapshots", "knowledge_snapshot"} <= tables


def test_migrate_is_idempotent(tmp_path) -> None:
    engine = create_storage_engine(StorageConfig.from_mapping({"driver": "sqlite", "path": "research.db"}, base_path=tmp_path))

    migrate(engine)
    migrate(engine)

    with engine.connect() as connection:
        assert connection.exec_driver_sql("SELECT COUNT(*) FROM schema_migrations").scalar_one() == 1
        assert connection.exec_driver_sql("SELECT checksum FROM schema_migrations").scalar_one()


def test_portable_schema_compiles_for_virtual_mysql() -> None:
    statements = []
    engine = create_mock_engine("mysql+pymysql://user:pass@db/alpha", lambda sql, *_: statements.append(str(sql.compile(dialect=engine.dialect))))

    from alpha_operator_framework.infrastructure.sqlalchemy_migrations import metadata
    metadata.create_all(engine)

    assert any("CREATE TABLE event_log" in statement for statement in statements)
    assert not any("PRAGMA" in statement or "AUTOINCREMENT" in statement for statement in statements)


def test_legacy_schema_compiles_for_virtual_mysql() -> None:
    statements = []
    engine = create_mock_engine("mysql+pymysql://user:pass@db/alpha", lambda sql, *_: statements.append(str(sql.compile(dialect=engine.dialect))))

    from alpha_operator_framework.database.schema import metadata
    metadata.create_all(engine)

    assert any("CREATE TABLE alpha_details" in statement for statement in statements)
    assert not any("PRAGMA" in statement or "AUTOINCREMENT" in statement for statement in statements)
