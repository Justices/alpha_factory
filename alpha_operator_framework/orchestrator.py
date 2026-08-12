"""三段工作流编排 — survey → deepen → submit.

整合 cold_templates 的三段方法论与 machine_lib 的多阶因子生成:

  survey:   字段池采样 × 全模板族 → 密度评估 → top-N
  deepen:   top-N模板 × 全字段 → 质量门筛选
  submit:   候选列表 → dry-run → check触发

设计红线:
  1. 会话单管理: 模拟经 alpha_machine.simulate (brain_client单例)
  2. 零授权submit: 默认dry-run, 需显式 --execute
  3. verifier预筛: FASTERPR error → 剔除
  4. 区域自适应: group操作符按region动态匹配
"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
from pathlib import Path
from typing import List, Sequence

# 项目根目录
ROOT = Path(__file__).resolve().parent.parent
RUNS = ROOT / "runs"

# 数据库 (无外部依赖, 可直接导入)
from alpha_operator_framework.database import AlphaDatabase, persist_workflow_row

# 延迟导入 (避免循环依赖)
# 实际使用时需要:
#   import alpha_machine
#   from alpha_operator_framework import families, density, fields


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def _survey_settings(args) -> dict:
    """从CLI参数构造回测设置 dict (供数据库持久化)."""
    return {
        "region": args.region,
        "universe": args.universe,
        "delay": args.delay,
        "neutralization": args.neutralization,
        "truncation": getattr(args, "truncation", 0.08),
    }


def _persist_rows(results: list, settings: dict, stage: str, status: str = "pending") -> int:
    """把结果行批量持久化到数据库, 返回写入条数."""
    db = AlphaDatabase(RUNS / "alpha_research.db")
    try:
        n = 0
        for row in results:
            if persist_workflow_row(db, row, settings, stage=stage, status=status):
                n += 1
        return n
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def _ns(**kw) -> argparse.Namespace:
    """构造 alpha_machine.simulate 需要的 Namespace."""
    defaults = dict(
        region="EUR",
        universe="TOP2500",
        delay=1,
        batch_size=8,
        neutralization="SUBINDUSTRY",
        truncation=0.08,
        nan_handling="OFF",
        test_period="P0Y0M"
    )
    defaults.update(kw)
    return argparse.Namespace(**defaults)


def _semantic_prune(field_specs: list, keep_per_category: int) -> list:
    """字段池语义剪枝: 每语义类留 keep_per_category 个代表 (keep<=0 不剪).

    survey/deepen 共用; 剪枝逻辑在 pruning.semantic_prune_fields.
    """
    if keep_per_category <= 0:
        return field_specs
    from alpha_operator_framework.pruning import semantic_prune_fields, SemanticPruneConfig
    kept, pruned = semantic_prune_fields(
        field_specs, SemanticPruneConfig(keep_per_category=keep_per_category))
    if pruned:
        print(f"  语义剪枝: 字段池 {len(field_specs)} → {len(kept)} "
              f"(每类留 {keep_per_category}, 剪掉 {len(pruned)})")
    return kept


def write_tasks(tasks: list, path: Path, settings: dict) -> Path:
    """写任务列表JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "settings": settings,
        "tasks": [t.to_sim_dict() for t in tasks],
        "annotated": [
            {
                "expression": t.expression,
                "family": t.family,
                "template_index": t.template_index,
                "source_freq": t.meta.get("source_freq"),
                "fields_per_alpha": t.fields_per_alpha
            }
            for t in tasks
        ],
    }

    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8"
    )
    return path


# ---------------------------------------------------------------------------
# Survey 阶段
# ---------------------------------------------------------------------------

def cmd_survey(args) -> None:
    """Survey: 字段池采样 × 全模板族 → 密度评估.

    步骤:
      1. 发现字段 (经 alpha_machine.fetch_datafields)
      2. 采样 (默认80组合)
      3. 构造任务 (一元/二元/三元/四元模板)
      4. verifier预筛 (可选)
      5. 模拟 (--execute才消耗额度)
      6. 计算密度
      7. 输出top-N

    Args:
        args: CLI参数

    示例:
        python -m alpha_operator_framework.orchestrator survey \\
            --region EUR --universe TOP2500 \\
            --sample 80 --execute
    """
    print(f"[survey] {args.region}/{args.universe} delay={args.delay} "
          f"dataset={args.dataset or 'all'} sample={args.sample}")

    # 1. 发现字段：本地文件优先；未提供文件时才请求平台。
    from alpha_operator_framework import families, fields
    fields_file = getattr(args, "fields_file", None)
    if fields_file:
        from alpha_operator_framework.local_fields import load_local_field_specs
        field_specs = load_local_field_specs(
            fields_file,
            region=args.region,
            universe=args.universe,
            delay=args.delay,
            dataset_id=args.dataset,
            search=args.search,
            data_type=args.type,
        )
        print(f"  本地字段文件 → {fields_file} ({len(field_specs)} 个匹配字段)")
    else:
        import alpha_machine
        page_delay = getattr(args, 'page_delay', 0.5)
        field_rows = asyncio.run(alpha_machine.fetch_datafields(
            args.region, args.universe, args.delay,
            dataset_id=args.dataset, search=args.search, data_type=args.type,
            page_delay=page_delay
        ))
        field_specs = [
            fields.FieldSpec(
                id=r["id"],
                dataset_id=r.get("dataset", {}).get("id", ""),
                type=r.get("type", "MATRIX"),
                coverage=r.get("coverage", 0.0),
                user_count=r.get("userCount", 0),
                alpha_count=r.get("alphaCount", 0)
            )
            for r in field_rows
        ]

    # 1.5 基于数据包预筛数据集 (可选)
    use_datapack = getattr(args, 'use_datapack', None)
    if use_datapack:
        from alpha_operator_framework.evaluation import (
            extract_datapack_stats, filter_datasets_by_datapack
        )
        print(f"  [数据包预筛] 从 {use_datapack} 提取质量统计...")
        try:
            stats = extract_datapack_stats(use_datapack, args.region, args.delay)
            dataset_mode = getattr(args, 'datapack_dataset_mode', 'sweet_spot')
            dataset_top_n = getattr(args, 'datapack_dataset_top', 10)
            allowed_datasets = filter_datasets_by_datapack(
                stats, mode=dataset_mode, top_n=dataset_top_n
            )
            print(f"  数据包预筛: 区域平均 sharpe={stats['mean_sharpe']:.3f}, "
                  f"甜点区={len(stats['sweet_spot'])}个, 允许数据集={len(allowed_datasets)}个")
            # 过滤字段行
            field_specs = [f for f in field_specs if f.dataset_id in allowed_datasets]
            print(f"  数据包过滤后: 字段池 {len(field_specs)} 个")
        except Exception as e:
            print(f"  警告: 数据包预筛失败, 跳过: {e}")

    # 1.6 语义剪枝 (可选, 压缩字段池)
    field_specs = _semantic_prune(field_specs, getattr(args, "prune_fields", 0))

    # 2. 采样
    spec = fields.SampleSpec(
        sample_n=args.sample,
        min_coverage=args.min_coverage,
        prefer_cold=not args.no_cold,
        seed=args.seed,
        backfill=args.backfill,
        winsorize_std=args.winsorize_std,
        all_combinations=getattr(args, "all_combinations", True),
    )
    selected_fields = fields.sample_field_specs(field_specs, spec)
    scalars = fields.sample_scalar_expressions(field_specs, spec)
    pairs = fields.sample_pair_combinations(field_specs, spec)
    triples = fields.sample_triple_combinations(field_specs, spec)

    # 3. 构造任务
    tasks: List = []
    unary_tasks: List = []
    semantic_pair_tasks: List = []
    if args.unary:
        # 调查阶段先展开一阶算子，形成表达式后统一进入回测。
        unary_tasks = families.first_order_task_factory(scalars)
        tasks.extend(unary_tasks)
    if getattr(args, "semantic_pairs", True):
        from alpha_operator_framework.semantic_pairs import semantic_pair_task_factory
        semantic_pair_tasks = semantic_pair_task_factory(
            selected_fields,
            backfill=args.backfill,
            winsorize_std=args.winsorize_std,
        )
        tasks.extend(semantic_pair_tasks)
    if args.binary:
        max_pairs = None if getattr(args, "all_combinations", True) else len(pairs)
        tasks.extend(families.binary_factory(scalars, max_pairs=max_pairs))
    if args.ternary:
        max_triples = None if getattr(args, "all_combinations", True) else len(triples)
        tasks.extend(families.ternary_factory(scalars, max_triples=max_triples))
    if args.quaternary and args.groups:
        tasks.extend(families.quaternary_factory(
            scalars, args.groups,
            max_quadruples=None if getattr(args, "all_combinations", True) else len(pairs)
        ))

    print(f"  构造任务 {len(tasks)} 个 "
          f"(unary={args.unary} binary={args.binary} ternary={args.ternary} quaternary={args.quaternary})")

    # 4. 一阶表达式全量入目录，再随机抽样回测。
    catalog_db = AlphaDatabase(RUNS / "alpha_research.db")
    catalog_count = catalog_db.catalog_tasks(unary_tasks, stage="first_order")
    catalog_count += catalog_db.catalog_tasks(semantic_pair_tasks, stage="semantic_pair")
    other_tasks = [t for t in tasks if t not in unary_tasks and t not in semantic_pair_tasks]
    catalog_count += catalog_db.catalog_tasks(other_tasks, stage="survey")
    sampled_expressions = catalog_db.sample_catalog_expressions(
        [task.expression for task in tasks],
        limit=getattr(args, "backtest_sample", 80),
        seed=args.seed,
    )
    sampled_set = set(sampled_expressions)
    sampled_tasks = [t for t in tasks if t.expression in sampled_set]
    catalog_db.close()

    # 5. 写入本次实际回测的任务列表
    write_tasks(
        sampled_tasks,
        RUNS / args.tasks_out,
        {
            "stage": "survey",
            "region": args.region,
            "universe": args.universe,
            "delay": args.delay,
            "dataset": args.dataset
        }
    )
    print(f"  一阶表达式目录 → {catalog_count} 条; 抽样回测 → {len(sampled_tasks)} 条")

    # 5. Dry-run检查
    if not args.execute:
        print("  [DRY RUN] 未模拟。加 --execute 消耗回测额度")
        return

    # 6. 模拟
    import alpha_machine
    results = asyncio.run(alpha_machine.simulate(
        [t.to_sim_dict() for t in sampled_tasks],
        _ns(
            region=args.region,
            universe=args.universe,
            delay=args.delay,
            batch_size=args.batch_size,
            neutralization=args.neutralization
        )
    ))

    # 7. 回填元数据
    meta = {t.expression: t for t in sampled_tasks}
    for row in results:
        expr = row.get("expression")
        if expr in meta:
            t = meta[expr]
            row["family"] = t.family
            row["template_index"] = t.template_index
            row["source_freq"] = t.meta.get("source_freq")
            row["fields_per_alpha"] = t.fields_per_alpha

    # 8. 写结果
    results_path = RUNS / args.results_out
    alpha_machine.write_json(results_path, {"settings": vars(args), "results": results})
    print(f"  results → {results_path} ({len(results)} 条)")

    # 8.5 持久化到数据库 (survey)
    n = _persist_rows(results, _survey_settings(args), stage="survey", status="pending")
    print(f"  db ← {n} 条 survey 结果 ({RUNS / 'alpha_research.db'})")

    # 9. 计算密度
    from alpha_operator_framework.density import compute_density, write_report, top_templates
    from alpha_operator_framework.operators import ACCESS_LIMITED_OPS

    rows = compute_density(results, access_limited_ops=ACCESS_LIMITED_OPS)
    report_path = RUNS / args.density_out
    write_report(rows, report_path, top_n=args.top_n,
                 extra={"region": args.region, "dataset": args.dataset})
    print(f"  密度报告 → {report_path}")

    # 10. 输出top-N
    for r in top_templates(rows, top_n=args.top_n):
        print(f"    top: [{r.family}/{r.template_index}] density={r.density:.2f} "
              f"sample={r.sample_n} signal={r.signal_n} fpa={r.fields_per_alpha}")


# ---------------------------------------------------------------------------
# Deepen 阶段
# ---------------------------------------------------------------------------

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
    from alpha_operator_framework.density import read_report, top_templates
    from alpha_operator_framework import families, fields

    # 1. 读density报告
    report = read_report(args.density_out)
    top = report.get("top_for_deepen", [])
    print(f"[deepen] 从 {args.density_out} 读 top {len(top)} 模板")

    # 2. 发现字段：本地文件优先；未提供文件时才请求平台。
    fields_file = getattr(args, "fields_file", None)
    if fields_file:
        from alpha_operator_framework.local_fields import load_local_field_specs
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
        import alpha_machine
        page_delay = getattr(args, 'page_delay', 0.5)
        field_rows = asyncio.run(alpha_machine.fetch_datafields(
            args.region, args.universe, args.delay,
            page_delay=page_delay
        ))
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

    # 4. 构造任务
    tasks: List = []
    for t in top:
        family, idx = t.get("family"), t.get("template_index")

        if family == "unary":
            donations = [(s,) for s in scalars]
        elif family == "binary":
            from itertools import combinations
            donations = list(combinations(scalars, 2))[:args.sample]
        elif family == "ternary":
            from itertools import combinations
            donations = list(combinations(scalars, 3))[:args.sample]
        else:
            continue

        tasks.extend(families.single_index_factory(family, idx, donations))

    print(f"  构造任务 {len(tasks)} 个")

    # 5. 写任务列表
    write_tasks(tasks, RUNS / args.tasks_out, {"stage": "deepen"})
    print(f"  tasks → {RUNS / args.tasks_out} ({len(tasks)} 条)")

    if not args.execute:
        print("  [DRY RUN] 未模拟。加 --execute 消耗回测额度")
        return

    # 6. 模拟
    import alpha_machine
    results = asyncio.run(alpha_machine.simulate(
        [t.to_sim_dict() for t in tasks],
        _ns(region=args.region, universe=args.universe, delay=args.delay)
    ))

    # 7. 质量门筛选
    gate = alpha_machine.QualityGate(
        args.sharpe, args.fitness, args.margin,
        args.min_turnover, args.max_turnover
    )
    kept, rejected = alpha_machine.filter_alpha_results(results, gate)

    # 7.5 同字段top-k剪枝 (可选, 防一字段垄断候选)
    if getattr(args, "prune_per_field", 0) > 0:
        from alpha_operator_framework.pruning import field_topk_prune, FieldTopKConfig
        kept, pruned = field_topk_prune(
            kept, FieldTopKConfig(keep_per_field=args.prune_per_field))
        if pruned:
            alpha_machine.write_json(
                RUNS / "deepen_pruned_topk.json",
                {"gate": {"prune_per_field": args.prune_per_field}, "pruned": pruned},
            )
        print(f"  同字段top-k剪枝: kept → {len(kept)} (剪掉 {len(pruned)})")

    alpha_machine.write_json(
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
    print(f"  db ← {n_kept} kept + {n_rejected} rejected ({RUNS / 'alpha_research.db'})")


# ---------------------------------------------------------------------------
# Submit 阶段
# ---------------------------------------------------------------------------

def cmd_submit(args) -> None:
    """Submit: 列出候选 → dry-run → check触发.

    步骤:
      1. 读kept文件列出候选
      2. (可选) --execute触发trigger_submission_checks

    Args:
        args: CLI参数

    示例:
        python -m alpha_operator_framework.orchestrator submit \\
            --kept-out runs/cold_deepen_kept.json
    """
    import alpha_machine

    kept_payload = alpha_machine.read_json(Path(args.kept_out))
    kept = (kept_payload.get("kept", kept_payload)
            if isinstance(kept_payload, dict) else kept_payload)

    # 相关性剪枝 (可选, 拉PnL只读去重, 不耗额度; 默认关)
    if getattr(args, "prune_corr", False):
        from alpha_operator_framework.pruning import correlation_prune
        kept, pruned = asyncio.run(correlation_prune(kept))
        print(f"  相关性剪枝: 候选 {len(kept) + len(pruned)} → {len(kept)}")
        if pruned:
            alpha_machine.write_json(
                RUNS / "submit_pruned_corr.json",
                {"pruned": pruned},
            )

    # 本地 SC 预检 (可选, 在 check 前先计算本地相关性; 默认关)
    blue_list, yellow_list, green_list = [], [], []
    if getattr(args, "local_sc", False):
        from alpha_operator_framework.pruning import local_sc_precheck, LocalCheckConfig
        # 获取已提交 alpha ID 列表 (可选)
        submitted_ids = []
        if getattr(args, "os_alpha_count", 0) > 0:
            try:
                os_rows = asyncio.run(alpha_machine.fetch_user_alphas(
                    stage="OS", limit=args.os_alpha_count
                ))
                submitted_ids = [r.get("id") for r in os_rows if r.get("id")]
            except Exception as e:
                print(f"  警告: 无法获取已提交 alpha 列表: {e}")

        config = LocalCheckConfig(
            sc_threshold=getattr(args, "sc_threshold", 0.7),
            sc_marginal=getattr(args, "sc_marginal", 0.05),
        )
        blue_list, yellow_list, green_list = asyncio.run(
            local_sc_precheck(kept, submitted_ids, config)
        )
        print(f"  本地 SC 预检: blue={len(blue_list)} yellow={len(yellow_list)} green={len(green_list)}")

        # 写入分级结果
        if green_list:
            alpha_machine.write_json(RUNS / "submit_sc_green.json", {"green": green_list})
        if yellow_list:
            alpha_machine.write_json(RUNS / "submit_sc_yellow.json", {"yellow": yellow_list})

        # green 列表的 alpha 跳过后续 check, 直接标记不可提交
        for row in green_list:
            row["local_sc_skip_check"] = True

        # 后续只处理 blue + yellow
        kept = blue_list + yellow_list

    alpha_ids = [row.get("alpha_id") for row in kept if row.get("alpha_id")]

    print(f"[submit] {len(alpha_ids)} 个候选 (from {args.kept_out})")

    for row in kept:
        print(f"  {row.get('alpha_id')}  sharpe={row.get('sharpe'):.2f} "
              f"fitness={row.get('fitness'):.2f}  {row.get('expression', '')[:60]}")

    if not alpha_ids:
        print("  无候选可提交")
        return

    # 数据库: 刷新 checks 并判断 SC/PC 是否通过 (本地读操作, dry-run 也可执行)
    db = AlphaDatabase(RUNS / "alpha_research.db")
    try:
        for row in kept:
            alpha_id = row.get("alpha_id")
            if not alpha_id:
                continue

            persist_workflow_row(db, row, {}, stage="submit", status="check")

            # 从数据库读取 SC/PC 判定
            checks = {c["name"]: c for c in db.get_checks(alpha_id)}
            sc = checks.get("SELF_CORRELATION")
            pc = checks.get("PROD_CORRELATION")
            sc_ok = sc is None or sc.get("result") in ("PASS", "WARNING")
            pc_ok = pc is None or pc.get("result") in ("PASS", "WARNING")

            status = "ready" if (sc_ok and pc_ok) else "optimize"
            db.update_alpha_status(alpha_id, status)

            print(f"  {alpha_id}: SC={sc.get('result') if sc else 'n/a'}"
                  f"  PC={pc.get('result') if pc else 'n/a'}  → {status}")
    finally:
        db.close()

    if not args.execute:
        print("\n  [DRY RUN] 未触发平台 check。确认候选后加 --execute 运行 trigger_submission_checks")
        print("  后续提交请人工决策(直接 submit_alpha 需用户在平台确认)。")
        return

    # 触发check
    print(f"\n  触发 trigger_submission_checks for {len(alpha_ids)} 个 alpha (仅 check, 不自动 submit)...")
    # TODO: 调用 trigger_submission_checks.py
    # subprocess.run([str(TRIGGER_CHECK), "--db", str(RUNS / "alpha_research.db")] + alpha_ids)


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
        unary=args.unary,
        binary=args.binary,
        ternary=args.ternary,
        quaternary=args.quaternary,
        groups=args.groups,
        fields_file=args.fields_file,
        semantic_pairs=args.semantic_pairs,
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


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    """构建CLI解析器."""
    ap = argparse.ArgumentParser(
        description="Alpha Operator Framework — survey → deepen → submit",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = ap.add_subparsers(dest="command", required=True)

    def add_common(p, simulate_default=True):
        """添加通用参数."""
        p.add_argument("--region", default="EUR")
        p.add_argument("--universe", default="TOP2500")
        p.add_argument("--delay", type=int, default=1)
        p.add_argument("--dataset", default="", help="数据集ID; 空=全字段")
        p.add_argument("--search", default="", help="字段搜索词")
        p.add_argument("--type", default="", help="字段类型过滤")
        p.add_argument("--fields-file", default=None,
                       help="本地字段文件（CSV 或 JSON 数组）；提供后不请求平台字段接口")
        p.add_argument("--min-coverage", type=float, default=0.0)
        p.add_argument("--seed", type=int, default=42)
        p.add_argument("--backfill", type=int, default=120)
        p.add_argument("--winsorize-std", type=float, default=4.0)
        p.add_argument("--no-cold", action="store_true", help="不优先冷门字段")
        p.add_argument("--no-semantic-pairs", action="store_false", dest="semantic_pairs",
                       help="关闭 positive/negative 与 *_cap 的定向二元配对")
        p.add_argument("--prune-fields", type=int, default=0,
                       help="语义剪枝: 每语义类保留字段代表数(0=关)")
        p.add_argument("--execute", action="store_true", help="实际消耗额度(默认dry-run)")

        if simulate_default:
            p.add_argument("--batch-size", type=int, default=8)
            p.add_argument("--neutralization", default="SUBINDUSTRY")

    # ═══════════════════════════════════════════════════════════════════
    # run-all 子命令 (一键运行)
    # ═══════════════════════════════════════════════════════════════════
    run_all = sub.add_parser("run-all", help="一键运行: Survey → Deepen → Submit")
    add_common(run_all)

    # Survey 参数
    run_all.add_argument("--survey-sample", type=int, default=80, help="Survey阶段字段池样本数")
    run_all.add_argument("--backtest-sample", type=int, default=80,
                         help="从一阶表达式目录随机抽样回测数量(<=0=全部)")
    run_all.add_argument("--unary", action="store_true", default=True)
    run_all.add_argument("--binary", action="store_true", default=True)
    run_all.add_argument("--ternary", action="store_true", default=False)
    run_all.add_argument("--quaternary", action="store_true", default=False)
    run_all.add_argument("--groups", nargs="*", default=None, help="GROUP字段列表")
    run_all.add_argument("--top-n", type=int, default=3, help="输出top-N模板")

    # Deepen 参数
    run_all.add_argument("--deepen-sample", type=int, default=400, help="Deepen阶段字段池上限")
    run_all.add_argument("--sharpe", type=float, default=1.58)
    run_all.add_argument("--fitness", type=float, default=1.0)
    run_all.add_argument("--margin", type=float, default=0.0005)
    run_all.add_argument("--min-turnover", type=float, default=0.01)
    run_all.add_argument("--max-turnover", type=float, default=0.70)
    run_all.add_argument("--prune-per-field", type=int, default=0,
                         help="同字段top-k剪枝: 每字段保留alpha数(0=关)")

    # Submit 参数
    run_all.add_argument("--local-sc", action="store_true",
                         help="check前本地计算SC, 按阈值分级减少平台调用")
    run_all.add_argument("--sc-threshold", type=float, default=0.7,
                         help="SC阈值 (默认0.7, >= 此值标记绿色跳过check)")
    run_all.add_argument("--sc-marginal", type=float, default=0.05,
                         help="SC边缘带 (默认0.05, threshold-marginal~threshold 标记黄色)")
    run_all.add_argument("--os-alpha-count", type=int, default=100,
                         help="拉取已提交alpha数量用于SC计算 (默认100)")
    run_all.add_argument("--prune-corr", action="store_true",
                         help="提交前做相关性剪枝(拉PnL去重, 只读不耗额度)")
    run_all.add_argument("--page-delay", type=float, default=0.5,
                         help="翻页请求间隔秒数 (默认0.5s, 防止429限流)")
    run_all.add_argument("--use-datapack", default="runs/WebData_20260219_V0.10.9.zip",
                         help="使用本地数据包预筛数据集 (默认: runs/WebData_20260219_V0.10.9.zip)")
    run_all.add_argument("--datapack-dataset-mode", default="sweet_spot",
                         choices=["sweet_spot", "top_n", "all"],
                         help="数据集筛选模式: sweet_spot=甜点区, top_n=提交最多, all=全部")
    run_all.add_argument("--datapack-dataset-top", type=int, default=10,
                         help="数据包预筛: 数据集数量上限")

    run_all.set_defaults(func=cmd_run_all)

    # ═══════════════════════════════════════════════════════════════════
    # survey 子命令
    # ═══════════════════════════════════════════════════════════════════
    survey = sub.add_parser("survey", help="调研: 字段池×全模板 → 密度 → top-N")
    add_common(survey)
    survey.add_argument("--sample", type=int, default=80, help="字段池样本数")
    survey.add_argument("--backtest-sample", type=int, default=80,
                        help="从一阶表达式目录随机抽样回测数量(<=0=全部)")
    survey.add_argument("--all-combinations", action="store_true", default=True,
                        help="第一阶段计算已选字段的全部二元/三元/四元组合(默认开启)")
    survey.add_argument("--unary", action="store_true", default=True)
    survey.add_argument("--binary", action="store_true", default=False,
                        help="信号筛选后再启用二元分支")
    survey.add_argument("--ternary", action="store_true", default=False)
    survey.add_argument("--quaternary", action="store_true", default=False)
    survey.add_argument("--groups", nargs="*", default=None, help="GROUP字段列表")
    survey.add_argument("--top-n", type=int, default=3)
    survey.add_argument("--tasks-out", default="survey_tasks.json")
    survey.add_argument("--results-out", default="survey_results.json")
    survey.add_argument("--density-out", default="survey_density.json")
    survey.add_argument("--page-delay", type=float, default=0.5,
                        help="翻页请求间隔秒数 (默认0.5s, 防止429限流)")
    survey.add_argument("--use-datapack", default=None,
                        help="使用本地数据包预筛数据集 (如: runs/WebData_20260219_V0.10.9.zip)")
    survey.add_argument("--datapack-dataset-mode", default="sweet_spot",
                        choices=["sweet_spot", "top_n", "all"],
                        help="数据集筛选模式: sweet_spot=甜点区, top_n=提交最多, all=全部")
    survey.add_argument("--datapack-dataset-top", type=int, default=10,
                        help="数据包预筛: 数据集数量上限")
    survey.set_defaults(func=cmd_survey)

    # deepen子命令
    deepen = sub.add_parser("deepen", help="深挖: top-N模板×全字段 → 质量门")
    add_common(deepen)
    deepen.add_argument("--density-out", required=True, help="survey产出的密度报告")
    deepen.add_argument("--sample", type=int, default=400, help="深挖字段池上限")
    deepen.add_argument("--sharpe", type=float, default=1.2)
    deepen.add_argument("--fitness", type=float, default=0.7)
    deepen.add_argument("--margin", type=float, default=5.0)
    deepen.add_argument("--min-turnover", type=float, default=0.01)
    deepen.add_argument("--max-turnover", type=float, default=0.70)
    deepen.add_argument("--tasks-out", default="deepen_tasks.json")
    deepen.add_argument("--results-out", default="deepen_results.json")
    deepen.add_argument("--kept-out", default="deepen_kept.json")
    deepen.add_argument("--prune-per-field", type=int, default=0,
                        help="同字段top-k剪枝: 每字段保留alpha数(0=关)")
    deepen.add_argument("--page-delay", type=float, default=0.5,
                        help="翻页请求间隔秒数 (默认0.5s, 防止429限流)")
    deepen.set_defaults(func=cmd_deepen)

    # submit子命令
    submit = sub.add_parser("submit", help="提交: 列出kept → dry-run → check")
    submit.add_argument("--kept-out", required=True, help="deepen产出的kept文件")
    submit.add_argument("--execute", action="store_true", help="实际触发check")
    submit.add_argument("--prune-corr", action="store_true",
                        help="提交前做相关性剪枝(拉PnL去重, 只读不耗额度)")
    submit.add_argument("--local-sc", action="store_true",
                        help="check前本地计算SC, 按阈值分级减少平台调用")
    submit.add_argument("--sc-threshold", type=float, default=0.7,
                        help="SC阈值 (默认0.7, >= 此值标记绿色跳过check)")
    submit.add_argument("--sc-marginal", type=float, default=0.05,
                        help="SC边缘带 (默认0.05, threshold-marginal~threshold 标记黄色)")
    submit.add_argument("--os-alpha-count", type=int, default=100,
                        help="拉取已提交alpha数量用于SC计算 (默认100)")
    submit.set_defaults(func=cmd_submit)

    return ap


def main() -> None:
    """CLI入口."""
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()


__all__ = [
    "cmd_survey",
    "cmd_deepen",
    "cmd_submit",
    "cmd_run_all",
    "build_parser",
    "main",
]
