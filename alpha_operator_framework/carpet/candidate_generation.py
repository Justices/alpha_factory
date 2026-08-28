"""Candidate expression generation for carpet mining."""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Tuple

from alpha_operator_framework.carpet.models import CarpetMiningConfig
from alpha_operator_framework.domain.ast import BreederConfig, SymbolicTreeBreeder
from alpha_operator_framework.domain.families import Task as _Task
from alpha_operator_framework.distill.template_pruner import matches_prune_rule

logger = logging.getLogger(__name__)


def Task(family, template_index, fields_per_alpha, expression, decay, meta):
    """Build a task while keeping the generation code declaration-oriented."""
    return _Task(
        expression=expression,
        template_index=template_index,
        family=family,
        fields_per_alpha=fields_per_alpha,
        decay=decay,
        meta=meta,
    )


def generate_candidate_expressions_by_category(
    config: CarpetMiningConfig, db, fields: List[Dict[str, Any]],
) -> Dict[str, List[Any]]:
    """Generate and classify the full carpet-mining candidate pool."""
    categories: Dict[str, List[Any]] = {
        "ts_momentum": [], "mean_reversion": [], "macd_velocity": [], "relative_ratio": [],
        "asymmetric_risk": [], "sector_decomposition": [], "three_tier_scaling": [],
        "cross_interaction": [], "evolved_distillation": [], "symbolic_evolution": [],
    }
    atomic_fields: List[Tuple[str, str, str]] = []
    for field in fields:
        field_id = field["id"]
        field_type = field.get("type", "MATRIX")
        if field_type in ("VECTOR", "EVENT"):
            atomic = f"winsorize(ts_backfill(vec_avg({field_id}), 120), std=4.0)"
        elif "rank" in field_id or "score" in field_id:
            atomic = f"rank({field_id})"
        else:
            atomic = field_id
        atomic_fields.append((field_id, atomic, field.get("dataset_id", "")))
    if not atomic_fields:
        return categories

    neutralization = config.neutralization.lower()
    for field_id, atomic, dataset in atomic_fields:
        for window in (20, 60, 120):
            categories["ts_momentum"].extend([
                Task("ts_momentum", 1, 1, f"group_neutralize(rank(ts_delta({atomic}, {window})), {neutralization})", config.decay, {"dataset": dataset, "field": field_id, "window": window}),
                Task("ts_momentum", 2, 1, f"group_neutralize(ts_decay_linear(ts_rank({atomic}, {window}), 10), {neutralization})", config.decay, {"dataset": dataset, "field": field_id, "window": window}),
            ])
        for window in (10, 22):
            categories["mean_reversion"].extend([
                Task("mean_reversion", 3, 1, f"-1.0 * group_neutralize(rank(ts_delta({atomic}, {window})), {neutralization})", config.decay, {"dataset": dataset, "field": field_id, "window": window}),
                Task("mean_reversion", 4, 1, f"-1.0 * group_neutralize(ts_rank({atomic}, {window}) - ts_rank({atomic}, {window * 3}), {neutralization})", config.decay, {"dataset": dataset, "field": field_id, "window": window}),
            ])
        categories["macd_velocity"].extend([
            Task("macd_velocity", 5, 1, f"group_neutralize(rank(ts_decay_linear({atomic}, 10)) - rank(ts_decay_linear({atomic}, 30)), {neutralization})", 10, {"dataset": dataset, "field": field_id}),
            Task("macd_velocity", 6, 1, f"group_neutralize(rank(ts_decay_linear({atomic}, 30)) - rank(ts_decay_linear({atomic}, 90)), {neutralization})", 20, {"dataset": dataset, "field": field_id}),
        ])
        for delta_window, std_window in ((10, 20), (20, 40), (60, 120)):
            categories["asymmetric_risk"].append(Task("asymmetric_risk", 9, 1, f"group_neutralize(rank(ts_delta({atomic}, {delta_window})) / (0.01 + rank(ts_std_dev({atomic}, {std_window}))), {neutralization})", config.decay, {"dataset": dataset, "field": field_id, "window_delta": delta_window, "window_std": std_window}))
        for window in (22, 63, 126):
            categories["sector_decomposition"].extend([
                Task("sector_decomposition", 11, 1, f"ts_zscore({atomic}, {window}) - ts_zscore(group_neutralize({atomic}, {neutralization}), {window})", config.decay, {"dataset": dataset, "field": field_id, "window": window, "decomp_type": "beta_drift"}),
                Task("sector_decomposition", 12, 1, f"group_neutralize(ts_rank(group_neutralize({atomic}, {neutralization}), {window}) - ts_rank({atomic}, {window}), {neutralization})", config.decay, {"dataset": dataset, "field": field_id, "window": window, "decomp_type": "idiosyncratic_divergence"}),
            ])
        for window in (22, 66, 120, 240):
            categories["three_tier_scaling"].extend([
                Task("three_tier_scaling", 13, 1, f"ts_scale(group_rank({atomic}, {neutralization}), {window})", config.decay, {"dataset": dataset, "field": field_id, "window": window, "tier_type": "ts_scale_industry"}),
                Task("three_tier_scaling", 14, 1, f"ts_rank(group_rank({atomic}, {neutralization}), {window})", config.decay, {"dataset": dataset, "field": field_id, "window": window, "tier_type": "ts_rank_industry"}),
                Task("three_tier_scaling", 15, 1, f"ts_zscore(group_rank({atomic}, {neutralization}), {window})", config.decay, {"dataset": dataset, "field": field_id, "window": window, "tier_type": "ts_zscore_industry"}),
                Task("three_tier_scaling", 16, 1, f"ts_scale(group_rank({atomic}, bucket(rank(cap), range='0.1, 1, 0.1')), {window})", config.decay, {"dataset": dataset, "field": field_id, "window": window, "tier_type": "ts_scale_market_cap_bucket"}),
            ])

    for index, (field_id, atomic, dataset) in enumerate(atomic_fields):
        for other_id, other_atomic, other_dataset in atomic_fields[index + 1:min(index + 4, len(atomic_fields))]:
            meta = {"dataset": f"{dataset}+{other_dataset}", "fields": [field_id, other_id]}
            categories["relative_ratio"].extend([
                Task("relative_ratio", 7, 2, f"group_neutralize(rank({atomic}) - rank({other_atomic}), {neutralization})", config.decay, meta),
                Task("relative_ratio", 8, 2, f"group_neutralize(rank({atomic}) / (0.01 + rank({other_atomic})), {neutralization})", config.decay, meta),
            ])
    by_dataset: Dict[str, List[Tuple[str, str]]] = {}
    for field_id, atomic, dataset in atomic_fields:
        by_dataset.setdefault(dataset, []).append((field_id, atomic))
    datasets = list(by_dataset)
    for index, first_dataset in enumerate(datasets):
        for second_dataset in datasets[index + 1:]:
            for first_id, first_atomic in by_dataset[first_dataset][:3]:
                for second_id, second_atomic in by_dataset[second_dataset][:3]:
                    categories["cross_interaction"].append(Task("cross_interaction", 10, 2, f"group_neutralize(rank(ts_decay_linear({first_atomic}, 20)) * rank({second_atomic}), {neutralization})", 15, {"dataset": f"{first_dataset}*{second_dataset}", "fields": [first_id, second_id]}))

    _add_database_templates(categories, config, db, atomic_fields, neutralization)
    try:
        categories["symbolic_evolution"] = SymbolicTreeBreeder(BreederConfig(seed=config.seed)).breed_task_cohort(fields=fields, default_decay=config.decay, neutralization=config.neutralization)
    except Exception as error:
        logger.warning("符号语法树杂交引擎执行异常: %s", error)
    rules = db.get_active_prune_rules() if hasattr(db, "get_active_prune_rules") else []
    for category, tasks in categories.items():
        categories[category] = [task for task in tasks if not any(matches_prune_rule(task.expression, rule) for rule in rules)]
    logger.info("共生成 %s 条候选表达式，分布在 %s 个大类中", sum(map(len, categories.values())), len(categories))
    return categories


def _add_database_templates(categories, config, db, atomic_fields, neutralization) -> None:
    if not (db and hasattr(db, "list_templates")):
        return
    try:
        templates = db.list_templates(active_only=True)
        for template in templates:
            raw = template.expression_template
            if not raw or ("{" not in raw and "<" not in raw):
                continue
            variants = [raw]
            for placeholder, operators in (("op_ts", ["ts_scale", "ts_rank", "ts_zscore", "ts_decay_linear", "ts_delta"]), ("op_group", ["group_rank", "group_neutralize", "group_zscore", "group_scale"]), ("op_cross", ["ts_corr"])):
                if f"{{{placeholder}}}" in raw or f"<{placeholder}>" in raw:
                    variants = [variant.replace(f"{{{placeholder}}}", operator).replace(f"<{placeholder}>", operator) for operator in operators for variant in variants]
            for variant in variants:
                slots = sorted(set(re.findall(r"\{([a-d])\}", variant)))
                if not slots or len(slots) > len(atomic_fields):
                    continue
                ranges = [range(min(len(atomic_fields), limit)) for limit in (8, 10, 6, 4)[:len(slots)]]
                # Preserve the original bounded combinations without repeating an index.
                def add(indexes):
                    if len(set(indexes)) != len(indexes):
                        return
                    selected = [atomic_fields[index] for index in indexes]
                    expression = variant.replace("{group}", neutralization).replace("<group>", neutralization).replace("{decay}", str(config.decay)).replace("<decay>", str(config.decay)).replace("{window}", "20").replace("<window>", "20").replace("{w}", "20").replace("{w1}", "20").replace("{w2}", "40")
                    for slot, (_, atomic, _) in zip(slots, selected):
                        expression = expression.replace(f"{{{slot}}}", atomic).replace(f"<{slot}>", atomic)
                    categories["evolved_distillation"].append(Task(template.family or "evolved_distillation", template.template_index or 999, len(selected), expression, config.decay, {"dataset": "+".join(item[2] for item in selected) if len(selected) < 4 else "multi_dataset", "fields": [item[0] for item in selected], "from_db_template": template.name}))
                if len(slots) == 1:
                    for index in range(len(atomic_fields)):
                        add((index,))
                elif len(slots) == 2:
                    for first in ranges[0]:
                        for second in range(first + 1, min(len(atomic_fields), 10)):
                            add((first, second))
                elif len(slots) == 3:
                    for first in ranges[0]:
                        for second in range(first + 1, min(len(atomic_fields), 5)):
                            for third in range(second + 1, min(len(atomic_fields), 6)):
                                add((first, second, third))
                elif len(slots) == 4:
                    add((0, 1, 2, 3))
    except Exception as error:
        logger.debug("加载 DB 进化模板库跳过: %s", error)
