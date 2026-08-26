"""Alpha repository write operations."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from ..base import BaseRepository
from ..models import AlphaDetail, WF_STAGES


class AlphaWriteMixin(BaseRepository):
    """Expression, detail, status, and workflow writes."""

    @classmethod
    def compute_alpha_sha(cls, expression: str, settings: Dict[str, Any]) -> str:
        """计算包含环境设置的 Alpha 综合指纹."""
        payload = json.dumps(
            {"expression": expression.strip(), "settings": settings},
            ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def insert_expression(self, expression: str, settings: Dict, *, expression_origin: str = "",
                          batch_id: Optional[int] = None, fields: Optional[List[str]] = None,
                          status: str = "pending", first_operator: Optional[str] = None,
                          commit: bool = True) -> int:
        """插入 alpha 表达式 (去重)."""
        from alpha_operator_framework.domain.operators import extract_first_operator
        from alpha_operator_framework.domain.pruning_components.field_topk import extract_fields

        conn = self._get_connection()
        cursor = conn.cursor()

        alpha_sha = self.compute_alpha_sha(expression, settings)
        settings_json = json.dumps(settings, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        fields_json = self._json(sorted(set(fields if fields is not None else extract_fields(expression))))
        first_operator = first_operator if first_operator is not None else extract_first_operator(expression)
        now = datetime.now().isoformat()

        try:
            cursor.execute("""
                INSERT INTO alpha_expressions
                    (alpha_sha, expression, expression_origin, settings,
                     batch_id, fields, status, first_operator, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (alpha_sha, expression, expression_origin, settings_json,
                  batch_id, fields_json, status, first_operator, now, now))
            if commit:
                conn.commit()
            return cursor.lastrowid
        except Exception as error:
            if error.__class__.__name__ != "IntegrityError":
                raise
            cursor.execute("""
                UPDATE alpha_expressions
                SET expression_origin = CASE WHEN expression_origin = '' THEN ? ELSE expression_origin END,
                    batch_id = COALESCE(?, batch_id),
                    fields = CASE WHEN ? != '[]' THEN ? ELSE fields END,
                    status = CASE WHEN ? = 'completed' THEN 'completed' ELSE status END,
                    first_operator = CASE WHEN first_operator = '' THEN ? ELSE first_operator END,
                    updated_at = ?
                WHERE alpha_sha = ?
            """, (expression_origin, batch_id, fields_json, fields_json, status, first_operator, now, alpha_sha))
            if commit:
                conn.commit()
            cursor.execute("SELECT id FROM alpha_expressions WHERE alpha_sha = ?", (alpha_sha,))
            row = cursor.fetchone()
            return row['id'] if row else -1

    def set_expression_status(self, expression: str, status: str, settings: Dict[str, Any]) -> None:
        """Update the primary expression lifecycle status without changing its lineage."""
        if status not in {"pending", "completed", "failed"}:
            raise ValueError(f"unsupported expression status: {status}")
        self._get_connection().execute(
            "UPDATE alpha_expressions SET status = ?, updated_at = ? WHERE alpha_sha = ?",
            (status, self._timestamp(), self.compute_alpha_sha(expression, settings)),
        )
        self._get_connection().commit()

    def catalog_research_candidates(self, round_id: str, candidates: List[Any], settings: Dict[str, Any]) -> None:
        """Create the explicit round-to-expression catalog links before selection."""
        now = self._timestamp()
        conn = self._get_connection()
        for candidate in candidates:
            conn.execute(
                """INSERT INTO round_candidates
                (round_id, candidate_id, alpha_sha, family, template_id, selection_status, pruning_status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, 'generated', 'active', ?, ?)
                ON CONFLICT(round_id, candidate_id) DO UPDATE SET
                    alpha_sha=excluded.alpha_sha, family=excluded.family,
                    template_id=excluded.template_id, updated_at=excluded.updated_at""",
                (round_id, candidate.candidate_id, self.compute_alpha_sha(candidate.expression, settings),
                 candidate.family, candidate.template_id, now, now),
            )
        conn.commit()

    def record_round_selection(self, round_id: str, decisions: List[Any]) -> None:
        """Persist the selector outcome independently from the round JSON snapshot."""
        now = self._timestamp()
        conn = self._get_connection()
        for decision in decisions:
            conn.execute(
                """UPDATE round_candidates
                SET selection_status=?, selection_reason=?, score_components_json=?, updated_at=?
                WHERE round_id=? AND candidate_id=?""",
                ("selected" if decision.selected else "not_selected", decision.reason,
                 self._json(dict(decision.score_components)), now, round_id, decision.candidate_id),
            )
        conn.commit()

    def mark_round_candidates_pruned(self, round_id: str, candidate_ids: List[str]) -> None:
        """Record pruning as a per-round judgement without changing selection or result status."""
        if not candidate_ids:
            return
        now = self._timestamp()
        placeholders = ",".join("?" for _ in candidate_ids)
        self._get_connection().execute(
            f"UPDATE round_candidates SET pruning_status='pruned', updated_at=? WHERE round_id=? AND candidate_id IN ({placeholders})",
            [now, round_id, *candidate_ids],
        )
        self._get_connection().commit()

    def upsert_expression_record(
        self,
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
                alpha_sha, expression, expression_origin, settings,
                fields, status, first_operator, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(alpha_sha) DO UPDATE SET
                expression_origin = CASE WHEN alpha_expressions.expression_origin = '' THEN excluded.expression_origin ELSE alpha_expressions.expression_origin END,
                status = CASE WHEN excluded.status = 'completed' THEN 'completed' ELSE alpha_expressions.status END,
                fields = CASE WHEN excluded.fields != '[]' THEN excluded.fields ELSE alpha_expressions.fields END,
                first_operator = CASE WHEN alpha_expressions.first_operator = '' THEN excluded.first_operator ELSE alpha_expressions.first_operator END,
                updated_at = excluded.updated_at
            """,
            (
                self.compute_alpha_sha(expression, settings or {}),
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
        if not tasks:
            return 0
        conn = self._get_connection()
        count = 0
        try:
            for task in tasks:
                base_flds = getattr(task, "base_fields", None) or getattr(task, "fields", None) or []
                meta_dict = getattr(task, "meta", None) or getattr(task, "metadata", None) or {}
                t_origin = getattr(task, "expression_origin", "") or getattr(task, "origin", "") or stage
                self.catalog_expression(
                    task.expression,
                    stage=stage,
                    family=getattr(task, "family", "unary"),
                    template_index=getattr(task, "template_index", -1),
                    fields_per_alpha=getattr(task, "fields_per_alpha", len(base_flds)),
                    base_fields=list(base_flds),
                    metadata=meta_dict,
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

    def mark_expressions_pruned(self, alpha_shas: List[str]) -> None:
        """标记表达式已被剪枝，不改变回测生命周期状态。"""
        now = self._timestamp()
        conn = self._get_connection()
        for sha in alpha_shas:
            conn.execute(
                """UPDATE alpha_expressions SET pruning_status='pruned', updated_at=?
                   WHERE alpha_sha=?""",
                (now, sha),
            )
        conn.commit()

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

    def _upsert_detail(self, cursor: Any, detail: AlphaDetail, now: str) -> None:
        """内部: 插入或更新 alpha_details."""
        cursor.execute("""
            INSERT INTO alpha_details (
                alpha_id, alpha_sha, expression,
                region, universe, delay, decay, neutralization, truncation,
                sharpe, fitness, turnover, margin, pnl, returns, drawdown, long_count, short_count,
                grade, stage_platform, status_platform,
                sc_result, sc_value, pc_result, pc_value, checks_json, ra_failed, ppa_failed,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(alpha_id) DO UPDATE SET
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
            detail.alpha_id, detail.alpha_sha, detail.expression,
            detail.region, detail.universe, detail.delay, detail.decay, detail.neutralization, detail.truncation,
            detail.sharpe, detail.fitness, detail.turnover, detail.margin, detail.pnl, detail.returns, detail.drawdown,
            detail.long_count, detail.short_count,
            detail.grade, detail.stage_platform, detail.status_platform,
            detail.sc_result, detail.sc_value, detail.pc_result, detail.pc_value, detail.checks_json,
            detail.ra_failed, detail.ppa_failed,
            now, now
        ))
