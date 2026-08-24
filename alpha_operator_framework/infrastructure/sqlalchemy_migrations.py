"""Portable, versioned schema for the event-led research runtime."""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib

from sqlalchemy import Column, Integer, MetaData, String, Table, Text, inspect, select, text
from sqlalchemy.engine import Engine


metadata = MetaData()

schema_migrations = Table(
    "schema_migrations", metadata,
    Column("version", String(64), primary_key=True),
    Column("applied_at", String(64), nullable=False),
    Column("checksum", String(64), nullable=False),
)
event_log = Table(
    "event_log", metadata,
    Column("global_offset", Integer, primary_key=True, autoincrement=True),
    Column("event_id", String(128), nullable=False, unique=True),
    Column("stream_id", String(128), nullable=False, index=True),
    Column("event_type", String(64), nullable=False, index=True),
    Column("schema_version", Integer, nullable=False),
    Column("payload", Text, nullable=False),
    Column("payload_ref", String(256)),
    Column("occurred_at", String(64), nullable=False),
    Column("actor", String(128), nullable=False),
    Column("metadata", Text, nullable=False),
)
research_round_snapshots = Table(
    "research_round_snapshots", metadata,
    Column("round_id", String(128), primary_key=True),
    Column("payload", Text, nullable=False),
)
experiment_batch_snapshots = Table(
    "experiment_batch_snapshots", metadata,
    Column("batch_id", String(128), primary_key=True),
    Column("payload", Text, nullable=False),
)
knowledge_snapshot = Table(
    "knowledge_snapshot", metadata,
    Column("id", Integer, primary_key=True),
    Column("payload", Text, nullable=False),
)
knowledge_snapshot_history = Table(
    "knowledge_snapshot_history", metadata,
    Column("version", Integer, primary_key=True),
    Column("payload", Text, nullable=False),
    Column("round_id", String(128)),
    Column("policy_version", String(128)),
    Column("created_at", String(64)),
    Column("event_offset", Integer),
)
template_promotions = Table(
    "template_promotions", metadata,
    Column("expression_template", String(768), primary_key=True),
    Column("support", Integer, nullable=False),
    Column("source_task_ids", Text, nullable=False),
)
submission_outbox = Table(
    "submission_outbox", metadata,
    Column("platform_alpha_id", String(128), primary_key=True),
    Column("expression", Text, nullable=False),
    Column("status", String(32), nullable=False),
    Column("attempts", Integer, nullable=False, default=0),
    Column("last_error", Text),
    Column("lease_until", String(64)),
)

def _checksum(version: str) -> str:
    return hashlib.sha256(version.encode("utf-8")).hexdigest()


MIGRATION_VERSIONS = ("001_research_runtime", "002_migration_checksums")


def _apply_runtime_schema(engine: Engine) -> None:
    """The initial, portable schema migration."""
    metadata.create_all(engine)


def _apply_migration_checksums(engine: Engine) -> None:
    """Upgrade databases created before migration checksums were introduced."""
    if "checksum" not in {column["name"] for column in inspect(engine).get_columns("schema_migrations")}:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE schema_migrations ADD COLUMN checksum VARCHAR(64) NOT NULL DEFAULT ''"))
    with engine.begin() as connection:
        for version in MIGRATION_VERSIONS:
            connection.execute(
                text("UPDATE schema_migrations SET checksum = :checksum WHERE version = :version AND checksum = ''"),
                {"version": version, "checksum": _checksum(version)},
            )


def _migration_records(engine: Engine) -> dict[str, str]:
    with engine.connect() as connection:
        return dict(connection.execute(select(schema_migrations.c.version, schema_migrations.c.checksum)).all())


def migrate(engine: Engine) -> None:
    """Apply ordered migrations and reject an altered applied migration."""
    # Bootstrap is deliberately limited to the migration ledger.  All runtime
    # tables are created by the first named migration below.
    schema_migrations.create(engine, checkfirst=True)
    _apply_migration_checksums(engine)
    for version in MIGRATION_VERSIONS:
        if version == "002_migration_checksums":
            _apply_migration_checksums(engine)
        records = _migration_records(engine)
        recorded_checksum = records.get(version)
        expected_checksum = _checksum(version)
        if recorded_checksum is not None:
            if recorded_checksum != expected_checksum:
                raise RuntimeError(f"schema migration checksum mismatch: {version}")
            continue
        if version == "001_research_runtime":
            _apply_runtime_schema(engine)
        with engine.begin() as connection:
            connection.execute(schema_migrations.insert().values(
                version=version,
                applied_at=datetime.now(UTC).isoformat(),
                checksum=expected_checksum,
            ))
