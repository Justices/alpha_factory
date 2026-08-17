"""Universe缓存 — 获取市场股票池列表."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from .base import DataCache
from .config import CACHE_ROOT, UNIVERSES_CACHE


class UniverseCache(DataCache):
    """Universe缓存.

    Universe 是 WorldQuant Brain 平台的股票池定义，
    如 TOP200, TOP500, TOP2500 等。
    """

    cache_name = "universes"
    cache_file = UNIVERSES_CACHE / "all.json"

    def __init__(self, region: str = ""):
        self.region = region
        if region:
            cache_dir = UNIVERSES_CACHE
        else:
            cache_dir = UNIVERSES_CACHE
        super().__init__(cache_dir)

    def _cache_path(self, key: str = "") -> Path:
        """获取缓存文件路径."""
        if key:
            return UNIVERSES_CACHE / f"{key}.json"
        return self.cache_file

    async def fetch_platform(self, region: str = "", **kwargs) -> Dict[str, Any]:
        """从平台获取 Universe 列表."""
        from cnhkmcp.untracked.platform_functions import brain_client

        await brain_client.ensure_authenticated()
        params = {"instrumentType": "EQUITY"}
        if region:
            params["region"] = region

        response = brain_client.session.get(
            f"{brain_client.base_url}/universes",
            params=params
        )
        response.raise_for_status()
        return response.json()

    def get_universes(self, region: str = "", force_refresh: bool = False) -> List[Dict[str, Any]]:
        """获取 Universe 列表.

        Args:
            region: 区域过滤（可选）
            force_refresh: 是否强制刷新

        Returns:
            Universe 列表
        """
        key = region if region else "all"
        return self.get_list(key=key, force_refresh=force_refresh, region=region)


def get_universes(region: str = "", force_refresh: bool = False) -> List[Dict[str, Any]]:
    """获取 Universe 列表（便捷函数）.

    Args:
        region: 区域过滤（可选）
        force_refresh: 是否强制刷新

    Returns:
        Universe 列表
    """
    return UniverseCache().get_universes(region, force_refresh)


__all__ = ["UniverseCache", "get_universes"]