"""Universe缓存 — 获取市场股票池列表."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from .base import DataCache
from .config import UNIVERSES_CACHE


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

    async def fetch_raw_platform_options(self) -> dict[str, Any]:
        """Fetch the unmodified response from ``OPTIONS /simulations``."""
        from cnhkmcp.untracked.platform_functions import brain_client

        await brain_client.ensure_authenticated()
        response = brain_client.session.options(f"{brain_client.base_url.rstrip('/')}/simulations")
        response.raise_for_status()
        return response.json()

    def get_raw_platform_options(self, force_refresh: bool = False) -> dict[str, Any]:
        """Return an exact local snapshot of the platform's simulation OPTIONS response."""
        path = self._cache_path("simulations_options")
        if not force_refresh and path.exists():
            try:
                cached = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(cached, dict):
                    return cached
            except (OSError, json.JSONDecodeError):
                pass

        raw_options = asyncio.run(self.fetch_raw_platform_options())
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(raw_options, ensure_ascii=False, indent=2), encoding="utf-8")
        return raw_options

    async def fetch_platform_settings(self) -> dict[str, dict[str, list[str]]]:
        """Fetch the complete EQUITY region/delay/universe mapping from the platform."""
        from cnhkmcp.untracked.platform_functions import brain_client

        options = await brain_client.get_platform_setting_options()
        mapping: dict[str, dict[str, list[str]]] = {}
        for option in options.get("instrument_options", []):
            if option.get("InstrumentType") != "EQUITY":
                continue
            region = str(option.get("Region") or "")
            raw_delay = option.get("Delay")
            delay = str(raw_delay) if raw_delay is not None else ""
            if not region or not delay:
                continue
            universes = mapping.setdefault(region, {}).setdefault(delay, [])
            for universe in option.get("Universe", []):
                value = str(universe or "")
                if value and value not in universes:
                    universes.append(value)
        return mapping

    def get_universe_map(self, force_refresh: bool = False) -> dict[str, dict[str, list[str]]]:
        """Return the cached complete platform Region → Delay → Universe mapping."""
        if not force_refresh:
            cached = self.load_local("settings")
            regions = cached.get("regions") if isinstance(cached, dict) else None
            if isinstance(regions, dict):
                return regions
        self.get_raw_platform_options(force_refresh=force_refresh)
        regions = asyncio.run(self.fetch_platform_settings())
        self.save_local({"regions": regions}, "settings")
        return regions

    async def fetch_platform(self, region: str = "", **kwargs) -> Dict[str, Any]:
        """从平台获取 Universe 列表."""
        settings = await self.fetch_platform_settings()
        seen: set[str] = set()
        universes: list[dict[str, str]] = []
        for scope_region, delays in settings.items():
            if region and scope_region != region:
                continue
            for values in delays.values():
                for value in values:
                    if value not in seen:
                        seen.add(value)
                        universes.append({"id": value})
        return universes

    def get_universes(self, region: str = "", force_refresh: bool = False) -> List[Dict[str, Any]]:
        """获取 Universe 列表.

        Args:
            region: 区域过滤（可选）
            force_refresh: 是否强制刷新

        Returns:
            Universe 列表
        """
        mapping = self.get_universe_map(force_refresh)
        seen: set[str] = set()
        universes: list[dict[str, str]] = []
        for scope_region, delays in mapping.items():
            if region and scope_region != region:
                continue
            for values in delays.values():
                for value in values:
                    if value not in seen:
                        seen.add(value)
                        universes.append({"id": value})
        return universes


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
