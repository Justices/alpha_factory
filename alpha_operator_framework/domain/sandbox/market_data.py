"""本地沙盒截面市场数据容器与数据生成器.

提供:
  1. MarketDataCrossSection: 存储日频 × 股票截面的数据字段矩阵 (close, open, volume, returns, industry 等)
  2. generate_synthetic_market_data: 生成具备真实统计特性的合成截面数据 (用于离线高速单测与预筛)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
import numpy as np


@dataclass
class MarketDataCrossSection:
    """截面市场数据容器.

    所有字段矩阵 shape 均为 (T, N):
      - T: 时间序列长度 (如 252 交易日)
      - N: 资产标的数量 (如 100 只股票)
    """

    dates: List[str]
    tickers: List[str]
    fields: Dict[str, np.ndarray] = field(default_factory=dict)
    forward_returns: Optional[np.ndarray] = None  # 下期收益率矩阵 R_{t+1} (用于计算 IC / PnL)
    groups: Optional[np.ndarray] = None           # 行业分组 (1D 或 2D int 数组)

    @property
    def shape(self) -> tuple[int, int]:
        return (len(self.dates), len(self.tickers))

    def get_field(self, name: str) -> Optional[np.ndarray]:
        """获取字段矩阵 (大小写不敏感)."""
        name_lower = name.lower()
        for k, v in self.fields.items():
            if k.lower() == name_lower:
                return v
        return None

    def add_field(self, name: str, data: np.ndarray) -> None:
        """添加或覆盖字段矩阵."""
        if data.shape != self.shape:
            raise ValueError(f"Field '{name}' shape {data.shape} does not match cross section {self.shape}")
        self.fields[name] = data


def generate_synthetic_market_data(
    n_days: int = 252,
    n_assets: int = 100,
    seed: int = 42,
) -> MarketDataCrossSection:
    """生成用于离线沙盒验证的合成截面市场数据.

    包含:
      - 真实几何布朗运动价格 (close, open, high, low)
      - 具备相关性的对数收益率 returns 与成交量 volume
      - 行业分类 industry / sector (10 个行业)
      - 常用典型因子字段 (analyst_eps, pe_ratio, roe, sentiment, momentum)

    Args:
        n_days: 交易天数 (默认 252)
        n_assets: 股票数 (默认 100)
        seed: 随机种子

    Returns:
        MarketDataCrossSection 实例
    """
    rng = np.random.default_rng(seed)

    dates = [f"2025-{i//20+1:02d}-{i%20+1:02d}" for i in range(n_days)]
    tickers = [f"STK_{i:04d}" for i in range(n_assets)]

    # 1. 模拟行业 (10 个行业)
    industries = rng.integers(0, 10, size=(n_assets,), dtype=np.int32)
    industry_matrix = np.tile(industries, (n_days, 1)).astype(np.float64)

    # 2. 模拟收益率 (共同市场因子 + 行业因子 + 个股特异收益)
    market_returns = rng.normal(0.0004, 0.01, size=(n_days, 1))
    sector_returns = rng.normal(0, 0.008, size=(n_days, 10))
    stock_noise = rng.normal(0, 0.015, size=(n_days, n_assets))

    stock_returns = market_returns + sector_returns[:, industries] + stock_noise

    # 3. 构造价格体系 (Close, Open, High, Low)
    init_prices = rng.uniform(10.0, 100.0, size=(1, n_assets))
    cum_returns = np.cumsum(stock_returns, axis=0)
    close_prices = init_prices * np.exp(cum_returns)

    # Open, High, Low
    open_prices = close_prices * (1 + rng.normal(0, 0.005, size=(n_days, n_assets)))
    high_prices = np.maximum(close_prices, open_prices) * (1 + np.abs(rng.normal(0, 0.008, size=(n_days, n_assets))))
    low_prices = np.minimum(close_prices, open_prices) * (1 - np.abs(rng.normal(0, 0.008, size=(n_days, n_assets))))

    # Volume (对数正态分布)
    base_vol = rng.uniform(1e5, 1e7, size=(1, n_assets))
    volume = base_vol * np.exp(rng.normal(0, 0.5, size=(n_days, n_assets)))

    # 4. 下期收益率 Forward Returns R_{t+1}
    forward_returns = np.full_like(stock_returns, np.nan)
    forward_returns[:-1] = stock_returns[1:]

    # 5. 构造具备一定预测信号或噪声的特征字段
    # momentum: 过去 20 天动量 + 噪声
    # analyst_eps: 与未来收益有弱正相关 (IC ~ 0.05) 的合成信号
    true_alpha_signal = forward_returns + rng.normal(0, 0.03, size=(n_days, n_assets))
    analyst_eps = np.roll(true_alpha_signal, shift=1, axis=0)
    analyst_eps[0] = 0.0

    roe = rng.uniform(0.02, 0.25, size=(1, n_assets)) + rng.normal(0, 0.01, size=(n_days, n_assets))
    sentiment = rng.normal(0, 1.0, size=(n_days, n_assets))

    fields = {
        "close": close_prices,
        "open": open_prices,
        "high": high_prices,
        "low": low_prices,
        "volume": volume,
        "returns": stock_returns,
        "industry": industry_matrix,
        "sector": industry_matrix,
        "market": np.ones((n_days, n_assets), dtype=np.float64),
        "analyst_eps": analyst_eps,
        "roe": roe,
        "sentiment": sentiment,
        "cap": close_prices * volume * 10,
    }

    return MarketDataCrossSection(
        dates=dates,
        tickers=tickers,
        fields=fields,
        forward_returns=forward_returns,
        groups=industry_matrix,
    )
