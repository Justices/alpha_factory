# WorldQuant Brain 平台配置

从 simulations OPTIONS 接口解析的完整配置。

## 区域汇总

| 区域 | Universe | Delay | Neutralization 数量 |
|------|----------|-------|---------------------|
| USA | TOP3000, TOP2000, TOP1000, TOP500, TOP200, ILLIQUID_MINVOL1M, TOPSP500 | 0, 1 | 11 |
| GLB | TOP3000, MINVOL1M, MINVOL10M, TOPDIV3000 | 1 | 12 (含 COUNTRY) |
| EUR | TOP2500, TOP1200, TOP800, TOP400, ILLIQUID_MINVOL1M, TOPCS1600 | 0, 1 | 12 (含 COUNTRY) |
| ASI | MINVOL1M, MINVOL10M, ILLIQUID_MINVOL1M, TOP500 | 1 | 12 (含 COUNTRY) |
| **CHN** | **TOP2000U** | 0, 1 | 11 |
| KOR | TOP600 | 1 | 11 |
| HKG | TOP800, TOP500 | 1 | 11 |
| IND | TOP500 | 1 | 11 |
| MEA | TOP400, TOP300 | 1 | 6 |
| DEU | TOP500 | 0, 1 | 11 |
| GBR | TOP700 | 0, 1 | 11 |

## 重要说明

### CHN 区域
- Universe 使用 **TOP2000U**（带 U 后缀），不是 TOP2000
- 支持 delay=0 和 delay=1
- 不支持 COUNTRY 中性化

### GLB 区域
- 仅支持 delay=1
- 额外支持 COUNTRY 中性化

### MEA 区域
- 中性化选项有限，仅支持：NONE, MARKET, SECTOR, INDUSTRY, SUBINDUSTRY, COUNTRY

## Neutralization 选项

### 通用选项
- `NONE` - 无
- `MARKET` - 市场中性
- `SECTOR` - 行业中性
- `INDUSTRY` - 产业中性
- `SUBINDUSTRY` - 子产业中性
- `REVERSION_AND_MOMENTUM` (RAM)
- `STATISTICAL`
- `CROWDING`
- `FAST`
- `SLOW`
- `SLOW_AND_FAST`

### 区域特定
- `COUNTRY` - 仅 GLB/EUR/ASI/MEA 支持

## 参数范围

| 参数 | 最小值 | 最大值 |
|------|--------|--------|
| decay | 0 | 512 |
| truncation | 0.0 | 1.0 |
| lookback | 0 | 1024 |
| selectionLimit | 10 | 1000 |

## 其他选项

- **pasteurization**: ON, OFF
- **nanHandling**: ON, OFF
- **language**: PYTHON, FASTEXPR
- **type**: REGULAR, SUPER

## 文件位置

- 原始 JSON: `data/simulation_schema.json`
- Python 配置: `alpha_operator_framework/platform_config.py`

## 使用示例

```python
from alpha_operator_framework.platform_config import (
    UNIVERSES, DELAYS, NEUTRALIZATIONS,
    validate_settings, get_region_info
)

# 获取 CHN 配置
info = get_region_info("CHN")
# {'region': 'CHN', 'universes': ['TOP2000U'], 'delays': [0, 1], ...}

# 验证参数
validate_settings("CHN", "TOP2000U", 1)  # True
validate_settings("CHN", "TOP2000", 1)   # False (错误的 universe)
```