"""Signal filtering and follow-up workflow branches."""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any, Dict, List, Sequence

from alpha_operator_framework.cli.field_pipeline import _write_json
from alpha_operator_framework.database import AlphaDatabase, get_database_path, persist_workflow_row
from alpha_operator_framework.domain import density, families
from alpha_operator_framework.platform.simulation_gateway import simulate
from alpha_operator_framework.workflow.models import SignalBranchConfig, SurveyConfig, WorkflowResult


def _make_sim_config(config: SurveyConfig) -> object:
    import argparse

    return argparse.Namespace(
        region=config.region,
        universe=config.universe,
        delay=config.delay,
        batch_size=config.batch_size,
        neutralization=config.neutralization,
        truncation=config.truncation,
        nan_handling="OFF",
        test_period="P0Y0M",
    )


def build_signal_branches(
    results: Sequence[Dict[str, Any]],
    config: SignalBranchConfig = SignalBranchConfig(),
) -> Dict[str, List[Dict[str, Any]]]:
    """从一阶回测信号生成二元与二阶两个分支的任务。

    这里先做信号门和表达式去重，再生成分支，避免把弱信号或重复表达式
    扩散到后续回测。返回值中的字典可直接转换为 ``Task.to_sim_dict``。
    """
    signal_gate = density.SignalGate(
        abs_sharpe_min=config.min_sharpe,
        abs_fitness_min=config.min_fitness,
    )
    expressions: List[str] = []
    seen = set()
    for row in results:
        expression = row.get("expression") or (row.get("regular") or {}).get("code")
        if not expression or expression in seen:
            continue
        ok, _ = signal_gate.is_signal(row)
        if ok:
            expressions.append(expression)
            seen.add(expression)
    if config.max_signal_expressions > 0:
        expressions = expressions[:config.max_signal_expressions]

    branches: Dict[str, List[Dict[str, Any]]] = {"binary": [], "second_order": []}
    if config.include_binary:
        branches["binary"] = [
            {
                "expression": task.expression,
                "family": task.family,
                "template_index": task.template_index,
                "fields_per_alpha": task.fields_per_alpha,
                "base_fields": list(task.base_fields),
            }
            for task in families.binary_factory(expressions)
        ]

    if config.include_second_order:
        from alpha_operator_framework.domain.operators import second_order_factory
        branches["second_order"] = [
            {
                "expression": expression,
                "family": "second_order",
                "template_index": index,
                "fields_per_alpha": 1,
                "base_fields": [source],
            }
            for source in expressions
            for index, expression in enumerate(
                second_order_factory(
                    [source],
                    group_ops_set=config.group_ops,
                    available_groups=config.groups or (),
                )
            )
        ]
    return branches


async def run_signal_branches(
    first_order_results: Sequence[Dict[str, Any]],
    survey_config: SurveyConfig,
    branch_config: SignalBranchConfig = SignalBranchConfig(),
    output_dir: Path = Path("runs"),
    execute: bool = False,
) -> Dict[str, WorkflowResult]:
    """分别回测并持久化一阶信号的二元、二阶分支。

    每个分支独立抽样、独立调用 simulate、独立写入结果文件和数据库，避免
    二元分支与二阶分支的结果互相覆盖。数据库 stage 分别为
    ``binary_branch`` 和 ``second_order_branch``。
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    branches = build_signal_branches(first_order_results, branch_config)
    output: Dict[str, WorkflowResult] = {}

    for branch_name, branch_tasks in branches.items():
        stage = f"{branch_name}_branch"
        rng = random.Random(survey_config.seed)
        sampled_tasks = list(branch_tasks)
        rng.shuffle(sampled_tasks)
        if branch_config.branch_backtest_sample_n > 0:
            sampled_tasks = sampled_tasks[:branch_config.branch_backtest_sample_n]

        tasks_file = output_dir / (
            f"{stage}_tasks_{survey_config.region}_"
            f"{survey_config.dataset_id or 'all'}.json"
        )
        tasks_file.write_text(
            json.dumps({
                "stage": stage,
                "source": "first_order_signal",
                "tasks": sampled_tasks,
            }, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        if not execute:
            output[branch_name] = WorkflowResult(
                success=True,
                stage=stage,
                message=f"[DRY-RUN] {branch_name}生成{len(branch_tasks)}个任务，抽样{len(sampled_tasks)}个",
                tasks_generated=len(sampled_tasks),
                tasks_file=tasks_file,
                config=branch_config.__dict__.copy(),
            )
            continue

        if not sampled_tasks:
            output[branch_name] = WorkflowResult(
                success=True,
                stage=stage,
                message=f"没有满足信号门的{branch_name}任务",
                tasks_file=tasks_file,
                config=branch_config.__dict__.copy(),
            )
            continue

        try:
            sim_tasks = [
                {
                    "expression": task["expression"],
                    "decay": survey_config.decay,
                    "family": task["family"],
                    "template_index": task["template_index"],
                    "fields_per_alpha": task["fields_per_alpha"],
                }
                for task in sampled_tasks
            ]
            results = await simulate(
                sim_tasks,
                _make_sim_config(survey_config),
                wait_for_completion=True,
                poll_interval=5.0,
                max_wait_seconds=600.0,
            )

            meta = {task["expression"]: task for task in sampled_tasks}
            for row in results:
                expression = row.get("expression")
                task = meta.get(expression)
                if task:
                    row["family"] = task["family"]
                    row["template_index"] = task["template_index"]
                    row["fields_per_alpha"] = task["fields_per_alpha"]
                    row["branch"] = branch_name

            results_file = output_dir / (
                f"{stage}_results_{survey_config.region}_"
                f"{survey_config.dataset_id or 'all'}.json"
            )
            _write_json(results_file, {
                "stage": stage,
                "config": survey_config.__dict__,
                "branch_config": branch_config.__dict__,
                "results": results,
            })

            db = AlphaDatabase(get_database_path())
            settings = {
                "region": survey_config.region,
                "universe": survey_config.universe,
                "delay": survey_config.delay,
                "neutralization": survey_config.neutralization,
                "truncation": survey_config.truncation,
                "decay": survey_config.decay,
                "branch": branch_name,
            }
            persisted = 0
            for row in results:
                if persist_workflow_row(db, row, settings, stage=stage, status="pending"):
                    persisted += 1
            db.close()

            output[branch_name] = WorkflowResult(
                success=True,
                stage=stage,
                message=f"{branch_name}完成: {len(results)}条回测，持久化{persisted}条",
                tasks_generated=len(sampled_tasks),
                tasks_file=tasks_file,
                simulations_run=len(results),
                results_file=results_file,
                config=branch_config.__dict__.copy(),
            )
        except ImportError:
            output[branch_name] = WorkflowResult(
                success=False,
                stage=stage,
                message="未安装alpha_machine,无法执行分支回测",
                tasks_generated=len(sampled_tasks),
                tasks_file=tasks_file,
                config=branch_config.__dict__.copy(),
            )

    return output


__all__ = ["build_signal_branches", "run_signal_branches"]
