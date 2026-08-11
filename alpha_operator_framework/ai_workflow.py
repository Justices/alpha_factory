"""AI友好的工作流API — 支持精确参数控制.

本模块提供两类接口:
  1. CLI接口: 保持orchestrator.py的命令行方式
  2. Python API: 供AI直接调用,支持精确控制

关键改进:
  - 支持指定数据字段列表(而非随机采样)
  - 支持单次调用完成survey→deepen→submit
  - 返回结构化结果(便于AI解析)
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Dict, Any, Optional, Sequence
from datetime import datetime

# 项目模块
from . import families
from . import fields
from . import density
from . import operators
from . import optimize  # 新增


# ---------------------------------------------------------------------------
# 配置数据结构
# ---------------------------------------------------------------------------

@dataclass
class OptimizeConfig:
    """优化阶段配置."""
    # 筛选方式1: 指定alpha_id列表
    alpha_ids: Optional[List[str]] = None

    # 筛选方式2: 按条件筛选
    min_sharpe: Optional[float] = None
    max_sharpe: Optional[float] = None
    min_fitness: Optional[float] = None
    max_fitness: Optional[float] = None
    min_turnover: Optional[float] = None
    max_turnover: Optional[float] = None

    # 其他筛选条件
    region: Optional[str] = None
    dataset_id: Optional[str] = None
    status: Optional[str] = None

    # 优化参数
    decay_variants: List[float] = field(default_factory=lambda: [3.0, 6.0, 9.0])
    neutralization_variants: List[str] = field(default_factory=lambda: ["MARKET", "SECTOR", "INDUSTRY"])
    max_variants_per_alpha: int = 10

    # 限制
    limit: Optional[int] = None

@dataclass
class SurveyConfig:
    """Survey阶段配置."""
    region: str = "EUR"
    universe: str = "TOP2500"
    delay: int = 1

    # 数据集选择
    dataset_id: str = ""                    # 空表示全字段
    field_ids: Optional[List[str]] = None   # None表示采样,否则使用指定字段列表

    # 采样参数(仅当field_ids=None时生效)
    sample_n: int = 80
    min_coverage: float = 0.0
    prefer_cold: bool = True
    seed: int = 42
    top_n_templates: int = 3  # 用于密度评估的top-N

    # 模板选择
    include_unary: bool = True
    include_binary: bool = True
    include_ternary: bool = False
    include_quaternary: bool = False
    group_fields: Optional[List[str]] = None

    # 模拟参数
    batch_size: int = 8
    neutralization: str = "SUBINDUSTRY"
    truncation: float = 0.08
    decay: float = 6.0


@dataclass
class DeepenConfig:
    """Deepen阶段配置."""
    # 质量门
    min_sharpe: float = 1.2
    min_fitness: float = 0.7
    min_margin: float = 5.0
    min_turnover: float = 0.01
    max_turnover: float = 0.70

    # 字段扩展
    sample_n: int = 400
    top_n_templates: int = 3


@dataclass
class WorkflowResult:
    """工作流结果."""
    success: bool
    stage: str
    message: str = ""

    # 任务列表
    tasks_generated: int = 0
    tasks_file: Optional[Path] = None

    # 模拟结果
    simulations_run: int = 0
    results_file: Optional[Path] = None

    # 密度评估
    density_report: Optional[Dict] = None
    top_templates: List[Dict] = field(default_factory=list)

    # 候选alpha
    candidates: List[Dict] = field(default_factory=list)
    kept_file: Optional[Path] = None

    # 元数据
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    config: Dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# AI友好的API接口
# ---------------------------------------------------------------------------

async def run_survey_with_fields(
    field_specs: Sequence[fields.FieldSpec],
    config: SurveyConfig,
    output_dir: Path = Path("runs"),
    execute: bool = False
) -> WorkflowResult:
    """使用指定字段列表运行Survey阶段.

    Args:
        field_specs: 字段规格列表(由AI或用户提供,不随机采样)
        config: Survey配置
        output_dir: 输出目录
        execute: 是否实际执行模拟(False则dry-run)

    Returns:
        WorkflowResult: 包含任务、结果、密度等信息

    Example:
        >>> from alpha_operator_framework import FieldSpec, SurveyConfig
        >>> fields_list = [
        ...     FieldSpec(id="close", dataset_id="pv1", type="MATRIX", coverage=0.95),
        ...     FieldSpec(id="volume", dataset_id="pv1", type="MATRIX", coverage=0.92)
        ... ]
        >>> config = SurveyConfig(region="EUR", universe="TOP2500")
        >>> result = await run_survey_with_fields(fields_list, config)
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        # 1. 字段预处理
        if config.field_ids:
            # 使用指定字段列表
            field_map = {f.id: f for f in field_specs}
            selected = [field_map[fid] for fid in config.field_ids if fid in field_map]
        else:
            # 采样
            spec = fields.SampleSpec(
                sample_n=config.sample_n,
                min_coverage=config.min_coverage,
                prefer_cold=config.prefer_cold,
                seed=config.seed
            )
            selected = fields.candidate_scalars(field_specs, spec)

        # 预处理成标量表达式
        scalars = []
        for f in selected:
            scalars.extend(fields.preprocess_field(f))

        # 2. 构造任务
        tasks = []
        if config.include_unary:
            tasks.extend(families.unary_factory(scalars))

        if config.include_binary:
            pairs = list(zip(scalars[::2], scalars[1::2]))  # 简单配对
            tasks.extend(families.binary_factory(scalars, max_pairs=len(pairs)))

        if config.include_ternary:
            from itertools import combinations
            triples = list(combinations(scalars, 3))[:config.sample_n]
            tasks.extend(families.ternary_factory(scalars, max_triples=len(triples)))

        if config.include_quaternary and config.group_fields:
            tasks.extend(families.quaternary_factory(
                scalars, config.group_fields, max_quadruples=len(pairs)
            ))

        # 3. 写任务列表
        tasks_file = output_dir / f"survey_tasks_{config.region}_{config.dataset_id or 'all'}.json"
        _write_tasks(tasks, tasks_file, config.__dict__)

        if not execute:
            return WorkflowResult(
                success=True,
                stage="survey",
                message=f"[DRY-RUN] 生成{len(tasks)}个任务,加execute=True运行模拟",
                tasks_generated=len(tasks),
                tasks_file=tasks_file,
                config=config.__dict__
            )

        # 4. 模拟(需alpha_machine)
        try:
            import alpha_machine

            sim_tasks = [
                {
                    "expression": t.expression,
                    "decay": config.decay,
                    "family": t.family,
                    "template_index": t.template_index,
                    "fields_per_alpha": t.fields_per_alpha
                }
                for t in tasks
            ]

            results = await alpha_machine.simulate(
                sim_tasks,
                _make_sim_config(config)
            )

            # 5. 写结果
            results_file = output_dir / f"survey_results_{config.region}_{config.dataset_id or 'all'}.json"
            alpha_machine.write_json(results_file, {
                "config": config.__dict__,
                "results": results
            })

            # 5.1 持久化到数据库 (survey)
            try:
                from .database import AlphaDatabase, persist_workflow_row

                db = AlphaDatabase(output_dir / "alpha_research.db")
                settings = {
                    "region": config.region,
                    "universe": config.universe,
                    "delay": config.delay,
                    "neutralization": config.neutralization,
                    "truncation": config.truncation,
                    "decay": config.decay,
                }
                n = 0
                for row in results:
                    if persist_workflow_row(db, row, settings, stage="survey", status="pending"):
                        n += 1
                db.close()
                print(f"  db ← {n} 条 survey 结果 ({output_dir / 'alpha_research.db'})")
            except Exception as e:
                print(f"  ⚠ 数据库写入失败: {e}")

            # 6. 计算密度
            # 回填元数据
            meta = {t.expression: t for t in tasks}
            for row in results:
                expr = row.get("expression")
                if expr in meta:
                    t = meta[expr]
                    row["family"] = t.family
                    row["template_index"] = t.template_index
                    row["fields_per_alpha"] = t.fields_per_alpha

            density_rows = density.compute_density(
                results,
                access_limited_ops=operators.ACCESS_LIMITED_OPS
            )

            # 写密度报告
            density_file = output_dir / f"survey_density_{config.region}_{config.dataset_id or 'all'}.json"
            density.write_report(density_rows, density_file, top_n=config.top_n_templates)

            top = density.top_templates(density_rows, top_n=config.top_n_templates)

            return WorkflowResult(
                success=True,
                stage="survey",
                message=f"完成: {len(tasks)}任务→{len(results)}结果→密度{len(density_rows)}",
                tasks_generated=len(tasks),
                tasks_file=tasks_file,
                simulations_run=len(results),
                results_file=results_file,
                density_report={"rows": [r.to_dict() for r in density_rows]},
                top_templates=[r.to_dict() for r in top],
                config=config.__dict__
            )

        except ImportError:
            return WorkflowResult(
                success=False,
                stage="survey",
                message="未安装alpha_machine,无法执行模拟",
                tasks_generated=len(tasks),
                tasks_file=tasks_file,
                config=config.__dict__
            )

    except Exception as e:
        return WorkflowResult(
            success=False,
            stage="survey",
            message=f"错误: {str(e)}",
            config=config.__dict__
        )


async def run_full_workflow(
    region: str,
    universe: str,
    delay: int = 1,
    dataset_id: str = "",
    field_ids: Optional[List[str]] = None,
    field_specs: Optional[Sequence[fields.FieldSpec]] = None,
    sample_n: int = 80,
    top_n: int = 3,
    min_sharpe: float = 1.2,
    execute: bool = False
) -> Dict[str, WorkflowResult]:
    """完整三段工作流(供AI单次调用).

    Args:
        region: 地区代码 (EUR/USA/CHN等)
        universe: 股票池 (TOP2500/TOP3000等)
        delay: 数据延迟 (0/1)
        dataset_id: 数据集ID (空=全字段)
        field_ids: 指定字段ID列表 (None=采样)
        field_specs: 字段规格列表 (如提供则不查询平台)
        sample_n: 采样数量 (仅当field_ids=None时生效)
        top_n: 取top-N模板用于深挖
        min_sharpe: Deepen阶段Sharpe阈值
        execute: 是否实际执行

    Returns:
        Dict[str, WorkflowResult]: survey/deepen/submit各阶段结果

    Example:
        >>> result = await run_full_workflow(
        ...     region="EUR",
        ...     universe="TOP2500",
        ...     dataset_id="pv1",
        ...     field_ids=["close", "volume", "returns"],
        ...     execute=False
        ... )
    """
    results = {}

    # 1. Survey阶段
    survey_config = SurveyConfig(
        region=region,
        universe=universe,
        delay=delay,
        dataset_id=dataset_id,
        field_ids=field_ids,
        sample_n=sample_n,
        top_n_templates=top_n
    )

    # 如果未提供field_specs,需要查询平台
    if field_specs is None:
        try:
            import alpha_machine
            field_rows = await alpha_machine.fetch_datafields(
                region, universe, delay, dataset_id=dataset_id
            )
            field_specs = [
                fields.FieldSpec(
                    id=r["id"],
                    dataset_id=r.get("dataset", {}).get("id", ""),
                    type=r.get("type", "MATRIX"),
                    coverage=r.get("coverage", 0.0),
                    user_count=r.get("userCount", 0)
                )
                for r in field_rows
            ]
        except ImportError:
            results["survey"] = WorkflowResult(
                success=False,
                stage="survey",
                message="未安装alpha_machine且未提供field_specs"
            )
            return results

    results["survey"] = await run_survey_with_fields(
        field_specs, survey_config, execute=execute
    )

    if not results["survey"].success or not execute:
        return results

    # 2. Deepen阶段 (基于survey结果)
    if results["survey"].top_templates:
        deepen_config = DeepenConfig(
            min_sharpe=min_sharpe,
            top_n_templates=top_n
        )
        results["deepen"] = await _run_deepen_from_survey(
            results["survey"],
            field_specs,
            deepen_config,
            execute=execute
        )

    # 3. Submit阶段
    if "deepen" in results and results["deepen"].candidates:
        results["submit"] = WorkflowResult(
            success=True,
            stage="submit",
            message=f"找到{len(results['deepen'].candidates)}个候选alpha",
            candidates=results["deepen"].candidates
        )

    return results


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def _make_sim_config(config: SurveyConfig) -> object:
    """构造alpha_machine.simulate需要的配置对象."""
    import argparse
    return argparse.Namespace(
        region=config.region,
        universe=config.universe,
        delay=config.delay,
        batch_size=config.batch_size,
        neutralization=config.neutralization,
        truncation=config.truncation,
        nan_handling="OFF",
        test_period="P0Y0M"
    )


def _write_tasks(tasks: list, path: Path, config: dict) -> None:
    """写任务列表JSON."""
    payload = {
        "config": config,
        "tasks": [t.to_sim_dict() for t in tasks],
        "annotated": [
            {
                "expression": t.expression,
                "family": t.family,
                "template_index": t.template_index,
                "fields_per_alpha": t.fields_per_alpha
            }
            for t in tasks
        ]
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8"
    )


async def _run_deepen_from_survey(
    survey_result: WorkflowResult,
    field_specs: Sequence[fields.FieldSpec],
    config: DeepenConfig,
    execute: bool = False
) -> WorkflowResult:
    """基于Survey结果运行Deepen阶段."""
    # 实现省略(类似survey逻辑)
    return WorkflowResult(
        success=False,
        stage="deepen",
        message="Deepen阶段待实现"
    )


# ---------------------------------------------------------------------------
# Alpha筛选与优化API
# ---------------------------------------------------------------------------

def filter_alphas_for_optimization(
    alphas: Sequence[Dict[str, Any]],
    alpha_ids: Optional[List[str]] = None,
    min_sharpe: Optional[float] = None,
    max_sharpe: Optional[float] = None,
    min_fitness: Optional[float] = None,
    max_fitness: Optional[float] = None,
    min_turnover: Optional[float] = None,
    max_turnover: Optional[float] = None,
    limit: Optional[int] = None
) -> List[Dict[str, Any]]:
    """筛选需要优化的alpha.

    支持两种筛选方式:
      1. 精确指定: alpha_ids参数
      2. 条件筛选: min_sharpe等指标范围

    Args:
        alphas: alpha结果列表(来自deepen或平台查询)
        alpha_ids: 指定alpha_id列表(精确模式)
        min_sharpe: 最小Sharpe
        max_sharpe: 最大Sharpe(用于筛选边缘alpha)
        min_fitness: 最小Fitness
        max_fitness: 最大Fitness
        min_turnover: 最小Turnover
        max_turnover: 最大Turnover
        limit: 限制数量

    Returns:
        筛选后的alpha列表

    Example:
        >>> # 方式1: 指定alpha_id
        >>> filtered = filter_alphas_for_optimization(
        ...     alphas,
        ...     alpha_ids=["a1", "a2", "a3"]
        ... )

        >>> # 方式2: 按条件筛选
        >>> filtered = filter_alphas_for_optimization(
        ...     alphas,
        ...     min_sharpe=1.58,
        ...     min_fitness=1.0,
        ...     min_turnover=0.03
        ... )

        >>> # 方式3: 筛选边缘alpha
        >>> filtered = filter_alphas_for_optimization(
        ...     alphas,
        ...     min_sharpe=1.2,
        ...     max_sharpe=1.8,
        ...     limit=20
        ... )
    """
    from .optimize import AlphaFilter, filter_alphas

    config = AlphaFilter(
        alpha_ids=alpha_ids,
        min_sharpe=min_sharpe,
        max_sharpe=max_sharpe,
        min_fitness=min_fitness,
        max_fitness=max_fitness,
        min_turnover=min_turnover,
        max_turnover=max_turnover,
        limit=limit
    )

    return filter_alphas(alphas, config)


def filter_high_quality_alphas(
    alphas: Sequence[Dict[str, Any]],
    min_sharpe: float = 1.58,
    min_fitness: float = 1.0,
    min_turnover: float = 0.03,
    limit: Optional[int] = None
) -> List[Dict[str, Any]]:
    """筛选高质量alpha(便捷函数).

    使用标准质量门:
      - sharpe ≥ 1.58
      - fitness ≥ 1.0
      - turnover ≥ 0.03

    Args:
        alphas: alpha结果列表
        min_sharpe: 最小Sharpe(默认1.58)
        min_fitness: 最小Fitness(默认1.0)
        min_turnover: 最小Turnover(默认0.03)
        limit: 限制数量

    Returns:
        高质量alpha列表

    Example:
        >>> high_quality = filter_high_quality_alphas(
        ...     alphas,
        ...     min_sharpe=1.58,
        ...     limit=50
        ... )
    """
    from .optimize import filter_by_quality
    return filter_by_quality(alphas, min_sharpe, min_fitness, min_turnover, limit)


def filter_marginal_alphas(
    alphas: Sequence[Dict[str, Any]],
    sharpe_range: tuple = (1.2, 1.8),
    fitness_range: tuple = (0.7, 1.5),
    turnover_range: tuple = (0.01, 0.1),
    limit: Optional[int] = None
) -> List[Dict[str, Any]]:
    """筛选边缘alpha(有优化潜力).

    边缘alpha特征:
      - Sharpe在1.2-1.8之间(接近提交线,有提升空间)
      - Fitness在0.7-1.5之间
      - Turnover适中

    Args:
        alphas: alpha结果列表
        sharpe_range: Sharpe范围(默认1.2-1.8)
        fitness_range: Fitness范围(默认0.7-1.5)
        turnover_range: Turnover范围(默认0.01-0.1)
        limit: 限制数量

    Returns:
        边缘alpha列表

    Example:
        >>> # 找出Sharpe在1.2-1.8之间的alpha进行优化
        >>> marginal = filter_marginal_alphas(
        ...     alphas,
        ...     sharpe_range=(1.2, 1.8),
        ...     limit=20
        ... )
    """
    from .optimize import filter_marginal
    return filter_marginal(alphas, sharpe_range, fitness_range, turnover_range, limit)


def filter_ready_for_submission(
    alphas: Sequence[Dict[str, Any]],
    min_sharpe: float = 1.58,
    min_fitness: float = 1.0,
    min_turnover: float = 0.01,
    max_turnover: float = 0.7,
    min_long_short_sum: int = 100,
    limit: Optional[int] = None
) -> List[Dict[str, Any]]:
    """筛选可提交的alpha(便捷函数).

    使用提交质量门:
      - sharpe ≥ 1.58
      - fitness ≥ 1.0
      - 0.01 ≤ turnover ≤ 0.7
      - long + short ≥ 100

    Args:
        alphas: alpha结果列表
        min_sharpe: 最小Sharpe(默认1.58)
        min_fitness: 最小Fitness(默认1.0)
        min_turnover: 最小Turnover(默认0.01)
        max_turnover: 最大Turnover(默认0.7)
        min_long_short_sum: 最小long+short数量(默认100)
        limit: 限制数量

    Returns:
        可提交的alpha列表

    Example:
        >>> ready = filter_ready_for_submission(alphas, limit=50)
    """
    from .optimize import filter_for_submission
    return filter_for_submission(
        alphas, min_sharpe, min_fitness, min_turnover, max_turnover, min_long_short_sum, limit
    )


# ---------------------------------------------------------------------------
# CLI兼容接口(保留orchestrator.py的命令行能力)
# ---------------------------------------------------------------------------

def main():
    """CLI入口(保持向后兼容)."""
    import argparse

    ap = argparse.ArgumentParser(description="Alpha Operator Framework (AI-friendly)")
    ap.add_argument("--region", default="EUR")
    ap.add_argument("--universe", default="TOP2500")
    ap.add_argument("--delay", type=int, default=1)
    ap.add_argument("--dataset", default="")
    ap.add_argument("--fields", nargs="*", help="指定字段ID列表")
    ap.add_argument("--sample", type=int, default=80)
    ap.add_argument("--top-n", type=int, default=3)
    ap.add_argument("--min-sharpe", type=float, default=1.2)
    ap.add_argument("--execute", action="store_true")

    args = ap.parse_args()

    result = asyncio.run(run_full_workflow(
        region=args.region,
        universe=args.universe,
        delay=args.delay,
        dataset_id=args.dataset,
        field_ids=args.fields,
        sample_n=args.sample,
        top_n=args.top_n,
        min_sharpe=args.min_sharpe,
        execute=args.execute
    ))

    print(json.dumps({
        stage: {
            "success": r.success,
            "message": r.message,
            "tasks_generated": r.tasks_generated,
            "simulations_run": r.simulations_run,
            "top_templates": len(r.top_templates),
            "candidates": len(r.candidates)
        }
        for stage, r in result.items()
    }, indent=2))


if __name__ == "__main__":
    main()


__all__ = [
    "SurveyConfig",
    "DeepenConfig",
    "OptimizeConfig",
    "WorkflowResult",
    "run_survey_with_fields",
    "run_full_workflow",
    "filter_alphas_for_optimization",
    "filter_high_quality_alphas",
    "filter_marginal_alphas",
    "filter_ready_for_submission",
]