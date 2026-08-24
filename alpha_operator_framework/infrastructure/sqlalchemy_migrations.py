"""Portable, versioned schema for the event-led research runtime."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Column, Integer, MetaData, String, Table, Text, select
from sqlalchemy.engine import Engine


metadata = MetaData()

schema_migrations = Table(
    "schema_migrations", metadata,
    Column("version", String(64), primary_key=True),
    Column("applied_at", String(64), nullable=False),
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

RUNTIME_SCHEMA_VERSION = "001_research_runtime"


def migrate(engine: Engine) -> None:
    """Apply the portable runtime schema exactly once per database."""
    metadata.create_all(engine)
    with engine.begin() as connection:
        exists = connection.execute(
            select(schema_migrations.c.version).where(schema_migrations.c.version == RUNTIME_SCHEMA_VERSION)
        ).scalar_one_or_none()
        if exists is None:
            connection.execute(schema_migrations.insert().values(
                version=RUNTIME_SCHEMA_VERSION,
                applied_at=datetime.now(UTC).isoformat(),
            ))
