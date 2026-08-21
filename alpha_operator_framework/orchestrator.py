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
from alpha_operator_framework.database.repository import submission_wf_stage

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
    db = AlphaDatabase()  # 使用默认路径 data/alpha_research.db
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
    from alpha_operator_framework.domain.pruning import semantic_prune_fields, SemanticPruneConfig
    kept, pruned = semantic_prune_fields(
        field_specs, SemanticPruneConfig(keep_per_category=keep_per_category))
    if pruned:
        print(f"  语义剪枝: 字段池 {len(field_specs)} → {len(kept)} "
              f"(每类留 {keep_per_category}, 剪掉 {len(pruned)})")
    return kept


def _convert_rows_to_specs(field_rows: list) -> list:
    """将平台字段行转换为 FieldSpec 列表."""
    from alpha_operator_framework import fields
    field_specs = []
    for r in field_rows:
        cat = r.get("category") or ""
        category = str(cat.get("id") or "") if isinstance(cat, dict) else str(cat or "")
        field_specs.append(fields.FieldSpec(
            id=r["id"],
            dataset_id=r.get("dataset", {}).get("id", "") if isinstance(r.get("dataset"), dict) else r.get("dataset_id", ""),
            type=r.get("type", "MATRIX"),
            coverage=r.get("coverage", 0.0),
            date_coverage=float(r.get("dateCoverage") or 0.0),
            user_count=r.get("userCount", 0),
            alpha_count=r.get("alphaCount", 0),
            category=category,
            description=r.get("description", ""),
        ))
    return field_specs


def _fetch_field_specs_from_cache(
    region: str, universe: str, delay: int,
    dataset_id: str = "", search: str = "", data_type: str = "",
    force_refresh: bool = False, page_delay: float = 0.5
) -> list:
    """从缓存获取字段（本地优先，平台兜底）."""
    from alpha_operator_framework.cache import get_datafields
    field_rows = get_datafields(
        region=region,
        universe=universe,
        delay=delay,
        dataset_id=dataset_id,
        search=search,
        data_type=data_type,
        force_refresh=force_refresh,
        page_delay=page_delay,
    )
    return _convert_rows_to_specs(field_rows)


def _fetch_field_specs_auto(args, fields_file_type: str, root: Path) -> list:
    """自动模式：本地文件优先，平台缓存兜底."""
    from alpha_operator_framework.platform.local_fields import (
        default_dataset_file, default_fields_directory, load_local_field_directory, load_local_field_specs,
    )
    from alpha_operator_framework import fields

    # 1. 尝试本地文件
    local_dir = default_fields_directory(root, args.region, args.delay, args.universe)
    field_specs = []

    if args.dataset:
        types = (fields_file_type,) if fields_file_type in ("csv", "json") else ("json", "csv")
        candidates = [
            default_dataset_file(root, args.region, args.delay, args.universe, args.dataset, kind)
            for kind in types
        ]
        local_file = next((path for path in candidates if path.is_file()), None)
        if local_file:
            field_specs = load_local_field_specs(
                local_file, file_type=local_file.suffix[1:], region=args.region, universe=args.universe,
                delay=args.delay, dataset_id=args.dataset, search=args.search, data_type=args.type,
            )
    else:
        if local_dir.is_dir():
            field_specs = load_local_field_directory(
                local_dir, file_type=fields_file_type, region=args.region, universe=args.universe,
                delay=args.delay, dataset_id=args.dataset, search=args.search, data_type=args.type,
            )

    if field_specs:
        print(f"  本地字段目录 → {local_dir} ({len(field_specs)} 个匹配字段)")
        return field_specs

    # 2. 本地无数据，使用缓存（平台兜底）
    force_refresh = getattr(args, "force_refresh", False)
    page_delay = getattr(args, "page_delay", 0.5)
    field_specs = _fetch_field_specs_from_cache(
        args.region, args.universe, args.delay,
        dataset_id=args.dataset, search=args.search, data_type=args.type,
        force_refresh=force_refresh, page_delay=page_delay
    )
    print(f"  缓存字段（平台兜底）→ {len(field_specs)} 个匹配字段")
    return field_specs


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
                "expression_origin": t.expression_origin,
                "source_freq": t.meta.get("source_freq"),
                "fields_per_alpha": t.fields_per_alpha,
                "base_fields": list(t.base_fields),
                "pair_kind": t.meta.get("pair_kind"),
                "pair_stage": t.meta.get("pair_stage"),
                "pair_source": t.meta.get("pair_source"),
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

    # 1. 发现字段：auto 优先加载约定本地目录，缺失时再访问平台。
    from alpha_operator_framework import families, fields
    fields_file = getattr(args, "fields_file", None)
    field_source = getattr(args, "field_source", "auto")
    fields_file_type = getattr(args, "fields_file_type", "auto")
    force_refresh = getattr(args, "force_refresh", False)

    if fields_file and field_source == "platform":
        raise ValueError("--fields-file 与 --field-source platform 不能同时使用")
    if fields_file:
        from alpha_operator_framework.platform.local_fields import load_local_field_directory, load_local_field_specs
        field_path = Path(fields_file)
        loader = load_local_field_directory if field_path.is_dir() else load_local_field_specs
        field_specs = loader(
            field_path,
            file_type=fields_file_type,
            region=args.region,
            universe=args.universe,
            delay=args.delay,
            dataset_id=args.dataset,
            search=args.search,
            data_type=args.type,
        )
        print(f"  本地字段{'目录' if field_path.is_dir() else '文件'} → {field_path} ({len(field_specs)} 个匹配字段)")
    elif field_source == "platform":
        # 直接从平台获取（使用缓存）
        field_specs = _fetch_field_specs_from_cache(
            args.region, args.universe, args.delay,
            dataset_id=args.dataset, search=args.search, data_type=args.type,
            force_refresh=force_refresh
        )
        print(f"  平台字段（缓存）→ {len(field_specs)} 个匹配字段")
    elif field_source == "local":
        # 仅本地
        from alpha_operator_framework.platform.local_fields import (
            default_dataset_file, default_fields_directory, load_local_field_directory, load_local_field_specs,
        )
        local_dir = default_fields_directory(ROOT, args.region, args.delay, args.universe)
        if args.dataset:
            types = (fields_file_type,) if fields_file_type in ("csv", "json") else ("json", "csv")
            candidates = [
                default_dataset_file(ROOT, args.region, args.delay, args.universe, args.dataset, kind)
                for kind in types
            ]
            local_file = next((path for path in candidates if path.is_file()), None)
            field_specs = load_local_field_specs(
                local_file, file_type=local_file.suffix[1:], region=args.region, universe=args.universe,
                delay=args.delay, dataset_id=args.dataset, search=args.search, data_type=args.type,
            ) if local_file else []
        else:
            field_specs = load_local_field_directory(
                local_dir, file_type=fields_file_type, region=args.region, universe=args.universe,
                delay=args.delay, dataset_id=args.dataset, search=args.search, data_type=args.type,
            ) if local_dir.is_dir() else []
        if not field_specs:
            raise FileNotFoundError(f"本地字段目录不存在或无匹配字段: {local_dir}")
        print(f"  本地字段目录 → {local_dir} ({len(field_specs)} 个匹配字段)")
    else:
        # auto: 本地缓存优先，平台兜底
        field_specs = _fetch_field_specs_auto(
            args, fields_file_type, ROOT
        )

    # 1.5 基于数据包预筛数据集 (可选)
    use_datapack = getattr(args, 'use_datapack', None)
    if use_datapack:
        from alpha_operator_framework.domain.evaluation import (
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

    # 2. 字段采样
    ordinary_fields = field_specs  # 新策略系统不需要paired分组
    scalar_pairs = fields.sample_scalar_field_pairs(ordinary_fields, spec)
    scalars = [sf.expr for sf in scalar_pairs]
    pairs = fields.sample_pair_combinations(ordinary_fields, spec)
    triples = fields.sample_triple_combinations(ordinary_fields, spec)

    # 3. 构造任务 (支持多种策略: multi_stage/template/test/multivariate)
    from alpha_operator_framework.generation.creation_strategy import create_strategy, CompositeStrategy, CompositeConfig
    catalog_db = AlphaDatabase()  # 使用默认路径 data/alpha_research.db

    # 策略选择 (CLI参数 --strategy)
    strategy_type = getattr(args, "strategy", "template")  # 默认模板策略

    if strategy_type == "composite":
        # 组合策略: multi_stage + template
        strategies = [
            create_strategy("multi_stage", {"decay": getattr(args, "decay", 6.0)}),
            create_strategy("template", {
                "all_combinations": getattr(args, "all_combinations", True),
                "sample_n": args.sample,
                "decay": getattr(args, "decay", 6.0),
                "template_categories": tuple(getattr(args, "template_categories", []) or ()),
            }),
        ]
        strategy = CompositeStrategy(strategies, CompositeConfig(mode="parallel"))
    else:
        # 单策略
        config_dict = {
            "all_combinations": getattr(args, "all_combinations", True),
            "sample_n": args.sample,
            "decay": getattr(args, "decay", 6.0),
            "template_categories": tuple(getattr(args, "template_categories", []) or ()),
        }
        # test_operators 仅适用于 test 策略
        if strategy_type == "test":
            config_dict["test_operators"] = tuple(getattr(args, "test_operators", []) or ("rank", "quantile"))
        strategy = create_strategy(strategy_type, config_dict)

    # 执行策略生成任务
    tasks = strategy.generate_tasks(scalar_pairs, args.groups or [], templates=catalog_db.list_templates())

    print(f"  构造任务 {len(tasks)} 个 (strategy={strategy_type})")

    # 4. 幂等过滤: 「数据集+策略类」已回测过的组合整体跳过 (不 catalog / 不回测)
    dataset_id = getattr(args, "dataset", "") or ""
    done_strategies = set(catalog_db.list_backtest_record_strategies(
        region=args.region, universe=args.universe, delay=args.delay, dataset_id=dataset_id))
    if strategy_type in done_strategies:
        print(f"  跳过已回测组合: {strategy_type} ({args.region}/{args.universe})")
        catalog_db.close()
        return

    catalog_count = catalog_db.catalog_tasks(tasks, stage=strategy_type, backtest_settings={
        "region": args.region,
        "universe": args.universe,
        "delay": args.delay,
        "decay": getattr(args, "decay", 6.0),
        "neutralization": getattr(args, "neutralization", "SUBINDUSTRY"),
        "truncation": getattr(args, "truncation", 0.08),
    })
    # 表达式生成完即记录「数据集+策略类」, 供后续同组合幂等过滤
    catalog_db.upsert_backtest_record(
        region=args.region, universe=args.universe, delay=args.delay,
        dataset_id=dataset_id, strategy=strategy_type,
        expression_count=len(tasks), backtest_count=0)
    is_glb = args.region.upper() == "GLB"
    sampled_expressions = catalog_db.sample_catalog_expressions(
        [task.expression for task in tasks],
        limit=getattr(args, "backtest_sample", 80),
        seed=args.seed,
        base_fields_list=[list(task.base_fields) if task.base_fields else [] for task in tasks],
        is_glb=is_glb,
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

    # 6. 模拟 (顺序执行批次，等待每批完成后再继续)
    import alpha_machine
    results = asyncio.run(alpha_machine.simulate(
        [t.to_sim_dict() for t in sampled_tasks],
        _ns(
            region=args.region,
            universe=args.universe,
            delay=args.delay,
            batch_size=args.batch_size,
            neutralization=args.neutralization
        ),
        wait_for_completion=True,
        poll_interval=getattr(args, "poll_interval", 5.0),
        max_wait=getattr(args, "max_wait", 600.0),
    ))

    # 7. 回填元数据
    meta = {t.expression: t for t in sampled_tasks}
    for row in results:
        expr = row.get("expression")
        if expr in meta:
            t = meta[expr]
            row["family"] = t.family
            row["template_index"] = t.template_index
            row["expression_origin"] = t.expression_origin
            row["source_freq"] = t.meta.get("source_freq")
            row["fields_per_alpha"] = t.fields_per_alpha

    # 8. 写结果
    results_path = RUNS / args.results_out
    alpha_machine.write_json(results_path, {"settings": vars(args), "results": results})
    print(f"  results → {results_path} ({len(results)} 条)")

    # 8.5 持久化到数据库 (survey)
    n = _persist_rows(results, _survey_settings(args), stage="survey", status="pending")
    print(f"  db ← {n} 条 survey 结果 (data/alpha_research.db)")

    # 9. 计算密度
    from alpha_operator_framework.domain.density import compute_density, write_report, top_templates
    from alpha_operator_framework.domain.operators import ACCESS_LIMITED_OPS

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
    from alpha_operator_framework.domain.density import read_report, top_templates
    from alpha_operator_framework import families, fields

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
    import alpha_machine
    results = asyncio.run(alpha_machine.simulate(
        [t.to_sim_dict() for t in tasks],
        _ns(region=args.region, universe=args.universe, delay=args.delay),
        wait_for_completion=True,
        poll_interval=getattr(args, "poll_interval", 5.0),
        max_wait=getattr(args, "max_wait", 600.0),
    ))

    # 7. 质量门筛选
    gate = alpha_machine.QualityGate(
        args.sharpe, args.fitness, args.margin,
        args.min_turnover, args.max_turnover
    )
    kept, rejected = alpha_machine.filter_alpha_results(results, gate)

    # 7.5 同字段top-k剪枝 (可选, 防一字段垄断候选)
    if getattr(args, "prune_per_field", 0) > 0:
        from alpha_operator_framework.domain.pruning import field_topk_prune, FieldTopKConfig
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
    print(f"  db ← {n_kept} kept + {n_rejected} rejected (data/alpha_research.db)")


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
        from alpha_operator_framework.domain.pruning import correlation_prune
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
        from alpha_operator_framework.domain.pruning import local_sc_precheck, LocalCheckConfig
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
    db = AlphaDatabase()  # 使用默认路径 data/alpha_research.db
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
            db.update_alpha_status(alpha_id, status)  # 保留原 status_platform 行为 (兼容)
            db.update_wf_stage(alpha_id, submission_wf_stage(
                sc.get("result") if sc else None,
                pc.get("result") if pc else None,
            ))

            print(f"  {alpha_id}: SC={sc.get('result') if sc else 'n/a'}"
                  f"  PC={pc.get('result') if pc else 'n/a'}  → {status}")
    finally:
        db.close()

    if not args.execute:
        print("\n  [DRY RUN] 未触发平台 check。确认候选后加 --execute 运行完整提交终审。")
        print("  所有提交候选均需经过 DecisionApprovalEngine 6 维证据核验与人工决策。")
        return

    # 触发 6 维决策终审治理
    print(f"\n  🛡️ 正在对 {len(alpha_ids)} 个 Alpha 执行 DecisionApprovalEngine 提交前 6 维证据审计...")
    from alpha_operator_framework.domain.evidence import DecisionApprovalEngine, EvidenceLevel
    from alpha_operator_framework.domain.judge.evaluator import AlphaJudge

    db = AlphaDatabase(db_path=args.db)
    try:
        ready_count = 0
        for aid in alpha_ids:
            details = db.get_alpha_details(aid)
            if not details:
                continue
            is_m = {
                "sharpe": getattr(details, "sharpe", 0.0),
                "fitness": getattr(details, "fitness", 0.0),
                "turnover": getattr(details, "turnover", 0.0),
                "margin": getattr(details, "margin", 0.0),
            }
            checks = db.get_alpha_checks(aid)
            checks_dicts = [{"name": c.check_name, "result": c.result, "value": c.value} for c in checks] if checks else []
            rep = DecisionApprovalEngine.evaluate(
                alpha_id=aid,
                evidence_level=EvidenceLevel.PLATFORM_IS,
                is_metrics=is_m,
                checks=checks_dicts,
                sc_value=getattr(details, "sc_value", None),
                pc_value=getattr(details, "pc_value", None),
                judge_verdict="READY" if getattr(details, "grade", "") == "READY" else "REVIEW",
            )
            if rep.approved:
                ready_count += 1
                db.update_wf_stage(aid, "submission_ready")
                print(f"    ✅ Alpha {aid}: 通过 6 维证据终审，已标记为 submission_ready")
            else:
                db.update_wf_stage(aid, "needs_optimization")
                print(f"    ⚠️ Alpha {aid}: 终审未通过 (原因: {'; '.join(rep.rejection_reasons)})")

        print(f"\n  📊 提交终审审计完成: {ready_count}/{len(alpha_ids)} 个 Alpha 达标 SUBMISSION_READY。")
    finally:
        db.close()



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
        p.add_argument("--field-source", choices=["auto", "local", "platform"], default="auto",
                       help="字段来源：auto=本地目录优先后平台，local=仅本地，platform=仅平台")
        p.add_argument("--fields-file-type", choices=["auto", "csv", "json"], default="auto",
                       help="本地目录读取的文件类型；指定 --fields-file 时也用于声明预期格式")
        p.add_argument("--force-refresh", action="store_true",
                       help="强制刷新缓存，重新从平台获取数据")
        p.add_argument("--page-delay", type=float, default=0.5,
                       help="平台翻页间隔(秒)，防429")
        p.add_argument("--min-coverage", type=float, default=0.0)
        p.add_argument("--seed", type=int, default=42)
        p.add_argument("--backfill", type=int, default=120)
        p.add_argument("--winsorize-std", type=float, default=4.0)
        p.add_argument("--no-cold", action="store_true", help="不优先冷门字段")
        p.add_argument("--no-semantic-pairs", action="store_false", dest="semantic_pairs",
                       help="关闭 positive/negative 与 *_cap 的定向二元配对")
        p.add_argument("--pair", dest="pairs", action="append", default=[],
                       metavar="KIND:LEFT:RIGHT[:DENOMINATOR]",
                       help="Explicit binary base signal; repeat as needed")
        p.add_argument("--prune-fields", type=int, default=0,
                       help="语义剪枝: 每语义类保留字段代表数(0=关)")
        p.add_argument("--execute", action="store_true", help="实际消耗额度(默认dry-run)")
        p.add_argument("--poll-interval", type=float, default=5.0,
                       help="批次轮询间隔(秒)")
        p.add_argument("--max-wait", type=float, default=600.0,
                       help="每批次最大等待时间(秒)")

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
    run_all.add_argument("--backtest-sample", type=int, default=0,
                         help="从一阶表达式目录随机抽样回测数量(<=0=全部)")

    # 策略相关参数
    run_all.add_argument("--strategy", choices=["multi_stage", "template", "test", "multivariate", "composite"],
                         default="template", help="任务生成策略类型")
    run_all.add_argument("--template-categories", nargs="*", default=None,
                         help="限制使用的模板/字段 category (如 pv analyst; 默认全匹配)")
    run_all.add_argument("--test-operators", nargs="*", default=["rank", "quantile"],
                         help="测试策略使用的算子 (rank quantile winsorize)")

    # 兼容旧参数 (deprecated)
    run_all.add_argument("--unary", action="store_true", default=True,
                         help="[DEPRECATED] 策略系统自动处理")
    run_all.add_argument("--raw-first-order", action="store_false", default=True,
                         help="[DEPRECATED] 策略系统自动处理")
    run_all.add_argument("--template-library", action="store_true", default=True,
                         help="[DEPRECATED] 使用 --strategy template")
    run_all.add_argument("--no-template-library", action="store_false", dest="template_library",
                         help="[DEPRECATED] 使用 --strategy multi_stage")
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
    survey.add_argument("--backtest-sample", type=int, default=0,
                        help="从一阶表达式目录随机抽样回测数量(<=0=全部)")
    survey.add_argument("--all-combinations", action="store_true", default=True,
                        help="第一阶段计算已选字段的全部二元/三元/四元组合(默认开启)")
    # --- 策略相关参数 ---
    survey.add_argument("--strategy", choices=["multi_stage", "template", "test", "multivariate", "composite"],
                         default="template", help="任务生成策略类型")
    survey.add_argument("--template-categories", nargs="*", default=None,
                         help="限制使用的模板/字段 category (如 pv analyst; 默认全匹配)")
    survey.add_argument("--test-operators", nargs="*", default=["rank", "quantile"],
                         help="测试策略使用的算子 (rank quantile winsorize)")

    # --- 兼容旧参数 (deprecated) ---
    survey.add_argument("--template-library", action="store_true", default=True,
                         help="[DEPRECATED] 使用 --strategy template")
    survey.add_argument("--no-template-library", action="store_false", dest="template_library",
                         help="[DEPRECATED] 使用 --strategy multi_stage")
    survey.add_argument("--unary", action="store_true", default=True,
                         help="[DEPRECATED] 策略系统自动处理")
    survey.add_argument("--raw-first-order", action="store_false", default=True,
                         help="[DEPRECATED] 策略系统自动处理")
    survey.add_argument("--binary", action="store_true", default=False,
                         help="[DEPRECATED] 策略系统自动处理")
    survey.add_argument("--ternary", action="store_true", default=False,
                         help="[DEPRECATED] 策略系统自动处理")
    survey.add_argument("--quaternary", action="store_true", default=False,
                         help="[DEPRECATED] 策略系统自动处理")
    survey.add_argument("--groups", nargs="*", default=None, help="GROUP字段列表")
    survey.add_argument("--top-n", type=int, default=3)
    survey.add_argument("--tasks-out", default="survey_tasks.json")
    survey.add_argument("--results-out", default="survey_results.json")
    survey.add_argument("--density-out", default="survey_density.json")
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
