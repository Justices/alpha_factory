"""Alpha repository query and stratified sampling operations."""

from __future__ import annotations

import json
import random
from typing import Dict, List, Mapping, Optional, Tuple

from ..base import BaseRepository, _isomorphic_fingerprint
from ..models import AlphaExpression


class AlphaQueryMixin(BaseRepository):
    """Expression queries and stratified sampling helpers."""

    def get_alpha_pnl_cache(self, alpha_id: str) -> dict[str, object] | None:
        """Return a cached immutable platform PnL payload when available."""
        row = self._get_connection().execute(
            "SELECT pnl_json FROM alpha_pnl_cache WHERE alpha_id=?", (alpha_id,)
        ).fetchone()
        if row is None:
            return None
        try:
            payload = json.loads(row["pnl_json"])
        except (TypeError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    def get_expression_by_sha(self, alpha_sha: str) -> Optional[AlphaExpression]:
        """Compatibility alias for the canonical Alpha SHA lookup."""
        return self.get_expression_by_alpha_sha(alpha_sha)

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

    def load_unbacktested_research_candidates(self, settings: Dict) -> List[object]:
        """Return active expressions for one settings scope that have not been backtested."""
        from alpha_operator_framework.research.round import Candidate
        from alpha_operator_framework.domain.ast import validate_expression

        settings_json = json.dumps(settings, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        try:
            scope_hash = self.settings_scope_hash(settings)
        except ValueError:
            # Legacy research rows may predate the complete result-pruning scope.
            # They have no construction provenance, so an impossible scope keeps
            # the original candidate-loading behavior without weakening new writes.
            scope_hash = ""
        rows = self._get_connection().execute(
            """SELECT ae.alpha_sha, ae.expression, ae.fields,
                      COALESCE(cp.leaf_family, MIN(rc.family)) AS family,
                      COALESCE(cp.template_id, MIN(rc.template_id)) AS template_id,
                      COALESCE(cp.strategy_id, '') AS strategy_id,
                      COALESCE(cp.order_depth, 0) AS order_depth,
                      COALESCE(cp.field_count, 0) AS field_count
                 FROM alpha_expressions ae
                 JOIN round_candidates rc ON rc.alpha_sha = ae.alpha_sha
                 LEFT JOIN candidate_provenance cp ON cp.id = (
                     SELECT cp2.id FROM candidate_provenance cp2
                      WHERE cp2.scope_hash = ? AND cp2.candidate_sha = ae.alpha_sha
                      ORDER BY cp2.strategy_priority, cp2.leaf_family, cp2.id LIMIT 1
                 )
                WHERE ae.settings = ? AND ae.status IN ('generated', 'pending')
                  AND ae.pruning_status = 'active' AND rc.pruning_status = 'active'
                GROUP BY ae.alpha_sha, ae.expression, ae.fields, cp.leaf_family,
                         cp.template_id, cp.strategy_id, cp.order_depth, cp.field_count
                ORDER BY ae.id""",
            (scope_hash, settings_json),
        ).fetchall()
        candidates = []
        for row in rows:
            validation = validate_expression(row["expression"])
            candidates.append(Candidate(
                row["alpha_sha"], row["expression"], row["family"],
                tuple(json.loads(row["fields"] or "[]")), tuple(sorted(validation.operators_used)), row["template_id"],
                origin_strategy=row["strategy_id"], leaf_family=row["family"],
                order_depth=int(row["order_depth"]), field_count=int(row["field_count"]),
            ))
        return candidates

    def load_candidate_provenance(
        self,
        settings: Mapping[str, object],
        candidate_sha: str,
    ) -> list[object]:
        """Load every preserved source claim for one canonical candidate."""
        from alpha_operator_framework.database.models import CandidateProvenanceRecord

        rows = self._get_connection().execute(
            """SELECT * FROM candidate_provenance
               WHERE scope_hash=? AND candidate_sha=?
               ORDER BY strategy_priority, leaf_family, id""",
            (self.settings_scope_hash(settings), candidate_sha),
        ).fetchall()
        return [
            CandidateProvenanceRecord(
                provenance_id=row["provenance_id"],
                scope_hash=row["scope_hash"],
                candidate_sha=row["candidate_sha"],
                strategy_id=row["strategy_id"],
                strategy_kind=row["strategy_kind"],
                strategy_priority=int(row["strategy_priority"]),
                leaf_family=row["leaf_family"],
                template_id=row["template_id"],
                hypothesis_id=row["hypothesis_id"],
                parent_shas=tuple(json.loads(row["parent_shas_json"] or "[]")),
                order_depth=int(row["order_depth"]),
                field_count=int(row["field_count"]),
                seed=int(row["seed"]),
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
            for row in rows
        ]

    def has_construction_lineage(
        self,
        settings: Mapping[str, object],
        parent_alpha_sha: str,
        strategy_id: str,
    ) -> bool:
        row = self._get_connection().execute(
            """SELECT 1 FROM construction_lineage
               WHERE scope_hash=? AND parent_alpha_sha=? AND strategy_id=? LIMIT 1""",
            (self.settings_scope_hash(settings), parent_alpha_sha, strategy_id),
        ).fetchone()
        return row is not None

    def has_parent_strategy_run(
        self,
        settings: Mapping[str, object],
        parent_alpha_sha: str,
        strategy_id: str,
    ) -> bool:
        row = self._get_connection().execute(
            """SELECT 1 FROM construction_parent_runs
               WHERE scope_hash=? AND parent_alpha_sha=? AND strategy_id=?
                 AND status IN ('GENERATED', 'EXHAUSTED') LIMIT 1""",
            (self.settings_scope_hash(settings), parent_alpha_sha, strategy_id),
        ).fetchone()
        return row is not None

    def selected_counts_by_family(self, task_id: str) -> dict[str, int]:
        """Count unique selected candidates across deterministic task shards."""
        rows = self._get_connection().execute(
            """SELECT family, COUNT(DISTINCT alpha_sha) AS selected_count
               FROM round_candidates
               WHERE (round_id=? OR round_id LIKE ?) AND selection_status='selected'
               GROUP BY family""",
            (task_id, f"{task_id}-%"),
        ).fetchall()
        return {row["family"]: int(row["selected_count"]) for row in rows}

    def next_task_round_sequence(self, task_id: str) -> int:
        row = self._get_connection().execute(
            """SELECT COUNT(DISTINCT round_id) AS round_count
               FROM round_candidates
               WHERE (round_id=? OR round_id LIKE ?) AND selection_status='selected'""",
            (task_id, f"{task_id}-%"),
        ).fetchone()
        return int(row["round_count"] or 0) + 1

    def load_construction_strategy_statuses(self, task_id: str) -> list[object]:
        from alpha_operator_framework.research.strategies import StrategyStatus

        rows = self._get_connection().execute(
            """SELECT strategy_id, kind, status, generated_count, error_message
               FROM construction_strategy_runs WHERE task_id=?
               ORDER BY strategy_priority, id""",
            (task_id,),
        ).fetchall()
        return [
            StrategyStatus(
                row["strategy_id"], row["kind"], row["status"],
                int(row["generated_count"]), row["error_message"],
            )
            for row in rows
        ]

    def construction_task_exists(self, task_id: str) -> bool:
        row = self._get_connection().execute(
            "SELECT 1 FROM construction_tasks WHERE task_id=? LIMIT 1",
            (task_id,),
        ).fetchone()
        return row is not None

    def get_result_prune_rules(self, settings: Mapping[str, object]) -> list[dict[str, str]]:
        """Return result-derived pruning rules for one complete settings scope."""
        rows = self._get_connection().execute(
            """SELECT pattern, pattern_type, reason FROM result_prune_rules
               WHERE scope_hash=? ORDER BY id""",
            (self.settings_scope_hash(settings),),
        ).fetchall()
        return [
            {"pattern": row["pattern"], "pattern_type": row["pattern_type"], "reason": row["reason"]}
            for row in rows
        ]

    def load_promotion_decisions(self, task_id: str) -> list[dict[str, object]]:
        rows = self._get_connection().execute(
            """SELECT alpha_sha, stage, decision, reason, details_json
               FROM promotion_decisions WHERE task_id=? ORDER BY stage, id""",
            (task_id,),
        ).fetchall()
        return [
            {
                "alpha_sha": row["alpha_sha"], "stage": int(row["stage"]),
                "decision": row["decision"], "reason": row["reason"],
                "details": json.loads(row["details_json"] or "{}"),
            }
            for row in rows
        ]

    def load_signal_validation_results(self, settings: Mapping[str, object]) -> list[dict[str, object]]:
        """Return completed rank/sign children paired with their parent metrics."""
        scope_hash = self.settings_scope_hash(settings)
        rows = self._get_connection().execute(
            """SELECT cl.parent_alpha_sha, cl.child_alpha_sha,
                      COALESCE(parent.alpha_id, '') AS parent_alpha_id,
                      COALESCE(parent.sharpe, 0.0) AS parent_sharpe,
                      COALESCE(child.alpha_id, '') AS child_alpha_id,
                      COALESCE(child.sharpe, 0.0) AS child_sharpe,
                      COALESCE(cp.template_id, '') AS validation_variant,
                      (SELECT COUNT(*) FROM alpha_checks ac
                        WHERE ac.alpha_id=parent.alpha_id
                          AND ac.check_name IN (
                            'LOW_ROBUST_UNIVERSE_SHARPE',
                            'LOW_ROBUST_UNIVERSE_SHARPE.WITH_RATIO',
                            'LOW_ROBUST_UNIVERSE_RETURNS'
                          )) AS robust_total,
                      (SELECT COUNT(*) FROM alpha_checks ac
                        WHERE ac.alpha_id=parent.alpha_id AND ac.result='PASS'
                          AND ac.check_name IN (
                            'LOW_ROBUST_UNIVERSE_SHARPE',
                            'LOW_ROBUST_UNIVERSE_SHARPE.WITH_RATIO',
                            'LOW_ROBUST_UNIVERSE_RETURNS'
                          )) AS robust_passed,
                      (SELECT COUNT(*) FROM alpha_checks ac
                        WHERE ac.alpha_id=parent.alpha_id AND ac.result='FAIL'
                          AND ac.check_name IN (
                            'LOW_ROBUST_UNIVERSE_SHARPE',
                            'LOW_ROBUST_UNIVERSE_SHARPE.WITH_RATIO',
                            'LOW_ROBUST_UNIVERSE_RETURNS'
                          )) AS robust_failed
                 FROM construction_lineage cl
                 JOIN alpha_details parent ON parent.alpha_sha=cl.parent_alpha_sha
                 JOIN alpha_details child ON child.alpha_sha=cl.child_alpha_sha
                 LEFT JOIN candidate_provenance cp ON cp.id = (
                     SELECT cp2.id FROM candidate_provenance cp2
                      WHERE cp2.scope_hash=cl.scope_hash
                        AND cp2.candidate_sha=cl.child_alpha_sha
                        AND cp2.strategy_id=cl.strategy_id
                      ORDER BY cp2.id LIMIT 1
                 )
                WHERE cl.scope_hash=? AND cl.transform_kind='signal_validation'
                ORDER BY cl.parent_alpha_sha, validation_variant""",
            (scope_hash,),
        ).fetchall()
        return [dict(row) for row in rows]

    def load_completed_expression_results(self, settings: Mapping[str, object]) -> list[object]:
        """Load completed expressions and their persisted metrics for one settings scope."""
        from alpha_operator_framework.research.optimization import CompletedExpression

        scope = self._result_pruning_settings(settings)
        settings_json = json.dumps(scope, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        rows = self._get_connection().execute(
            """SELECT ae.alpha_sha, ae.expression, ae.expression_origin, ae.fields, MIN(rc.family) AS family,
                      COALESCE(ad.alpha_id, '') AS platform_alpha_id,
                      COALESCE(ad.sharpe, 0.0) AS sharpe, COALESCE(ad.fitness, 0.0) AS fitness,
                      COALESCE(ad.turnover, 0.0) AS turnover, COALESCE(ad.margin, 0.0) AS margin,
                      ad.pnl AS pnl, ad.long_count AS long_count, ad.short_count AS short_count,
                      COALESCE(ad.ra_failed, 0) AS ra_failed, COALESCE(ad.ppa_failed, 0) AS ppa_failed
                 FROM alpha_expressions ae
                 LEFT JOIN round_candidates rc ON rc.alpha_sha = ae.alpha_sha
                 JOIN alpha_details ad ON ad.alpha_sha = ae.alpha_sha
                WHERE ae.settings = ? AND ae.status = 'completed'
                GROUP BY ae.alpha_sha, ae.expression, ae.expression_origin, ae.fields,
                         ad.alpha_id, ad.sharpe, ad.fitness, ad.turnover, ad.margin,
                         ad.pnl, ad.long_count, ad.short_count, ad.ra_failed, ad.ppa_failed
                ORDER BY ae.id""",
            (settings_json,),
        ).fetchall()
        return [
            CompletedExpression(
                expression=row["expression"], fields=tuple(json.loads(row["fields"] or "[]")),
                sharpe=float(row["sharpe"]), fitness=float(row["fitness"]),
                checks_passed=not bool(row["ra_failed"] or row["ppa_failed"]),
                alpha_sha=row["alpha_sha"], family=row["family"] or "base",
                origin_strategy=row["expression_origin"] or "",
                platform_alpha_id=row["platform_alpha_id"] or "",
                turnover=float(row["turnover"]), margin=float(row["margin"]),
                pnl=float(row["pnl"]) if row["pnl"] is not None else None,
                long_count=int(row["long_count"]) if row["long_count"] is not None else None,
                short_count=int(row["short_count"]) if row["short_count"] is not None else None,
            )
            for row in rows
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
