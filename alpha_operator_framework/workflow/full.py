"""End-to-end AI workflow composition."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from alpha_operator_framework.domain import fields
from alpha_operator_framework.workflow.branches import run_signal_branches
from alpha_operator_framework.workflow.models import (
    DeepenConfig,
    SignalBranchConfig,
    SurveyConfig,
    WorkflowResult,
)
from alpha_operator_framework.workflow.survey import _run_deepen_from_survey, run_survey_with_fields


async def run_full_workflow(
    region: str,
    universe: str,
    delay: int = 1,
    dataset_id: str = "",
    field_ids: Optional[List[str]] = None,
    field_specs: Optional[Sequence[fields.FieldSpec]] = None,
    fields_file: Optional[str | Path] = None,
    sample_n: int = 80,
    top_n: int = 3,
    min_sharpe: float = 1.2,
    template_families: Optional[Tuple[str, ...]] = None,
    backtest_sample_n: int = 80,
    operator_min_trials: int = 3,
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
        fields_file: 本地字段文件（CSV 或 JSON 数组）；如提供则不查询平台
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
        ...     field_ids=["vwap", "volume", "returns"],
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
        top_n_templates=top_n,
        template_families=template_families,
        backtest_sample_n=backtest_sample_n,
        operator_min_trials=operator_min_trials,
    )

    # 本地字段文件优先；其次使用调用方提供的字段；最后才查询平台。
    if fields_file is not None:
        from alpha_operator_framework.platform.local_fields import load_local_field_specs
        field_specs = load_local_field_specs(
            fields_file,
            region=region,
            universe=universe,
            delay=delay,
            dataset_id=dataset_id,
        )

    if field_specs is None:
        # 本地缓存优先 → 平台兜底 (含分页+节流+429退避), 避免全量实时拉取触发限流
        try:
            from alpha_operator_framework.cache.datafields import aget_datafields
            field_rows = await aget_datafields(
                region, universe, delay, dataset_id=dataset_id
            )
            field_specs = [
                fields.FieldSpec(
                    id=r["id"],
                    dataset_id=r.get("dataset", {}).get("id", ""),
                    type=r.get("type", "MATRIX"),
                    coverage=r.get("coverage", 0.0),
                    date_coverage=float(r.get("dateCoverage") or 0.0),
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

    # 2. 一阶信号后分成两条独立路径：二元组合 / 二阶算子变化。
    if results["survey"].results_file and results["survey"].results_file.exists():
        survey_payload = json.loads(results["survey"].results_file.read_text(encoding="utf-8"))
        branch_results = await run_signal_branches(
            survey_payload.get("results", []),
            survey_config,
            SignalBranchConfig(),
            output_dir=Path("runs"),
            execute=execute,
        )
        results.update(branch_results)

    # 3. Deepen阶段 (基于survey结果)
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


__all__ = ["run_full_workflow"]
