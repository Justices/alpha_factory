"""Alpha 表达式、回测指标与 18 项 Checks 仓储 (Alpha Factor Repository).

管理表:
  - alpha_expressions (表达式规范化主表与指纹去重)
  - alpha_details (平台绩效指标与工作流阶段)
  - alpha_checks (平台全部 18 项 Checks 检查子表)
"""

from __future__ import annotations

import hashlib
import json
import random
import re
import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from ..base import BaseRepository, _num, _extract_pc_sc, _isomorphic_fingerprint
from ..models import AlphaDetail, AlphaExpression, WF_STAGES
from alpha_operator_framework.domain.evaluation import count_failed_gates


class AlphaRepository(BaseRepository):
    """Alpha 表达式、回测指标与 18 项 Checks 仓储."""

    @staticmethod
    def compute_sha(expression: str) -> str:
        """计算表达式 SHA256 哈希."""
        return hashlib.sha256(expression.strip().encode("utf-8")).hexdigest()

    @classmethod
    def compute_alpha_sha(cls, expression: str, settings: Dict[str, Any]) -> str:
        """计算包含环境设置的 Alpha 综合指纹."""
        payload = f"{expression.strip()}|{settings.get('region','')}|{settings.get('universe','')}|{settings.get('delay',1)}|{settings.get('decay',0.0)}|{settings.get('neutralization','')}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def insert_expression(self, expression: str, settings: Dict, *, expression_origin: str = "",
                          batch_id: Optional[int] = None, fields: Optional[List[str]] = None,
                          status: str = "pending", first_operator: Optional[str] = None,
                          commit: bool = True) -> int:
        """插入 alpha 表达式 (去重)."""
        from alpha_operator_framework.domain.operators import extract_first_operator
        from alpha_operator_framework.domain.pruning import extract_fields

        conn = self._get_connection()
        cursor = conn.cursor()

        expression_sha = self.compute_sha(expression)
        settings_json = json.dumps(settings)
        fields_json = self._json(sorted(set(fields if fields is not None else extract_fields(expression))))
        first_operator = first_operator if first_operator is not None else extract_first_operator(expression)
        now = datetime.now().isoformat()

        try:
            cursor.execute("""
                INSERT INTO alpha_expressions
                    (expression_sha, expression, expression_origin, settings,
                     batch_id, fields, status, first_operator, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (expression_sha, expression, expression_origin, settings_json,
                  batch_id, fields_json, status, first_operator, now, now))
            if commit:
                conn.commit()
            return cursor.lastrowid
        except sqlite3.IntegrityError:
            cursor.execute("""
                UPDATE alpha_expressions
                SET expression_origin = CASE WHEN expression_origin = '' THEN ? ELSE expression_origin END,
                    batch_id = COALESCE(?, batch_id),
                    fields = CASE WHEN ? != '[]' THEN ? ELSE fields END,
                    status = CASE WHEN ? = 'completed' THEN 'completed' ELSE status END,
                    first_operator = CASE WHEN first_operator = '' THEN ? ELSE first_operator END,
                    updated_at = ?
                WHERE expression_sha = ?
            """, (expression_origin, batch_id, fields_json, fields_json, status, first_operator, now, expression_sha))
            if commit:
                conn.commit()
            cursor.execute("SELECT id FROM alpha_expressions WHERE expression_sha = ?", (expression_sha,))
            row = cursor.fetchone()
            return row['id'] if row else -1

    def upsert_expression_record(
        self,
        expression_sha: str,
        expression: str,
        origin: str = "",
        settings: Optional[Dict[str, Any]] = None,
        fields: Optional[List[str]] = None,
        status: str = "pending",
        first_operator: str = "",
    ) -> None:
        """插入或更新单个表达式主记录."""
        now_iso = self._timestamp()
        conn = self._get_connection()
        conn.execute(
            """
            INSERT INTO alpha_expressions (
                expression_sha, expression, expression_origin, settings,
                fields, status, first_operator, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(expression_sha) DO UPDATE SET
                expression_origin = CASE WHEN alpha_expressions.expression_origin = '' THEN excluded.expression_origin ELSE alpha_expressions.expression_origin END,
                status = CASE WHEN excluded.status = 'completed' THEN 'completed' ELSE alpha_expressions.status END,
                fields = CASE WHEN excluded.fields != '[]' THEN excluded.fields ELSE alpha_expressions.fields END,
                first_operator = CASE WHEN alpha_expressions.first_operator = '' THEN excluded.first_operator ELSE alpha_expressions.first_operator END,
                updated_at = excluded.updated_at
            """,
            (
                expression_sha,
                expression,
                origin,
                self._json(settings or {}),
                self._json(fields or []),
                status,
                first_operator,
                now_iso,
                now_iso,
            ),
        )
        conn.commit()

    def get_expression_by_sha(self, expression_sha: str) -> Optional[AlphaExpression]:
        """通过 SHA 查询表达式."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM alpha_expressions WHERE expression_sha = ?", (expression_sha,))
        row = cursor.fetchone()
        if row:
            return AlphaExpression(
                id=row['id'],
                expression_sha=row['expression_sha'],
                expression=row['expression'],
                expression_origin=row['expression_origin'],
                settings=row['settings'],
                batch_id=row['batch_id'],
                fields=row['fields'],
                status=row['status'],
                first_operator=row['first_operator'],
                created_at=row['created_at'],
                updated_at=row['updated_at'],
            )
        return None

    def catalog_expression(
        self,
        expression: str,
        *,
        stage: str = "first_order",
        family: str = "unary",
        template_index: int = -1,
        fields_per_alpha: int = 0,
        base_fields: Optional[List[str]] = None,
        metadata: Optional[Dict] = None,
        status: str = "generated",
        expression_origin: str = "",
        batch_id: Optional[int] = None,
        backtest_status: str = "pending",
        backtest_settings: Optional[Dict] = None,
        commit: bool = True,
    ) -> int:
        """登记候选表达式到 alpha_expressions 表."""
        settings = {
            "stage": stage,
            "family": family,
            "template_index": template_index,
            "fields_per_alpha": fields_per_alpha,
            "base_fields": base_fields or [],
            "metadata": metadata or {},
            "status": status,
        }
        if backtest_settings:
            settings["backtest"] = backtest_settings
        return self.insert_expression(
            expression, settings,
            expression_origin=expression_origin,
            batch_id=batch_id,
            fields=list(base_fields) if base_fields else None,
            status=backtest_status,
            commit=commit,
        )

    def catalog_tasks(
        self, tasks: List[Any], *, stage: str = "first_order", backtest_settings: Optional[Dict] = None,
        batch_id: Optional[int] = None
    ) -> int:
        """批量登记 Task 到 alpha_expressions 表."""
        count = 0
        conn = self._get_connection()
        try:
            for task in tasks:
                t_fields = getattr(task, "fields", None) or []
                t_origin = getattr(task, "origin", "") or ""
                self.catalog_expression(
                    task.expression,
                    stage=stage,
                    family=getattr(task, "family", "unary"),
                    template_index=getattr(task, "template_index", -1),
                    fields_per_alpha=len(t_fields),
                    base_fields=t_fields,
                    metadata=getattr(task, "metadata", None),
                    expression_origin=t_origin,
                    batch_id=batch_id,
                    backtest_settings=backtest_settings,
                    commit=False,
                )
                count += 1
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        return count

    def mark_expressions_pruned(self, expression_shas: List[str]) -> None:
        """把表达式标记为被剪枝 (pruned)."""
        now = self._timestamp()
        conn = self._get_connection()
        for sha in expression_shas:
            conn.execute(
                """UPDATE alpha_expressions SET status='pruned', updated_at=?
                   WHERE expression_sha=? AND status != 'completed'""",
                (now, sha),
            )
        conn.commit()

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
                expression_sha=r['expression_sha'],
                expression=r['expression'],
                expression_origin=r['expression_origin'],
                settings=r['settings'],
                batch_id=r['batch_id'],
                fields=r['fields'],
                status=r['status'],
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
        shas = [self.compute_sha(e) for e in expressions]
        placeholders = ",".join("?" * len(shas))
        query = f"SELECT expression, batch_id, fields FROM alpha_expressions WHERE expression_sha IN ({placeholders})"
        try:
            rows = conn.execute(query, shas).fetchall()
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

    def insert_alpha_detail(self, detail: AlphaDetail) -> int:
        """插入或更新 alpha_details 行."""
        conn = self._get_connection()
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        self._upsert_detail(cursor, detail, now)
        conn.commit()
        return cursor.lastrowid

    def update_alpha_status(self, alpha_id: str, status: str) -> None:
        """更新 alpha_details 中的平台状态。"""
        conn = self._get_connection()
        conn.execute(
            "UPDATE alpha_details SET status_platform = ?, updated_at = ? WHERE alpha_id = ?",
            (status, datetime.now().isoformat(), alpha_id),
        )
        conn.commit()

    def update_wf_stage(self, alpha_id: str, wf_stage: str) -> None:
        """更新 alpha_details 中的工作流阶段."""
        if wf_stage not in WF_STAGES:
            raise ValueError(f"unknown wf_stage: {wf_stage!r} (expected one of {WF_STAGES})")
        conn = self._get_connection()
        conn.execute(
            "UPDATE alpha_details SET wf_stage = ?, updated_at = ? WHERE alpha_id = ?",
            (wf_stage, datetime.now().isoformat(), alpha_id),
        )
        conn.commit()

    def mark_alpha_submitted(self, alpha_id: str) -> None:
        """标记已提交."""
        self.update_wf_stage(alpha_id, "submitted")

    def mark_alpha_failed(self, alpha_id: str) -> None:
        """标记回测/校验失败."""
        self.update_wf_stage(alpha_id, "failed")

    def _upsert_detail(self, cursor: sqlite3.Cursor, detail: AlphaDetail, now: str) -> None:
        """内部: 插入或更新 alpha_details."""
        cursor.execute("""
            INSERT INTO alpha_details (
                alpha_id, expression_sha, alpha_sha, expression,
                region, universe, delay, decay, neutralization, truncation,
                sharpe, fitness, turnover, margin, pnl, returns, drawdown, long_count, short_count,
                grade, stage_platform, status_platform,
                sc_result, sc_value, pc_result, pc_value, checks_json, ra_failed, ppa_failed,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(alpha_id) DO UPDATE SET
                expression_sha=excluded.expression_sha,
                alpha_sha=excluded.alpha_sha,
                expression=excluded.expression,
                region=excluded.region,
                universe=excluded.universe,
                delay=excluded.delay,
                decay=excluded.decay,
                neutralization=excluded.neutralization,
                truncation=excluded.truncation,
                sharpe=excluded.sharpe,
                fitness=excluded.fitness,
                turnover=excluded.turnover,
                margin=excluded.margin,
                pnl=excluded.pnl,
                returns=excluded.returns,
                drawdown=excluded.drawdown,
                long_count=excluded.long_count,
                short_count=excluded.short_count,
                grade=excluded.grade,
                stage_platform=excluded.stage_platform,
                status_platform=excluded.status_platform,
                sc_result=excluded.sc_result,
                sc_value=excluded.sc_value,
                pc_result=excluded.pc_result,
                pc_value=excluded.pc_value,
                checks_json=excluded.checks_json,
                ra_failed=excluded.ra_failed,
                ppa_failed=excluded.ppa_failed,
                updated_at=excluded.updated_at
        """, (
            detail.alpha_id, detail.expression_sha, detail.alpha_sha, detail.expression,
            detail.region, detail.universe, detail.delay, detail.decay, detail.neutralization, detail.truncation,
            detail.sharpe, detail.fitness, detail.turnover, detail.margin, detail.pnl, detail.returns, detail.drawdown,
            detail.long_count, detail.short_count,
            detail.grade, detail.stage_platform, detail.status_platform,
            detail.sc_result, detail.sc_value, detail.pc_result, detail.pc_value, detail.checks_json,
            detail.ra_failed, detail.ppa_failed,
            now, now
        ))

    def query_alphas(
        self,
        min_sharpe: Optional[float] = None,
        max_sharpe: Optional[float] = None,
        min_fitness: Optional[float] = None,
        max_fitness: Optional[float] = None,
        region: Optional[str] = None,
        stage_platform: Optional[str] = None,
        status: Optional[str] = None,
        wf_stage: Optional[str] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[AlphaDetail]:
        """查询 alpha 列表."""
        conn = self._get_connection()
        cursor = conn.cursor()
        conditions = []
        params = []
        if min_sharpe is not None:
            conditions.append("sharpe >= ?")
            params.append(min_sharpe)
        if max_sharpe is not None:
            conditions.append("sharpe <= ?")
            params.append(max_sharpe)
        if min_fitness is not None:
            conditions.append("fitness >= ?")
            params.append(min_fitness)
        if max_fitness is not None:
            conditions.append("fitness <= ?")
            params.append(max_fitness)
        if region:
            conditions.append("region = ?")
            params.append(region)
        if stage_platform:
            conditions.append("stage_platform = ?")
            params.append(stage_platform)
        if status:
            conditions.append("status_platform = ?")
            params.append(status)
        if wf_stage:
            conditions.append("wf_stage = ?")
            params.append(wf_stage)

        where_clause = " AND ".join(conditions) if conditions else "1=1"
        query = f"SELECT * FROM alpha_details WHERE {where_clause} ORDER BY sharpe DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        cursor.execute(query, params)
        rows = cursor.fetchall()
        return [self._row_to_detail(row) for row in rows]

    def _row_to_detail(self, row: sqlite3.Row) -> AlphaDetail:
        """将数据库行转换为 AlphaDetail 对象."""
        return AlphaDetail(
            id=row['id'],
            alpha_id=row['alpha_id'],
            expression_sha=row['expression_sha'],
            expression=row['expression'],
            region=row['region'],
            universe=row['universe'],
            delay=row['delay'],
            decay=row['decay'],
            neutralization=row['neutralization'],
            truncation=row['truncation'],
            sharpe=row['sharpe'],
            fitness=row['fitness'],
            turnover=row['turnover'],
            margin=row['margin'],
            pnl=row['pnl'],
            returns=row['returns'],
            drawdown=row['drawdown'],
            long_count=row['long_count'],
            short_count=row['short_count'],
            grade=row['grade'],
            stage_platform=row['stage_platform'],
            status_platform=row['status_platform'],
            wf_stage=row['wf_stage'],
            sc_result=row['sc_result'] or "",
            sc_value=row['sc_value'],
            pc_result=row['pc_result'] or "",
            pc_value=row['pc_value'],
            checks_json=row['checks_json'] or "",
            ra_failed=row['ra_failed'] or 0,
            ppa_failed=row['ppa_failed'] or 0,
            created_at=row['created_at'],
            updated_at=row['updated_at'],
        )

    @staticmethod
    def check_array_to_rows(checks: List[Dict], alpha_id: str = "") -> List[Dict]:
        """将 is.checks 数组归一化为 alpha_checks 行 dict."""
        rows = []
        for check in checks or []:
            if not isinstance(check, dict):
                continue
            name = check.get("name") or ""
            if not name:
                continue
            extra = {k: v for k, v in check.items() if k not in ("name", "result", "limit", "value")}
            rows.append({
                "alpha_id": alpha_id,
                "check_name": name,
                "result": check.get("result"),
                "limit": _num(check, "limit"),
                "value": _num(check, "value"),
                "extra_json": json.dumps(extra, ensure_ascii=False) if extra else None,
            })
        return rows

    def _write_checks(self, cursor: sqlite3.Cursor, alpha_id: str, checks: List[Dict], now: str) -> None:
        """内部: 替换式写入 checks."""
        cursor.execute("DELETE FROM alpha_checks WHERE alpha_id = ?", (alpha_id,))
        for row in self.check_array_to_rows(checks, alpha_id):
            cursor.execute("""
                INSERT INTO alpha_checks (alpha_id, check_name, result, "limit", value, extra_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (row["alpha_id"], row["check_name"], row["result"], row["limit"],
                  row["value"], row["extra_json"], now, now))

    def upsert_checks(self, alpha_id: str, checks: List[Dict]) -> int:
        """替换式写入某 alpha 的全部 checks."""
        conn = self._get_connection()
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        self._write_checks(cursor, alpha_id, checks, now)
        conn.commit()
        return len(self.check_array_to_rows(checks, alpha_id))

    def get_checks(self, alpha_id: str) -> List[Dict]:
        """返回某 alpha 的 checks 列表."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT check_name, result, "limit", value, extra_json
            FROM alpha_checks
            WHERE alpha_id = ?
            ORDER BY check_name
        """, (alpha_id,))
        rows = cursor.fetchall()
        out = []
        for row in rows:
            item = {
                "name": row["check_name"],
                "result": row["result"],
                "limit": row["limit"],
                "value": row["value"],
            }
            if row["extra_json"]:
                try:
                    extra = json.loads(row["extra_json"])
                    if isinstance(extra, dict):
                        item.update(extra)
                except (json.JSONDecodeError, TypeError):
                    pass
            out.append(item)
        return out

    def get_alpha_checks(self, alpha_id: str) -> List[Any]:
        """返回某 alpha 的 checks 详细模型列表."""
        from ..models import AlphaCheck
        conn = self._get_connection()
        rows = conn.execute(
            """SELECT check_name, result, "limit", value, extra_json FROM alpha_checks
               WHERE alpha_id = ? ORDER BY check_name""",
            (alpha_id,),
        ).fetchall()
        return [
            AlphaCheck(
                check_name=r["check_name"],
                result=r["result"],
                limit=r["limit"],
                value=r["value"],
                extra_json=r["extra_json"],
            )
            for r in rows
        ]

    def save_result_with_checks(
        self,
        alpha_id: str,
        is_dict_or_result: Dict,
        settings_dict: Optional[Dict] = None
    ) -> None:
        """保存模拟结果 + 全部 checks 指标."""
        conn = self._get_connection()
        cursor = conn.cursor()
        now = datetime.now().isoformat()

        is_block = is_dict_or_result
        settings = settings_dict or {}
        expression = ""
        top = is_dict_or_result if isinstance(is_dict_or_result, dict) else {}

        if isinstance(is_block, dict) and isinstance(is_block.get("is"), dict):
            is_block = is_block["is"]
            settings = top.get("settings") or settings
            regular = top.get("regular") if isinstance(top.get("regular"), dict) else {}
            expression = regular.get("code") or top.get("expression") or ""
        elif isinstance(is_block, dict):
            expression = is_block.get("expression") or ""

        if not isinstance(is_block, dict):
            is_block = {}

        checks = is_block.get("checks") or []
        sc_value, pc_value, sc_result, pc_result = _extract_pc_sc(is_block, checks)
        gate = count_failed_gates(checks)

        detail = AlphaDetail(
            alpha_id=alpha_id,
            expression_sha=self.compute_sha(expression) if expression else "",
            alpha_sha=self.compute_alpha_sha(expression, settings) if expression else "",
            expression=expression,
            region=settings.get("region", ""),
            universe=settings.get("universe", ""),
            delay=settings.get("delay", 1),
            decay=settings.get("decay", 0.0),
            neutralization=settings.get("neutralization", ""),
            truncation=settings.get("truncation", 0.0),
            sharpe=_num(is_block, "sharpe") or 0.0,
            fitness=_num(is_block, "fitness") or 0.0,
            turnover=_num(is_block, "turnover") or 0.0,
            margin=_num(is_block, "margin") or 0.0,
            pnl=_num(is_block, "pnl") or 0.0,
            returns=_num(is_block, "returns") or 0.0,
            drawdown=_num(is_block, "drawdown") or 0.0,
            long_count=int(_num(is_block, "longCount") or 0),
            short_count=int(_num(is_block, "shortCount") or 0),
            grade=is_block.get("grade") or top.get("grade") or "",
            stage_platform=settings.get("stage") or top.get("stage") or "",
            status_platform=settings.get("status") or top.get("status") or "",
            sc_result=sc_result,
            sc_value=sc_value,
            pc_result=pc_result,
            pc_value=pc_value,
            checks_json=json.dumps(checks, ensure_ascii=False) if checks else None,
            ra_failed=gate.failed_ra,
            ppa_failed=gate.failed_ppa,
        )

        try:
            self._upsert_detail(cursor, detail, now)
            self._write_checks(cursor, alpha_id, checks, now)
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    def get_candidates_for_super_alpha(self) -> List[Dict[str, Any]]:
        """获取可用于构建 Super Alpha 的全部 Alpha 候选指标."""
        conn = self._get_connection()
        rows = conn.execute(
            "SELECT alpha_id, expression, sharpe, fitness, turnover, sc_value, pc_value FROM alpha_details"
        ).fetchall()
        return [dict(r) for r in rows]

    def get_top_performing_alphas(self, min_sharpe: float = 1.25, min_fitness: float = 1.0) -> List[Dict[str, Any]]:
        """获取达标指定夏普与健康度门槛的 Alpha 列表."""
        conn = self._get_connection()
        rows = conn.execute("""
            SELECT alpha_id, expression, sharpe, fitness, turnover, margin, sc_value, pc_value, grade
            FROM alpha_details
            WHERE sharpe >= ? AND fitness >= ?
            ORDER BY sharpe DESC
        """, (min_sharpe, min_fitness)).fetchall()
        return [
            {
                "alpha_id": r[0],
                "expression": r[1],
                "sharpe": float(r[2]),
                "fitness": float(r[3]),
                "turnover": float(r[4]),
                "margin": float(r[5]),
                "sc_value": float(r[6]) if r[6] is not None else 0.20,
                "pc_value": float(r[7]) if r[7] is not None else 0.20,
                "grade": str(r[8] or ""),
            }
            for r in rows
        ]

    def get_total_alpha_details_count(self) -> int:
        """获取已回测记录的 Alpha 总数."""
        conn = self._get_connection()
        row = conn.execute("SELECT COUNT(*) FROM alpha_details").fetchone()
        return int(row[0]) if row else 0
