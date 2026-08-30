"""Survey-stage orchestration and its field/task helpers."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from alpha_operator_framework.cli.field_pipeline import _write_json
from alpha_operator_framework.database import AlphaDatabase, persist_workflow_row
from alpha_operator_framework.platform.simulation_gateway import simulate

ROOT = Path(__file__).resolve().parent.parent.parent
RUNS = ROOT / "runs"

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
    """把结果行批量持久化到数据库, 并登记到持久化试验账本."""
    from alpha_operator_framework.domain.overfitting import TrialLedger
    db = AlphaDatabase()
    trial_ledger = TrialLedger(persistent=True)
    try:
        n = 0
        for row in results:
            expr = row.get("expression") or ""
            fam = row.get("family") or "default"
            trial_ledger.record_trial(
                expression=expr,
                family=fam,
                region=settings.get("region", "GBR"),
                universe=settings.get("universe", "TOP700"),
                metrics=row,
            )
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
    from alpha_operator_framework.domain.pruning_components.semantic import semantic_prune_fields, SemanticPruneConfig
    kept, pruned = semantic_prune_fields(
        field_specs, SemanticPruneConfig(keep_per_category=keep_per_category))
    if pruned:
        print(f"  语义剪枝: 字段池 {len(field_specs)} → {len(kept)} "
              f"(每类留 {keep_per_category}, 剪掉 {len(pruned)})")
    return kept


def _convert_rows_to_specs(field_rows: list) -> list:
    """将平台字段行转换为 FieldSpec 列表."""
    from alpha_operator_framework.domain import fields
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
    from alpha_operator_framework.domain import fields
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
    scalar_pairs = fields.sample_scalar_field_pairs(field_specs, spec)
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
    results = asyncio.run(simulate(
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
        max_wait_seconds=getattr(args, "max_wait", 600.0),
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
    _write_json(results_path, {"settings": vars(args), "results": results})
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

__all__ = ["cmd_survey"]
