"""WorldQuant Brain 平台配置.

从 simulations OPTIONS 接口解析，包含:
- 各区域 (region) 支持的 universe
- 各区域支持的 delay
- 各区域支持的 neutralization
- 其他回测参数配置
"""

from __future__ import annotations

from typing import Dict, List


# ============================================================================
# 区域配置
# ============================================================================

# 所有支持的区域
REGIONS = ["USA", "GLB", "EUR", "ASI", "CHN", "KOR", "HKG", "IND", "MEA", "DEU", "GBR"]


# ============================================================================
# Universe 配置 - 各区域支持的股票池
# ============================================================================

UNIVERSES: Dict[str, List[str]] = {
    "USA": ["TOP3000", "TOP2000", "TOP1000", "TOP500", "TOP200", "ILLIQUID_MINVOL1M", "TOPSP500"],
    "GLB": ["TOP3000", "MINVOL1M", "MINVOL10M", "TOPDIV3000"],
    "EUR": ["TOP2500", "TOP1200", "TOP800", "TOP400", "ILLIQUID_MINVOL1M", "TOPCS1600"],
    "ASI": ["MINVOL1M", "MINVOL10M", "ILLIQUID_MINVOL1M", "TOP500"],
    "CHN": ["TOP2000U"],  # 注意: CHN 使用 TOP2000U (带 U 后缀)
    "KOR": ["TOP600"],
    "HKG": ["TOP800", "TOP500"],
    "IND": ["TOP500"],
    "MEA": ["TOP400", "TOP300"],
    "DEU": ["TOP500"],
    "GBR": ["TOP700"],
}


# ============================================================================
# Delay 配置 - 各区域支持的延迟
# ============================================================================

DELAYS: Dict[str, List[int]] = {
    "USA": [1, 0],      # 支持 0 和 1
    "GLB": [1],         # 仅支持 1
    "EUR": [1, 0],
    "ASI": [1],
    "CHN": [0, 1],      # 支持 0 和 1
    "KOR": [1],
    "HKG": [1],
    "IND": [1],
    "MEA": [1],
    "DEU": [1, 0],
    "GBR": [1, 0],
}


# ============================================================================
# Neutralization 配置 - 各区域支持的中性化方式
# ============================================================================

# 通用中性化选项 (大多数区域)
NEUTRALIZATION_COMMON = [
    "NONE",                    # 无
    "REVERSION_AND_MOMENTUM",  # RAM
    "STATISTICAL",             # Statistical
    "CROWDING",                # Crowding Factors
    "FAST",                    # Fast Factors
    "SLOW",                    # Slow Factors
    "MARKET",                  # Market
    "SECTOR",                  # Sector
    "INDUSTRY",                # Industry
    "SUBINDUSTRY",             # Subindustry
    "SLOW_AND_FAST",           # Slow + Fast Factors
]

# GLB/EUR/ASI 额外支持 COUNTRY
NEUTRALIZATION_WITH_COUNTRY = NEUTRALIZATION_COMMON + ["COUNTRY"]

# MEA 区域支持有限
NEUTRALIZATION_MEA = [
    "NONE",
    "MARKET",
    "SECTOR",
    "INDUSTRY",
    "SUBINDUSTRY",
    "COUNTRY",
]

# 各区域中性化配置
NEUTRALIZATIONS: Dict[str, List[str]] = {
    "USA": NEUTRALIZATION_COMMON,
    "GLB": NEUTRALIZATION_WITH_COUNTRY,
    "EUR": NEUTRALIZATION_WITH_COUNTRY,
    "ASI": NEUTRALIZATION_WITH_COUNTRY,
    "CHN": NEUTRALIZATION_COMMON,
    "KOR": NEUTRALIZATION_COMMON,
    "HKG": NEUTRALIZATION_COMMON,
    "IND": NEUTRALIZATION_COMMON,
    "MEA": NEUTRALIZATION_MEA,
    "DEU": NEUTRALIZATION_COMMON,
    "GBR": NEUTRALIZATION_COMMON,
}


# ============================================================================
# 其他回测参数
# ============================================================================

# Decay 范围
DECAY_MIN = 0
DECAY_MAX = 512

# Truncation 范围
TRUNCATION_MIN = 0.0
TRUNCATION_MAX = 1.0

# Lookback 范围
LOOKBACK_MIN = 0
LOOKBACK_MAX = 1024

# Pasteurization 选项
PASTEURIZATION_OPTIONS = ["ON", "OFF"]

# UnitHandling 选项
UNIT_HANDLING_OPTIONS = ["VERIFY"]

# NaN Handling 选项
NAN_HANDLING_OPTIONS = ["ON", "OFF"]

# Selection Handling 选项
SELECTION_HANDLING_OPTIONS = ["POSITIVE", "NON_ZERO", "NON_NAN"]

# Selection Limit 范围
SELECTION_LIMIT_MIN = 10
SELECTION_LIMIT_MAX = 1000

# Language 选项
LANGUAGE_OPTIONS = ["PYTHON", "FASTEXPR"]

# Alpha Type 选项
ALPHA_TYPES = ["REGULAR", "SUPER"]


# ============================================================================
# 便捷函数
# ============================================================================

def get_default_universe(region: str) -> str:
    """获取区域默认 universe."""
    universes = UNIVERSES.get(region, [])
    return universes[0] if universes else ""


def get_default_delay(region: str) -> int:
    """获取区域默认 delay."""
    delays = DELAYS.get(region, [])
    return delays[0] if delays else 1


def get_default_neutralization(region: str) -> str:
    """获取区域默认 neutralization."""
    neuts = NEUTRALIZATIONS.get(region, [])
    return neuts[0] if neuts else "NONE"


def validate_settings(region: str, universe: str, delay: int, neutralization: str = "") -> bool:
    """验证回测参数是否有效."""
    if region not in REGIONS:
        return False
    if universe not in UNIVERSES.get(region, []):
        return False
    if delay not in DELAYS.get(region, []):
        return False
    if neutralization and neutralization not in NEUTRALIZATIONS.get(region, []):
        return False
    return True


def get_region_info(region: str) -> dict:
    """获取区域完整配置."""
    return {
        "region": region,
        "universes": UNIVERSES.get(region, []),
        "delays": DELAYS.get(region, []),
        "neutralizations": NEUTRALIZATIONS.get(region, []),
        "default_universe": get_default_universe(region),
        "default_delay": get_default_delay(region),
        "default_neutralization": get_default_neutralization(region),
    }


__all__ = [
    # 区域列表
    "REGIONS",
    # 配置字典
    "UNIVERSES",
    "DELAYS",
    "NEUTRALIZATIONS",
    # 参数范围
    "DECAY_MIN",
    "DECAY_MAX",
    "TRUNCATION_MIN",
    "TRUNCATION_MAX",
    "LOOKBACK_MIN",
    "LOOKBACK_MAX",
    "SELECTION_LIMIT_MIN",
    "SELECTION_LIMIT_MAX",
    # 选项列表
    "PASTEURIZATION_OPTIONS",
    "UNIT_HANDLING_OPTIONS",
    "NAN_HANDLING_OPTIONS",
    "SELECTION_HANDLING_OPTIONS",
    "LANGUAGE_OPTIONS",
    "ALPHA_TYPES",
    # 便捷函数
    "get_default_universe",
    "get_default_delay",
    "get_default_neutralization",
    "validate_settings",
    "get_region_info",
]