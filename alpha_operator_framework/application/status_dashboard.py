"""Read-only production dashboard use case."""

from __future__ import annotations

from typing import Any


def build_status_dashboard(repository: Any) -> dict[str, Any]:
    """Obtain one repository-owned aggregate for presentation."""
    return repository.dashboard_snapshot()
