"""Pure models for comparing quality-tool snapshots."""

from .ratchet import (
    SCHEMA_VERSION,
    BaselineError,
    ComparisonResult,
    Issue,
    compare,
    fingerprint,
)

__all__ = [
    "SCHEMA_VERSION",
    "BaselineError",
    "ComparisonResult",
    "Issue",
    "compare",
    "fingerprint",
]
