"""Public data models for carpet mining."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from alpha_operator_framework.domain.judge.evaluator import JudgeReport
from alpha_operator_framework.platform.platform_simulator import PlatformAlphaResult


@dataclass
class CarpetMiningConfig:
    """地毯式挖掘配置."""

    region: str = "GBR"
    universe: str = "TOP700"
    delay: int = 1
    datasets: List[str] = field(default_factory=list)
    sample_per_family: int = 4
    batch_size: int = 5
    decay: int = 12
    neutralization: str = "SUBINDUSTRY"
    truncation: float = 0.08
    unit_handling: str = "VERIFY"
    nan_handling: str = "OFF"
    optimize_signals: bool = True
    min_sharpe_for_opt: float = 0.35
    min_return_for_opt: float = 0.02
    execute: bool = True
    seed: Optional[int] = None


@dataclass
class CarpetMiningResult:
    """地毯式挖掘全流程汇总结果."""

    config: CarpetMiningConfig
    total_expressions_generated: int
    sampled_cohort_size: int
    categories_tested: List[str]
    first_gen_results: List[PlatformAlphaResult]
    pruned_families: List[str]
    optimized_results: List[PlatformAlphaResult]
    all_persisted_ids: List[str]
    ranked_reports: List[JudgeReport]
    elapsed_seconds: float
    distilled_templates: List[str] = field(default_factory=list)

    def summary_markdown(self) -> str:
        """生成 Markdown 格式的执行总结研报."""
        lines = [
            "# 🎯 地毯式 Alpha 分层挖掘与自进化研报",
            "",
            f"- **目标市场**: `{self.config.region}` ({self.config.universe}, Delay {self.config.delay})",
            f"- **覆盖数据集**: `{', '.join(self.config.datasets)}`",
            f"- **表达式生成规模**: 初始生成 `{self.total_expressions_generated}` 条 ➔ 分层抽样 `{self.sampled_cohort_size}` 条 ({len(self.categories_tested)} 个大类)",
            f"- **回测与入库**: 平台实测 `{len(self.first_gen_results)}` 条第一代 + `{len(self.optimized_results)}` 条二代优化",
            f"- **淘汰剪枝族数**: `{len(self.pruned_families)}` 族 (已沉淀剪枝规则)",
            f"- **自主蒸馏模板**: 新沉淀 `{len(self.distilled_templates)}` 个高阶模板至知识库",
            f"- **全流程耗时**: `{self.elapsed_seconds:.1f}` 秒",
            "",
            "## 一、 综合优胜 Alpha 终审排行榜 (Top 10)",
            "",
            "| 排名 | 平台 Alpha ID | 来源类别 | Sharpe | Fitness | 换手率 | 年化收益 | 最大回撤 | 评级 | 行动建议 |",
            "| :---: | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :--- |",
        ]

        for idx, rep in enumerate(self.ranked_reports[:10], 1):
            icon = "🥇" if idx == 1 else ("🥈" if idx == 2 else ("🥉" if idx == 3 else f"{idx}"))
            metrics = rep.metrics if hasattr(rep, "metrics") and rep.metrics else {}
            if isinstance(metrics, dict):
                sharpe = float(metrics.get("sharpe") or 0.0)
                fitness = float(metrics.get("fitness") or 0.0)
                turnover = float(metrics.get("turnover") or 0.0)
                returns = float(metrics.get("returns") or metrics.get("annualized_return") or 0.0)
                drawdown = float(metrics.get("drawdown") or metrics.get("max_drawdown") or 0.0)
            else:
                sharpe = float(getattr(metrics, "sharpe", 0.0))
                fitness = float(getattr(metrics, "fitness", 0.0))
                turnover = float(getattr(metrics, "turnover", 0.0))
                returns = float(getattr(metrics, "returns", getattr(metrics, "annualized_return", 0.0)))
                drawdown = float(getattr(metrics, "drawdown", getattr(metrics, "max_drawdown", 0.0)))
            family = getattr(rep, "family", None) or (metrics.get("family") if isinstance(metrics, dict) else getattr(metrics, "family", "mining")) or "mining"
            verdict = rep.verdict.value if hasattr(rep.verdict, "value") else str(rep.verdict)
            recommendation = rep.actionable_recommendations[0] if rep.actionable_recommendations else "保持观察"
            lines.append(f"| {icon} | `{rep.alpha_id}` | `{family}` | **{sharpe:.2f}** | {fitness:.2f} | {turnover:.1%} | **{returns:.2%}** | {drawdown:.1%} | `{verdict}` | {recommendation} |")

        if self.ranked_reports:
            best = self.ranked_reports[0]
            metrics = best.metrics if hasattr(best, "metrics") and best.metrics else {}
            if isinstance(metrics, dict):
                b_sharpe = float(metrics.get("sharpe") or 0.0)
                b_fitness = float(metrics.get("fitness") or 0.0)
                b_turnover = float(metrics.get("turnover") or 0.0)
                b_returns = float(metrics.get("returns") or metrics.get("annualized_return") or 0.0)
                b_drawdown = float(metrics.get("drawdown") or metrics.get("max_drawdown") or 0.0)
            else:
                b_sharpe = float(getattr(metrics, "sharpe", 0.0))
                b_fitness = float(getattr(metrics, "fitness", 0.0))
                b_turnover = float(getattr(metrics, "turnover", 0.0))
                b_returns = float(getattr(metrics, "returns", getattr(metrics, "annualized_return", 0.0)))
                b_drawdown = float(getattr(metrics, "drawdown", getattr(metrics, "max_drawdown", 0.0)))
            lines.extend([
                "", "## 二、 重点优胜 Alpha 详情", "",
                f"- **平台 Alpha ID**: `{best.alpha_id}`",
                f"- **规范 AST 表达式**: `{best.expression}`",
                f"- **综合表现**: Sharpe **{b_sharpe:.2f}**, Fitness **{b_fitness:.2f}**, 年化收益 **{b_returns:.2%}**, 最大回撤 **{b_drawdown:.1%}**, 换手率 **{b_turnover:.1%}**",
            ])

        if self.distilled_templates:
            lines.extend(["", "## 三、 🧬 本轮自主反向蒸馏沉淀的新模板骨架", "", "系统已自动将本轮胜出的高夏普 Alpha 结构泛化提取并存入 `template_library` 数据库，后续将自动跨数据集复用：", ""])
            lines.extend(f"{idx}. `{skeleton}`" for idx, skeleton in enumerate(self.distilled_templates, 1))
        return "\n".join(lines)


__all__ = ["CarpetMiningConfig", "CarpetMiningResult"]
