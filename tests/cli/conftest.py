"""Shared fixtures for CLI tests.

Registers a lightweight stub for the vendor ``cnhkmcp.untracked.platform_functions``
module so that tests in this package can import ``alpha_machine`` and exercise the
compatibility facade without requiring the proprietary vendor SDK.
"""

from __future__ import annotations

import sys
import types


def _make_platform_functions_stub() -> types.ModuleType:
    """Return a minimal stub that satisfies alpha_machine's compatibility facade."""
    stub = types.ModuleType("cnhkmcp.untracked.platform_functions")

    async def get_user_alphas(*args, **kwargs):  # noqa: D401
        """Stub – returns empty list in test environment."""
        return []

    async def get_alpha_details(*args, **kwargs):  # noqa: D401
        """Stub – returns None in test environment."""
        return None

    stub.get_user_alphas = get_user_alphas
    stub.get_alpha_details = get_alpha_details
    return stub


# Pre-inject before any module-level import can trigger the real shim.
if "cnhkmcp.untracked.platform_functions" not in sys.modules:
    sys.modules["cnhkmcp.untracked.platform_functions"] = _make_platform_functions_stub()
