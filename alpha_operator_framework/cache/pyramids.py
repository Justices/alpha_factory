"""金字塔缓存 — 获取 WorldQuant Brain 平台金字塔列表."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .base import DataCache
from .config import CACHE_ROOT


class PyramidCache(DataCache):
    """金字塔缓存.

    金字塔是 WorldQuant Brain 平台的多因子组合产品，
    用于提交 alpha 时选择合适的金字塔。
    """

    cache_name = "pyramids"
    cache_file = CACHE_ROOT / "pyramids.json"

    async def fetch_platform(self, **kwargs) -> Dict[str, Any]:
        """从平台获取金字塔列表."""
        from cnhkmcp.untracked.platform_functions import brain_client

        await brain_client.ensure_authenticated()
        response = brain_client.session.get(
            f"{brain_client.base_url}/pyramids",
            params={"instrumentType": "EQUITY"}
        )
        response.raise_for_status()
        return response.json()

    def get_pyramids(self, force_refresh: bool = False) -> List[Dict[str, Any]]:
        """获取金字塔列表.

        Args:
            force_refresh: 是否强制刷新

        Returns:
            金字塔列表
        """
        return self.get_list(force_refresh=force_refresh)


def get_pyramids(force_refresh: bool = False) -> List[Dict[str, Any]]:
    """获取金字塔列表（便捷函数）.

    Args:
        force_refresh: 是否强制刷新

    Returns:
        金字塔列表
    """
    return PyramidCache().get_pyramids(force_refresh)


__all__ = ["PyramidCache", "get_pyramids"]