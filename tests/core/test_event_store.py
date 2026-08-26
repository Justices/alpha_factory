import inspect

import pytest

from alpha_operator_framework.core.event_store import EventStore


def test_event_store_requires_an_injected_repository_for_persistence() -> None:
    assert "db_path" not in inspect.signature(EventStore).parameters
    with pytest.raises(ValueError, match="repository"):
        EventStore(persistent=True)
