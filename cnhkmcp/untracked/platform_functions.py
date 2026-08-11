"""Shim that re-exports functions from the installed cnhkmcp package file.

The installed package's top-level __init__ may have stale imports, but the
underlying platform_functions module still contains the required coroutine
implementations. This shim loads that file directly to avoid package import
failures.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from cnhkmcp.session_manager import make_managed_client


def _load_real_module():
    workspace_root = Path(__file__).resolve().parents[2]
    candidate_paths = [
        # 优先: 复用 quant 工作区 venv 里的真实平台函数 (迁移来源)
        Path("/Users/liujiaping/ai/quant/.venv/lib/python3.13/site-packages/cnhkmcp/untracked/platform_functions.py"),
        # 其次: 本工作区若有 venv 且装了同款 cnhkmcp 则可用
        workspace_root / ".venv/lib/python3.13/site-packages/cnhkmcp/untracked/platform_functions.py",
        # 兜底: ai-worker 工作区 (历史来源)
        Path("/Users/liujiaping/ai/ai-worker/.venv/lib/python3.13/site-packages/cnhkmcp/untracked/platform_functions.py"),
        Path("/Users/liujiaping/ai/ai-worker/.venv/lib/python3.13/site-packages/cnhkmcp/untracked/platform_functions.pyc"),
    ]
    for path in candidate_paths:
        if path.exists() and path.suffix == ".py":
            spec = importlib.util.spec_from_file_location("_cnhkmcp_real_platform_functions", path)
            if spec and spec.loader:
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                return module
    raise ImportError("cannot locate real cnhkmcp.untracked.platform_functions module")


_real = _load_real_module()

_VendorBrainApiClient = _real.BrainApiClient
# Vendor functions and MCP tools resolve this variable from their own module
# globals, so replacing it covers the whole imported vendor surface.
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
