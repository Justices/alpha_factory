"""Task-local coverage allocation and conservative, bounded TS refinement."""

from __future__ import annotations

import hashlib
import math
from collections import Counter, defaultdict, deque
from dataclasses import replace
from typing import Sequence

from alpha_operator_framework.domain.ast import FunctionCallNode, LiteralNode, parse_expression, to_canonical_string
from alpha_operator_framework.domain.fields import FieldSpec
from .round import Candidate
from .strategy_config import ParentGate, TSWindowPolicy


def phase(candidate: Candidate) -> int:
    if candidate.family.startswith("signal_validation/"):
        return 2
    if ":refine:" in candidate.template_id:
        return 1
    if candidate.family.startswith(("depth_construction/", "field_composition/", "group_second_order/")):
        return 1
    return 0


def balanced_cohort(
    candidates: Sequence[Candidate], history: Sequence[Candidate], fields: Sequence[FieldSpec],
    *, limit: int, seed: int, weights: tuple[int, int, int] = (4, 2, 2),
) -> list[Candidate]:
    """Allocate ready slots by phase, then least-tested dataset/field/operator.

    Counts are reconstructed from the root catalog, so process restarts do not
    reset coverage. Unavailable phases lend their slots to ready phases.
    """
    datasets = {f.id: f.dataset_id for f in fields}

    def key(c):
        return (phase(c), tuple(sorted({datasets.get(f, "unknown") for f in c.fields})),
                tuple(sorted(c.fields)), c.family, tuple(c.operators))

    counts = [Counter() for _ in range(5)]

    def charge(k):
        p, ds, fs, family, ops = k
        for counter, item in zip(counts, (p, (p, ds), (p, ds, fs), (p, ds, fs, family, ops), (p, family))):
            counter[item] += 1

    for c in history:
        charge(key(c))
    grouped = defaultdict(list)
    for c in candidates:
        grouped[key(c)].append(c)
    buckets = {k: deque(sorted(rows, key=lambda c: c.candidate_id)) for k, rows in grouped.items()}
    tie = {k: hashlib.sha256(f"{seed}:{k}".encode()).hexdigest() for k in buckets}
    chosen = []
    for _ in range(min(limit, len(candidates))):
        def priority(k):
            p, ds, fs, family, ops = k
            return (counts[0][p] / weights[p], counts[1][p, ds], counts[2][p, ds, fs],
                    counts[3][p, ds, fs, family, ops], counts[4][p, family], tie[k])
        k = min(buckets, key=priority)
        chosen.append(buckets[k].popleft())
        charge(k)
        if not buckets[k]:
            del buckets[k]
    return chosen


def refine_ts_windows(rows, policy: TSWindowPolicy, gate: ParentGate):
    """Only interpolate adjacent successful probes of the same scalar signal.

    This is in-sample sensitivity evidence, not a claim of temporal stability.
    Existing expressions, including failed probes, are never regenerated.
    """
    from .strategies import CandidateDraft
    if not policy.enabled:
        return []
    groups = defaultdict(dict)
    existing = {to_canonical_string(row.expression) for row in rows}
    for row in rows:
        if not row.family.startswith("raw_first_order/"):
            continue
        try:
            node = parse_expression(row.expression)
        except ValueError:
            continue
        if (not isinstance(node, FunctionCallNode) or not node.name.startswith("ts_")
                or len(node.args) != 2 or not isinstance(node.args[1], LiteralNode)):
            continue
        window = node.args[1].value
        if window not in policy.probe_windows:
            continue
        groups[row.origin_strategy, node.name, to_canonical_string(node.args[0])][window] = (row, node)
    drafts = []
    for (strategy, operator, _), probes in sorted(groups.items()):
        for left, right in zip(policy.probe_windows, policy.probe_windows[1:]):
            if left not in probes or right not in probes:
                continue
            a, node = probes[left]
            b, _ = probes[right]
            if not all(math.isfinite(v) for v in (a.sharpe, a.fitness, b.sharpe, b.fitness)):
                continue
            if not all(gate.passes(r.sharpe, r.fitness) for r in (a, b)):
                continue
            if any(max(x, y) <= 0 or min(x, y) / max(x, y) < policy.minimum_neighbor_ratio
                   for x, y in ((a.sharpe, b.sharpe), (a.fitness, b.fitness))):
                continue
            for window in policy.candidate_windows:
                if not left < window < right or window in policy.probe_windows:
                    continue
                expression = to_canonical_string(replace(node, args=(node.args[0], LiteralNode(window))))
                if expression in existing:
                    continue
                existing.add(expression)
                drafts.append(CandidateDraft(expression, strategy, "raw_first_order", a.family.split("/")[1],
                    template_id=f"{operator}:refine:{window}",
                    hypothesis_id=f"adjacent-probes:{left}:{right}",
                    parent_ids=(a.alpha_sha or a.expression, b.alpha_sha or b.expression)))
    return drafts
