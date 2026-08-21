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
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Dict, Any, Optional, Sequence, Tuple
from datetime import datetime

# 项目模块
from alpha_operator_framework.domain import families
from alpha_operator_framework.domain import fields
from alpha_operator_framework.domain import density
from alpha_operator_framework.domain import operators
from alpha_operator_framework.domain import optimize  # 新增
from alpha_operator_framework.database import AlphaDatabase, persist_workflow_row


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

# 一阶算子冷启动白名单 (顺序即优先级)。
# 证据沉淀 (operator_signal_stats) 之前由这份 curated 顺序兜底;
# 有回测数据后由 select_curated_operators 按 hit_rate 接管挑选。
DEFAULT_FIRST_ORDER_OPS = (
    "rank", "zscore", "ts_rank", "ts_delta", "ts_zscore",
    "quantile", "normalize", "ts_std_dev", "ts_mean", "ts_sum", "ts_delay",
)


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
    sample_n: int = 80                 # 字段池大小
    backtest_sample_n: int = 80        # 一阶表达式抽样回测数量; <=0=全部
    min_coverage: float = 0.5          # 股票截面覆盖闸 (0=不过滤)
    min_date_coverage: float = 0.9       # 平台 dateCoverage 闸 (历史日期覆盖; 0=不过滤)
    prefer_cold: bool = True
    seed: int = 42
    top_n_templates: int = 3  # 用于密度评估的top-N

    # 模板选择
    include_unary: bool = True
    include_raw_first_order: bool = True   # 额外生成裸字段一阶 (rank(close) 等)
    use_template_library: bool = True      # 基于模板类库生成 4 族模板任务
    template_families: Optional[Tuple[str, ...]] = None  # 模板类库启用族 (None=4 族)
    template_categories: Optional[Tuple[str, ...]] = None  # category 过滤 (None=全匹配)
    include_binary: bool = False       # 信号筛选后再走二元分支
    include_ternary: bool = False
    include_quaternary: bool = False
    include_semantic_pairs: bool = True
    include_antonym_pairs: bool = True  # 自动发现相反指标配对 (bullish/bearish 等, difference 语义)
    include_paired_bases: bool = True  # 自动发现复合配对 (net_revision/spread, 带 denominator)
    group_fields: Optional[List[str]] = None

    # 模拟参数
    batch_size: int = 8
    neutralization: str = "SUBINDUSTRY"
    truncation: float = 0.08
    decay: float = 6.0

    # 第一阶段默认完整计算已选字段的所有组合；sample_n仍用于字段池大小。
    all_combinations: bool = True

    # 算子挑选 (证据驱动, 替代全量展开): None=每轮从 operator_signal_stats
    # 按 hit_rate 挑选 + 冷启动白名单兜底; 显式传Tuple则固定使用
    first_order_ops: Optional[Tuple[str, ...]] = None
    curated_top_n: int = 8                 # 挑选算子上限
    curated_min_trials: int = 3            # 淘汰判定最小样本数
    curated_cold_slots: int = 2            # 冷启动探索名额

    # 模板 operator 槽算子信号回流: 零命中且样本充足(trials>=该值)的算子淘汰, 其余全部展开
    operator_min_trials: int = 3

    # 总量预算: 已回测 alpha (alpha_details) + 本轮回测 <= 该值, 超出则裁剪/跳过
    max_alpha_budget: int = 1000


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
class SignalBranchConfig:
    """一阶信号筛选后的分支配置."""
    min_sharpe: float = 0.7
    min_fitness: float = 0.7
    max_signal_expressions: int = 200
    branch_backtest_sample_n: int = 80  # 每个分支回测数量; <=0=全部
    include_binary: bool = True
    include_second_order: bool = True
    group_ops: Optional[List[str]] = None
    groups: Optional[List[str]] = None


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
            import alpha_machine

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
            results = await alpha_machine.simulate(
                sim_tasks,
                _make_sim_config(survey_config),
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
            alpha_machine.write_json(results_file, {
                "stage": stage,
                "config": survey_config.__dict__,
                "branch_config": branch_config.__dict__,
                "results": results,
            })

            db = AlphaDatabase(output_dir / "alpha_research.db")
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


# ---------------------------------------------------------------------------
# AI友好的API接口
# ---------------------------------------------------------------------------

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
        database: 数据库文件路径; 缺省用 output_dir / "alpha_research.db"。
            研究闭环 (loop) 里必须与蒸馏沉淀库一致, 否则模板淘汰/蒸馏回填与
            survey 消费的模板不在同一个库, 回流管道断裂。

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
    # 统一数据库路径: catalog/模板库消费/结果持久化 都写同一个库
    db_path = database or (output_dir / "alpha_research.db")

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
            existing_alphas = catalog_db._get_connection().execute(
                "SELECT COUNT(*) FROM alpha_details").fetchone()[0]
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
            catalog_db.mark_expressions_pruned([catalog_db.compute_sha(e) for e in unsampled])
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
            import alpha_machine

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

            results = await alpha_machine.simulate(
                sim_tasks,
                _make_sim_config(config),
                wait_for_completion=True,  # 真实回测必须等待结果, 否则只有 submitted 状态、拿不到 sharpe/fitness
            )
            # simulate(wait_for_completion=True) 返回的是 simulation_results 表行, sharpe/fitness
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
            alpha_machine.write_json(results_file, {
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


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

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
    ap.add_argument("--operator-min-trials", type=int, default=3,
                    help="模板 operator 槽淘汰阈值: 零命中且样本充足(trials>=该值)的算子淘汰")
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
        operator_min_trials=args.operator_min_trials,
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
    "SignalBranchConfig",
    "OptimizeConfig",
    "WorkflowResult",
    "build_signal_branches",
    "run_signal_branches",
    "run_survey_with_fields",
    "run_full_workflow",
    "filter_alphas_for_optimization",
    "filter_high_quality_alphas",
    "filter_marginal_alphas",
    "filter_ready_for_submission",
]
