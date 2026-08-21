"""数据缓存模块 — 统一的数据获取入口.

实现本地优先策略:
  1. 先从本地文件加载
  2. 本地无数据则从平台获取
  3. 平台获取后自动保存到本地

支持的数据类型:
  - 金字塔 (Pyramids)
  - Universe（市场/股票池）
  - 数据集和数据字段 (Datasets/DataFields)
  - 操作符 (Operators)

使用示例:
    from alpha_operator_framework.cache import get_datafields

    # 本地优先获取数据字段
    fields = get_datafields("EUR", "TOP2500", delay=1)

    # 强制刷新
    fields = get_datafields("EUR", "TOP2500", delay=1, force_refresh=True)
"""

from .config import (
    PROJECT_ROOT,
    DATA_DIR,
    CACHE_ROOT,
    PYRAMIDS_CACHE,
    UNIVERSES_CACHE,
    DATAFIELDS_DIR,
    OPERATORS_CACHE,
    DEFAULT_TTL,
)
from .base import DataCache
from .pyramids import PyramidCache, get_pyramids
from .universes import UniverseCache, get_universes
from .datafields import DataFieldCache, get_datafields, aget_datafields, get_datafields_by_region, get_dataset_ids
from .operators import OperatorCache, get_operators, get_flat_operators


__all__ = [
    # 配置
    "PROJECT_ROOT",
    "DATA_DIR",
    "CACHE_ROOT",
    "PYRAMIDS_CACHE",
    "UNIVERSES_CACHE",
    "DATAFIELDS_DIR",
    "OPERATORS_CACHE",
    "DEFAULT_TTL",
    # 基类
    "DataCache",
    # 缓存类
    "PyramidCache",
    "UniverseCache",
    "DataFieldCache",
    "OperatorCache",
    # 便捷函数
    "get_pyramids",
    "get_universes",
    "get_datafields",
    "aget_datafields",
    "get_datafields_by_region",
    "get_dataset_ids",
    "get_operators",
    "get_flat_operators",
]