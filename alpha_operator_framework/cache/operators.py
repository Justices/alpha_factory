"""操作符缓存 — 获取平台支持的操作符列表."""

from __future__ import annotations

from typing import Any, Dict, List

from .base import DataCache
from .config import OPERATORS_CACHE


# 硬编码常用操作符（平台 API 可能不提供完整列表）
DEFAULT_OPERATORS = {
    # 时序算子
    "ts": [
        "ts_rank", "ts_zscore", "ts_delta", "ts_mean", "ts_std_dev",
        "ts_sum", "ts_delay", "ts_max", "ts_min", "ts_arg_max",
        "ts_arg_min", "ts_corr", "ts_covariance", "ts_scale", "ts_decay_linear",
        "ts_product", "ts_av_diff", "ts_regression", "ts_step",
    ],
    # 横截面算子
    "cross_sectional": [
        "rank", "zscore", "scale", "normalize", "quantile",
        "winsorize", "outlier", "sigmoid", "log", "abs",
        "sign", "power", "sqrt", "inverse", "fraction",
    ],
    # 分组算子
    "group": [
        "group_rank", "group_zscore", "group_neutralize", "group_mean",
        "group_sum", "group_count", "group_std_dev",
    ],
    # 向量算子
    "vector": [
        "vec_avg", "vec_sum", "vec_min", "vec_max", "vec_count",
        "vec_stddev", "vec_range",
    ],
    # 逻辑算子
    "logical": [
        "if_else", "max", "min", "clamp", "nan_mask",
    ],
    # 回填/填充
    "fill": [
        "ts_backfill", "densify", "bucket",
    ],
}


class OperatorCache(DataCache):
    """操作符缓存.

    操作符列表可能从平台获取，也可能使用硬编码默认值。
    """

    cache_name = "operators"
    cache_file = OPERATORS_CACHE

    async def fetch_platform(self, **kwargs) -> Dict[str, Any]:
        """从平台获取操作符列表.

        注意: Brain 平台可能不提供操作符 API，此时使用硬编码默认值。
        """
        from cnhkmcp.untracked.platform_functions import brain_client

        await brain_client.ensure_authenticated()
        try:
            response = brain_client.session.get(
                f"{brain_client.base_url}/operators"
            )
            response.raise_for_status()
            return response.json()
        except Exception:
            # 平台不支持时返回硬编码列表
            return DEFAULT_OPERATORS

    def get_operators(self, force_refresh: bool = False) -> Dict[str, List[str]]:
        """获取操作符列表.

        Args:
            force_refresh: 是否强制刷新

        Returns:
            按类别分组的操作符字典
        """
        data = self.get(force_refresh=force_refresh)
        if isinstance(data, dict):
            if "items" in data:
                return data["items"]
            return data
        return DEFAULT_OPERATORS

    def get_flat_operators(self, force_refresh: bool = False) -> List[str]:
        """获取扁平化的操作符列表.

        Args:
            force_refresh: 是否强制刷新

        Returns:
            操作符名称列表
        """
        ops_dict = self.get_operators(force_refresh)
        flat: List[str] = []
        for category, ops in ops_dict.items():
            if isinstance(ops, list):
                flat.extend(ops)
        return sorted(set(flat))


def get_operators(force_refresh: bool = False) -> Dict[str, List[str]]:
    """获取操作符列表（便捷函数）.

    Args:
        force_refresh: 是否强制刷新

    Returns:
        按类别分组的操作符字典
    """
    return OperatorCache().get_operators(force_refresh)


def get_flat_operators(force_refresh: bool = False) -> List[str]:
    """获取扁平化的操作符列表（便捷函数）.

    Args:
        force_refresh: 是否强制刷新

    Returns:
        操作符名称列表
    """
    return OperatorCache().get_flat_operators(force_refresh)


__all__ = ["OperatorCache", "get_operators", "get_flat_operators", "DEFAULT_OPERATORS"]