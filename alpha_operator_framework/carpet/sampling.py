"""Cohort sampling for carpet mining."""

from __future__ import annotations

import hashlib
import logging
import random
from collections import defaultdict
from typing import Dict, List

from alpha_operator_framework.carpet.field_catalog import _extract_task_fields
from alpha_operator_framework.carpet.models import CarpetMiningConfig
from alpha_operator_framework.domain.families import Task

logger = logging.getLogger(__name__)


def sample_cohort(config: CarpetMiningConfig, db, categorized_tasks: Dict[str, List[Task]]) -> List[Task]:
    """Sample each family while prioritizing untested expressions and field coverage."""
    cohort: List[Task] = []
    existing_shas: set[str] = set()
    if db:
        try:
            rows = db._get_connection().execute(
                "SELECT expression_sha FROM alpha_expressions WHERE status IN ('completed', 'failed', 'pruned')"
            ).fetchall()
            existing_shas = {row[0] for row in rows}
        except Exception:
            pass
    rng = random.Random(config.seed) if config.seed is not None else random
    all_unique_fields = {field for tasks in categorized_tasks.values() for task in tasks for field in _extract_task_fields(task)}
    field_sampled_counts: Dict[str, int] = defaultdict(int)
    for category, task_list in categorized_tasks.items():
        if not task_list:
            continue
        untested_by_field: Dict[str, List[Task]] = defaultdict(list)
        all_untested: List[Task] = []
        all_tested: List[Task] = []
        for task in task_list:
            task_sha = db.compute_sha(task.expression) if db else hashlib.sha256(task.expression.strip().encode()).hexdigest()
            primary_field = (_extract_task_fields(task) or ["unknown"])[0]
            if task_sha in existing_shas:
                all_tested.append(task)
            else:
                untested_by_field[primary_field].append(task)
                all_untested.append(task)
        sampled: List[Task] = []
        for field in sorted(all_unique_fields, key=lambda value: (field_sampled_counts[value], rng.random())):
            if len(sampled) >= config.sample_per_family or not untested_by_field[field]:
                continue
            task = rng.choice(untested_by_field[field])
            sampled.append(task)
            untested_by_field[field].remove(task)
            all_untested.remove(task)
            for task_field in _extract_task_fields(task):
                field_sampled_counts[task_field] += 1
        if len(sampled) < config.sample_per_family and all_untested:
            rng.shuffle(all_untested)
            for task in all_untested[: config.sample_per_family - len(sampled)]:
                sampled.append(task)
                for task_field in _extract_task_fields(task):
                    field_sampled_counts[task_field] += 1
        if len(sampled) < config.sample_per_family and all_tested:
            rng.shuffle(all_tested)
            fallback = all_tested[: config.sample_per_family - len(sampled)]
            sampled.extend(fallback)
            for task in fallback:
                for task_field in _extract_task_fields(task):
                    field_sampled_counts[task_field] += 1
            logger.info("[%s] 未回测候选不足，已补充 %s 条历史条目", category, len(fallback))
        cohort.extend(sampled)
    covered = {field for field, count in field_sampled_counts.items() if count > 0 and field in all_unique_fields}
    coverage = len(covered) / len(all_unique_fields) * 100.0 if all_unique_fields else 100.0
    logger.info("双轴正交分层抽样完成: 字段覆盖 %s/%s (%.1f%%); 共抽样 %s 条; 平均 %.1f 次/字段", len(covered), len(all_unique_fields), coverage, len(cohort), sum(field_sampled_counts.values()) / max(1, len(covered)))
    return cohort
