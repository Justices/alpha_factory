"""Alpha repository query and stratified sampling operations."""

from __future__ import annotations

import json
import random
from typing import Dict, List, Optional, Tuple

from ..base import BaseRepository, _isomorphic_fingerprint
from ..models import AlphaExpression


class AlphaQueryMixin(BaseRepository):
    """Expression queries and stratified sampling helpers."""

    def get_expression_by_alpha_sha(self, alpha_sha: str) -> Optional[AlphaExpression]:
        """按表达式与 settings 的联合身份查询。"""
        row = self._get_connection().execute(
            "SELECT * FROM alpha_expressions WHERE alpha_sha = ?", (alpha_sha,)
        ).fetchone()
        if row is None:
            return None
        return AlphaExpression(
            id=row["id"], alpha_sha=row["alpha_sha"],
            expression=row["expression"], expression_origin=row["expression_origin"],
            settings=row["settings"], batch_id=row["batch_id"], fields=row["fields"],
            status=row["status"], pruning_status=row["pruning_status"],
            first_operator=row["first_operator"], created_at=row["created_at"], updated_at=row["updated_at"],
        )

    def query_expressions(
        self,
        status: Optional[str] = None,
        batch_id: Optional[int] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[AlphaExpression]:
        """查询表达式列表."""
        conn = self._get_connection()
        cursor = conn.cursor()
        conditions = []
        params = []
        if status:
            conditions.append("status = ?")
            params.append(status)
        if batch_id is not None:
            conditions.append("batch_id = ?")
            params.append(batch_id)
        where_clause = " AND ".join(conditions) if conditions else "1=1"
        query = f"SELECT * FROM alpha_expressions WHERE {where_clause} ORDER BY id LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        cursor.execute(query, params)
        rows = cursor.fetchall()
        return [
            AlphaExpression(
                id=r['id'],
                alpha_sha=r['alpha_sha'],
                expression=r['expression'],
                expression_origin=r['expression_origin'],
                settings=r['settings'],
                batch_id=r['batch_id'],
                fields=r['fields'],
                status=r['status'],
                pruning_status=r['pruning_status'],
                first_operator=r['first_operator'],
                created_at=r['created_at'],
                updated_at=r['updated_at'],
            )
            for r in rows
        ]

    # ---------------------------------------------------------------------------
    # 分层抽样与近亲去重
    # ---------------------------------------------------------------------------

    def sample_expressions_stratified(
        self,
        expressions: List[str],
        limit: int,
        distribution: str = "proportional",
        per_group: int = 5,
        seed: Optional[int] = None,
        batch_cap: Optional[int] = None,
        dedup_isomorphic: bool = True,
    ) -> List[str]:
        """三层分层抽样 (批次配额 ➔ 字段组 ➔ 同构折叠)."""
        if limit <= 0 or not expressions:
            return []
        if len(expressions) <= limit and not dedup_isomorphic:
            return list(expressions)

        rng = random.Random(seed)
        conn = self._get_connection()

        expr_meta: Dict[str, Tuple[Optional[int], Tuple[str, ...]]] = {}
        placeholders = ",".join("?" * len(expressions))
        query = f"SELECT expression, batch_id, fields FROM alpha_expressions WHERE expression IN ({placeholders})"
        try:
            rows = conn.execute(query, expressions).fetchall()
            for r in rows:
                expr = r["expression"]
                bid = r["batch_id"]
                try:
                    flds = tuple(sorted(json.loads(r["fields"] or "[]")))
                except (json.JSONDecodeError, TypeError):
                    flds = ()
                expr_meta[expr] = (bid, flds)
        except Exception:
            pass

        for e in expressions:
            if e not in expr_meta:
                expr_meta[e] = (None, ())

        effective_batch_cap = batch_cap if batch_cap is not None else max(1, int(limit * 0.4))
        return self._sample_by_batches_and_fields(
            expressions, limit, distribution, rng, expr_meta, effective_batch_cap,
            dedup_isomorphic=dedup_isomorphic,
        )

    def _sample_by_batches_and_fields(
        self,
        expressions: List[str],
        limit: int,
        distribution: str,
        rng: random.Random,
        expr_meta: Dict[str, Tuple[Optional[int], Tuple[str, ...]]],
        batch_cap: int,
        dedup_isomorphic: bool = True,
    ) -> List[str]:
        """按批次和字段组合执行分层抽样."""
        by_batch: Dict[Optional[int], List[str]] = {}
        for expr in expressions:
            bid = expr_meta[expr][0]
            by_batch.setdefault(bid, []).append(expr)

        n_batches = len(by_batch)
        batch_alloc: Dict[Optional[int], int] = {}
        if distribution == "uniform":
            per_batch = max(1, limit // max(n_batches, 1))
            for bid in by_batch:
                batch_alloc[bid] = min(per_batch, len(by_batch[bid]), batch_cap)
        else:
            total = len(expressions)
            for bid, items in by_batch.items():
                batch_alloc[bid] = min((limit * len(items)) // max(total, 1), len(items), batch_cap)

        allocated = sum(batch_alloc.values())
        if allocated < limit:
            remaining = limit - allocated
            for bid in sorted(by_batch, key=lambda b: -len(by_batch.get(b, []))):
                if remaining <= 0:
                    break
                current = batch_alloc.get(bid, 0)
                add = min(remaining, len(by_batch[bid]) - current, batch_cap - current)
                if add > 0:
                    batch_alloc[bid] = current + add
                    remaining -= add

        out: List[str] = []
        global_fps: Optional[set] = set() if dedup_isomorphic else None
        for bid, batch_exprs in by_batch.items():
            batch_limit = batch_alloc.get(bid, 0)
            if batch_limit <= 0:
                continue

            by_fields: Dict[Tuple[str, ...], List[str]] = {}
            for expr in batch_exprs:
                fields_key = expr_meta[expr][1]
                by_fields.setdefault(fields_key, []).append(expr)

            n_fields_groups = len(by_fields)
            if n_fields_groups == 0:
                continue

            fields_alloc: Dict[Tuple[str, ...], int] = {}
            if distribution == "uniform":
                per_fg = max(1, batch_limit // max(n_fields_groups, 1))
                for fk in by_fields:
                    fields_alloc[fk] = min(per_fg, len(by_fields[fk]))
            else:
                batch_total = len(batch_exprs)
                for fk, items in by_fields.items():
                    fields_alloc[fk] = min((batch_limit * len(items)) // max(batch_total, 1), len(items))

            allocated_fg = sum(fields_alloc.values())
            if allocated_fg < batch_limit:
                remaining = batch_limit - allocated_fg
                for fk in sorted(by_fields, key=lambda f: -len(by_fields.get(f, []))):
                    if remaining <= 0:
                        break
                    add = min(remaining, len(by_fields[fk]) - fields_alloc.get(fk, 0))
                    fields_alloc[fk] = fields_alloc.get(fk, 0) + add
                    remaining -= add

            for fk in sorted(fields_alloc):
                pool = list(by_fields[fk])
                picked = self._pick_with_isomorphic_dedup(pool, fields_alloc[fk], rng, dedup_isomorphic)
                if global_fps is not None:
                    picked = [e for e in picked if _isomorphic_fingerprint(e) not in global_fps]
                    for e in picked:
                        global_fps.add(_isomorphic_fingerprint(e))
                out.extend(picked)

        if len(out) < limit:
            rest = [e for e in expressions if e not in out]
            rng.shuffle(rest)
            batch_counts: Dict[Optional[int], int] = {}
            for e in out:
                bid = expr_meta[e][0]
                batch_counts[bid] = batch_counts.get(bid, 0) + 1
            chosen_fps = {_isomorphic_fingerprint(e) for e in out} if dedup_isomorphic else None
            for e in rest:
                if len(out) >= limit:
                    break
                if chosen_fps is not None:
                    fp = _isomorphic_fingerprint(e)
                    if fp in chosen_fps:
                        continue
                bid = expr_meta[e][0]
                if batch_counts.get(bid, 0) < batch_cap:
                    out.append(e)
                    batch_counts[bid] = batch_counts.get(bid, 0) + 1
                    if chosen_fps is not None:
                        chosen_fps.add(fp)

        return out

    def sample_catalog_expressions(
        self, expressions: List[str], *, limit: int = 80, seed: Optional[int] = 42,
        distribution: str = "proportional", per_group: int = 0,
        batch_ids: Optional[List[int]] = None,
        base_fields_list: Optional[List[List[str]]] = None,
        max_per_batch: int = 8,
        max_per_batch_glb: int = 4,
        is_glb: bool = False,
        dedup_isomorphic: bool = True,
    ) -> List[str]:
        """分层抽样表达式 (按批次配额 ➔ 字段组 ➔ 同构折叠)."""
        from alpha_operator_framework.domain.operators import extract_first_operator

        if not expressions or limit <= 0:
            return list(expressions)

        rng = random.Random(seed)
        batch_cap = max_per_batch_glb if is_glb else max_per_batch

        if not batch_ids and not base_fields_list:
            groups: Dict[str, List[str]] = {}
            for expr in expressions:
                groups.setdefault(extract_first_operator(expr), []).append(expr)
            return self._sample_from_groups(groups, limit, distribution, per_group, rng, dedup_isomorphic)

        expr_meta: Dict[str, Tuple[Optional[int], Tuple[str, ...]]] = {}
        for i, expr in enumerate(expressions):
            bid = batch_ids[i] if batch_ids and i < len(batch_ids) else None
            fields = tuple(sorted(base_fields_list[i])) if base_fields_list and i < len(base_fields_list) else ()
            expr_meta[expr] = (bid, fields)

        return self._sample_by_batches_and_fields(
            expressions, limit, distribution, rng, expr_meta, batch_cap,
            dedup_isomorphic=dedup_isomorphic,
        )

    def _sample_from_groups(
        self, groups: Dict[str, List[str]], limit: int,
        distribution: str, per_group: int, rng: random.Random,
        dedup_isomorphic: bool = True,
    ) -> List[str]:
        """从分组中抽样 (按第一算子退化分组)."""
        sizes = {op: len(v) for op, v in groups.items()}
        if distribution == "uniform":
            per = max(1, limit // max(len(sizes), 1))
            alloc = {op: min(per, sz) for op, sz in sizes.items()}
        elif distribution == "per_group":
            alloc = {op: min(max(per_group, 0), sz) for op, sz in sizes.items()}
        else:
            total = sum(sizes.values())
            alloc = {op: (limit * sz) // total for op, sz in sizes.items()}
            for op in alloc:
                alloc[op] = min(alloc[op], sizes[op])
            remaining = limit - sum(alloc.values())
            for op in sorted(sizes, key=lambda o: (-sizes[o], o)):
                if remaining <= 0:
                    break
                add = min(remaining, sizes[op] - alloc[op])
                alloc[op] += add
                remaining -= add

        out: List[str] = []
        for op in sorted(alloc):
            pool = list(groups[op])
            out.extend(self._pick_with_isomorphic_dedup(pool, alloc[op], rng, dedup_isomorphic))
        if len(out) < limit:
            rest = [e for e in groups.get("__all__", []) if e not in out]
            rng.shuffle(rest)
            chosen_fps = {_isomorphic_fingerprint(e) for e in out} if dedup_isomorphic else None
            for e in rest:
                if len(out) >= limit:
                    break
                if chosen_fps is not None and _isomorphic_fingerprint(e) in chosen_fps:
                    continue
                out.append(e)
                if chosen_fps is not None:
                    chosen_fps.add(_isomorphic_fingerprint(e))
        return out

    @staticmethod
    def _pick_with_isomorphic_dedup(
        pool: List[str], limit: int, rng: random.Random, dedup: bool = True
    ) -> List[str]:
        """从池中选取 limit 个并做同构折叠."""
        if limit <= 0:
            return []
        if not dedup:
            rng.shuffle(pool)
            return list(pool[:limit])
        reps: Dict[str, str] = {}
        for e in pool:
            fp = _isomorphic_fingerprint(e)
            if fp not in reps:
                reps[fp] = e
        unique = list(reps.values())
        rng.shuffle(unique)
        return unique[:limit]


    # ---------------------------------------------------------------------------
    # Alpha 详情与 18 Checks 操作
    # ---------------------------------------------------------------------------
