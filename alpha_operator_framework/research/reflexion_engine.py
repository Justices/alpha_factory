"""大模型自主假说与失败自反思进化引擎 (LLM Autonomous Reflexion Engine).

功能:
  1. 自主假说推演 (Autonomous Hypothesis Generation):
     - 向大模型提供可用字段的物理/金融含义与平台算子全景图
     - 无需人类预设模板，让大模型自主设计具有前沿金融经济学逻辑的高阶复合公式
  2. 诊断与失败自反思 (Empirical Diagnostic Self-Reflexion):
     - 将真实平台回测的失败数据与病因诊断 (如换手率过高、子宇宙不达标、回撤过大) 反馈给大模型
     - 大模型自主撰写反思 (Reflexion)，并针对性重构数学公式 (如注入时序阻尼、市值分箱、不对称波动惩罚)
  3. 知识沉淀与模板蒸馏联动:
     - 对经过反思迭代后跑出高夏普 (Sharpe >= 1.0) 的胜出因子，自动调用 TemplateAbstractor 沉淀至 template_library
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from alpha_operator_framework.database.repository import AlphaDatabase
from alpha_operator_framework.domain.ast.canonicalizer import to_canonical_string
from alpha_operator_framework.domain.ast.validator import validate_expression
from alpha_operator_framework.domain.families import Task
from alpha_operator_framework.distill.diagnostic import FailureDiagnosis, diagnose_alpha_failure
from alpha_operator_framework.distill.template_abstractor import abstract_templates
from alpha_operator_framework.platform.platform_simulator import (
    BrainPlatformSimulator,
    PlatformAlphaResult,
)
from alpha_operator_framework.research.idea_extractor import PaperIdea
from alpha_operator_framework.research.llm_client import UnifiedLLMClient

logger = logging.getLogger(__name__)


@dataclass
class ReflexionIteration:
    """单轮自主反思进化的详细过程记录."""

    iteration: int
    hypotheses: List[PaperIdea]
    tasks: List[Task]
    results: List[PlatformAlphaResult]
    reflexion_critique: str = ""
    distilled_templates: List[str] = field(default_factory=list)


class LLMReflexionEngine:
    """大模型自主假说与自反思投研进化引擎."""

    def __init__(
        self,
        db: Optional[AlphaDatabase] = None,
        llm_client: Optional[UnifiedLLMClient] = None,
    ):
        self.db = db or AlphaDatabase()
        self.llm = llm_client or UnifiedLLMClient()
        self.simulator = BrainPlatformSimulator()

    def generate_autonomous_hypotheses(
        self,
        fields: Sequence[Dict[str, Any]],
        market_context: str = "GBR TOP700",
        count: int = 5,
        provider: Optional[str] = None,
        model: Optional[str] = None,
    ) -> List[PaperIdea]:
        """让大模型自由推导前沿量化假说与数学表达式 (无需预置模板)."""
        sample_fields = [
            {"id": f["id"], "type": f.get("type", "MATRIX"), "description": str(f.get("description", ""))[:80]}
            for f in fields[:20]
        ]

        prompt_lines = [
            "你是一名顶级量化对冲基金的首席量化架构师。",
            f"请针对目标股票宇宙【{market_context}】，根据以下可用基础特征字段，自主构思并设计 {count} 个前沿高阶 Alpha 因子公式。",
            "",
            "【要求】：",
            "1. 完全自主创造，不要套用简单死板的单指标公式，必须是有深厚经济学/行为金融学机理的高阶复合公式；",
            "2. 鼓励采用三层架构 (特征核 -> 截面分组/行业中性化 -> 时序尺度标准化 ts_scale/ts_zscore) 或 行业-特质正交分解 (ts_zscore(A) - ts_zscore(group_neutralize(A, subindustry)))；",
            "3. 公式中的算子必须是 WorldQuant BRAIN 合法算子 (如 ts_scale, ts_rank, ts_zscore, ts_decay_linear, group_rank, group_neutralize, rank, winsorize 等)；",
            "4. 如果使用 VECTOR 或 EVENT 字段，请务必内层先使用 vec_avg() 和 ts_backfill(..., 120) 包装；",
            "",
            "【可用特征字段】：",
            json.dumps(sample_fields, ensure_ascii=False, indent=2),
            "",
            "请严格输出 JSON 数组格式，不要包含其它任何文字：",
            "[",
            "  {",
            '    "title": "因子名称",',
            '    "category": "alpha_category",',
            '    "rationale": "深刻的金融经济学或微观结构逻辑",',
            '    "abstract_formula": "完整可执行的表达式",',
            '    "recommended_decay": 12',
            "  }",
            "]",
        ]
        prompt = "\n".join(prompt_lines)

        try:
            raw_response = self.llm.chat(
                prompt=prompt,
                provider=provider,
                model=model,
                system_prompt="你是一名精通 WorldQuant BRAIN 算子语法与金融微观结构的资深量化总监。",
            )
            ideas = self._parse_ideas_from_json(raw_response)
            if ideas:
                return ideas
        except Exception as e:
            logger.warning(f"LLM 自主假说推理异常，采用离线符号规则生成: {e}")

        # 降级备用: 启发式自主合成
        return self._fallback_autonomous_ideas(fields)

    def reflect_and_reformulate(
        self,
        failed_results: List[PlatformAlphaResult],
        previous_hypotheses: List[PaperIdea],
        provider: Optional[str] = None,
        model: Optional[str] = None,
    ) -> Tuple[str, List[PaperIdea]]:
        """基于实测失败指标让大模型进行定性与定量反思，并输出重构后的二代进化公式."""
        if not failed_results:
            return "无失败记录需反思", []

        case_summaries = []
        for r in failed_results[:5]:
            diag = diagnose_alpha_failure(r)
            case_summaries.append({
                "expression": r.expression,
                "sharpe": r.sharpe,
                "fitness": r.fitness,
                "turnover": r.turnover,
                "returns": r.annualized_return,
                "drawdown": r.max_drawdown,
                "primary_cause": diag.primary_cause.value if hasattr(diag.primary_cause, "value") else str(diag.primary_cause),
                "diagnosis_summary": diag.summary,
            })

        prompt_lines = [
            "你是一名资深量化回测诊断专家。上一轮提交到 WorldQuant 真实回测的 Alpha 表现未达预期，以下是实测病因诊断数据：",
            "",
            json.dumps(case_summaries, ensure_ascii=False, indent=2),
            "",
            "请执行两阶段任务：",
            "1. 【深度反思】：分析上述公式为什么在实盘/实测中失效（例如是否由于高频噪声放大导致换手率飙升？或者缺乏行业中性化导致受宏观风暴冲击？）；",
            "2. 【结构重构】：针对上述每个失败案例，提出改良后的二代高阶数学公式（例如包裹 ts_scale 降低换手率、注入 group_neutralize 剔除行业 Beta、增加下行波动率惩罚项）。",
            "",
            "请以 JSON 格式输出：",
            "{",
            '  "reflexion": "你的详细量化反思总结",',
            '  "evolved_ideas": [',
            "    {",
            '      "title": "进化因子名",',
            '      "category": "evolved_reflexion",',
            '      "rationale": "改良逻辑与结构修复原因",',
            '      "abstract_formula": "改良后的完整表达式",',
            '      "recommended_decay": 12',
            "    }",
            "  ]",
            "}",
        ]
        prompt = "\n".join(prompt_lines)

        try:
            raw_response = self.llm.chat(
                prompt=prompt,
                provider=provider,
                model=model,
                system_prompt="你是一名极其严谨的量化回测风控与因子基因重构专家。",
            )
            data = json.loads(re.search(r"\{.*\}", raw_response, re.DOTALL).group(0))
            critique = data.get("reflexion", "")
            evolved = []
            for item in data.get("evolved_ideas", []):
                evolved.append(PaperIdea(
                    idea_id=f"refl_{uuid.uuid4().hex[:8]}",
                    title=item.get("title", "Reflexion Evolved Alpha"),
                    category="evolved_reflexion",
                    rationale=item.get("rationale", ""),
                    abstract_formula=item.get("abstract_formula", ""),
                    variable_roles={},
                    recommended_decay=int(item.get("recommended_decay", 12)),
                ))
            return critique, evolved
        except Exception as e:
            logger.warning(f"LLM 失败反思异常: {e}")
            return "启发式规则自适应变异", []

    def _parse_ideas_from_json(self, raw_text: str) -> List[PaperIdea]:
        """从 LLM 输出解析 JSON 数组."""
        match = re.search(r"\[.*\]", raw_text, re.DOTALL)
        if not match:
            return []
        try:
            arr = json.loads(match.group(0))
            ideas = []
            for item in arr:
                formula = item.get("abstract_formula", "").strip()
                if formula:
                    ideas.append(PaperIdea(
                        idea_id=f"idea_{uuid.uuid4().hex[:8]}",
                        title=item.get("title", "Autonomous Alpha"),
                        category=item.get("category", "autonomous_discovery"),
                        rationale=item.get("rationale", ""),
                        abstract_formula=formula,
                        variable_roles={},
                        recommended_decay=int(item.get("recommended_decay", 12)),
                    ))
            return ideas
        except Exception:
            return []

    def _fallback_autonomous_ideas(self, fields: Sequence[Dict[str, Any]]) -> List[PaperIdea]:
        """离线启发式自主假说推导."""
        ideas = []
        for idx, f in enumerate(fields[:4]):
            fid = f["id"]
            ideas.append(PaperIdea(
                idea_id=f"auto_{uuid.uuid4().hex[:8]}",
                title=f"Autonomous 3-Tier {fid}",
                category="autonomous_three_tier",
                rationale=f"基于 {fid} 特征核的截面细分行业中性化与 66 日时序极值归一化平滑",
                abstract_formula=f"ts_scale(group_rank({fid}, subindustry), 66)",
                variable_roles={"core": fid},
                recommended_decay=12,
            ))
        return ideas
