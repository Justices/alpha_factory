"""Portable schema migration tests for the research runtime."""

import pytest
from sqlalchemy import create_mock_engine, inspect

from alpha_operator_framework.infrastructure.sqlalchemy_migrations import MIGRATION_VERSIONS, _checksum, migrate
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
        assert connection.exec_driver_sql("SELECT COUNT(*) FROM schema_migrations").scalar_one() == len(MIGRATION_VERSIONS)
        assert connection.exec_driver_sql("SELECT COUNT(*) FROM schema_migrations WHERE checksum = ''").scalar_one() == 0


def test_migrate_upgrades_legacy_knowledge_history_columns(tmp_path) -> None:
    """A database created before snapshot provenance still accepts runtime saves."""
    engine = create_storage_engine(StorageConfig.from_mapping({"driver": "sqlite", "path": "research.db"}, base_path=tmp_path))
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE schema_migrations (version VARCHAR(64) PRIMARY KEY, applied_at VARCHAR(64) NOT NULL, checksum VARCHAR(64) NOT NULL)")
        for version in ("001_research_runtime", "002_migration_checksums"):
            connection.exec_driver_sql("INSERT INTO schema_migrations VALUES (?, ?, ?)", (version, "now", _checksum(version)))
        connection.exec_driver_sql("CREATE TABLE knowledge_snapshot_history (version INTEGER PRIMARY KEY, payload TEXT NOT NULL)")

    migrate(engine)

    assert {"round_id", "policy_version", "created_at", "event_offset"} <= {
        column["name"] for column in inspect(engine).get_columns("knowledge_snapshot_history")
    }


def test_migrate_rejects_a_recorded_checksum_that_does_not_match(tmp_path) -> None:
    engine = create_storage_engine(StorageConfig.from_mapping({"driver": "sqlite", "path": "research.db"}, base_path=tmp_path))
    migrate(engine)
    with engine.begin() as connection:
        connection.exec_driver_sql("UPDATE schema_migrations SET checksum = 'tampered' WHERE version = '001_research_runtime'")

    with pytest.raises(RuntimeError, match="checksum mismatch"):
        migrate(engine)


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
