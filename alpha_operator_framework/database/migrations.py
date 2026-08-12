"""Schema migration discovery for the local SQLite research database."""

from pathlib import Path


SCHEMA_DIR = Path(__file__).with_name("schema")


def migration_files() -> list[Path]:
    """Return versioned schema scripts in execution order."""
    return sorted(SCHEMA_DIR.glob("[0-9][0-9][0-9]_*.sql"))
