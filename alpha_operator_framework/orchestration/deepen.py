"""Deepen-stage orchestration."""

from __future__ import annotations

import asyncio
from typing import List

from alpha_operator_framework.cli.field_pipeline import QualityGate, _write_json, filter_alpha_results
from alpha_operator_framework.platform.datafields import fetch_datafields
from alpha_operator_framework.platform.simulation_gateway import simulate

from .survey import RUNS, _ns, _persist_rows, _semantic_prune, _survey_settings, write_tasks

def cmd_deepen(args) -> None:
    """Deepen: top-N模板 × 全字段 → 质量门筛选.

    步骤:
      1. 读density报告取top-N
      2. 发现字段 (全字段, 不采样)
      3. 对每个top模板展开任务
      4. 模拟 (--execute才消耗额度)
      5. 质量门筛选 (sharpe/fitness/margin/turnover)

    Args:
        args: CLI参数

    示例:
        python -m alpha_operator_framework.orchestrator deepen \\
            --density-out runs/cold_survey_density.json \\
            --sample 400 --execute
    """
    from alpha_operator_framework.domain.density import read_report, top_templates
    from alpha_operator_framework.domain import families, fields

    # 1. 读density报告
    report = read_report(args.density_out)
    top = report.get("top_for_deepen", [])
    print(f"[deepen] 从 {args.density_out} 读 top {len(top)} 模板")

    # 2. 发现字段：本地文件优先；未提供文件时才请求平台。
    fields_file = getattr(args, "fields_file", None)
    if fields_file:
        from alpha_operator_framework.platform.local_fields import load_local_field_specs
        field_specs = load_local_field_specs(
            fields_file,
            region=args.region,
            universe=args.universe,
            delay=args.delay,
            dataset_id=getattr(args, "dataset", ""),
            search=getattr(args, "search", ""),
            data_type=getattr(args, "type", ""),
        )
        print(f"  本地字段文件 → {fields_file} ({len(field_specs)} 个匹配字段)")
    else:
        page_delay = getattr(args, 'page_delay', 0.5)
        field_rows = asyncio.run(fetch_datafields(
            args.region, args.universe, args.delay,
            page_delay=page_delay
        ))
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

    # 2.5 语义剪枝 (可选, 压缩字段池)
    field_specs = _semantic_prune(field_specs, getattr(args, "prune_fields", 0))

    # 3. 采样 (深挖时sample更大)
    spec = fields.SampleSpec(
        sample_n=args.sample,
        min_coverage=args.min_coverage,
        prefer_cold=not args.no_cold,
        seed=args.seed
    )
    scalars = fields.sample_scalar_expressions(field_specs, spec)
    selected_fields = fields.sample_field_specs(field_specs, spec)  # 用于 first_order_raw 重建

    # 4. 构造任务
    tasks: List = []
    for t in top:
        family, idx = t.get("family"), t.get("template_index")
        origin = t.get("expression_origin", "")

        if family == "unary":
            if origin == "first_order":
                tasks.extend(
                    task for task in families.first_order_task_factory(scalars)
                    if task.template_index == idx
                )
                continue
            if origin == "first_order_raw":
                tasks.extend(
                    task for task in families.raw_first_order_task_factory(
                        [f.id for f in selected_fields])
                    if task.template_index == idx
                )
                continue
            if origin in ("", "unary_template"):
                tasks.extend(
                    task for task in families.unary_factory(scalars)
                    if task.template_index == idx
                )
                continue
            continue
        elif family == "binary":
            generated = families.binary_factory(scalars, max_pairs=args.sample)
        elif family == "ternary":
            generated = families.ternary_factory(scalars, max_triples=args.sample)
        else:
            continue

        tasks.extend(task for task in generated if task.template_index == idx)

    print(f"  构造任务 {len(tasks)} 个")

    # 5. 写任务列表
    write_tasks(tasks, RUNS / args.tasks_out, {"stage": "deepen"})
    print(f"  tasks → {RUNS / args.tasks_out} ({len(tasks)} 条)")

    if not args.execute:
        print("  [DRY RUN] 未模拟。加 --execute 消耗回测额度")
        return

    # 6. 模拟 (顺序执行批次，等待每批完成后再继续)
    results = asyncio.run(simulate(
        [t.to_sim_dict() for t in tasks],
        _ns(region=args.region, universe=args.universe, delay=args.delay),
        wait_for_completion=True,
        poll_interval=getattr(args, "poll_interval", 5.0),
        max_wait_seconds=getattr(args, "max_wait", 600.0),
    ))

    # 7. 质量门筛选
    gate = QualityGate(
        args.sharpe, args.fitness, args.margin,
        args.min_turnover, args.max_turnover
    )
    kept, rejected = filter_alpha_results(results, gate)

    # 7.5 同字段top-k剪枝 (可选, 防一字段垄断候选)
    if getattr(args, "prune_per_field", 0) > 0:
        from alpha_operator_framework.domain.pruning import field_topk_prune, FieldTopKConfig
        kept, pruned = field_topk_prune(
            kept, FieldTopKConfig(keep_per_field=args.prune_per_field))
        if pruned:
            _write_json(
                RUNS / "deepen_pruned_topk.json",
                {"gate": {"prune_per_field": args.prune_per_field}, "pruned": pruned},
            )
        print(f"  同字段top-k剪枝: kept → {len(kept)} (剪掉 {len(pruned)})")

    _write_json(
        RUNS / args.kept_out,
        {
            "gate": {
                "sharpe": args.sharpe,
                "fitness": args.fitness,
                "margin": args.margin
            },
            "kept": kept,
            "rejected": rejected
        }
    )
    print(f"  质量门: kept={len(kept)} rejected={len(rejected)} → {RUNS / args.kept_out}")

    # 8. 持久化到数据库 (deepen)
    settings = _survey_settings(args)
    n_kept = _persist_rows(kept, settings, stage="deepen", status="kept")
    n_rejected = _persist_rows(rejected, settings, stage="deepen", status="rejected")
    print(f"  db ← {n_kept} kept + {n_rejected} rejected (data/alpha_research.db)")

__all__ = ["cmd_deepen"]
