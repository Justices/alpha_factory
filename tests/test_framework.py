#!/usr/bin/env python
"""
单元测试 — Alpha Operator Framework

测试核心模块:
  - operators: 算子库和工厂函数
  - families: 模板族生成
  - fields: 字段预处理
  - density: 因子密度评估
"""

import sys
import sqlite3
import tempfile
import ast
import importlib
import json
from pathlib import Path

# 添加项目根目录到PYTHONPATH
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from alpha_operator_framework import (
    # 算子
    basic_ops, ts_ops, group_ops, vec_ops, extended_ops,
    ts_factory, first_order_factory,
    # 模板族
    UNARY_TEMPLATES, BINARY_TEMPLATES, TERNARY_TEMPLATES,
    unary_factory, binary_factory, ternary_factory, first_order_task_factory,
    Task,
    # 字段
    FieldSpec, SampleSpec,
    preprocess_field, sample_scalar_expressions, load_local_field_specs,
    find_positive_negative_pairs, find_cap_pairs, semantic_pair_task_factory,
    # 密度
    SignalGate, compute_density, top_templates,
    # 剪枝
    classify_field, extract_field_ids,
    semantic_prune_fields, SemanticPruneConfig,
    field_topk_prune, FieldTopKConfig,
)
from alpha_operator_framework.database import AlphaDatabase
from alpha_operator_framework.economic_rules import allowed_first_order_ops
from alpha_operator_framework.local_fields import (
    default_fields_directory, default_dataset_file, load_local_field_directory,
)
from alpha_machine import write_json
from alpha_machine import main as alpha_machine_main
from alpha_operator_framework.simulation_tracker import SimulationTracker
from alpha_operator_framework.paired_bases import (
    discover_pair_specs, paired_field_ids, parse_pair_spec, paired_base_task_factory,
    paired_group_first_order_task_factory,
)


def test_operators():
    """测试算子库."""
    print("测试算子库...")

    # 基础检查
    assert len(basic_ops) == 6, f"basic_ops应有6个, 实际{len(basic_ops)}"
    assert len(ts_ops) >= 10, f"ts_ops应至少10个, 实际{len(ts_ops)}"
    assert len(group_ops) == 3, f"group_ops应有3个, 实际{len(group_ops)}"
    assert vec_ops == [
        "vec_avg", "vec_sum", "vec_min", "vec_max", "vec_stddev", "vec_range", "vec_count"
    ], f"VEC算子集合不正确: {vec_ops}"

    # ts_factory测试
    exprs = ts_factory("ts_rank", "close", windows=[5, 22])
    assert len(exprs) == 2, f"应生成2个表达式, 实际{len(exprs)}"
    assert exprs[0] == "ts_rank(close, 5)", f"第一个表达式应为'ts_rank(close, 5)', 实际'{exprs[0]}'"

    # first_order_factory测试
    exprs = first_order_factory(["close"], ["rank", "ts_rank"])
    assert len(exprs) > 0, "应生成至少1个表达式"

    print("✓ 算子库测试通过")


def test_families():
    """测试模板族."""
    print("测试模板族...")

    # 常量检查
    assert len(UNARY_TEMPLATES) == 10, f"一元模板应有10个, 实际{len(UNARY_TEMPLATES)}"
    assert len(BINARY_TEMPLATES) == 8, f"二元模板应有8个, 实际{len(BINARY_TEMPLATES)}"
    assert len(TERNARY_TEMPLATES) == 7, f"三元模板应有7个, 实际{len(TERNARY_TEMPLATES)}"

    # Task数据结构测试
    task = Task(
        expression="rank(close)",
        template_index=0,
        family="unary",
        fields_per_alpha=1,
        decay=6.0
    )
    assert task.to_sim_dict() == {"expression": "rank(close)", "decay": 6.0}

    # unary_factory测试
    scalars = ["close", "volume"]
    tasks = unary_factory(scalars)
    assert {task.expression_origin for task in tasks} == {"unary_template"}

    first_order_tasks = first_order_task_factory(["close"], ["rank"])
    assert {task.expression_origin for task in first_order_tasks} == {"first_order"}
    assert len(tasks) == 20, f"2字段×10模板应生成20个任务, 实际{len(tasks)}"

    # binary_factory测试
    tasks = binary_factory(scalars)
    assert len(tasks) == 8, f"1对×8模板应生成8个任务, 实际{len(tasks)}"

    # ternary_factory测试
    scalars3 = ["close", "volume", "returns"]
    tasks = ternary_factory(scalars3)
    assert len(tasks) == 7, f"1三元组×7模板应生成7个任务, 实际{len(tasks)}"

    print("✓ 模板族测试通过")


def test_expression_origin_catalog():
    """alpha_expressions persists expression origin in a dedicated column."""
    with tempfile.TemporaryDirectory() as tmp:
        db = AlphaDatabase(Path(tmp) / "research.db")
        task = unary_factory(["close"])[0]
        db.catalog_tasks([task])
        row = db._get_connection().execute(
            "SELECT expression_origin FROM alpha_expressions WHERE expression = ?", (task.expression,)
        ).fetchone()
        assert row["expression_origin"] == "unary_template"
        db.close()


def test_density_separates_same_index_by_expression_origin():
    rows = compute_density([
        {"family": "unary", "template_index": 0, "expression_origin": "unary_template"},
        {"family": "unary", "template_index": 0, "expression_origin": "first_order"},
    ])
    assert {row.expression_origin for row in rows} == {"unary_template", "first_order"}


def test_expression_origin_migrates_legacy_database():
    """Opening a legacy alpha_expressions table adds and populates the origin column."""
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "legacy.db"
        conn = sqlite3.connect(db_path)
        conn.execute("""
            CREATE TABLE alpha_expressions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                expression_sha TEXT NOT NULL UNIQUE,
                expression TEXT NOT NULL,
                settings TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        legacy_task = first_order_task_factory(["close"], ["rank"])[0]
        conn.execute(
            "INSERT INTO alpha_expressions (expression_sha, expression, settings, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (AlphaDatabase.compute_sha(legacy_task.expression), legacy_task.expression, "{}", "legacy", "legacy"),
        )
        conn.commit()
        conn.close()

        db = AlphaDatabase(db_path)
        db.catalog_tasks([legacy_task])
        row = db._get_connection().execute(
            "SELECT expression_origin FROM alpha_expressions WHERE expression = ?", (legacy_task.expression,)
        ).fetchone()
        assert row["expression_origin"] == "first_order"
        db.close()


def test_database_creates_missing_parent_directory():
    """Survey can create its research database before the runs directory exists."""
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "new-runs" / "research.db"
        db = AlphaDatabase(db_path)
        assert db_path.exists()
        db.close()


def test_simulation_batch_database_lifecycle():
    """Every platform simulation batch and expression result is auditable."""
    with tempfile.TemporaryDirectory() as tmp:
        db = AlphaDatabase(Path(tmp) / "simulation.db")
        try:
            batch_id = db.create_simulation_batch(
                [{"expression": "rank(close)", "decay": 6.0}, {"expression": "rank(volume)", "decay": 6.0}],
                {"region": "GBR", "universe": "TOP700", "delay": 1},
            )
            assert AlphaDatabase.compute_alpha_sha("rank(close)", {"region": "GBR", "delay": 1}) != \
                   AlphaDatabase.compute_alpha_sha("rank(close)", {"region": "USA", "delay": 1})
            db.attach_platform_batch(batch_id, "batch-123", "https://api.worldquantbrain.com/simulations/batch-123")
            db.record_simulation_result(batch_id, 0, status="completed", alpha_id="alpha-1", result={"id": "alpha-1"})
            db.record_simulation_result(batch_id, 1, status="failed", error_message="invalid expression")
            batch = db.get_simulation_batch(batch_id)
            assert batch["platform_batch_id"] == "batch-123"
            assert batch["completed_count"] == 1 and batch["failed_count"] == 1
            assert batch["status"] == "completed"
            assert len(db.get_simulation_results(batch_id)) == 2
            assert all(row["alpha_sha"] for row in db.get_simulation_results(batch_id))
        finally:
            db.close()


def test_simulation_tracker_submits_once_and_polls_children():
    """A saved platform batch is polled and never posted twice."""
    submitted = []
    children = ["https://api.worldquantbrain.com/simulations/child-a", "https://api.worldquantbrain.com/simulations/child-b"]

    def submit(payload):
        submitted.append(payload)
        return "https://api.worldquantbrain.com/simulations/batch-123"

    def fetch(location):
        if location.endswith("batch-123"):
            return {"children": children}, 0
        return ({"alpha": "alpha-a"} if location.endswith("child-a") else {"alpha": "alpha-b"}), 0

    def detail(alpha_id):
        return {"id": alpha_id, "regular": {"code": "rank(close)"}}

    with tempfile.TemporaryDirectory() as tmp:
        db = AlphaDatabase(Path(tmp) / "tracker.db")
        try:
            tracker = SimulationTracker(db, submit=submit, fetch=fetch, detail=detail)
            batch_id = tracker.submit([
                {"expression": "rank(close)", "decay": 6.0},
                {"expression": "rank(volume)", "decay": 6.0},
            ], {"region": "GBR", "universe": "TOP700", "delay": 1})
            assert len(submitted) == 1
            tracker.poll(batch_id)
            assert db.get_simulation_batch(batch_id)["status"] == "completed"
            assert [row["alpha_id"] for row in db.get_simulation_results(batch_id)] == ["alpha-a", "alpha-b"]
            tracker.poll(batch_id)
            assert len(submitted) == 1
        finally:
            db.close()


def test_platform_loader_uses_active_python_environment_only():
    """The platform shim must derive its vendor path from sys.path, not a machine path."""
    source_path = ROOT / "cnhkmcp" / "untracked" / "platform_functions.py"
    module = ast.parse(source_path.read_text(encoding="utf-8"))
    loader = next(node for node in module.body if isinstance(node, ast.FunctionDef) and node.name == "_load_real_module")
    loader_source = ast.get_source_segment(source_path.read_text(encoding="utf-8"), loader)
    assert "sys.path" in loader_source
    assert "candidate_paths" in loader_source
    assert "workspace_root" not in loader_source


def test_database_package_has_models_repository_and_schema_files():
    """Database implementation is split into a dedicated import-compatible package."""
    database_dir = ROOT / "alpha_operator_framework" / "database"
    assert (database_dir / "__init__.py").is_file()
    assert (database_dir / "models.py").is_file()
    assert (database_dir / "repository.py").is_file()
    assert (database_dir / "migrations.py").is_file()
    assert (database_dir / "schema" / "001_initial.sql").is_file()
    assert (database_dir / "schema" / "002_expression_origin.sql").is_file()


def test_session_manager_imports_on_current_platform():
    """The shared BRAIN session manager must support the current OS."""
    print("Testing cross-platform session manager import...")
    module = importlib.import_module("cnhkmcp.session_manager")
    assert hasattr(module, "BrainSessionManager")
    print("OK cross-platform session manager import")


def test_alpha_machine_write_json_serializes_platform_values():
    """Simulation output must persist platform objects that are not JSON primitives."""
    class PlatformValue:
        def __str__(self):
            return "platform-value"

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "results.json"
        write_json(path, {"result": PlatformValue()})
        assert json.loads(path.read_text(encoding="utf-8")) == {"result": "platform-value"}


def test_alpha_machine_poll_command_is_available():
    """The CLI exposes polling without requiring a second simulation submission."""
    import alpha_machine
    previous = sys.argv
    try:
        sys.argv = ["alpha_machine.py", "poll-simulation", "--batch-id", "7", "--output", "ignored.json"]
        parser = alpha_machine.argparse.ArgumentParser()
        # `main` owns parser construction; inspect source to keep this test network-free.
        assert "poll-simulation" in (ROOT / "alpha_machine.py").read_text(encoding="utf-8")
        assert "poll_simulation_batch" in (ROOT / "alpha_machine.py").read_text(encoding="utf-8")
    finally:
        sys.argv = previous


def test_fields():
    """测试字段处理."""
    print("测试字段处理...")

    # FieldSpec测试
    field = FieldSpec(
        id="close",
        dataset_id="pv1",
        type="MATRIX",
        coverage=0.95,
        user_count=300
    )
    assert field.id == "close"
    assert field.type == "MATRIX"

    # preprocess_field测试 (MATRIX)
    exprs = preprocess_field(field)
    assert len(exprs) == 1, f"MATRIX字段应生成1个表达式, 实际{len(exprs)}"
    assert "winsorize(ts_backfill(close, 120)" in exprs[0]

    # preprocess_field测试 (VECTOR)
    vec_field = FieldSpec(
        id="sentiment",
        dataset_id="nws82",
        type="VECTOR",
        coverage=0.80
    )
    exprs = preprocess_field(vec_field)
    assert len(exprs) == len(vec_ops), f"VECTOR字段应为每个VEC算子生成表达式, 实际{len(exprs)}"

    # sample_scalar_expressions测试
    fields = [field, vec_field]
    spec = SampleSpec(sample_n=10, seed=42)
    scalars = sample_scalar_expressions(fields, spec)
    assert len(scalars) == 1 + len(vec_ops), f"应生成MATRIX与全部VEC归约表达式, 实际{len(scalars)}"

    print("✓ 字段处理测试通过")


def test_economic_rules_filter_invalid_first_order_operators():
    """Economic metadata removes unstable transforms without limiting unknown fields."""
    positive_flow = FieldSpec(
        id="revenue", dataset_id="fund", type="MATRIX",
        economic_type="fundamental_flow", frequency="quarterly", signedness="nonnegative", scale="level",
    )
    allowed = allowed_first_order_ops(positive_flow)
    assert "inverse" not in allowed
    assert "ts_delta" in allowed

    returns = FieldSpec(
        id="returns", dataset_id="pv1", type="MATRIX",
        economic_type="return", frequency="daily", signedness="signed", scale="ratio",
    )
    assert "inverse" not in allowed_first_order_ops(returns)

    unknown = FieldSpec(id="custom", dataset_id="d", type="MATRIX")
    assert "inverse" in allowed_first_order_ops(unknown)


def test_local_field_files():
    """测试本地 CSV / JSON 字段文件读取和研究设置预筛选。"""
    print("测试本地字段文件...")

    fixture_dir = ROOT / "tests" / "fixtures"
    csv_fields = load_local_field_specs(
        fixture_dir / "local_fields.csv", region="GBR", universe="TOP700", delay=1
    )
    assert len(csv_fields) == 1
    assert csv_fields[0].id == "act_12m_cps_value"
    assert csv_fields[0].dataset_id == "analyst7"
    assert csv_fields[0].coverage == 0.1642

    json_fields = load_local_field_specs(
        fixture_dir / "local_fields.json", region="GBR", universe="TOP700", delay=1,
        dataset_id="acquisition_model", data_type="VECTOR",
    )
    assert len(json_fields) == 1
    assert json_fields[0].id == "country_percentile_acquisition_likelihood"
    assert json_fields[0].type == "VECTOR"
    assert load_local_field_specs(fixture_dir / "local_fields.json", region="EUR") == []

    single_json = fixture_dir / "single_field.json"
    single_json.write_text('{"id":"one","dataset":{"id":"d1"},"type":"MATRIX"}', encoding="utf-8")
    assert load_local_field_specs(single_json)[0].id == "one"
    single_json.unlink()

    local_dir = default_fields_directory(ROOT, "GBR", 1, "TOP700")
    assert local_dir == ROOT / "data" / "fields" / "GBR" / "1" / "TOP700"
    assert default_dataset_file(ROOT, "GBR", 1, "TOP700", "risk68", "json") == \
        local_dir / "risk68.json"
    assert len(load_local_field_directory(local_dir, file_type="json", region="GBR", universe="TOP700", delay=1)) > 0

    print("✓ 本地字段文件测试通过")


def test_semantic_pairs():
    """测试正负字段配对和同前缀 cap 归一化。"""
    print("测试语义二元配对...")
    fields = [
        FieldSpec(id="earnings_positive", dataset_id="d1", type="MATRIX"),
        FieldSpec(id="earnings_negative", dataset_id="d1", type="MATRIX"),
        FieldSpec(id="abc_revenue", dataset_id="d1", type="MATRIX"),
        FieldSpec(id="abc_cap", dataset_id="d1", type="MATRIX"),
        FieldSpec(id="other_positive", dataset_id="d2", type="MATRIX"),
        FieldSpec(id="other_negative", dataset_id="d3", type="MATRIX"),
    ]
    assert [(a.id, b.id) for a, b in find_positive_negative_pairs(fields)] == [
        ("earnings_positive", "earnings_negative")
    ]
    assert [(a.id, b.id) for a, b in find_cap_pairs(fields)] == [("abc_revenue", "abc_cap")]
    tasks = semantic_pair_task_factory(fields)
    assert len(tasks) == 2
    assert any(" - " in task.expression and task.meta["pair_type"] == "polarity" for task in tasks)
    assert any(" / " in task.expression and task.meta["pair_type"] == "cap_ratio" for task in tasks)
    print("✓ 语义二元配对测试通过")


def test_parameterized_paired_bases():
    """Test explicit binary base signals and their first-order expansion."""
    print("Testing parameterized paired base signals...")
    fields = [
        FieldSpec(id="raised", dataset_id="analyst7", type="MATRIX"),
        FieldSpec(id="lowered", dataset_id="analyst7", type="MATRIX"),
        FieldSpec(id="num", dataset_id="analyst7", type="MATRIX"),
    ]
    ratio = parse_pair_spec("ratio:raised:num")
    revision = parse_pair_spec("net_revision:raised:lowered:num")
    assert ratio.kind == "ratio" and ratio.denominator is None
    assert revision.kind == "net_revision" and revision.denominator == "num"

    base_tasks = paired_base_task_factory([ratio, revision], fields)
    assert len(base_tasks) == 2
    assert {task.expression_origin for task in base_tasks} == {"paired_base"}
    assert any("raised / (num + 0.000001)" in task.expression for task in base_tasks)
    assert any("(raised - lowered) / (num + 0.000001)" in task.expression for task in base_tasks)
    assert all(task.meta["pair_kind"] in {"ratio", "net_revision"} for task in base_tasks)
    assert all(task.meta["pair_stage"] == "base" for task in base_tasks)

    assert {task.meta["pair_source"] for task in base_tasks} == {"explicit"}
    assert paired_field_ids([ratio, revision]) == {"raised", "lowered", "num"}
    grouped_first_order = paired_group_first_order_task_factory(base_tasks, ["rank", "ts_rank"])
    assert any(task.expression.startswith("rank(") for task in grouped_first_order)
    assert any(task.expression.startswith("ts_rank(") for task in grouped_first_order)
    assert {task.expression_origin for task in grouped_first_order} == {"paired_first_order"}
    assert all(task.meta["pair_stage"] == "combined_first_order" for task in grouped_first_order)

    try:
        parse_pair_spec("ratio:raised")
    except ValueError:
        pass
    else:
        raise AssertionError("incomplete --pair must fail")
    print("OK parameterized paired base signals")


def test_automatic_paired_field_discovery():
    """Only exact, same-dataset field groups become automatic paired bases."""
    print("Testing automatic paired field discovery...")
    fields = [
        FieldSpec(id="est_12m_ebi_raisednum_4wks", dataset_id="analyst7", type="MATRIX"),
        FieldSpec(id="est_12m_ebi_lowerednum_4wks", dataset_id="analyst7", type="MATRIX"),
        FieldSpec(id="est_12m_ebi_num", dataset_id="analyst7", type="MATRIX"),
        FieldSpec(id="eps_high", dataset_id="analyst7", type="MATRIX"),
        FieldSpec(id="eps_low", dataset_id="analyst7", type="MATRIX"),
        FieldSpec(id="eps_mean", dataset_id="analyst7", type="MATRIX"),
        FieldSpec(id="bad_raisednum_4wks", dataset_id="d1", type="MATRIX"),
        FieldSpec(id="bad_lowerednum_4wks", dataset_id="d2", type="MATRIX"),
        FieldSpec(id="bad_num", dataset_id="d1", type="MATRIX"),
    ]
    specs = discover_pair_specs(fields)
    assert [(spec.kind, spec.left, spec.right, spec.denominator, spec.source) for spec in specs] == [
        ("net_revision", "est_12m_ebi_raisednum_4wks", "est_12m_ebi_lowerednum_4wks", "est_12m_ebi_num", "auto"),
        ("spread", "eps_high", "eps_low", "eps_mean", "auto"),
    ]
    base_tasks = paired_base_task_factory(specs, fields)
    assert {task.expression_origin for task in base_tasks} == {"paired_base"}
    assert {task.meta["pair_source"] for task in base_tasks} == {"auto"}
    print("OK automatic paired field discovery")


def test_density():
    """测试密度评估."""
    print("测试密度评估...")

    # SignalGate测试
    gate = SignalGate()
    row = {
        "sharpe": 1.5,
        "fitness": 1.2,
        "pnl": 5e6,
        "longCount": 60,
        "shortCount": 60
    }
    is_signal, snap = gate.is_signal(row)
    assert is_signal, "应判定为信号"
    assert snap["sharpe"] == 1.5

    # 非信号测试
    row_fail = {"sharpe": 0.5, "fitness": 0.3, "pnl": 1e5, "longCount": 30, "shortCount": 30}
    is_signal, _ = gate.is_signal(row_fail)
    assert not is_signal, "应判定为非信号"

    # compute_density测试
    results = [
        {
            "expression": "rank(close)",
            "family": "unary",
            "template_index": 0,
            "source_freq": "unknown",
            "fields_per_alpha": 1,
            **row
        },
        {
            "expression": "rank(volume)",
            "family": "unary",
            "template_index": 0,
            "source_freq": "unknown",
            "fields_per_alpha": 1,
            **row_fail
        }
    ]
    density_rows = compute_density(results, gate)
    assert len(density_rows) == 1, f"应聚合为1个密度行, 实际{len(density_rows)}"
    assert density_rows[0].density == 0.5, f"密度应为0.5, 实际{density_rows[0].density}"

    # top_templates测试
    top = top_templates(density_rows, top_n=1)
    assert len(top) == 1
    assert top[0].template_index == 0

    print("✓ 密度评估测试通过")


def test_pruning():
    """测试三阶段剪枝 (纯函数部分, 离线; correlation_prune 网络路径不在此测)."""
    print("测试剪枝模块...")

    # --- classify_field ---
    f_market = FieldSpec(id="close", dataset_id="pv1", type="MATRIX", coverage=0.9, user_count=5)
    f_analyst = FieldSpec(id="analyst4_fy1", dataset_id="analyst4", type="MATRIX", coverage=0.8)
    f_other = FieldSpec(id="xyz_abc", dataset_id="zzz123", type="MATRIX", coverage=0.5)
    assert classify_field(f_market) == "market", f"close/pv1应归market, 实际{classify_field(f_market)}"
    assert classify_field(f_analyst) == "analyst", f"analyst4_fy1应归analyst, 实际{classify_field(f_analyst)}"
    assert classify_field(f_other) == "other", f"未知字段应归other, 实际{classify_field(f_other)}"

    # --- semantic_prune_fields (冷门优先) ---
    fields = [
        # market: 3个 (user_count 5/1/3)
        f_market,                                          # user_count=5
        FieldSpec(id="volume", dataset_id="pv1", type="MATRIX", coverage=0.9, user_count=1),
        FieldSpec(id="returns", dataset_id="pv1", type="MATRIX", coverage=0.9, user_count=3),
        # analyst: 3个
        f_analyst,
        FieldSpec(id="analyst4_fy2", dataset_id="analyst4", type="MATRIX", coverage=0.8, user_count=2),
        FieldSpec(id="target_price", dataset_id="analyst4", type="MATRIX", coverage=0.8, user_count=4),
        # GROUP字段应被跳过
        FieldSpec(id="group_field", dataset_id="g1", type="GROUP", coverage=0.9, user_count=1),
    ]
    kept, pruned = semantic_prune_fields(
        fields, SemanticPruneConfig(keep_per_category=2))
    assert len(kept) == 4, f"2类×每类2个应留4个, 实际{len(kept)}"
    assert len(pruned) == 2, f"应剪掉2个, 实际{len(pruned)}"
    # 冷门优先: market类留 user_count 最低的 volume(1)和 returns(3), close(5)被剪
    kept_market = {f.id for f in kept if classify_field(f) == "market"}
    assert kept_market == {"volume", "returns"}, f"冷门优先失败, kept_market={kept_market}"
    assert all(p["category"] in ("market", "analyst") for p in pruned), "剪掉字段应带category"

    # --- extract_field_ids ---
    assert extract_field_ids("winsorize(ts_backfill(analyst4_fy1, 120), std=4)") == {"analyst4_fy1"}
    assert extract_field_ids("winsorize(ts_backfill(vec_avg(close), 120), std=4)") == {"close"}
    assert extract_field_ids("winsorize(rank(close, 5), std=4)") == {"__no_field__"}

    # --- field_topk_prune (每字段留最高sharpe) ---
    rows = [
        {"alpha_id": "a1", "expression": "winsorize(ts_backfill(close, 120), std=4)", "sharpe": 1.5},
        {"alpha_id": "a2", "expression": "winsorize(ts_backfill(close, 120), std=4)", "sharpe": 1.2},
        {"alpha_id": "a3", "expression": "winsorize(ts_backfill(volume, 120), std=4)", "sharpe": 1.4},
        {"alpha_id": "a4", "expression": "winsorize(ts_backfill(volume, 120), std=4)", "sharpe": 1.1},
    ]
    kept_rows, pruned_rows = field_topk_prune(rows, FieldTopKConfig(keep_per_field=1))
    assert {r["alpha_id"] for r in kept_rows} == {"a1", "a3"}, \
        f"每字段应留sharpe最高者, 实际{ {r['alpha_id'] for r in kept_rows} }"
    assert len(pruned_rows) == 2, f"应剪掉2个, 实际{len(pruned_rows)}"
    pruned_reasons = {r["prune_reason"] for r in pruned_rows}
    assert "same_field_topk:close" in pruned_reasons and "same_field_topk:volume" in pruned_reasons, \
        f"prune_reason缺失, 实际{pruned_reasons}"

    # --- field_topk_prune 正负方向分开 (split_by_sign=True) ---
    rows_sign = [
        {"alpha_id": "p1", "expression": "winsorize(ts_backfill(close, 120), std=4)", "sharpe": 1.6},   # +close
        {"alpha_id": "p2", "expression": "winsorize(ts_backfill(close, 120), std=4)", "sharpe": 1.2},   # +close (剪)
        {"alpha_id": "n1", "expression": "-winsorize(ts_backfill(close, 120), std=4)", "sharpe": -1.5}, # -close
        {"alpha_id": "n2", "expression": "-winsorize(ts_backfill(close, 120), std=4)", "sharpe": -1.1},# -close (剪)
    ]
    kept2, pruned2 = field_topk_prune(rows_sign, FieldTopKConfig(keep_per_field=1, split_by_sign=True))
    assert {r["alpha_id"] for r in kept2} == {"p1", "n1"}, \
        f"正负方向应分开计数, 保留p1/n1, 实际{ {r['alpha_id'] for r in kept2} }"
    assert {r["alpha_id"] for r in pruned2} == {"p2", "n2"}
    # 验证 prune_reason 带 "-close" 符号
    assert any("-close" in r.get("prune_reason", "") for r in pruned2), pruned2

    print("✓ 剪枝测试通过")


def run_all_tests():
    """运行所有测试."""
    print("\n" + "="*70)
    print("Alpha Operator Framework 单元测试")
    print("="*70 + "\n")

    try:
        test_operators()
        test_families()
        test_expression_origin_catalog()
        test_density_separates_same_index_by_expression_origin()
        test_expression_origin_migrates_legacy_database()
        test_database_creates_missing_parent_directory()
        test_simulation_batch_database_lifecycle()
        test_simulation_tracker_submits_once_and_polls_children()
        test_platform_loader_uses_active_python_environment_only()
        test_database_package_has_models_repository_and_schema_files()
        test_session_manager_imports_on_current_platform()
        test_alpha_machine_write_json_serializes_platform_values()
        test_alpha_machine_poll_command_is_available()
        test_fields()
        test_economic_rules_filter_invalid_first_order_operators()
        test_local_field_files()
        test_semantic_pairs()
        test_parameterized_paired_bases()
        test_automatic_paired_field_discovery()
        test_density()
        test_pruning()

        print("\n" + "="*70)
        print("✓ 所有测试通过!")
        print("="*70 + "\n")
        return 0

    except AssertionError as e:
        print(f"\n✗ 测试失败: {e}\n")
        return 1
    except Exception as e:
        print(f"\n✗ 测试异常: {e}\n")
        import traceback
        traceback.print_exc()
        return 2


if __name__ == "__main__":
    sys.exit(run_all_tests())
