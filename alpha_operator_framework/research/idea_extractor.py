"""文献逻辑抽取器 (Research Idea Extractor).

功能:
  1. 将非结构化研报/论文提炼为结构化 PaperIdea 实体 (包含异象分类、因果机理、抽象公式与变量角色)
  2. 支持标准 LLM 提示词生成与结构化 JSON 响应反序列化
  3. 内置离线启发式规则抽取引擎 (Rule-based Heuristics)，在无大模型时也能提炼公式
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from alpha_operator_framework.domain.fields import FieldSpec
from alpha_operator_framework.research.document_parser import ParsedDocument


@dataclass
class PaperIdea:
    """从文献研报中提炼出的 Alpha 假说原型."""

    idea_id: str
    title: str
    category: str                   # 异象类别 (如 momentum_reversal / liquidity_volatility)
    rationale: str                  # 金融经济学机理
    abstract_formula: str           # 抽象公式原型 (如 rank(momentum) / (rank(volatility) + 0.01))
    variable_roles: Dict[str, str]  # 变量角色说明 (如 {"momentum": "20日动量", "volatility": "60日波动率"})
    recommended_decay: int = 6
    source_reference: str = ""


class IdeaExtractor:
    """文献认知提炼与假说抽取器."""

    @staticmethod
    def build_extraction_prompt(
        doc: ParsedDocument,
        available_fields: Optional[Sequence[FieldSpec]] = None,
    ) -> str:
        """构建供 LLM 推理抽取的结构化 Prompt."""
        fields_hint = ""
        if available_fields:
            sample_fields = [
                {"id": f.id, "type": f.type, "description": (f.description or "")[:60]}
                for f in available_fields[:25]
            ]
            fields_hint = f"当前量化平台可用的部分真实字段参考：\n{json.dumps(sample_fields, ensure_ascii=False, indent=2)}\n\n"

        return (
            f"你是一名顶级量化对冲基金的首席金工分析师。\n"
            f"请仔细研读以下量化文献/研报内容，提取出其中所包含的 Alpha 因子假说、超额收益机理和数学公式。\n\n"
            f"文献标题: {doc.title}\n"
            f"文献摘要/主要内容:\n{doc.clean_text[:2500]}\n\n"
            f"{fields_hint}"
            f"请严格以 JSON 数组格式输出提取出的每个 Alpha 假说（若有多个请输出多个对象）：\n"
            f"[\n"
            f"  {{\n"
            f"    \"title\": \"因子名称\",\n"
            f"    \"category\": \"momentum_reversal | liquidity_volatility | analyst_dispersion | quality_value | sentiment_attention\",\n"
            f"    \"rationale\": \"为什么该因子能产生超额收益 (经济学/行为金融逻辑)\",\n"
            f"    \"abstract_formula\": \"WorldQuant BRAIN 语法格式的公式 (如 group_neutralize(rank(momentum) / (rank(volatility) + 0.01), industry))\",\n"
            f"    \"variable_roles\": {{\n"
            f"      \"momentum\": \"20日收盘价动量\",\n"
            f"      \"volatility\": \"60日特质波动率\"\n"
            f"    }},\n"
            f"    \"recommended_decay\": 6\n"
            f"  }}\n"
            f"]\n"
        )

    @staticmethod
    def parse_llm_response(
        response_text: str | Dict[str, Any] | List[Dict[str, Any]],
        source_title: str = "",
    ) -> List[PaperIdea]:
        """解析 LLM 返回的 JSON 响应为 PaperIdea 列表."""
        if isinstance(response_text, (dict, list)):
            data = response_text
        else:
            clean_json = response_text.strip()
            # 提取 ```json ... ``` 块
            json_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", clean_json)
            if json_match:
                clean_json = json_match.group(1).strip()
            data = json.loads(clean_json)

        if isinstance(data, dict):
            data = [data]

        ideas: List[PaperIdea] = []
        for idx, item in enumerate(data):
            idea_id = f"idea_{uuid.uuid4().hex[:8]}"
            title = str(item.get("title") or f"{source_title} - Idea {idx+1}")
            category = str(item.get("category") or "momentum_reversal")
            rationale = str(item.get("rationale") or "")
            formula = str(item.get("abstract_formula") or item.get("formula") or "")
            var_roles = item.get("variable_roles") or {}
            decay = int(item.get("recommended_decay", 6))

            if formula:
                ideas.append(
                    PaperIdea(
                        idea_id=idea_id,
                        title=title,
                        category=category,
                        rationale=rationale,
                        abstract_formula=formula,
                        variable_roles=var_roles,
                        recommended_decay=decay,
                        source_reference=source_title,
                    )
                )

        return ideas

    @staticmethod
    def extract_from_text_rule_based(doc: ParsedDocument) -> List[PaperIdea]:
        """离线规则抽取引擎: 从文档公式或金融关键字中启发式合成 PaperIdea."""
        ideas: List[PaperIdea] = []

        # 1. 优先使用提取出的公式块
        for idx, f in enumerate(doc.formulas_found):
            # 简单清洗
            clean_f = f.strip().rstrip(";")
            if any(op in clean_f for op in ("rank", "ts_rank", "group_neutralize", "ts_delta", "ts_decay_linear", "+", "-", "/", "*")):
                # 提取公式中出现的单词作为变量候选
                tokens = re.findall(r"\b[a-zA-Z_]\w*\b", clean_f)
                known_ops = {"rank", "zscore", "scale", "group_neutralize", "group_rank", "ts_rank", "ts_mean", "ts_delta", "ts_delay", "ts_decay_linear", "signed_power", "reverse", "industry", "subindustry", "sector"}
                vars_found = [t for t in tokens if t not in known_ops and not t.isdigit()]

                roles = {v: f"Variable {v} extracted from paper" for v in vars_found}

                ideas.append(
                    PaperIdea(
                        idea_id=f"rule_idea_{idx+1}",
                        title=f"{doc.title} - Formula {idx+1}",
                        category="momentum_reversal" if "mom" in clean_f.lower() or "ret" in clean_f.lower() else "liquidity_volatility",
                        rationale=doc.abstract[:150] or "Heuristically extracted from paper formula block",
                        abstract_formula=clean_f,
                        variable_roles=roles,
                        recommended_decay=6,
                        source_reference=doc.title,
                    )
                )

        # 2. 如果没有发现显式公式，根据关键词启发式生成
        if not ideas:
            txt = doc.clean_text.lower()
            if "波动率" in txt or "volatility" in txt:
                ideas.append(
                    PaperIdea(
                        idea_id="rule_vol_01",
                        title=f"{doc.title} - 波动率修正",
                        category="liquidity_volatility",
                        rationale="基于文献提炼的低波动率与流动性溢价假说",
                        abstract_formula="rank(returns) / (rank(volume) + 0.01)",
                        variable_roles={"returns": "收益率", "volume": "成交量"},
                        recommended_decay=8,
                        source_reference=doc.title,
                    )
                )
            else:
                ideas.append(
                    PaperIdea(
                        idea_id="rule_mom_01",
                        title=f"{doc.title} - 动量均值回归",
                        category="momentum_reversal",
                        rationale="基于文献提炼的极值反转假说",
                        abstract_formula="ts_rank(returns, 22) - ts_rank(volume, 22)",
                        variable_roles={"returns": "收益率", "volume": "成交量"},
                        recommended_decay=5,
                        source_reference=doc.title,
                    )
                )

        return ideas
