"""Survey workflow implementation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Optional, Sequence

from alpha_operator_framework.cli.field_pipeline import _write_json
from alpha_operator_framework.database import AlphaDatabase, get_database_path
from alpha_operator_framework.domain import density, families, fields, operators
from alpha_operator_framework.platform.simulation_gateway import simulate
from alpha_operator_framework.workflow.models import (
    DEFAULT_FIRST_ORDER_OPS,
    DeepenConfig,
    SurveyConfig,
    WorkflowResult,
)


async def run_survey_with_fields(
    field_specs: Sequence[fields.FieldSpec],
    config: SurveyConfig,
    output_dir: Path = Path("runs"),
    execute: bool = False,
    database: Optional[Path] = None
) -> WorkflowResult:
    """使用指定字段列表运行Survey阶段.

    Args:
        field_specs: 字段规格列表(由AI或用户提供,不随机采样)
        config: Survey配置
        output_dir: 输出目录 (任务/结果文件)
        execute: 是否实际执行模拟(False则dry-run)
        database: 数据库文件路径; 缺省为全局主库 `data/alpha_research.db`。

    Returns:
        WorkflowResult: 包含任务、结果、密度等信息
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    # 统一全局主数据库路径 (支持测试传入自定义 output_dir 隔离)
    if database is not None:
        db_path = Path(database)
    elif str(output_dir) not in ("runs", ".", ""):
        db_path = output_dir / "alpha_research.db"
    else:
        db_path = get_database_path()

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
                min_date_coverage=config.min_date_coverage,
                prefer_cold=config.prefer_cold,
                seed=config.seed,
                all_combinations=config.all_combinations,
            )
            selected = fields.sample_field_specs(field_specs, spec)

        # 预处理成标量表达式 (VECTOR 字段按轮转分配聚合算子, 消除近亲冗余)
        scalars = [e for _, e in fields.preprocess_fields_rotated(selected, seed=config.seed)]

        # 2. 构造任务
        # 算子挑选 (证据驱动): 不做全量展开/随机抽样 —— 从 operator_signal_stats
        # 按 hit_rate 挑选有证据的算子, 零命中且样本充足的淘汰, 缺口用白名单补齐。
        if config.first_order_ops is not None:
            curated_ops = list(config.first_order_ops)
        else:
            from alpha_operator_framework.distill.operator_signals import select_curated_operators
            from alpha_operator_framework.database import AlphaDatabase as _AlphaDB
            _ops_db = _AlphaDB(db_path)
            try:
                curated_ops = select_curated_operators(
                    _ops_db,
                    default_ops=DEFAULT_FIRST_ORDER_OPS,
                    region=config.region, universe=config.universe, delay=config.delay,
                    top_n=config.curated_top_n,
                    min_trials=config.curated_min_trials,
                    cold_slots=config.curated_cold_slots,
                )
            finally:
                _ops_db.close()
            print(f"  算子挑选: {curated_ops}")

        tasks = []
        unary_tasks = []
        semantic_pair_tasks = []
        antonym_pair_tasks = []
        paired_base_tasks = []
        if config.include_unary:
            # 调查阶段用挑选出的算子展开一阶表达式 (curated, 非全量/随机)。
            unary_tasks = families.first_order_task_factory(scalars, ops_set=curated_ops, decay=config.decay)
            # 裸字段一阶 (可选, 默认开启): 直接作用于原始字段id, 与预处理一阶并存
            if config.include_raw_first_order:
                # 只对 MATRIX 字段生成裸字段一阶。VECTOR 字段不能直接 ts_delta/rank,
                # 必须先 vec_ 归约成标量 (已由上面的 preprocess_field 处理); 若对 VECTOR
                # 字段裸一阶, 会产生 ts_delta(vec_field, N) 这类非法表达式, 平台回测直接 ERROR。
                raw_tasks = families.raw_first_order_task_factory(
                    [f.id for f in selected if f.type != "VECTOR"], ops_set=curated_ops, decay=config.decay)
                unary_tasks.extend(raw_tasks)
            tasks.extend(unary_tasks)

        if config.include_semantic_pairs:
            from alpha_operator_framework.domain.semantic_pairs import semantic_pair_task_factory
            semantic_pair_tasks = semantic_pair_task_factory(
                selected,
                decay=config.decay,
            )
            tasks.extend(semantic_pair_tasks)

        # 相反词配对: 自动发现同 dataset 内、名称只在相反词上不同的字段对
        # (如 bullish/bearish、up/down), 生成 difference 基准信号。与 semantic_pairs
        # 互补 —— 它覆盖 positive/negative 之外的相反形态。
        if config.include_antonym_pairs:
            from alpha_operator_framework.domain.antonyms import antonym_pair_tasks as _antonym_factory
            antonym_pair_tasks = _antonym_factory(selected, decay=config.decay)
            tasks.extend(antonym_pair_tasks)

        # 复合配对 (net_revision / spread): 自动发现带分母的经济指标组
        # (如 raisednum/lowerednum/num 的净上调比例, high/low/mean 的离散度),
        # 与 antonym 的纯差值配对互补 —— 它们需要额外 denominator 归一化。
        if config.include_paired_bases:
            from alpha_operator_framework.domain.paired_bases import discover_pair_specs, paired_base_task_factory
            compound_specs = discover_pair_specs(selected)
            paired_base_tasks = paired_base_task_factory(compound_specs, selected, decay=config.decay)
            tasks.extend(paired_base_tasks)

        # 模板类库策略 (binary/ternary/quaternary); use_template_library=False 回退旧 factory
        if config.use_template_library:
            from alpha_operator_framework.database import AlphaDatabase
            from alpha_operator_framework.generation.template_library import TemplateStrategyConfig, template_creation_strategy
            scalar_pairs = [
                fields.ScalarField(expr=e, category=f.category, field_id=f.id)
                for f, e in fields.preprocess_fields_rotated(selected, seed=config.seed)
            ]
            tpl_db = AlphaDatabase(db_path)
            # 算子信号回流 (第6→2): 查本 region/universe/delay 的算子级信号统计,
            # 注入 operator 槽生成 —— 有信号算子优先展开、零命中且样本充足淘汰、冷启动兜底。
            operator_signal_rows = (
                tpl_db.get_operator_signal_stats(
                    region=config.region, universe=config.universe, delay=config.delay,
                    min_trials=1, limit=1000,
                )
                if hasattr(tpl_db, "get_operator_signal_stats") else []
            )
            families_to_use = config.template_families or ("binary", "ternary", "quaternary")
            tpl_cfg = TemplateStrategyConfig(
                families=families_to_use,
                all_combinations=config.all_combinations,
                sample_n=config.sample_n,
                decay=config.decay,
                template_categories=config.template_categories or (),
            )
            # vector_fields: 裸 VECTOR 字段 id, 供含 vec_ 槽位的模板 (vector 槽)。
            # 生成期类型约束 —— vector 槽只填裸 VECTOR 字段, 从源头杜绝
            # vec_count(winsorize(ts_backfill(vec_sum(field)...))) 双重嵌套。
            vector_fields = [f.id for f in selected if f.type == "VECTOR"]
            for fam in families_to_use:
                # binary/ternary/quaternary 受 include_* 开关控制; distilled 等附加族默认启用
                if fam in ("binary", "ternary", "quaternary") and not getattr(config, f"include_{fam}"):
                    continue
                tpls = tpl_db.list_templates(families=(fam,))
                if tpls:
                    tasks.extend(template_creation_strategy(
                        tpls, scalar_pairs, config.group_fields or [], tpl_cfg,
                        vector_fields=vector_fields,
                        operator_signals=operator_signal_rows or None,
                        operator_min_trials=config.operator_min_trials,
                    ))
            tpl_db.close()
        else:
            if config.include_binary:
                max_pairs = None if config.all_combinations else config.sample_n
                tasks.extend(families.binary_factory(scalars, max_pairs=max_pairs))
            if config.include_ternary:
                max_triples = None if config.all_combinations else config.sample_n
                tasks.extend(families.ternary_factory(scalars, max_triples=max_triples))
            if config.include_quaternary and config.group_fields:
                tasks.extend(families.quaternary_factory(
                    scalars, config.group_fields, max_quadruples=None
                ))

        # 3. 淘汰匹配 + 一阶表达式全量入目录，再随机抽样回测。
        from alpha_operator_framework.database import AlphaDatabase
        from alpha_operator_framework.distill.template_pruner import matches_prune_rule
        catalog_db = AlphaDatabase(db_path)

        # 生成表达式时就地淘汰: 匹配规则库, 命中的表达式不进入 catalog、不消耗回测额度。
        # 这是比 template_library.active=0 更彻底的一层 —— 按表达式模式匹配, 能淘汰
        # 模板的所有变体 (如所有嵌套 ts_delta 的表达式, 不管来自哪个模板族)。
        # (注: vec 双重嵌套不再需要运行时兜底 —— vector 槽约束 (vec 槽只填裸 VECTOR
        #  字段) 已在生成源头保证, 2026-08-20 已移除 has_vec_nesting 兜底检查。)
        prune_rules = catalog_db.get_prune_rules(active_only=True)
        def _blocked(expr: str) -> bool:
            # 规则库匹配 (模板淘汰规则)
            return bool(prune_rules) and any(matches_prune_rule(expr, r) for r in prune_rules)

        before = len(tasks)
        tasks = [t for t in tasks if not _blocked(t.expression)]
        unary_tasks = [t for t in unary_tasks if not _blocked(t.expression)]
        semantic_pair_tasks = [t for t in semantic_pair_tasks if not _blocked(t.expression)]
        antonym_pair_tasks = [t for t in antonym_pair_tasks if not _blocked(t.expression)]
        paired_base_tasks = [t for t in paired_base_tasks if not _blocked(t.expression)]
        pruned_count = before - len(tasks)
        if pruned_count:
            print(f"  淘汰匹配过滤 {pruned_count} 条表达式 (规则 {len(prune_rules)} 条)")

        # 回测设置 (6 核心字段): 随表达式写入 settings JSON 的 "backtest" 键, 供追溯回测参数
        backtest_settings = {
            "region": config.region,
            "universe": config.universe,
            "delay": config.delay,
            "decay": config.decay,
            "neutralization": config.neutralization,
            "truncation": config.truncation,
        }
        other_tasks = [t for t in tasks if t not in unary_tasks and t not in semantic_pair_tasks
                       and t not in antonym_pair_tasks and t not in paired_base_tasks]
        # 按 stage 分组 + 幂等过滤: 「数据集+策略」已回测过的组合整体跳过 (不 catalog / 不回测),
        # 避免同一数据集 + 同一策略在多轮闭环里重复生成+回测消耗额度。
        stage_tasks = {
            "first_order": unary_tasks,
            "semantic_pair": semantic_pair_tasks,
            "antonym_pair": antonym_pair_tasks,
            "paired_base": paired_base_tasks,
            "survey": other_tasks,
        }
        done_strategies = set(catalog_db.list_backtest_record_strategies(
            region=config.region, universe=config.universe, delay=config.delay,
            dataset_id=config.dataset_id or ""))
        catalog_count = 0
        active_tasks = []
        expr_to_stage: Dict[str, str] = {}  # expression → stage, 供回测后按 stage 回填 backtest_count
        for stage, stasks in stage_tasks.items():
            if stage in done_strategies:
                print(f"  跳过已回测组合: {stage} ({config.region}/{config.universe})")
                continue
            if not stasks:
                continue
            catalog_count += catalog_db.catalog_tasks(stasks, stage=stage, backtest_settings=backtest_settings)
            # 表达式生成完即记录「数据集+策略」, 供后续同组合幂等过滤
            catalog_db.upsert_backtest_record(
                region=config.region, universe=config.universe, delay=config.delay,
                dataset_id=config.dataset_id or "", strategy=stage,
                expression_count=len(stasks), backtest_count=0)
            active_tasks.extend(stasks)
            for t in stasks:
                expr_to_stage[t.expression] = stage
        tasks = active_tasks  # 后续抽样/落选标记只针对「未回测组合」的任务
        # 总量预算护栏: 已回测 alpha (alpha_details) + 本轮回测 <= max_alpha_budget。
        # 平台账户对 alpha 总量有上限 (1000), 超预算时裁剪本轮回测数, 额度耗尽则跳过回测。
        budget = int(getattr(config, "max_alpha_budget", 0) or 0)
        backtest_n = config.backtest_sample_n
        if budget > 0:
            existing_alphas = catalog_db.get_total_alpha_details_count()
            allowance = budget - int(existing_alphas)
            requested = backtest_n if backtest_n > 0 else allowance
            if requested > allowance:
                print(f"  预算裁剪: alpha总量上限{budget}, 已有{existing_alphas}, "
                      f"本轮回测 {requested}→{max(allowance, 0)}")
                backtest_n = max(allowance, 0)

        if backtest_n == 0:
            sampled_tasks = []
            sampled_expressions: set = set()
        else:
            sampled_expressions = catalog_db.sample_catalog_expressions(
                [task.expression for task in tasks],
                limit=backtest_n,
                seed=config.seed,
            )
            sampled_set = set(sampled_expressions)
            sampled_tasks = [t for t in tasks if t.expression in sampled_set]
        # 落选标记: 本轮 catalog 的表达式里, 没被抽中回测的标记 pruned (被剪枝),
        # 让 alpha_expressions 状态完整 —— completed=回测完成 / pruned=本轮落选 / pending=待回测。
        # 落选不是终态: 下轮若被抽中, create_simulation_batch 会回填 batch_id 并置回 pending。
        unsampled = [t.expression for t in tasks if t.expression not in sampled_set]
        if unsampled:
            catalog_db.mark_expressions_pruned([
                catalog_db.compute_alpha_sha(e, backtest_settings) for e in unsampled
            ])
        catalog_db.close()

        # 4. 写入本次实际回测的任务列表
        tasks_file = output_dir / f"survey_tasks_{config.region}_{config.dataset_id or 'all'}.json"
        _write_tasks(sampled_tasks, tasks_file, config.__dict__)

        if not execute:
            return WorkflowResult(
                success=True,
                stage="survey",
                message=f"[DRY-RUN] 一阶目录{catalog_count}个，抽样{len(sampled_tasks)}个回测",
                tasks_generated=len(sampled_tasks),
                tasks_file=tasks_file,
                config=config.__dict__
            )

        # 4. 模拟(需alpha_machine)
        try:
            sim_tasks = [
                {
                    "expression": t.expression,
                    "decay": config.decay,
                    "family": t.family,
                    "template_index": t.template_index,
                    "fields_per_alpha": t.fields_per_alpha
                }
                for t in sampled_tasks
            ]

            results = await simulate(
                sim_tasks,
                _make_sim_config(config),
                wait_for_completion=True,
                poll_interval=5.0,
                max_wait_seconds=600.0,
            )
            # simulate 返回的是 simulation_results 表行, sharpe/fitness
            # 嵌套在 result_json.is 里; 展开到顶层, 让下游 density/distill 统一读顶层指标。
            results = _flatten_sim_results(results)

            # 回填 backtest_count: 按 stage 统计实际回测数 (simulate 完成后)
            from collections import Counter
            backtest_by_stage = Counter(expr_to_stage.get(t.expression) for t in sampled_tasks)
            _bdb = AlphaDatabase(db_path)
            for _stage, _cnt in backtest_by_stage.items():
                if _stage:
                    _bdb.upsert_backtest_record(
                        region=config.region, universe=config.universe, delay=config.delay,
                        dataset_id=config.dataset_id or "", strategy=_stage,
                        expression_count=0, backtest_count=_cnt)
            _bdb.close()

            # 5. 写结果
            results_file = output_dir / f"survey_results_{config.region}_{config.dataset_id or 'all'}.json"
            _write_json(results_file, {
                "config": config.__dict__,
                "results": results
            })

            # 5.1 持久化到数据库 (survey)
            try:
                from alpha_operator_framework.database import AlphaDatabase, persist_workflow_row

                db = AlphaDatabase(db_path)
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
                # 实际写库是 db_path (survey 消费/蒸馏沉淀统一库), 不要显示 output_dir 误导
                print(f"  db ← {n} 条 survey 结果 ({db_path})")
            except Exception as e:
                print(f"  ⚠ 数据库写入失败: {e}")

            # 6. 计算密度
            # 回填元数据
            meta = {t.expression: t for t in sampled_tasks}
            for row in results:
                expr = row.get("expression")
                if expr in meta:
                    t = meta[expr]
                    row["family"] = t.family
                    row["template_index"] = t.template_index
                    row["fields_per_alpha"] = t.fields_per_alpha
                    # expression_origin 是 density 聚合的关键区分维度: 模板库模板
                    # (unary_template) vs 一阶算子 (first_order) 都标记 family=unary,
                    # 缺了它 density 无法区分两类, 蒸馏淘汰会误伤一阶算子。
                    row["expression_origin"] = t.expression_origin
                    if t.meta and t.meta.get("source_freq"):
                        row["source_freq"] = t.meta.get("source_freq")
                    # 回填配对元数据, 供 pair_signal 沉淀识别「这条结果属于哪个配对」
                    if t.meta and t.meta.get("pair_spec"):
                        row["pair_spec"] = t.meta["pair_spec"]
                        row["pair_kind"] = t.meta.get("pair_kind", "")

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
                message=f"完成: 目录{catalog_count}个→抽样{len(sampled_tasks)}个→{len(results)}结果→密度{len(density_rows)}",
                tasks_generated=len(sampled_tasks),
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
                tasks_generated=len(sampled_tasks),
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


def _flatten_sim_results(results: list) -> list:
    """展开 simulate 返回的 simulation_results 行: result_json.is.* → 顶层.

    simulate(wait_for_completion=True) 返回的是 simulation_results 表行, sharpe/fitness/
    pnl/longCount/shortCount 等指标嵌套在 result_json.is 里; 而 SignalGate._metric 只查
    顶层或 is 子键, 读不到 result_json 这一层。这里把 is 统计提升到顶层, 让下游
    density/distill 统一读顶层指标, 并把完整 alpha 详情留在 _alpha_details 备查。
    """
    out = []
    for row in results or []:
        r = dict(row)
        rj = r.get("result_json")
        if isinstance(rj, str):
            try:
                rj = json.loads(rj)
            except Exception:
                rj = None
        is_block = rj.get("is") if isinstance(rj, dict) else None
        if isinstance(is_block, dict):
            # 顶层优先, 缺失才用 is.* 补 (不覆盖可能已存在的顶层字段)
            for k, v in is_block.items():
                r.setdefault(k, v)
            r["_alpha_details"] = rj
        out.append(r)
    return out


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


__all__ = ["run_survey_with_fields"]
