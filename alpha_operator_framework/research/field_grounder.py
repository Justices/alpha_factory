"""字段语义对齐与落地器 (Semantic Field Grounder).

功能:
  1. 将文献/研报中出现的抽象变量概念 (如 'idiosyncratic_volatility', 'operating_cashflow', 'momentum')
     自动映射对齐到平台/本地真实数据字段 (FieldSpec)
  2. 支持同义词词典、模糊匹配、字段描述语义打分与保底回退
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from alpha_operator_framework.domain.fields import FieldSpec


# 金融概念同义词词典 (Concept -> Synonyms / Keywords) - 移除平台不再支持的 close 字段
_CONCEPT_SYNONYMS: Dict[str, Tuple[str, ...]] = {
    "price": ("vwap", "returns", "market_cap", "price", "stock_price"),
    "volume": ("volume", "turnover", "shares", "trade_volume", "vol", "trade"),
    "momentum": ("returns", "ret", "vwap", "price_momentum", "momentum", "trend"),
    "volatility": ("volatility", "std_dev", "ivol", "variance", "std", "vol", "deviation"),
    "cashflow": ("cashflow", "operating_cashflow", "free_cashflow", "cfo", "cf", "cash"),
    "earnings": ("net_income", "profit", "ebit", "ebitda", "eps", "operating_income", "earning", "income"),
    "analyst": ("analyst", "est_eps", "target_price", "rating", "analyst_revision", "estimate", "revision", "forecast", "upward"),
    "sentiment": ("sentiment", "news_score", "social_attention", "sentiment_score", "news", "attention"),
    "turnover": ("turnover", "volume", "shares_traded"),
}


class SemanticFieldGrounder:
    """语义字段对齐器."""

    @staticmethod
    def ground_variable(
        var_name: str,
        var_description: str,
        available_fields: Sequence[FieldSpec],
    ) -> str:
        """为单个抽象变量匹配最佳的平台真实字段 ID.

        Args:
            var_name: 变量名 (如 'momentum_20', 'ivol')
            var_description: 变量描述 (如 '20-day price momentum')
            available_fields: 当前可用的真实字段规格列表

        Returns:
            匹配出的真实 field_id (若无完全匹配则回退到最相近字段或 returns/volume)
        """
        if not available_fields:
            return var_name

        var_clean = var_name.lower()
        desc_clean = (var_description or "").lower()
        combined_text = f"{var_clean} {desc_clean}"
        tokens = set(re.findall(r"\b\w+\b", combined_text))

        # 1. 检查是否存在完全精确同名字段 (排除已废弃的 close/open/high/low)
        for f in available_fields:
            if f.id.lower() == var_clean and f.id.lower() not in ("close", "open", "high", "low"):
                return f.id

        best_field: Optional[str] = None
        best_score = 0

        # 2. 直接分词重叠打分 (排除已废弃字段)
        for f in available_fields:
            if f.id.lower() in ("close", "open", "high", "low"):
                continue
            f_id_lower = f.id.lower()
            f_desc_lower = (f.description or "").lower()

            score = 0
            for t in tokens:
                if len(t) < 3:
                    continue
                if t in f_id_lower:
                    score += 5
                if t in f_desc_lower:
                    score += 3

            if score > best_score:
                best_score = score
                best_field = f.id

        # 3. 检查同义词概念词典打分
        for concept, synonyms in _CONCEPT_SYNONYMS.items():
            if any(syn in combined_text for syn in synonyms):
                for f in available_fields:
                    if f.id.lower() in ("close", "open", "high", "low"):
                        continue
                    f_id_lower = f.id.lower()
                    f_desc_lower = (f.description or "").lower()
                    c_score = sum(4 for s in synonyms if s in f_id_lower) + sum(2 for s in synonyms if s in f_desc_lower)
                    if c_score > best_score:
                        best_score = c_score
                        best_field = f.id

        if best_field and best_score >= 2:
            return best_field

        # 4. 保底机制: 返回可用的常用矩阵字段 (优先 returns/volume/vwap)
        for preferred in ("returns", "volume", "vwap", "market_cap"):
            for f in available_fields:
                if f.id.lower() == preferred:
                    return f.id

        valid_fields = [f.id for f in available_fields if f.id.lower() not in ("close", "open", "high", "low")]
        return valid_fields[0] if valid_fields else available_fields[0].id

    def ground_idea(
        self,
        variable_roles: Dict[str, str],
        available_fields: Sequence[FieldSpec],
    ) -> Dict[str, str]:
        """批量将 PaperIdea 的全部抽象变量映射为真实字段字典."""
        grounded_map: Dict[str, str] = {}
        for var_name, var_desc in variable_roles.items():
            actual_field = self.ground_variable(var_name, var_desc, available_fields)
            grounded_map[var_name] = actual_field
        return grounded_map
