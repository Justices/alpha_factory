"""Cross-stage orchestration commands."""

from __future__ import annotations

import argparse

from .deepen import cmd_deepen
from .submission import cmd_submit
from .survey import RUNS, cmd_survey

def cmd_run_all(args) -> None:
    """一键运行完整流程: Survey → Deepen → Submit.

    步骤:
      1. Survey: 字段池 × 模板族 → 密度报告
      2. Deepen: top-N模板 × 全字段 → 质量门筛选
      3. Submit: 本地SC预检 → 相关性剪枝 → (可选)平台check

    Args:
        args: CLI参数

    示例:
        # 完整流程 (消耗额度)
        python -m alpha_operator_framework.orchestrator run-all \\
            --region USA --universe TOP3000 \\
            --execute

        # 仅本地预检 (不消耗额度)
        python -m alpha_operator_framework.orchestrator run-all \\
            --region USA --universe TOP3000 \\
            --local-sc
    """
    print("=" * 70)
    print("Alpha Operator Framework — 一键运行")
    print("=" * 70)

    # --- Phase 1: Survey ---
    print("\n[Phase 1/3] Survey — 字段池 × 模板族 → 密度报告")
    print("-" * 70)

    survey_args = argparse.Namespace(
        region=args.region,
        universe=args.universe,
        delay=args.delay,
        dataset=args.dataset or "",
        search=args.search or "",
        type=args.type or "",
        min_coverage=args.min_coverage,
        seed=args.seed,
        backfill=args.backfill,
        winsorize_std=args.winsorize_std,
        no_cold=args.no_cold,
        execute=args.execute,  # 只有 --execute 才消耗额度
        batch_size=args.batch_size,
        neutralization=args.neutralization,
        sample=args.survey_sample,
        strategy=getattr(args, "strategy", "template"),  # 新策略参数
        template_categories=args.template_categories,
        test_operators=getattr(args, "test_operators", ["rank", "quantile"]),
        groups=args.groups,
        fields_file=args.fields_file,
        field_source=args.field_source,
        fields_file_type=args.fields_file_type,
        backtest_sample=args.backtest_sample,
        top_n=args.top_n,
        prune_fields=args.prune_fields,
        tasks_out="survey_tasks.json",
        results_out="survey_results.json",
        density_out="survey_density.json",
    )
    cmd_survey(survey_args)

    # 检查 density 文件是否存在
    density_path = RUNS / "survey_density.json"
    if not density_path.exists():
        print("\n[错误] Survey 未生成密度报告，流程终止")
        return

    # --- Phase 2: Deepen ---
    print("\n[Phase 2/3] Deepen — top-N模板 × 全字段 → 质量门筛选")
    print("-" * 70)

    deepen_args = argparse.Namespace(
        region=args.region,
        universe=args.universe,
        delay=args.delay,
        dataset=args.dataset or "",
        search=args.search or "",
        type=args.type or "",
        min_coverage=args.min_coverage,
        seed=args.seed,
        backfill=args.backfill,
        winsorize_std=args.winsorize_std,
        no_cold=args.no_cold,
        execute=args.execute,
        batch_size=args.batch_size,
        neutralization=args.neutralization,
        density_out=str(density_path),
        sample=args.deepen_sample,
        sharpe=args.sharpe,
        fitness=args.fitness,
        margin=args.margin,
        min_turnover=args.min_turnover,
        max_turnover=args.max_turnover,
        prune_fields=args.prune_fields,
        prune_per_field=args.prune_per_field,
        fields_file=args.fields_file,
        tasks_out="deepen_tasks.json",
        results_out="deepen_results.json",
        kept_out="deepen_kept.json",
    )
    cmd_deepen(deepen_args)

    # 检查 kept 文件是否存在
    kept_path = RUNS / "deepen_kept.json"
    if not kept_path.exists():
        print("\n[错误] Deepen 未生成 kept 文件，流程终止")
        return

    # --- Phase 3: Submit ---
    print("\n[Phase 3/3] Submit — 本地SC预检 → 相关性剪枝")
    print("-" * 70)

    submit_args = argparse.Namespace(
        kept_out=str(kept_path),
        execute=args.execute,
        prune_corr=args.prune_corr,
        local_sc=args.local_sc,
        sc_threshold=args.sc_threshold,
        sc_marginal=args.sc_marginal,
        os_alpha_count=args.os_alpha_count,
    )
    cmd_submit(submit_args)

    # --- 完成 ---
    print("\n" + "=" * 70)
    print("流程完成")
    print("=" * 70)
    print(f"  密度报告: {density_path}")
    print(f"  候选列表: {kept_path}")
    if args.local_sc:
        print(f"  SC预检结果: runs/submit_sc_*.json")
    if args.prune_corr:
        print(f"  相关性剪枝: runs/submit_pruned_corr.json")
    print("\n下一步: 检查候选列表, 确认后手动提交")

__all__ = ["cmd_run_all"]

