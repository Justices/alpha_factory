"""数据缓存基类 — 实现本地优先策略."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import DEFAULT_TTL


class DataCache:
    """数据缓存基类.

    实现本地优先策略:
      1. 先从本地文件加载
      2. 本地无数据则从平台获取
      3. 平台获取后自动保存到本地
    """

    # 子类应覆盖
    cache_name: str = "data"
    cache_file: Path = Path("cache.json")

    def __init__(self, cache_dir: Optional[Path] = None):
        self.cache_dir = cache_dir or self.cache_file.parent
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _cache_path(self, key: str = "") -> Path:
        """获取缓存文件路径."""
        if key:
            return self.cache_dir / f"{key}.json"
        return self.cache_file

    def load_local(self, key: str = "") -> Optional[Dict[str, Any]]:
        """从本地加载缓存.

        Args:
            key: 缓存键（可选）

        Returns:
            缓存数据，不存在返回 None
        """
        path = self._cache_path(key)
        if not path.exists():
            return None

        try:
            content = path.read_text(encoding="utf-8")
            if not content.strip():
                return None
            data = json.loads(content)
            # 检查 TTL
            if DEFAULT_TTL > 0:
                cached_at = data.get("__cached_at__", "")
                if cached_at:
                    elapsed = (datetime.now() - datetime.fromisoformat(cached_at)).total_seconds()
                    if elapsed > DEFAULT_TTL:
                        return None
            return data
        except (json.JSONDecodeError, ValueError):
            return None

    def save_local(self, data: Dict[str, Any], key: str = "") -> None:
        """保存到本地缓存.

        Args:
            data: 要缓存的数据
            key: 缓存键（可选）
        """
        path = self._cache_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)

        # 添加缓存时间戳
        to_save = {**data, "__cached_at__": datetime.now().isoformat()}
        path.write_text(json.dumps(to_save, ensure_ascii=False, indent=2), encoding="utf-8")

    def save_list(self, items: List[Dict[str, Any]], key: str = "") -> None:
        """保存列表数据到本地缓存.

        Args:
            items: 数据列表
            key: 缓存键（可选）
        """
        path = self._cache_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)

        to_save = {
            "items": items,
            "count": len(items),
            "__cached_at__": datetime.now().isoformat(),
        }
        path.write_text(json.dumps(to_save, ensure_ascii=False, indent=2), encoding="utf-8")

    def load_list(self, key: str = "") -> Optional[List[Dict[str, Any]]]:
        """从本地加载列表缓存.

        Args:
            key: 缓存键（可选）

        Returns:
            数据列表，不存在返回 None
        """
        data = self.load_local(key)
        if data is None:
            return None
        return data.get("items", data) if isinstance(data, dict) else data

    async def fetch_platform(self, *args, **kwargs) -> Any:
        """从平台获取数据（子类实现）.

        Raises:
            NotImplementedError: 子类必须实现
        """
        raise NotImplementedError(f"{self.__class__.__name__}.fetch_platform() 未实现")

    def get(self, key: str = "", force_refresh: bool = False, **kwargs) -> Any:
        """获取数据：本地优先，平台兜底.

        Args:
            key: 缓存键
            force_refresh: 是否强制刷新
            **kwargs: 传递给 fetch_platform 的参数

        Returns:
            缓存或平台数据
        """
        import asyncio

        if not force_refresh:
            cached = self.load_local(key)
            if cached is not None:
                return cached

        # 平台获取
        data = asyncio.run(self.fetch_platform(**kwargs))
        if data is not None:
            self.save_local(data, key)
        return data

    def get_list(self, key: str = "", force_refresh: bool = False, **kwargs) -> List[Dict[str, Any]]:
        """获取列表数据：本地优先，平台兜底."""
        import asyncio

        if not force_refresh:
            cached = self.load_list(key)
            if cached is not None:
                return cached

        data = asyncio.run(self.fetch_platform(**kwargs))
        if data is not None:
            if isinstance(data, list):
                self.save_list(data, key)
                return data
            if isinstance(data, dict) and "items" in data:
                items = data["items"]
                self.save_list(items, key)
                return items
        return []


__all__ = ["DataCache"]