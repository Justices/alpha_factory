"""Portable, versioned schema for the event-led research runtime."""

from __future__ import annotations

from sqlalchemy import Column, Integer, MetaData, String, Table, Text
from sqlalchemy.engine import Engine


metadata = MetaData()

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
knowledge_snapshot = Table(
    "knowledge_snapshot", metadata,
    Column("id", Integer, primary_key=True),
    Column("payload", Text, nullable=False),
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
research_round_snapshot = Table(
    "research_round_snapshot", metadata,
    Column("round_id", String(128), primary_key=True),
    Column("payload", Text, nullable=False),
    Column("status", String(32), nullable=False),
    Column("error", Text),
)
experiment_batch_snapshot = Table(
    "experiment_batch_snapshot", metadata,
    Column("batch_id", String(128), primary_key=True),
    Column("payload", Text, nullable=False),
    Column("status", String(32), nullable=False),
    Column("error", Text),
)

def migrate(engine: Engine) -> None:
    """Create the compact event runtime schema for a fresh validation database."""
    metadata.create_all(engine)
