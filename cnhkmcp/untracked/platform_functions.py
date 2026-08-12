"""Compatibility shim for the vendor platform functions in the active Python environment."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from cnhkmcp.session_manager import make_managed_client


def _load_real_module():
    """Load the vendor module installed alongside the Python interpreter in use."""
    shim_path = Path(__file__).resolve()
    candidate_paths = [
        Path(entry) / "cnhkmcp" / "untracked" / "platform_functions.py"
        for entry in sys.path
        if entry
    ]
    for path in candidate_paths:
        if path.resolve() == shim_path or not path.is_file():
            continue
        spec = importlib.util.spec_from_file_location("_cnhkmcp_real_platform_functions", path)
        if spec and spec.loader:
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module

    checked = ", ".join(str(path) for path in candidate_paths)
    raise ImportError(
        "cannot locate vendor cnhkmcp.untracked.platform_functions in the active Python environment; "
        f"checked: {checked}"
    )


_real = _load_real_module()

_VendorBrainApiClient = _real.BrainApiClient
brain_client = make_managed_client(_VendorBrainApiClient)
BrainApiClient = type(brain_client)
_real.brain_client = brain_client


def _load_config_with_direct_credentials():
    """Accept the workspace's flat ``.brain.json`` shape in vendor MCP tools."""
    config = _vendor_load_config()
    if config.get("email") and config.get("password") and not config.get("credentials"):
        config = dict(config)
        config["credentials"] = {"email": config["email"], "password": config["password"]}
    return config


_vendor_load_config = _real.load_config
_real.load_config = _load_config_with_direct_credentials


async def authenticate(email: str | None = None, password: str | None = None):
    """Compatibility entry point backed by the shared client."""
    return await brain_client.authenticate(email, password)


create_multi_simulation = _real.create_multi_simulation


def __getattr__(name: str):
    """Keep vendor models and functions import-compatible for scripts."""
    return getattr(_real, name)
