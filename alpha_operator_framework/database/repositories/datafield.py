"""数据字段与信号特征自学习仓储 (Datafield & Signal Statistics Repository).

管理表:
  - datafields (平台数据字段元数据与使用记录)
  - field_signal_stats (单字段信号统计与命中率自学习)
  - pair_signal_stats (双字段配对组合信号自学习)
  - operator_signal_stats (算子信号统计与胜率沉淀)
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Sequence

from ..base import BaseRepository, _num
from ..models import DataField


class DatafieldRepository(BaseRepository):
    """数据字段与信号特征自学习仓储."""

    def get_tried_field_ids(self, region: str) -> set[str]:
        """获取指定区域已尝试过的字段列表 (用于冷启动探索)."""
        conn = self._get_connection()
        try:
            rows = conn.execute(
                "SELECT DISTINCT field_id FROM field_signal_stats WHERE region=?",
                (region,),
            ).fetchall()
            return {r[0] for r in rows if r[0]}
        except Exception:
            return set()

    def get_existing_datafield_ids(self, region: str, delay: int) -> set[str]:
        """获取已录入库的字段 ID 集合."""
        conn = self._get_connection()
        rows = conn.execute(
            "SELECT field_id FROM datafields WHERE region=? AND delay=?",
            (region, delay),
        ).fetchall()
        return {r[0] for r in rows if r[0]}

    def upsert_datafield(self, row: Dict[str, Any], *, expression_shas: Optional[List[str]] = None) -> Optional[str]:
        """把平台原始 datafield 行 upsert 进 datafields 表."""
        field_id = str(row.get("id") or "")
        if not field_id:
            return None
        dataset = row.get("dataset") or {}
        dataset_id = str(dataset.get("id") or row.get("dataset_id") or "")
        dataset_name = str(dataset.get("name") or "")
        region = str(row.get("region") or "")
        delay = int(row.get("delay") or 1)
        universe = str(row.get("universe") or "")
        cat = row.get("category") or ""
        category = str(cat.get("id") or "") if isinstance(cat, dict) else str(cat or "")
        now = self._timestamp()
        conn = self._get_connection()
        existing = conn.execute(
            "SELECT universes_json, expression_shas_json FROM datafields "
            "WHERE field_id=? AND dataset_id=? AND region=? AND delay=?",
            (field_id, dataset_id, region, delay),
        ).fetchone()
        universes = set(json.loads(existing["universes_json"])) if existing else set()
        if universe:
            universes.add(universe)
        shas = set(json.loads(existing["expression_shas_json"])) if existing else set()
        shas.update(expression_shas or [])
        conn.execute("""
            INSERT INTO datafields (field_id, dataset_id, dataset_name, description, type, region, delay,
                universes_json, coverage, date_coverage, user_count, alpha_count, category, expression_shas_json,
                last_fetched_at, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(field_id, dataset_id, region, delay) DO UPDATE SET
                dataset_name=excluded.dataset_name,
                description=excluded.description,
                type=excluded.type,
                universes_json=excluded.universes_json,
                coverage=excluded.coverage,
                date_coverage=excluded.date_coverage,
                user_count=excluded.user_count,
                alpha_count=excluded.alpha_count,
                category=excluded.category,
                expression_shas_json=excluded.expression_shas_json,
                last_fetched_at=excluded.last_fetched_at,
                updated_at=excluded.updated_at
        """, (
            field_id, dataset_id, dataset_name, str(row.get("description") or ""),
            str(row.get("type") or "MATRIX").upper(), region, delay,
            self._json(sorted(universes)), _num(row, "coverage") or 0.0,
            _num(row, "dateCoverage") or 0.0,
            int(_num(row, "userCount") or 0), int(_num(row, "alphaCount") or 0),
            category, self._json(sorted(shas)), now, now, now,
        ))
        conn.commit()
        return field_id

    def upsert_datafields(self, rows: List[Dict[str, Any]], *,
                          expression_shas: Optional[List[str]] = None) -> int:
        """批量 upsert datafield 行."""
        count = 0
        for row in rows or []:
            if self.upsert_datafield(row, expression_shas=expression_shas):
                count += 1
        return count

    def get_datafields(self, *, region: Optional[str] = None, dataset_id: str = "",
                       limit: int = 200) -> List[DataField]:
        """查询 datafields 表 (支持 region/dataset_id 过滤)."""
        sql = "SELECT * FROM datafields"
        params: List[Any] = []
        conds = []
        if region:
            conds.append("region = ?")
            params.append(region)
        if dataset_id:
            conds.append("dataset_id = ?")
            params.append(dataset_id)
        if conds:
            sql += " WHERE " + " AND ".join(conds)
        sql += " ORDER BY field_id LIMIT ?"
        params.append(limit)
        rows = self._get_connection().execute(sql, params).fetchall()
        out: List[DataField] = []
        for r in rows:
            out.append(DataField(
                field_id=r["field_id"], dataset_id=r["dataset_id"], dataset_name=r["dataset_name"],
                description=r["description"], type=r["type"], region=r["region"], delay=r["delay"],
                universes=json.loads(r["universes_json"] or "[]"), coverage=r["coverage"],
                date_coverage=r["date_coverage"],
                user_count=r["user_count"], alpha_count=r["alpha_count"], category=r["category"] or "",
                expression_shas=json.loads(r["expression_shas_json"] or "[]"),
                last_fetched_at=r["last_fetched_at"], created_at=r["created_at"], updated_at=r["updated_at"],
            ))
        return out

    def missing_datafield_candidates(self, *, region: Optional[str] = None,
                                     delay: Optional[int] = None, limit: int = 200) -> List[str]:
        """返回已被 alpha 使用、但 datafields 表中缺失的字段id池 (增量采集候选)."""
        rows = self._get_connection().execute(
            "SELECT fields FROM alpha_expressions WHERE fields IS NOT NULL AND fields != '[]'"
        ).fetchall()
        used: set[str] = set()
        for r in rows:
            try:
                used.update(json.loads(r["fields"]))
            except (json.JSONDecodeError, TypeError):
                pass
        if region is not None and delay is not None:
            have = {r["field_id"] for r in self._get_connection().execute(
                "SELECT DISTINCT field_id FROM datafields WHERE region=? AND delay=?", (region, delay))}
        else:
            have = {r["field_id"] for r in self._get_connection().execute(
                "SELECT DISTINCT field_id FROM datafields")}
        return sorted(used - have)[:limit]

    def upsert_field_signal_stats(self, rows: List[Dict[str, Any]], *,
                                  accumulate: bool = False) -> int:
        """批量 upsert 字段级信号统计行."""
        now = self._timestamp()
        conn = self._get_connection()
        count = 0
        for row in rows or []:
            field_id = str(row.get("field_id") or "")
            if not field_id:
                continue
            key = (
                field_id, str(row.get("dataset_id") or ""), str(row.get("region") or ""),
                str(row.get("universe") or ""), int(row.get("delay") or 1),
                int(row.get("round") or 0),
            )
            trials = int(row.get("trials") or 0)
            signal_count = int(row.get("signal_count") or 0)
            hit_rate = _num(row, "hit_rate") or 0.0
            avg_sharpe = _num(row, "avg_sharpe") or 0.0
            max_sharpe = _num(row, "max_sharpe") or 0.0
            min_sharpe = _num(row, "min_sharpe") or 0.0
            avg_fitness = _num(row, "avg_fitness") or 0.0

            if accumulate:
                existing = conn.execute(
                    "SELECT trials, signal_count, max_sharpe, min_sharpe FROM field_signal_stats "
                    "WHERE field_id=? AND dataset_id=? AND region=? AND universe=? AND delay=? AND round=?",
                    key,
                ).fetchone()
                if existing:
                    trials += int(existing["trials"] or 0)
                    signal_count += int(existing["signal_count"] or 0)
                    max_sharpe = max(max_sharpe, float(existing["max_sharpe"] or 0.0))
                    min_sharpe = min(min_sharpe, float(existing["min_sharpe"] or 0.0))
                hit_rate = (signal_count / trials) if trials else 0.0

            conn.execute("""
                INSERT INTO field_signal_stats (field_id, dataset_id, region, universe, delay, round,
                    trials, signal_count, hit_rate, avg_sharpe, max_sharpe, min_sharpe, avg_fitness,
                    created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(field_id, dataset_id, region, universe, delay, round) DO UPDATE SET
                    trials=excluded.trials,
                    signal_count=excluded.signal_count,
                    hit_rate=excluded.hit_rate,
                    avg_sharpe=excluded.avg_sharpe,
                    max_sharpe=excluded.max_sharpe,
                    min_sharpe=excluded.min_sharpe,
                    avg_fitness=excluded.avg_fitness,
                    updated_at=excluded.updated_at
            """, (
                field_id, key[1], key[2], key[3], key[4], key[5],
                trials, signal_count, hit_rate, avg_sharpe, max_sharpe, min_sharpe, avg_fitness,
                now, now,
            ))
            count += 1
        conn.commit()
        return count

    def get_field_signal_stats(self, *, region: Optional[str] = None,
                               universe: Optional[str] = None,
                               delay: Optional[int] = None,
                               round_n: Optional[int] = None,
                               min_trials: int = 1,
                               limit: int = 200) -> List[Dict[str, Any]]:
        """查询字段级信号统计, 按 hit_rate 降序."""
        sql = "SELECT * FROM field_signal_stats"
        conds = ["trials >= ?"]
        params: List[Any] = [min_trials]
        if region:
            conds.append("region = ?")
            params.append(region)
        if universe:
            conds.append("universe = ?")
            params.append(universe)
        if delay is not None:
            conds.append("delay = ?")
            params.append(int(delay))
        if round_n is not None:
            conds.append("round = ?")
            params.append(int(round_n))
        sql += " WHERE " + " AND ".join(conds)
        sql += " ORDER BY hit_rate DESC, signal_count DESC LIMIT ?"
        params.append(limit)
        rows = self._get_connection().execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def upsert_pair_signal_stats(self, rows: List[Dict[str, Any]], *,
                                 accumulate: bool = True) -> int:
        """批量 upsert 配对级信号统计行."""
        now = self._timestamp()
        conn = self._get_connection()
        count = 0
        for row in rows or []:
            pair_spec = str(row.get("pair_spec") or "")
            if not pair_spec:
                continue
            key = (
                pair_spec, str(row.get("region") or ""), str(row.get("universe") or ""),
                int(row.get("delay") or 1), int(row.get("round") or 0),
            )
            trials = int(row.get("trials") or 0)
            signal_count = int(row.get("signal_count") or 0)
            hit_rate = _num(row, "hit_rate") or 0.0
            avg_sharpe = _num(row, "avg_sharpe") or 0.0
            max_sharpe = _num(row, "max_sharpe") or 0.0
            min_sharpe = _num(row, "min_sharpe") or 0.0

            if accumulate:
                existing = conn.execute(
                    "SELECT trials, signal_count, max_sharpe, min_sharpe FROM pair_signal_stats "
                    "WHERE pair_spec=? AND region=? AND universe=? AND delay=? AND round=?",
                    key,
                ).fetchone()
                if existing:
                    trials += int(existing["trials"] or 0)
                    signal_count += int(existing["signal_count"] or 0)
                    max_sharpe = max(max_sharpe, float(existing["max_sharpe"] or 0.0))
                    min_sharpe = min(min_sharpe, float(existing["min_sharpe"] or 0.0))
                hit_rate = (signal_count / trials) if trials else 0.0

            conn.execute("""
                INSERT INTO pair_signal_stats (pair_spec, pair_kind, region, universe, delay, round,
                    trials, signal_count, hit_rate, avg_sharpe, max_sharpe, min_sharpe,
                    created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(pair_spec, region, universe, delay, round) DO UPDATE SET
                    trials=excluded.trials,
                    signal_count=excluded.signal_count,
                    hit_rate=excluded.hit_rate,
                    avg_sharpe=excluded.avg_sharpe,
                    max_sharpe=excluded.max_sharpe,
                    min_sharpe=excluded.min_sharpe,
                    updated_at=excluded.updated_at
            """, (
                pair_spec, str(row.get("pair_kind") or ""), key[1], key[2], key[3], key[4],
                trials, signal_count, hit_rate, avg_sharpe, max_sharpe, min_sharpe,
                now, now,
            ))
            count += 1
        conn.commit()
        return count

    def get_pair_signal_stats(self, *, region: Optional[str] = None,
                              round_n: Optional[int] = None,
                              min_trials: int = 1,
                              limit: int = 200) -> List[Dict[str, Any]]:
        """查询配对级信号统计, 按 hit_rate 降序."""
        sql = "SELECT * FROM pair_signal_stats"
        conds = ["trials >= ?"]
        params: List[Any] = [min_trials]
        if region:
            conds.append("region = ?")
            params.append(region)
        if round_n is not None:
            conds.append("round = ?")
            params.append(int(round_n))
        sql += " WHERE " + " AND ".join(conds)
        sql += " ORDER BY hit_rate DESC, signal_count DESC LIMIT ?"
        params.append(limit)
        rows = self._get_connection().execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def upsert_operator_signal_stats(self, rows: List[Dict[str, Any]], *,
                                     accumulate: bool = True) -> int:
        """批量 upsert 算子级信号统计行."""
        now = self._timestamp()
        conn = self._get_connection()
        count = 0
        for row in rows or []:
            op = str(row.get("operator") or "")
            if not op:
                continue
            key = (
                op, str(row.get("region") or ""), str(row.get("universe") or ""),
                int(row.get("delay") or 1), int(row.get("round") or 0),
            )
            trials = int(row.get("trials") or 0)
            signal_count = int(row.get("signal_count") or 0)
            max_sharpe = _num(row, "max_sharpe") or 0.0
            min_sharpe = _num(row, "min_sharpe") or 0.0
            if accumulate:
                existing = conn.execute(
                    "SELECT trials, signal_count, max_sharpe, min_sharpe FROM operator_signal_stats "
                    "WHERE operator=? AND region=? AND universe=? AND delay=? AND round=?",
                    key,
                ).fetchone()
                if existing:
                    trials += existing["trials"]
                    signal_count += existing["signal_count"]
                    max_sharpe = max(max_sharpe, existing["max_sharpe"] or 0.0)
                    min_sharpe = min(min_sharpe, existing["min_sharpe"] or 0.0)
            count += conn.execute(
                """
                INSERT INTO operator_signal_stats
                    (operator, region, universe, delay, round, trials, signal_count, hit_rate,
                     avg_sharpe, max_sharpe, min_sharpe, avg_fitness, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(operator, region, universe, delay, round) DO UPDATE SET
                    trials=excluded.trials, signal_count=excluded.signal_count,
                    hit_rate=excluded.hit_rate, avg_sharpe=excluded.avg_sharpe,
                    max_sharpe=excluded.max_sharpe, min_sharpe=excluded.min_sharpe,
                    avg_fitness=excluded.avg_fitness, updated_at=excluded.updated_at
                """,
                (
                    key[0], key[1], key[2], key[3], key[4],
                    trials, signal_count,
                    (signal_count / trials) if trials else 0.0,
                    _num(row, "avg_sharpe") or 0.0,
                    max_sharpe,
                    min_sharpe,
                    _num(row, "avg_fitness") or 0.0,
                    now, now,
                ),
            ).rowcount
        conn.commit()
        return count

    def get_operator_signal_stats(self, *, region: Optional[str] = None,
                                  universe: Optional[str] = None,
                                  delay: Optional[int] = None,
                                  round_n: Optional[int] = None,
                                  min_trials: int = 1,
                                  limit: int = 200) -> List[Dict[str, Any]]:
        """查询算子级信号统计, 按 hit_rate 降序."""
        sql = "SELECT * FROM operator_signal_stats"
        conds = ["trials >= ?"]
        params: List[Any] = [min_trials]
        if region:
            conds.append("region = ?")
            params.append(region)
        if universe:
            conds.append("universe = ?")
            params.append(universe)
        if delay is not None:
            conds.append("delay = ?")
            params.append(int(delay))
        if round_n is not None:
            conds.append("round = ?")
            params.append(int(round_n))
        sql += " WHERE " + " AND ".join(conds)
        sql += " ORDER BY hit_rate DESC, signal_count DESC LIMIT ?"
        params.append(limit)
        rows = self._get_connection().execute(sql, params).fetchall()
        return [dict(r) for r in rows]
