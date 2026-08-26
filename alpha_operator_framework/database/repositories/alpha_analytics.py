"""Alpha repository analytics and aggregate queries."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..base import BaseRepository
from ..models import AlphaDetail


class AlphaAnalyticsMixin(BaseRepository):
    """Alpha queries, candidate analytics, and dashboard aggregates."""

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

    def _row_to_detail(self, row: Any) -> AlphaDetail:
        """将数据库行转换为 AlphaDetail 对象."""
        return AlphaDetail(
            id=row['id'],
            alpha_id=row['alpha_id'],
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

    def dashboard_snapshot(self) -> Dict[str, Any]:
        """Return the read-only production dashboard aggregate."""
        conn = self._get_connection()
        expression_status = {row[0]: int(row[1]) for row in conn.execute(
            "SELECT status, COUNT(*) FROM alpha_expressions GROUP BY status"
        ).fetchall()}
        simulation_row = conn.execute(
            "SELECT COUNT(*), AVG(sharpe), MAX(sharpe), AVG(turnover) FROM alpha_details"
        ).fetchone()
        workflow_status = {row[0]: int(row[1]) for row in conn.execute(
            "SELECT wf_stage, COUNT(*) FROM alpha_details GROUP BY wf_stage"
        ).fetchall()}
        submission_ready = [dict(row) for row in conn.execute(
            "SELECT alpha_id, expression, sharpe, fitness, turnover, margin FROM alpha_details "
            "WHERE wf_stage = 'submission_ready' ORDER BY sharpe DESC LIMIT 5"
        ).fetchall()]
        templates = [dict(row) for row in conn.execute(
            "SELECT id, name, family, expression_template FROM template_library "
            "WHERE active = 1 ORDER BY id DESC LIMIT 5"
        ).fetchall()]
        return {
            "expression_status": expression_status,
            "simulation": {"total": int(simulation_row[0] or 0), "avg_sharpe": float(simulation_row[1] or 0), "max_sharpe": float(simulation_row[2] or 0), "avg_turnover": float(simulation_row[3] or 0)},
            "workflow_status": workflow_status,
            "submission_ready": submission_ready,
            "templates": templates,
        }

    def get_total_alpha_details_count(self) -> int:
        """获取已回测记录的 Alpha 总数."""
        conn = self._get_connection()
        row = conn.execute("SELECT COUNT(*) FROM alpha_details").fetchone()
        return int(row[0]) if row else 0
