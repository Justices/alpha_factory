from __future__ import annotations

import pytest

from alpha_operator_framework.platform.platform_simulator import BrainPlatformSimulator


class _SessionManager:
    def hydrate(self, _session) -> None:
        pass


class _Response:
    status_code = 200
    text = "failure"
    headers: dict[str, str] = {}

    def json(self):
        return {"status": "FAILED", "error": {"code": "INVALID_SIMULATION", "message": "expression rejected"}}


class _Session:
    def get(self, _url, timeout: int):
        return _Response()


def test_poll_batch_preserves_platform_failure_details() -> None:
    simulator = BrainPlatformSimulator(session_manager=_SessionManager())
    simulator.session = _Session()
    simulator.ensure_authenticated = lambda: None

    with pytest.raises(RuntimeError, match=r"status=FAILED.*code=INVALID_SIMULATION.*expression rejected"):
        simulator.poll_batch("/simulations/123")
