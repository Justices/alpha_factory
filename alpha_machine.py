#!/usr/bin/env python3
"""可恢复的 Alpha Machine：字段探索、一/二阶构造、回测任务与筛选。

默认不访问 BRAIN；`discover` 与 `simulate --execute` 才会访问平台。所有网络访问
均使用工作区的 managed BRAIN client，避免独立认证会话。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE_PATH = Path("data") / "alpha_research.db"
STANDARD_WINDOWS = (5, 22, 66, 120, 252, 504)
FIRST_ORDER_OPS = ("rank", "zscore", "quantile", "normalize", "ts_rank", "ts_zscore",
                   "ts_delta", "ts_mean", "ts_std_dev", "ts_sum", "ts_delay")
GROUP_OPS = ("group_neutralize", "group_rank", "group_zscore")
VEC_OPS = ("vec_avg", "vec_sum", "vec_min", "vec_count", "vec_max", "vec_stddev", "vec_range")


@dataclass(frozen=True)
class FieldSpec:
    id: str
    dataset_id: str = ""
    type: str = "MATRIX"
    coverage: float = 0.0
    user_count: int = 0
    alpha_count: int = 0
    category: str = ""
    description: str = ""


@dataclass(frozen=True)
class QualityGate:
    sharpe: float = 1.2
    fitness: float = 0.7
    margin: float = 5.0
    min_turnover: float = 0.01
    max_turnover: float = 0.70
    require_sub_universe_pass: bool = False
    require_2y_pass: bool = False


def field_from_dict(row: dict[str, Any]) -> FieldSpec:
    # category 兼容嵌套 dict {"id":...} 与字符串 (平台原始行 category 是嵌套对象)
    cat = row.get("category") or row.get("category_name") or ""
    if isinstance(cat, dict):
        cat = str(cat.get("id") or "")
    return FieldSpec(
        id=str(row["id"]), dataset_id=str(row.get("dataset_id") or row.get("dataset", {}).get("id") or ""),
        type=str(row.get("type") or "MATRIX").upper(), coverage=float(row.get("coverage") or 0),
        user_count=int(row.get("userCount") or row.get("user_count") or 0),
        alpha_count=int(row.get("alphaCount") or row.get("alpha_count") or 0),
        category=str(cat),
        description=str(row.get("description") or ""),
    )


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )


def database_path(args: argparse.Namespace) -> Path:
    """Return the durable simulation database, optionally overridden by the CLI."""
    configured = getattr(args, "database", None)
    return Path(configured) if configured else DEFAULT_DATABASE_PATH


def prepare_super_candidates(database: Any, settings: dict[str, Any], *, max_candidates: int = 6) -> list[dict[str, Any]]:
    """Build and persist bounded SUPER hypotheses from regular alpha_details records."""
    from alpha_operator_framework.super_alpha import SuperAlphaConfig, build_super_candidates

    rows = [dict(row) for row in database._get_connection().execute(
        "SELECT alpha_id, expression, sharpe, fitness, turnover, sc_value, pc_value FROM alpha_details"
    ).fetchall()]
    candidates = build_super_candidates(rows, SuperAlphaConfig(max_candidates=max_candidates), settings)
    database.save_super_candidates(candidates, settings)
    return candidates


def select_fields(rows: Iterable[dict[str, Any]], *, dataset_id: str = "", data_type: str = "",
                  min_coverage: float = 0.0, max_users: int | None = None,
                  require_used: bool = False, limit: int = 0) -> list[FieldSpec]:
    """对 MCP 字段返回做确定性筛选；coverage/userCount 缺失时按 0 处理。"""
    selected: list[FieldSpec] = []
    for row in rows:
        field = field_from_dict(row)
        if dataset_id and field.dataset_id != dataset_id:
            continue
        if data_type and field.type != data_type.upper():
            continue
        if field.coverage < min_coverage:
            continue
        if max_users is not None and field.user_count > max_users:
            continue
        if require_used and field.user_count <= 0:
            continue
        selected.append(field)
    selected.sort(key=lambda f: (-f.coverage, f.user_count, -f.alpha_count, f.id))
    return selected[:limit] if limit else selected


def preprocess_field(field: FieldSpec, *, backfill: int = 120, winsorize_std: float = 4.0,
                     vector_ops: Sequence[str] = VEC_OPS) -> list[str]:
    """将可用 MATRIX/VECTOR 字段变成一阶工厂的标量输入；GROUP 不当作原子信号。"""
    if field.type == "MATRIX":
        bases = [field.id]
    elif field.type == "VECTOR":
        bases = [f"{op}({field.id})" for op in vector_ops]
    else:
        return []
    return [f"winsorize(ts_backfill({base}, {backfill}), std={winsorize_std:g})" for base in bases]


def preprocess_fields(fields: Iterable[FieldSpec], **kwargs: Any) -> list[str]:
    return [expr for field in fields for expr in preprocess_field(field, **kwargs)]


def first_order_factory(fields: Iterable[str], ops: Sequence[str] = FIRST_ORDER_OPS,
                        windows: Sequence[int] = STANDARD_WINDOWS) -> list[str]:
    expressions: list[str] = []
    for field in fields:
        expressions.append(field)
        for op in ops:
            if op.startswith("ts_"):
                expressions.extend(f"{op}({field}, {window})" for window in windows)
            else:
                expressions.append(f"{op}({field})")
    return expressions


def group_candidates(region: str, *, field_type: str = "MATRIX", category: str = "",
                     available_groups: Sequence[FieldSpec] = ()) -> list[str]:
    """从当前设定下实际可用的 GROUP 字段中选择二阶 group。

    ``available_groups`` 应来自同一 Region/Universe/Delay 的字段查询；因此不会把其它
    区域的 pv13/sta 等历史字段硬编码进表达式。没有元数据时仅保留 BRAIN 通用分类 group，
    作为离线兼容回退。
    """
    category = category.lower()
    base = ["market", "sector", "industry", "subindustry"]
    structural = [
        "bucket(rank(cap), range='0.1, 1, 0.1')",
        "bucket(rank(close * volume), range='0.1, 1, 0.1')",
    ]
    if any(key in category for key in ("fundamental", "analyst", "earnings", "value", "quality")):
        structural.insert(1, "bucket(rank(assets), range='0.1, 1, 0.1')")
    if any(key in category for key in ("pv", "price", "volume", "risk", "sentiment")):
        structural.append("bucket(rank(ts_std_dev(returns, 20)), range='0.1, 1, 0.1')")
    actual_groups = [field for field in available_groups if field.type == "GROUP"]
    actual_groups.sort(key=lambda field: (-field.coverage, field.user_count, field.id))
    dynamic = [field.id for field in actual_groups]
    if field_type.upper() == "VECTOR":
        # VECTOR 已由 vec_* 归约，使用行业/流动性横截面，避免把原始向量当 group。
        candidates = base[1:] + structural[-2:] + dynamic
    else:
        candidates = base + structural + dynamic
    return list(dict.fromkeys(candidates))


def group_factory(op: str, expression: str, region: str, *, field_type: str = "MATRIX",
                  category: str = "", groups: Sequence[str] | None = None,
                  available_groups: Sequence[FieldSpec] = ()) -> list[str]:
    if op not in GROUP_OPS:
        raise ValueError(f"unsupported group operator: {op}")
    return [f"{op}({expression}, densify({group}))"
            for group in (list(groups) if groups is not None else group_candidates(
                region, field_type=field_type, category=category, available_groups=available_groups
            ))]


def second_order_factory(expressions: Iterable[str], region: str, *, field_type: str = "MATRIX",
                         category: str = "", ops: Sequence[str] = GROUP_OPS,
                         available_groups: Sequence[FieldSpec] = ()) -> list[str]:
    return [candidate for expression in expressions for op in ops
            for candidate in group_factory(op, expression, region, field_type=field_type, category=category,
                                           available_groups=available_groups)]


def pair_and_shuffle(expressions: Iterable[str], decays: Sequence[float] = (6,), seed: int | None = None) -> list[dict[str, Any]]:
    tasks = [{"expression": expression, "decay": decay} for expression in expressions for decay in decays]
    random.Random(seed).shuffle(tasks)
    return tasks


def load_task_pool(tasks: Sequence[dict[str, Any]], batch_size: int = 8, concurrency: int = 1) -> list[list[list[dict[str, Any]]]]:
    if not 2 <= batch_size <= 8:
        raise ValueError("batch_size must be in [2, 8] for create_multi_simulation")
    if concurrency < 1:
        raise ValueError("concurrency must be positive")
    batches = [list(tasks[i:i + batch_size]) for i in range(0, len(tasks), batch_size)]
    return [batches[i:i + concurrency] for i in range(0, len(batches), concurrency)]


def _metric(row: dict[str, Any], key: str) -> Any:
    return row.get(key, (row.get("is") or {}).get(key))


def filter_alpha_results(rows: Iterable[dict[str, Any]], gate: QualityGate = QualityGate()) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    kept, rejected = [], []
    for row in rows:
        reasons: list[str] = []
        sharpe, fitness, margin, turnover = (_metric(row, key) for key in ("sharpe", "fitness", "margin", "turnover"))
        if not isinstance(sharpe, (int, float)) or sharpe <= gate.sharpe: reasons.append("sharpe")
        if not isinstance(fitness, (int, float)) or fitness <= gate.fitness: reasons.append("fitness")
        if not isinstance(margin, (int, float)) or margin <= gate.margin: reasons.append("margin")
        if isinstance(turnover, (int, float)) and not gate.min_turnover <= turnover <= gate.max_turnover: reasons.append("turnover")
        checks = {c.get("name"): c.get("result") for c in ((row.get("is") or {}).get("checks") or []) if isinstance(c, dict)}
        if gate.require_sub_universe_pass and checks.get("LOW_SUB_UNIVERSE_SHARPE") != "PASS": reasons.append("sub_universe")
        if gate.require_2y_pass and checks.get("LOW_2Y_SHARPE") != "PASS": reasons.append("low_2y")
        enriched = {**row, "filter_reasons": reasons}
        (kept if not reasons else rejected).append(enriched)
    kept.sort(key=lambda row: (_metric(row, "sharpe") or -999, _metric(row, "fitness") or -999), reverse=True)
    return kept, rejected


async def fetch_datafields(region: str, universe: str, delay: int, dataset_id: str = "", search: str = "", data_type: str = "", page_delay: float = 0.5) -> list[dict[str, Any]]:
    """获取数据字段列表 (带翻页延迟防 429).

    Args:
        region: 区域
        universe: 股票池
        delay: 延迟
        dataset_id: 数据集 ID 过滤
        search: 搜索词
        data_type: 字段类型过滤
        page_delay: 翻页间隔秒数 (默认 0.5s, 防止 429)

    Returns:
        字段列表
    """
    import asyncio
    from cnhkmcp.untracked.platform_functions import brain_client
    await brain_client.ensure_authenticated()
    params: dict[str, str] = {"instrumentType": "EQUITY", "region": region, "universe": universe,
                              "delay": str(delay), "limit": "50", "offset": "0"}
    if dataset_id: params["dataset.id"] = dataset_id
    if search: params["search"] = search
    if data_type: params["type"] = data_type.upper()
    rows: list[dict[str, Any]] = []
    total: int | None = None
    page_count = 0
    while total is None or len(rows) < total:
        if page_count > 0 and page_delay > 0:
            await asyncio.sleep(page_delay)
        params["offset"] = str(len(rows))
        response = brain_client.session.get(f"{brain_client.base_url}/data-fields", params=params)
        response.raise_for_status()
        payload = response.json()
        total = int(payload.get("count") or 0)
        page = payload.get("results") or []
        if not page: break
        rows.extend(page)
        page_count += 1
    return rows


async def simulate(tasks: Sequence[dict[str, Any]], args: argparse.Namespace,
                    wait_for_completion: bool = False,
                    poll_interval: float = 5.0,
                    max_wait: float = 600.0) -> list[dict[str, Any]]:
    """Submit durable batches and optionally wait for completion.

    Args:
        tasks: List of {expression, decay} dicts
        args: Namespace with region/universe/delay/batch_size etc.
        wait_for_completion: If True, poll each batch until complete before next
        poll_interval: Seconds between polls when waiting
        max_wait: Maximum seconds to wait per batch

    Returns:
        List of result dicts (with alpha_id/sharpe/fitness if waited)
    """
    from alpha_operator_framework.database import AlphaDatabase
    from alpha_operator_framework.simulation_tracker import SimulationTracker
    from cnhkmcp.untracked.platform_functions import brain_client
    await brain_client.ensure_authenticated()
    results: list[dict[str, Any]] = []
    by_decay: dict[float, list[dict[str, Any]]] = {}
    for task in tasks: by_decay.setdefault(float(task["decay"]), []).append(task)

    for decay, items in by_decay.items():
        for start in range(0, len(items), args.batch_size):
            batch = items[start:start + args.batch_size]
            if len(batch) < 2:
                results.extend({**task, "status": "PENDING_NEEDS_PAIR"} for task in batch)
                continue
            settings = {"region": args.region, "universe": args.universe, "delay": args.delay,
                        "decay": decay, "neutralization": args.neutralization, "truncation": args.truncation,
                        "nan_handling": args.nan_handling, "test_period": args.test_period}
            db = AlphaDatabase(database_path(args))
            try:
                def submit(batch_tasks):
                    payload = [{"type": "REGULAR", "settings": {
                        "instrumentType": "EQUITY", "region": args.region, "universe": args.universe,
                        "delay": args.delay, "decay": decay, "neutralization": args.neutralization,
                        "truncation": args.truncation, "pasteurization": "ON", "unitHandling": "VERIFY",
                        "nanHandling": args.nan_handling, "language": "FASTEXPR", "visualization": False,
                        "testPeriod": args.test_period, "maxTrade": "OFF",
                    }, "regular": task["expression"]} for task in batch_tasks]
                    response = brain_client.session.post(f"{brain_client.base_url}/simulations", json=payload)
                    response.raise_for_status()
                    location = response.headers.get("Location")
                    if not location:
                        raise RuntimeError("platform did not return a simulation Location")
                    return location

                def fetch(location):
                    response = brain_client.session.get(location)
                    response.raise_for_status()
                    return (response.json() if response.text else {}, float(response.headers.get("Retry-After", 0)))

                def detail(alpha_id):
                    response = brain_client.session.get(f"{brain_client.base_url}/alphas/{alpha_id}")
                    response.raise_for_status()
                    return response.json()

                tracker = SimulationTracker(db, submit=submit, fetch=fetch, detail=detail)
                batch_id = tracker.submit(batch, settings)

                if wait_for_completion:
                    # 等待批次完成
                    batch_result = await _wait_for_batch(
                        tracker, batch_id, db,
                        poll_interval=poll_interval,
                        max_wait=max_wait
                    )
                    results.extend(batch_result)
                else:
                    results.append({"simulation_batch_id": batch_id, "status": "submitted",
                                    "requested_count": len(batch)})
            finally:
                db.close()
    return results


async def _wait_for_batch(tracker, batch_id: int, db,
                          poll_interval: float = 5.0,
                          max_wait: float = 600.0) -> list[dict[str, Any]]:
    """轮询等待批次完成，返回结果列表."""
    import asyncio
    import time

    start_time = time.time()
    while True:
        elapsed = time.time() - start_time
        if elapsed > max_wait:
            # 超时，返回当前状态
            batch = tracker.poll(batch_id)
            return db.get_simulation_results(batch_id) or [{"batch_id": batch_id, "status": "timeout"}]

        batch = tracker.poll(batch_id)
        status = batch.get("status", "") if batch else ""

        if status in ("COMPLETED", "DONE", "completed"):
            # 批次完成，返回结果
            results = db.get_simulation_results(batch_id)
            return results if results else [{"batch_id": batch_id, "status": "completed", "alpha_count": 0}]

        if status in ("FAILED", "ERROR", "failed", "error"):
            return [{"batch_id": batch_id, "status": "failed"}]

        # 未完成，等待后继续轮询
        await asyncio.sleep(poll_interval)


async def poll_simulation_batch(batch_id: int, database: Path = DEFAULT_DATABASE_PATH) -> dict[str, Any]:
    """Poll one persisted platform batch without submitting a new simulation."""
    from alpha_operator_framework.database import AlphaDatabase
    from alpha_operator_framework.simulation_tracker import SimulationTracker
    from cnhkmcp.untracked.platform_functions import brain_client

    await brain_client.ensure_authenticated()
    db = AlphaDatabase(database)
    try:
        def fetch(location):
            response = brain_client.session.get(location)
            response.raise_for_status()
            return (response.json() if response.text else {}, float(response.headers.get("Retry-After", 0)))

        def detail(alpha_id):
            response = brain_client.session.get(f"{brain_client.base_url}/alphas/{alpha_id}")
            response.raise_for_status()
            return response.json()

        tracker = SimulationTracker(db, submit=lambda _: "", fetch=fetch, detail=detail)
        batch = tracker.poll(batch_id)
        return {"batch": batch, "results": db.get_simulation_results(batch_id)}
    finally:
        db.close()


async def simulate_super(candidates: Sequence[dict[str, Any]], args: argparse.Namespace) -> list[dict[str, Any]]:
    """Submit each durable SUPER hypothesis once; polling is a separate command."""
    from alpha_operator_framework.database import AlphaDatabase
    from alpha_operator_framework.simulation_tracker import SimulationTracker
    from alpha_operator_framework.super_alpha import super_simulation_payload
    from cnhkmcp.untracked.platform_functions import brain_client

    await brain_client.ensure_authenticated()
    settings = {"region": args.region, "universe": args.universe, "delay": args.delay, "decay": args.decay,
                "neutralization": args.neutralization, "truncation": args.truncation, "nan_handling": args.nan_handling,
                "simulation_type": "SUPER"}
    results = []
    for candidate in candidates:
        task = {**candidate, "expression": candidate["candidate_sha"], "decay": args.decay}
        db = AlphaDatabase(database_path(args))
        try:
            def submit(tasks):
                payload = super_simulation_payload(tasks[0], {"instrumentType": "EQUITY", **settings,
                    "pasteurization": "ON", "unitHandling": "VERIFY", "language": "FASTEXPR", "visualization": False})
                response = brain_client.session.post(f"{brain_client.base_url}/simulations", json=payload)
                response.raise_for_status()
                location = response.headers.get("Location")
                if not location:
                    raise RuntimeError("platform did not return a simulation Location")
                return location
            tracker = SimulationTracker(db, submit=submit, fetch=lambda _: ({}, 0), detail=lambda _: {})
            batch_id = tracker.submit([task], settings)
            results.append({"candidate_sha": candidate["candidate_sha"], "simulation_batch_id": batch_id, "status": "submitted"})
        finally:
            db.close()
    return results


def parse_decays(raw: str) -> tuple[float, ...]:
    values = tuple(float(value.strip()) for value in raw.split(",") if value.strip())
    if not values: raise ValueError("at least one decay is required")
    return values


def command_discover(args: argparse.Namespace) -> None:
    rows = asyncio.run(fetch_datafields(args.region, args.universe, args.delay, args.dataset, args.search, args.type))
    fields = select_fields(rows, dataset_id=args.dataset, data_type=args.type, min_coverage=args.min_coverage,
                           max_users=args.max_users, require_used=args.require_used, limit=args.limit)
    write_json(Path(args.output), {"settings": vars(args), "fields": [asdict(field) for field in fields]})
    print(f"fields={len(fields)} output={args.output}")


def command_prepare(args: argparse.Namespace) -> None:
    payload = read_json(Path(args.fields))
    fields = [field_from_dict(row) for row in payload.get("fields", payload)]
    atomic = preprocess_fields(fields, backfill=args.backfill, winsorize_std=args.winsorize_std)
    expressions = first_order_factory(atomic, windows=tuple(args.windows))
    tasks = pair_and_shuffle(expressions, parse_decays(args.decays), args.seed)
    write_json(Path(args.output), {"fields": [asdict(field) for field in fields], "atomic_fields": atomic,
                                   "first_order_expressions": expressions, "tasks": tasks,
                                   "pools": load_task_pool(tasks, args.batch_size, args.concurrency)})
    print(f"atomic={len(atomic)} first_order={len(expressions)} tasks={len(tasks)} output={args.output}")


def command_filter(args: argparse.Namespace) -> None:
    payload = read_json(Path(args.results))
    rows = payload.get("results", payload) if isinstance(payload, dict) else payload
    gate = QualityGate(args.sharpe, args.fitness, args.margin, args.min_turnover, args.max_turnover,
                       args.require_sub_universe_pass, args.require_2y_pass)
    kept, rejected = filter_alpha_results(rows, gate)
    write_json(Path(args.output), {"gate": asdict(gate), "kept": kept, "rejected": rejected})
    print(f"kept={len(kept)} rejected={len(rejected)} output={args.output}")


def command_second_order(args: argparse.Namespace) -> None:
    payload = read_json(Path(args.winners))
    winners = payload.get("kept", payload) if isinstance(payload, dict) else payload
    expressions = [row.get("expression") or row.get("regular", {}).get("code") for row in winners]
    expressions = [expr for expr in expressions if expr]
    group_fields: list[FieldSpec] = []
    if args.groups_file:
        group_payload = read_json(Path(args.groups_file))
        group_fields = [field_from_dict(row) for row in group_payload.get("fields", group_payload)]
    elif args.fetch_groups:
        rows = asyncio.run(fetch_datafields(args.region, args.universe, args.delay, data_type="GROUP"))
        group_fields = [field_from_dict(row) for row in rows]
    second = second_order_factory(expressions, args.region, field_type=args.field_type, category=args.category,
                                  available_groups=group_fields)
    tasks = pair_and_shuffle(second, parse_decays(args.decays), args.seed)
    write_json(Path(args.output), {"source_count": len(expressions), "group_fields": [asdict(field) for field in group_fields],
                                   "expressions": second, "tasks": tasks,
                                   "pools": load_task_pool(tasks, args.batch_size, args.concurrency)})
    print(f"second_order={len(second)} tasks={len(tasks)} output={args.output}")


def command_simulate(args: argparse.Namespace) -> None:
    if not args.execute:
        raise SystemExit("Refusing to consume BRAIN simulation quota: rerun with --execute.")
    payload = read_json(Path(args.tasks))
    tasks = payload.get("tasks", payload) if isinstance(payload, dict) else payload
    results = asyncio.run(simulate(tasks, args))
    write_json(Path(args.output), {"settings": vars(args), "results": results})
    print(f"simulation batches={len(results)} output={args.output}")


def command_poll_simulation(args: argparse.Namespace) -> None:
    payload = asyncio.run(poll_simulation_batch(args.batch_id, database_path(args)))
    write_json(Path(args.output), payload)
    batch = payload["batch"]
    print(f"batch={args.batch_id} status={batch['status']} completed={batch['completed_count']} failed={batch['failed_count']}")


def command_prepare_super(args: argparse.Namespace) -> None:
    from alpha_operator_framework.database import AlphaDatabase
    settings = {"region": args.region, "universe": args.universe, "delay": args.delay, "decay": args.decay,
                "neutralization": args.neutralization, "truncation": args.truncation, "nan_handling": args.nan_handling}
    db = AlphaDatabase(database_path(args))
    try:
        candidates = prepare_super_candidates(db, settings, max_candidates=args.max_candidates)
    finally:
        db.close()
    write_json(Path(args.output), {"settings": settings, "candidates": candidates})
    print(f"super_candidates={len(candidates)} output={args.output}")


def command_simulate_super(args: argparse.Namespace) -> None:
    if not args.execute:
        raise SystemExit("Refusing to consume BRAIN simulation quota: rerun with --execute.")
    payload = read_json(Path(args.candidates))
    candidates = payload.get("candidates", payload) if isinstance(payload, dict) else payload
    results = asyncio.run(simulate_super(candidates, args))
    write_json(Path(args.output), {"settings": vars(args), "results": results})
    print(f"super simulation batches={len(results)} output={args.output}")


def add_settings(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--region", required=True); parser.add_argument("--universe", required=True)
    parser.add_argument("--delay", type=int, default=1)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    discover = sub.add_parser("discover", help="按平台条件获取并筛选全量字段")
    add_settings(discover); discover.add_argument("--dataset", default=""); discover.add_argument("--search", default="")
    discover.add_argument("--type", default=""); discover.add_argument("--min-coverage", type=float, default=0.0)
    discover.add_argument("--max-users", type=int); discover.add_argument("--require-used", action="store_true")
    discover.add_argument("--limit", type=int, default=0); discover.add_argument("--output", required=True); discover.set_defaults(func=command_discover)
    prepare = sub.add_parser("prepare", help="预处理字段、一阶生成、配 decay、shuffle、task pool")
    prepare.add_argument("--fields", required=True); prepare.add_argument("--output", required=True)
    prepare.add_argument("--backfill", type=int, default=120); prepare.add_argument("--winsorize-std", type=float, default=4)
    prepare.add_argument("--windows", type=int, nargs="+", default=list(STANDARD_WINDOWS)); prepare.add_argument("--decays", default="6")
    prepare.add_argument("--seed", type=int); prepare.add_argument("--batch-size", type=int, default=8); prepare.add_argument("--concurrency", type=int, default=1); prepare.set_defaults(func=command_prepare)
    filter_p = sub.add_parser("filter", help="按 Alpha 指标筛选潜力候选")
    filter_p.add_argument("--results", required=True); filter_p.add_argument("--output", required=True)
    filter_p.add_argument("--sharpe", type=float, default=1.2); filter_p.add_argument("--fitness", type=float, default=0.7); filter_p.add_argument("--margin", type=float, default=5)
    filter_p.add_argument("--min-turnover", type=float, default=0.01); filter_p.add_argument("--max-turnover", type=float, default=0.70)
    filter_p.add_argument("--require-sub-universe-pass", action="store_true"); filter_p.add_argument("--require-2y-pass", action="store_true"); filter_p.set_defaults(func=command_filter)
    second = sub.add_parser("second-order", help="以字段适配 group 规则生成二阶任务")
    add_settings(second); second.add_argument("--winners", required=True); second.add_argument("--output", required=True)
    second.add_argument("--field-type", default="MATRIX"); second.add_argument("--category", default="")
    second.add_argument("--groups-file", default="", help="同一设定下 discover --type GROUP 的输出")
    second.add_argument("--fetch-groups", action="store_true", help="实时获取同一 Region/Universe/Delay 的 GROUP 字段")
    second.add_argument("--decays", default="6"); second.add_argument("--seed", type=int); second.add_argument("--batch-size", type=int, default=8); second.add_argument("--concurrency", type=int, default=1); second.set_defaults(func=command_second_order)
    sim = sub.add_parser("simulate", help="使用 MCP multi-simulation 回测已准备任务")
    add_settings(sim); sim.add_argument("--tasks", required=True); sim.add_argument("--output", required=True); sim.add_argument("--execute", action="store_true")
    sim.add_argument("--batch-size", type=int, default=8); sim.add_argument("--neutralization", default="SUBINDUSTRY"); sim.add_argument("--truncation", type=float, default=0.08)
    sim.add_argument("--nan-handling", default="OFF"); sim.add_argument("--test-period", default="P0Y0M")
    sim.add_argument("--database", default=str(DEFAULT_DATABASE_PATH), help="持久化回测状态的 SQLite 文件")
    sim.set_defaults(func=command_simulate)
    poll = sub.add_parser("poll-simulation", help="Poll an existing persisted BRAIN simulation batch")
    poll.add_argument("--batch-id", required=True, type=int)
    poll.add_argument("--output", required=True)
    poll.add_argument("--database", default=str(DEFAULT_DATABASE_PATH), help="持久化回测状态的 SQLite 文件")
    poll.set_defaults(func=command_poll_simulation)
    super_prepare = sub.add_parser("prepare-super", help="从已回测普通 Alpha 构造并持久化 Super Alpha 候选")
    add_settings(super_prepare)
    super_prepare.add_argument("--output", required=True); super_prepare.add_argument("--database", default=str(DEFAULT_DATABASE_PATH))
    super_prepare.add_argument("--max-candidates", type=int, default=6); super_prepare.add_argument("--decay", type=float, default=6)
    super_prepare.add_argument("--neutralization", default="SUBINDUSTRY"); super_prepare.add_argument("--truncation", type=float, default=0.08)
    super_prepare.add_argument("--nan-handling", default="OFF"); super_prepare.set_defaults(func=command_prepare_super)
    super_sim = sub.add_parser("simulate-super", help="异步提交已准备的 Super Alpha 候选")
    add_settings(super_sim); super_sim.add_argument("--candidates", required=True); super_sim.add_argument("--output", required=True)
    super_sim.add_argument("--execute", action="store_true"); super_sim.add_argument("--database", default=str(DEFAULT_DATABASE_PATH))
    super_sim.add_argument("--decay", type=float, default=6); super_sim.add_argument("--neutralization", default="SUBINDUSTRY")
    super_sim.add_argument("--truncation", type=float, default=0.08); super_sim.add_argument("--nan-handling", default="OFF")
    super_sim.set_defaults(func=command_simulate_super)
    super_poll = sub.add_parser("poll-super", help="轮询已持久化的 Super Alpha 回测批次")
    super_poll.add_argument("--batch-id", required=True, type=int); super_poll.add_argument("--output", required=True)
    super_poll.add_argument("--database", default=str(DEFAULT_DATABASE_PATH)); super_poll.set_defaults(func=command_poll_simulation)
    args = parser.parse_args(); args.func(args)


if __name__ == "__main__":
    main()
