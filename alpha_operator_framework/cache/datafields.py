"""数据字段缓存 — 获取平台数据字段列表.

复用现有 data/fields/{region}/{delay}/{universe}/ 目录结构。
每个数据集存储为 {dataset_id}.json 文件。
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from .base import DataCache
from .config import DATAFIELDS_DIR


class DataFieldCache(DataCache):
    """数据字段缓存.

    目录结构: data/fields/{region}/{delay}/{universe}/{dataset_id}.json
    全量字段: data/fields/{region}/{delay}/{universe}/_all.json
    """

    cache_name = "datafields"
    cache_file = DATAFIELDS_DIR / "_all.json"

    def __init__(self):
        super().__init__(DATAFIELDS_DIR)

    def _get_dir(self, region: str, delay: int, universe: str) -> Path:
        """获取字段目录路径."""
        return DATAFIELDS_DIR / region / str(delay) / universe

    def _cache_path(self, key: str = "") -> Path:
        """获取缓存文件路径.

        key 格式: {region}/{delay}/{universe} 或 {region}/{delay}/{universe}/{dataset_id}
        """
        if not key:
            return self.cache_file
        return DATAFIELDS_DIR / f"{key}.json"

    def load_local(self, key: str = "") -> Optional[Dict[str, Any]]:
        """从本地加载缓存.

        Args:
            key: 缓存键，格式为 {region}/{delay}/{universe} 或 {region}/{delay}/{universe}/{dataset_id}

        Returns:
            缓存数据，不存在返回 None
        """
        path = self._cache_path(key)
        if not path.exists():
            return None

        try:
            # 支持 UTF-8 BOM (Windows 导出常见)
            content = path.read_text(encoding="utf-8-sig")
            if not content.strip():
                return None
            data = json.loads(content)
            # 支持两种格式: 列表 或 {"items": [...], "count": N}
            if isinstance(data, list):
                return {"items": data, "count": len(data)}
            return data
        except (json.JSONDecodeError, ValueError):
            return None

    def load_list(self, key: str = "") -> Optional[List[Dict[str, Any]]]:
        """从本地加载列表缓存."""
        data = self.load_local(key)
        if data is None:
            return None
        return data.get("items", data) if isinstance(data, dict) else data

    def save_local(self, data: Dict[str, Any], key: str = "") -> None:
        """保存到本地缓存."""
        path = self._cache_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def save_list(self, items: List[Dict[str, Any]], key: str = "") -> None:
        """保存列表数据到本地缓存."""
        path = self._cache_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        # 直接保存列表，与现有格式兼容
        path.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")

    async def fetch_platform(
        self,
        region: str = "",
        universe: str = "",
        delay: int = 1,
        dataset_id: str = "",
        search: str = "",
        data_type: str = "",
        page_delay: float = 0.5,
        **kwargs
    ) -> Dict[str, Any]:
        """从平台获取数据字段列表."""
        from cnhkmcp.untracked.platform_functions import brain_client

        await brain_client.ensure_authenticated()
        params: Dict[str, str] = {
            "instrumentType": "EQUITY",
            "region": region,
            "universe": universe,
            "delay": str(delay),
            "limit": "50",
            "offset": "0",
        }
        if dataset_id:
            params["dataset.id"] = dataset_id
        if search:
            params["search"] = search
        if data_type:
            params["type"] = data_type.upper()

        rows: List[Dict[str, Any]] = []
        total: Optional[int] = None
        page_count = 0

        while total is None or len(rows) < total:
            if page_count > 0 and page_delay > 0:
                await asyncio.sleep(page_delay)
            params["offset"] = str(len(rows))
            response = brain_client.session.get(
                f"{brain_client.base_url}/data-fields",
                params=params
            )
            response.raise_for_status()
            payload = response.json()
            total = int(payload.get("count") or 0)
            page = payload.get("results") or []
            if not page:
                break
            rows.extend(page)
            page_count += 1

        return {"items": rows, "count": len(rows)}

    def get_datafields(
        self,
        region: str,
        universe: str,
        delay: int = 1,
        dataset_id: str = "",
        search: str = "",
        data_type: str = "",
        force_refresh: bool = False,
        page_delay: float = 0.5,
    ) -> List[Dict[str, Any]]:
        """获取数据字段列表.

        本地优先策略:
          1. 从 data/fields/{region}/{delay}/{universe}/{dataset_id}.json 加载
          2. 不存在则从平台获取
          3. 平台获取后保存到本地

        Args:
            region: 区域
            universe: 股票池
            delay: 延迟
            dataset_id: 数据集ID过滤
            search: 搜索词
            data_type: 字段类型过滤
            force_refresh: 是否强制刷新
            page_delay: 翻页间隔

        Returns:
            数据字段列表
        """
        # 构建缓存键
        key = f"{region}/{delay}/{universe}"
        if dataset_id:
            key += f"/{dataset_id}"

        return self.get_list(
            key=key,
            force_refresh=force_refresh,
            region=region,
            universe=universe,
            delay=delay,
            dataset_id=dataset_id,
            search=search,
            data_type=data_type,
            page_delay=page_delay,
        )

    def get_all_datasets(self, region: str, universe: str, delay: int = 1) -> Dict[str, List[Dict]]:
        """获取指定目录下所有数据集的字段.

        Args:
            region: 区域
            universe: 股票池
            delay: 延迟

        Returns:
            按数据集ID分组的字段字典
        """
        dir_path = self._get_dir(region, delay, universe)
        if not dir_path.exists():
            return {}

        result: Dict[str, List[Dict]] = {}
        for path in dir_path.glob("*.json"):
            if path.stem.startswith("_"):
                continue
            try:
                items = json.loads(path.read_text(encoding="utf-8-sig"))
                if isinstance(items, list):
                    result[path.stem] = items
            except (json.JSONDecodeError, ValueError):
                continue

        return result


def get_datafields(
    region: str,
    universe: str,
    delay: int = 1,
    dataset_id: str = "",
    search: str = "",
    data_type: str = "",
    force_refresh: bool = False,
    page_delay: float = 0.5,
) -> List[Dict[str, Any]]:
    """获取数据字段列表（便捷函数）.

    Args:
        region: 区域
        universe: 股票池
        delay: 延迟
        dataset_id: 数据集ID过滤
        search: 搜索词
        data_type: 字段类型过滤
        force_refresh: 是否强制刷新
        page_delay: 翻页间隔

    Returns:
        数据字段列表
    """
    return DataFieldCache().get_datafields(
        region=region,
        universe=universe,
        delay=delay,
        dataset_id=dataset_id,
        search=search,
        data_type=data_type,
        force_refresh=force_refresh,
        page_delay=page_delay,
    )


__all__ = ["DataFieldCache", "get_datafields"]