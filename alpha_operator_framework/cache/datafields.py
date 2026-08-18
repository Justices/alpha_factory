"""数据字段缓存 — 获取平台数据字段列表.

目录结构: data/fields/{region}/{delay}/{universe}/{dataset_id}.json
每个数据集存储为单独的 JSON 文件。
"""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from .base import DataCache
from .config import DATAFIELDS_DIR


class DataFieldCache(DataCache):
    """数据字段缓存.

    目录结构: data/fields/{region}/{delay}/{universe}/{dataset_id}.json
    """

    cache_name = "datafields"
    cache_file = DATAFIELDS_DIR / "_all.json"

    def __init__(self):
        super().__init__(DATAFIELDS_DIR)

    def _get_dir(self, region: str, delay: int, universe: str) -> Path:
        """获取字段目录路径."""
        return DATAFIELDS_DIR / region / str(delay) / universe

    def _cache_path(self, region: str, delay: int, universe: str, dataset_id: str = "") -> Path:
        """获取缓存文件路径.

        Args:
            region: 区域
            delay: 延迟
            universe: 股票池
            dataset_id: 数据集ID，为空时返回目录路径

        Returns:
            缓存文件路径
        """
        dir_path = self._get_dir(region, delay, universe)
        if dataset_id:
            return dir_path / f"{dataset_id}.json"
        return dir_path

    def load_dataset(self, region: str, delay: int, universe: str, dataset_id: str) -> Optional[List[Dict[str, Any]]]:
        """加载单个数据集的字段."""
        path = self._cache_path(region, delay, universe, dataset_id)
        if not path.exists():
            return None
        try:
            content = path.read_text(encoding="utf-8-sig")
            if not content.strip():
                return None
            data = json.loads(content)
            return data if isinstance(data, list) else data.get("items", [])
        except (json.JSONDecodeError, ValueError):
            return None

    def save_dataset(self, region: str, delay: int, universe: str, dataset_id: str, items: List[Dict[str, Any]]) -> None:
        """保存单个数据集的字段."""
        path = self._cache_path(region, delay, universe, dataset_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")

    def load_all_datasets(self, region: str, delay: int, universe: str) -> Optional[Dict[str, List[Dict[str, Any]]]]:
        """加载目录下所有数据集."""
        dir_path = self._get_dir(region, delay, universe)
        if not dir_path.exists():
            return None

        result: Dict[str, List[Dict[str, Any]]] = {}
        for path in dir_path.glob("*.json"):
            if path.stem.startswith("_"):
                continue
            try:
                items = json.loads(path.read_text(encoding="utf-8-sig"))
                if isinstance(items, list):
                    result[path.stem] = items
            except (json.JSONDecodeError, ValueError):
                continue

        return result if result else None

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
        """从平台获取数据字段列表 (复用 alpha_machine.fetch_datafields, 自带分页+节流+429退避)."""
        import alpha_machine

        try:
            rows = await alpha_machine.fetch_datafields(
                region, universe, delay,
                dataset_id=dataset_id, search=search, data_type=data_type,
                page_delay=page_delay,
            )
        except Exception:
            # 平台拉取失败 (如 dataset_id 无效返回 400) → 返回空, 由调用方决定降级
            return {"items": [], "count": 0}
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
          3. 平台获取后按数据集分开保存

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
        # 指定数据集时，直接加载/获取该数据集
        if dataset_id:
            if not force_refresh:
                cached = self.load_dataset(region, delay, universe, dataset_id)
                if cached is not None:
                    return cached

            # 从平台获取
            import asyncio
            result = asyncio.run(self.fetch_platform(
                region=region, universe=universe, delay=delay,
                dataset_id=dataset_id, search=search, data_type=data_type,
                page_delay=page_delay
            ))
            items = result.get("items", [])
            if items:
                self.save_dataset(region, delay, universe, dataset_id, items)
            return items

        # 未指定数据集时，检查本地所有数据集
        if not force_refresh:
            all_datasets = self.load_all_datasets(region, delay, universe)
            if all_datasets is not None:
                # 合并所有数据集的字段
                all_fields: List[Dict[str, Any]] = []
                for ds_items in all_datasets.values():
                    all_fields.extend(ds_items)
                return all_fields

        # 从平台获取全量字段
        import asyncio
        result = asyncio.run(self.fetch_platform(
            region=region, universe=universe, delay=delay,
            search=search, data_type=data_type, page_delay=page_delay
        ))
        items = result.get("items", [])

        # 按数据集分组保存
        if items:
            self._save_by_dataset(region, delay, universe, items)

        return items

    async def aget_datafields(
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
        """async 版 get_datafields: 本地缓存优先 → 平台兜底 (供 async 上下文使用).

        与 get_datafields 逻辑一致, 但平台兜底用 await 而非 asyncio.run,
        避免在事件循环内二次 run 报错。

        三条分支的取舍 (本地优先的核心价值 = 避免 data-fields 全量拉取触发 429):
        """
        # 分支1: 指定 dataset_id → 只加载/拉取单个数据集。
        #   精确命中单个 {dataset}.json, 避免为了一个数据集拉全量字段 (限流主因)。
        if dataset_id:
            if not force_refresh:
                cached = self.load_dataset(region, delay, universe, dataset_id)
                if cached is not None:
                    return cached  # 本地命中, 零网络
            result = await self.fetch_platform(
                region=region, universe=universe, delay=delay,
                dataset_id=dataset_id, search=search, data_type=data_type,
                page_delay=page_delay,
            )
            items = result.get("items", [])
            if items:
                self.save_dataset(region, delay, universe, dataset_id, items)  # 拉取即落盘, 下次命中
            return items

        # 分支2: 未指定 dataset_id → 先合并本地所有数据集文件。
        #   本地已有完整缓存 (如 GBR/TOP700) 时一次命中, 完全避开网络。
        if not force_refresh:
            all_datasets = self.load_all_datasets(region, delay, universe)
            if all_datasets is not None:
                all_fields: List[Dict[str, Any]] = []
                for ds_items in all_datasets.values():
                    all_fields.extend(ds_items)
                return all_fields

        # 分支3: 本地全 miss → 平台全量拉取 (带 429 退避), 并按数据集落盘。
        #   落盘后下一次进入分支2, 本地优先命中, 网络只碰这一次。
        result = await self.fetch_platform(
            region=region, universe=universe, delay=delay,
            search=search, data_type=data_type, page_delay=page_delay,
        )
        items = result.get("items", [])
        if items:
            self._save_by_dataset(region, delay, universe, items)
        return items

    def _save_by_dataset(self, region: str, delay: int, universe: str, items: List[Dict[str, Any]]) -> None:
        """按数据集分组保存字段."""
        # 按数据集ID分组
        by_dataset: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for item in items:
            ds = item.get("dataset")
            if isinstance(ds, dict):
                ds_id = ds.get("id", "unknown")
            else:
                ds_id = ds or "unknown"
            by_dataset[ds_id].append(item)

        # 保存每个数据集
        for ds_id, ds_items in by_dataset.items():
            self.save_dataset(region, delay, universe, ds_id, ds_items)

    def get_dataset_ids(self, region: str, delay: int, universe: str) -> List[str]:
        """获取目录下所有数据集ID."""
        dir_path = self._get_dir(region, delay, universe)
        if not dir_path.exists():
            return []
        return [p.stem for p in dir_path.glob("*.json") if not p.stem.startswith("_")]


def get_datafields(
    region: str,
    universe: str = "",
    delay: int = -1,
    dataset_id: str = "",
    search: str = "",
    data_type: str = "",
    force_refresh: bool = False,
    page_delay: float = 0.5,
) -> List[Dict[str, Any]]:
    """获取数据字段列表（便捷函数）.

    自动填充默认值:
      - universe: 区域默认股票池
      - delay: 区域默认延迟

    Args:
        region: 区域 (必填)
        universe: 股票池 (可选，自动填充默认值)
        delay: 延迟 (可选，-1 表示自动填充默认值)
        dataset_id: 数据集ID过滤
        search: 搜索词
        data_type: 字段类型过滤
        force_refresh: 是否强制刷新
        page_delay: 翻页间隔

    Returns:
        数据字段列表
    """
    from alpha_operator_framework.platform.platform_config import get_default_universe, get_default_delay

    if not universe:
        universe = get_default_universe(region)
    if delay < 0:
        delay = get_default_delay(region)

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


async def aget_datafields(
    region: str,
    universe: str = "",
    delay: int = -1,
    dataset_id: str = "",
    search: str = "",
    data_type: str = "",
    force_refresh: bool = False,
    page_delay: float = 0.5,
) -> List[Dict[str, Any]]:
    """async 便捷入口: 本地缓存优先 → 平台兜底 (供 async 上下文使用).

    自动填充 universe/delay 默认值, 与 get_datafields 一致。
    """
    from alpha_operator_framework.platform.platform_config import get_default_universe, get_default_delay

    if not universe:
        universe = get_default_universe(region)
    if delay < 0:
        delay = get_default_delay(region)
    return await DataFieldCache().aget_datafields(
        region=region,
        universe=universe,
        delay=delay,
        dataset_id=dataset_id,
        search=search,
        data_type=data_type,
        force_refresh=force_refresh,
        page_delay=page_delay,
    )


def get_datafields_by_region(region: str, **kwargs) -> List[Dict[str, Any]]:
    """仅指定区域获取数据字段（极简接口）.

    Args:
        region: 区域
        **kwargs: 其他参数传递给 get_datafields

    Returns:
        数据字段列表

    Example:
        >>> fields = get_datafields_by_region("CHN")
        >>> fields = get_datafields_by_region("USA", search="volume")
    """
    return get_datafields(region=region, **kwargs)


def get_dataset_ids(region: str, universe: str = "", delay: int = -1) -> List[str]:
    """获取本地缓存的数据集ID列表.

    Args:
        region: 区域
        universe: 股票池 (可选)
        delay: 延迟 (可选)

    Returns:
        数据集ID列表
    """
    from alpha_operator_framework.platform.platform_config import get_default_universe, get_default_delay

    if not universe:
        universe = get_default_universe(region)
    if delay < 0:
        delay = get_default_delay(region)

    return DataFieldCache().get_dataset_ids(region, delay, universe)


__all__ = ["DataFieldCache", "get_datafields", "aget_datafields", "get_datafields_by_region", "get_dataset_ids"]