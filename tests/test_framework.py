#!/usr/bin/env python
"""
单元测试 — Alpha Operator Framework

测试核心模块:
  - operators: 算子库和工厂函数
  - families: 模板族生成
  - fields: 字段预处理
  - density: 因子密度评估
"""

import argparse
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
    extract_first_operator,
    # 模板族
    UNARY_TEMPLATES, BINARY_TEMPLATES, TERNARY_TEMPLATES,
    unary_factory, binary_factory, ternary_factory, quaternary_factory,
    first_order_task_factory,
    raw_first_order_task_factory,
    Task,
    # 字段
    FieldSpec, ScalarField, SampleSpec,
    preprocess_field, sample_scalar_expressions, sample_scalar_field_pairs, load_local_field_specs,
    find_positive_negative_pairs, find_cap_pairs, semantic_pair_task_factory,
    # 模板类库
    Template, TemplateStrategyConfig,
    template_creation_strategy, build_family_template_rows, import_knowledge_base_templates,
    # 密度
    SignalGate, compute_density, top_templates,
    # 剪枝
    classify_field, extract_field_ids, extract_fields,
    semantic_prune_fields, SemanticPruneConfig,
    field_topk_prune, FieldTopKConfig,
    # 评价
    count_failed_gates,
)
from alpha_operator_framework.database import AlphaDatabase, AlphaDetail, WF_STAGES
from alpha_operator_framework.database.repository import submission_wf_stage
from alpha_operator_framework.domain.economic_rules import allowed_first_order_ops
from alpha_operator_framework.platform.local_fields import (
    default_fields_directory, default_dataset_file, load_local_field_directory,
)
from alpha_machine import write_json
from alpha_machine import main as alpha_machine_main
from alpha_operator_framework.orchestrator import build_parser
from alpha_operator_framework.platform.simulation_tracker import SimulationTracker
from alpha_operator_framework.generation.super_alpha import (
    SuperAlphaConfig,
    build_super_candidates,
    super_simulation_payload,
)
from alpha_operator_framework.domain.paired_bases import (
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


def test_submit_cli_accepts_database_path():
    """The production submit command must carry its durable database path."""
    parser = build_parser()
    args = parser.parse_args([
        "submit", "--kept-out", "runs/kept.json", "--database", "data/production.db",
    ])
    assert args.database == "data/production.db"


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


def test_expression_pipeline_columns_migrate_legacy_database():
    """Opening a legacy database adds backtest pipeline columns with correct defaults."""
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "legacy.db"
        conn = sqlite3.connect(db_path)
        conn.executescript("""
            CREATE TABLE alpha_expressions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                expression_sha TEXT NOT NULL UNIQUE,
                expression TEXT NOT NULL,
                expression_origin TEXT NOT NULL DEFAULT '',
                settings TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE alpha_details (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                alpha_id TEXT NOT NULL UNIQUE, expression_sha TEXT NOT NULL,
                alpha_sha TEXT NOT NULL DEFAULT '', expression TEXT NOT NULL,
                region TEXT, universe TEXT, delay INTEGER DEFAULT 1, decay REAL DEFAULT 0,
                neutralization TEXT, truncation REAL DEFAULT 0, sharpe REAL DEFAULT 0,
                fitness REAL DEFAULT 0, turnover REAL DEFAULT 0, margin REAL DEFAULT 0,
                pnl REAL DEFAULT 0, returns REAL DEFAULT 0, drawdown REAL DEFAULT 0,
                long_count INTEGER DEFAULT 0, short_count INTEGER DEFAULT 0,
                grade TEXT, stage_platform TEXT, status_platform TEXT,
                sc_result TEXT, sc_value REAL, pc_result TEXT, pc_value REAL, checks_json TEXT,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            INSERT INTO alpha_expressions (expression_sha, expression, settings, created_at, updated_at)
            VALUES ('legacy-sha', 'ts_delta(close, 252)', '{}', 't0', 't0');
        """)
        conn.commit()
        conn.close()

        db = AlphaDatabase(db_path)
        expr_cols = {r["name"] for r in db._get_connection().execute(
            "PRAGMA table_info(alpha_expressions)")}
        detail_cols = {r["name"] for r in db._get_connection().execute(
            "PRAGMA table_info(alpha_details)")}
        assert {"batch_id", "fields", "status", "first_operator"} <= expr_cols
        assert {"ra_failed", "ppa_failed"} <= detail_cols
        row = db._get_connection().execute(
            "SELECT status, fields, first_operator, batch_id FROM alpha_expressions WHERE expression_sha='legacy-sha'"
        ).fetchone()
        assert row["status"] == "pending"
        assert row["fields"] == "[]"
        assert row["first_operator"] == ""
        assert row["batch_id"] is None
        db.close()


def test_wf_stage_defaults_to_pending_validation():
    """New alpha_details rows default to wf_stage='pending_validation'."""
    with tempfile.TemporaryDirectory() as tmp:
        db = AlphaDatabase(Path(tmp) / "research.db")
        db.save_result_with_checks("a1", {"sharpe": 1.5, "checks": []}, {"region": "GBR"})
        rows = db.query_alphas(wf_stage="pending_validation", limit=5)
        assert [d.alpha_id for d in rows] == ["a1"]
        assert rows[0].wf_stage == "pending_validation"
        db.close()


def test_wf_stage_upsert_preserves_existing_stage():
    """Re-saving a result must not overwrite an already-advanced wf_stage."""
    with tempfile.TemporaryDirectory() as tmp:
        db = AlphaDatabase(Path(tmp) / "research.db")
        db.save_result_with_checks("a1", {"sharpe": 1.5, "checks": []}, {"region": "GBR"})
        db.update_wf_stage("a1", "validated")
        db.save_result_with_checks("a1", {"sharpe": 1.8, "checks": []}, {"region": "GBR"})
        row = db.query_alphas(limit=5)[0]
        assert row.wf_stage == "validated"
        assert row.sharpe == 1.8  # upsert 更新了指标, 但没打回阶段
        db.close()


def test_update_wf_stage_validates_values():
    """update_wf_stage rejects unknown stages with ValueError."""
    with tempfile.TemporaryDirectory() as tmp:
        db = AlphaDatabase(Path(tmp) / "research.db")
        db.save_result_with_checks("a1", {"sharpe": 1.5, "checks": []}, {"region": "GBR"})
        db.update_wf_stage("a1", "validated")  # 合法
        try:
            db.update_wf_stage("a1", "bogus")
            assert False, "expected ValueError"
        except ValueError:
            pass
        db.close()


def test_mark_alpha_submitted_and_failed():
    """mark_alpha_submitted / mark_alpha_failed set the expected wf_stage."""
    with tempfile.TemporaryDirectory() as tmp:
        db = AlphaDatabase(Path(tmp) / "research.db")
        db.save_result_with_checks("a1", {"sharpe": 1.5, "checks": []}, {"region": "GBR"})
        db.save_result_with_checks("a2", {"sharpe": 1.6, "checks": []}, {"region": "GBR"})
        db.mark_alpha_submitted("a1")
        db.mark_alpha_failed("a2")
        by_id = {d.alpha_id: d.wf_stage for d in db.query_alphas(limit=5)}
        assert by_id["a1"] == "submitted"
        assert by_id["a2"] == "failed"
        db.close()


def test_submission_wf_stage_mapping():
    """SC/PC both PASS/WARNING (or missing) → validated, otherwise needs_optimization."""
    assert submission_wf_stage("PASS", "PASS") == "validated"
    assert submission_wf_stage("WARNING", "PASS") == "validated"
    assert submission_wf_stage(None, None) == "validated"
    assert submission_wf_stage("FAIL", "PASS") == "needs_optimization"
    assert submission_wf_stage("PASS", "ERROR") == "needs_optimization"


def test_cmd_submit_sc_pc_scenario():
    """SC/PC judgement (as in cmd_submit) drives validated vs needs_optimization."""
    with tempfile.TemporaryDirectory() as tmp:
        db = AlphaDatabase(Path(tmp) / "research.db")
        # 通过: SC=PASS PC=PASS
        db.save_result_with_checks(
            "a_ok", {"sharpe": 1.6, "checks": [
                {"name": "SELF_CORRELATION", "result": "PASS", "value": 0.4},
                {"name": "PROD_CORRELATION", "result": "PASS", "value": 0.5},
            ]}, {"region": "GBR"})
        db.update_wf_stage("a_ok", submission_wf_stage("PASS", "PASS"))
        # 不通过: SC=FAIL
        db.save_result_with_checks(
            "a_bad", {"sharpe": 1.6, "checks": [
                {"name": "SELF_CORRELATION", "result": "FAIL", "value": 0.8},
                {"name": "PROD_CORRELATION", "result": "PASS", "value": 0.5},
            ]}, {"region": "GBR"})
        db.update_wf_stage("a_bad", submission_wf_stage("FAIL", "PASS"))
        by_id = {d.alpha_id: d.wf_stage for d in db.query_alphas(limit=5)}
        assert by_id["a_ok"] == "validated"
        assert by_id["a_bad"] == "needs_optimization"
        db.close()


def test_query_alphas_filters_by_wf_stage():
    """query_alphas(wf_stage=...) filters by the system-internal stage column."""
    with tempfile.TemporaryDirectory() as tmp:
        db = AlphaDatabase(Path(tmp) / "research.db")
        db.save_result_with_checks("a1", {"sharpe": 1.5, "checks": []}, {"region": "GBR"})
        db.save_result_with_checks("a2", {"sharpe": 1.6, "checks": []}, {"region": "GBR"})
        db.update_wf_stage("a2", "validated")
        validated = db.query_alphas(wf_stage="validated", limit=5)
        pending = db.query_alphas(wf_stage="pending_validation", limit=5)
        assert [d.alpha_id for d in validated] == ["a2"]
        assert [d.alpha_id for d in pending] == ["a1"]
        db.close()


def test_wf_stage_column_migrates_legacy_database():
    """Opening a legacy alpha_details (no wf_stage) adds the column with correct default."""
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "legacy.db"
        conn = sqlite3.connect(db_path)
        conn.executescript("""
            CREATE TABLE alpha_details (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                alpha_id TEXT NOT NULL UNIQUE, expression_sha TEXT NOT NULL,
                alpha_sha TEXT NOT NULL DEFAULT '', expression TEXT NOT NULL,
                region TEXT, universe TEXT, delay INTEGER DEFAULT 1, decay REAL DEFAULT 0,
                neutralization TEXT, truncation REAL DEFAULT 0, sharpe REAL DEFAULT 0,
                fitness REAL DEFAULT 0, turnover REAL DEFAULT 0, margin REAL DEFAULT 0,
                pnl REAL DEFAULT 0, returns REAL DEFAULT 0, drawdown REAL DEFAULT 0,
                long_count INTEGER DEFAULT 0, short_count INTEGER DEFAULT 0,
                grade TEXT, stage_platform TEXT, status_platform TEXT,
                sc_result TEXT, sc_value REAL, pc_result TEXT, pc_value REAL, checks_json TEXT,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            INSERT INTO alpha_details (alpha_id, expression_sha, expression, created_at, updated_at)
            VALUES ('legacy', 's1', 'rank(close)', 't0', 't0');
        """)
        conn.commit()
        conn.close()

        db = AlphaDatabase(db_path)
        cols = {r["name"] for r in db._get_connection().execute(
            "PRAGMA table_info(alpha_details)")}
        assert "wf_stage" in cols
        row = db._get_connection().execute(
            "SELECT wf_stage FROM alpha_details WHERE alpha_id='legacy'").fetchone()
        assert row["wf_stage"] == "pending_validation"
        db.close()


def test_raw_first_order_task_factory():
    """raw_first_order_task_factory applies operators to raw field ids with first_order_raw origin."""
    tasks = raw_first_order_task_factory(["close"])
    expressions = {t.expression for t in tasks}
    assert "rank(close)" in expressions
    assert "ts_rank(close, 22)" in expressions
    assert all(t.expression_origin == "first_order_raw" for t in tasks)
    assert all(t.fields_per_alpha == 1 for t in tasks)


def test_raw_first_order_separates_from_preprocessed_in_density():
    """density distinguishes first_order_raw from preprocessed first_order."""
    rows = compute_density([
        {"family": "unary", "template_index": 3, "expression_origin": "first_order"},
        {"family": "unary", "template_index": 3, "expression_origin": "first_order_raw"},
    ])
    origins = {row.expression_origin for row in rows}
    assert "first_order" in origins
    assert "first_order_raw" in origins


def test_template_library_seed_and_query():
    """template_library seeds 4-family templates idempotently and supports filtering."""
    with tempfile.TemporaryDirectory() as tmp:
        db = AlphaDatabase(Path(tmp) / "research.db")
        tpls = db.list_templates()
        assert len(tpls) == 30
        assert len(db.list_templates(families=("unary",))) == 10
        assert len(db.list_templates(families=("binary",))) == 8
        assert len(db.list_templates(families=("ternary",))) == 7
        assert len(db.list_templates(families=("quaternary",))) == 5
        names = [t.name for t in tpls]
        assert len(set(names)) == len(names)  # name 唯一
        assert all(t.active == 1 for t in tpls)
        db.seed_template_library()  # 幂等
        assert len(db.list_templates()) == 30
        db.close()


def test_template_creation_strategy_matches_factories():
    """Strategy output must be byte-identical to the four family factories (default config)."""
    rows = build_family_template_rows()
    fields = [
        ScalarField(expr=f"winsorize(ts_backfill({f},120),std=4)", category="pv", field_id=f)
        for f in ("close", "volume", "open")
    ]
    cfg = TemplateStrategyConfig()
    for family, factory in (("unary", unary_factory), ("binary", binary_factory),
                            ("ternary", ternary_factory)):
        s = template_creation_strategy([r for r in rows if r.family == family], fields, [], cfg)
        f = factory([x.expr for x in fields])
        s_set = {(t.expression, t.template_index, t.expression_origin,
                  t.base_fields, t.fields_per_alpha) for t in s}
        f_set = {(t.expression, t.template_index, t.expression_origin,
                  t.base_fields, t.fields_per_alpha) for t in f}
        assert s_set == f_set, family
    s = template_creation_strategy([r for r in rows if r.family == "quaternary"],
                                   fields, ["sector", "industry"], cfg)
    f = quaternary_factory([x.expr for x in fields], ["sector", "industry"])
    s_set = {(t.expression, t.template_index, t.expression_origin,
              t.base_fields, t.meta.get("group")) for t in s}
    f_set = {(t.expression, t.template_index, t.expression_origin,
              t.base_fields, t.meta.get("group")) for t in f}
    assert s_set == f_set, "quaternary"


def test_template_creation_strategy_filters_by_category():
    """Strategy filters scalar fields by template categories (empty=ALL)."""
    from dataclasses import replace
    rows = build_family_template_rows()
    pv_tpl = replace(rows[0], categories=["pv"])
    fields = [
        ScalarField(expr="winsorize(ts_backfill(close,120),std=4)", category="pv", field_id="close"),
        ScalarField(expr="winsorize(ts_backfill(eps,120),std=4)", category="fundamental", field_id="eps"),
    ]
    s = template_creation_strategy([pv_tpl], fields, [], TemplateStrategyConfig())
    assert len(s) == 1 and "close" in s[0].expression and "eps" not in s[0].expression
    s_all = template_creation_strategy(rows[:1], fields, [], TemplateStrategyConfig())
    assert len(s_all) == 2  # categories 空=ALL


def test_template_creation_strategy_fixed_and_group_slots():
    """Fixed templates emit once; group slots expand over provided group fields."""
    from dataclasses import replace
    rows = build_family_template_rows()
    fixed = replace(rows[0], template_type="fixed",
                    expression_template="rank(close) - rank(volume)")
    tasks = template_creation_strategy([fixed], [], [], TemplateStrategyConfig())
    assert len(tasks) == 1
    assert tasks[0].expression == "rank(close) - rank(volume)"
    # quaternary: group 槽展开
    fields = [ScalarField(expr=f"winsorize(ts_backfill({f},120),std=4)", category="pv", field_id=f)
              for f in ("close", "volume", "open")]
    qua = [r for r in rows if r.family == "quaternary"]
    tasks = template_creation_strategy(qua, fields, ["sector", "industry"], TemplateStrategyConfig())
    assert any("sector" in t.expression for t in tasks)
    assert any("industry" in t.expression for t in tasks)


def test_template_library_knowledge_base_import():
    """import_knowledge_base_templates parses knowledge-base JSONL into Template rows."""
    kb = Path("/Users/liujiaping/ai/quant/knowledge_base/alpha_templates")
    if not (kb / "placeholder_alpha_templates.jsonl").is_file():
        return  # 知识库目录不存在时跳过
    ph = import_knowledge_base_templates(kb / "placeholder_alpha_templates.jsonl", source_type="placeholder")
    assert len(ph) == 11
    assert ph[0].name.startswith("kb_placeholder_")
    assert ph[0].template_type == "placeholder"
    assert ph[0].expression_template  # 非空
    f101 = import_knowledge_base_templates(kb / "101_formulaic_alphas.jsonl", source_type="formulaic")
    assert len(f101) == 101
    assert all(t.template_type == "fixed" for t in f101)


def test_template_library_seed_knowledge_base():
    """seed_template_library(include_knowledge_base=True) writes >30 rows idempotently."""
    kb = Path("/Users/liujiaping/ai/quant/knowledge_base/alpha_templates")
    if not (kb / "placeholder_alpha_templates.jsonl").is_file():
        return
    with tempfile.TemporaryDirectory() as tmp:
        db = AlphaDatabase(Path(tmp) / "research.db")
        db.seed_template_library(include_knowledge_base=True, knowledge_base_dir=kb)
        total = len(db.list_templates())
        assert total > 30
        db.seed_template_library(include_knowledge_base=True, knowledge_base_dir=kb)
        assert len(db.list_templates()) == total  # 幂等
        db.close()


def test_category_pipeline():
    """Platform category is carried through FieldSpec, local_fields, and datafields."""
    with tempfile.TemporaryDirectory() as tmp:
        db = AlphaDatabase(Path(tmp) / "research.db")
        # upsert_datafield 带嵌套 category dict
        db.upsert_datafield({"id": "close", "region": "GBR", "delay": 1, "universe": "TOP700",
                             "dataset": {"id": "pv1", "name": "PV"}, "type": "MATRIX",
                             "category": {"id": "pv", "name": "PV"}})
        f = db.get_datafields(region="GBR")[0]
        assert f.category == "pv"
        # alpha_machine.field_from_dict 嵌套 dict
        from alpha_machine import field_from_dict
        spec = field_from_dict({"id": "close", "category": {"id": "model", "name": "Model"}})
        assert spec.category == "model"
        db.close()


def test_survey_template_library_hook():
    """run_survey_with_fields dry-run with use_template_library produces tasks."""
    import asyncio
    from alpha_operator_framework.ai_workflow import SurveyConfig, run_survey_with_fields
    field_specs = [
        FieldSpec(id="close", dataset_id="pv1", type="MATRIX", coverage=0.9, user_count=3, category="pv"),
        FieldSpec(id="volume", dataset_id="pv1", type="MATRIX", coverage=0.8, user_count=5, category="pv"),
    ]
    config = SurveyConfig(region="GBR", universe="TOP700", delay=1, field_ids=["close", "volume"],
                          include_semantic_pairs=False, include_binary=True)
    with tempfile.TemporaryDirectory() as tmp:
        result = asyncio.run(run_survey_with_fields(
            field_specs, config, Path(tmp), execute=False))
        assert result.success


def test_extract_first_operator():
    """The first operator is the leftmost function-call name for every expression family."""
    cases = {
        "group_neutralize(ts_rank(rank(close)/rank(volume), 10), industry)": "group_neutralize",
        "ts_delta(close, 252)/ts_delay(close, 252)": "ts_delta",
        "reverse(ts_rank(ts_zscore(close, 500), 500))": "reverse",
        "rank(winsorize(ts_backfill(close, 120), std=4))": "rank",
        "vector_neut(vec_avg(close), vec_avg(open))": "vector_neut",
        "if_else(vec_avg(close) > vec_avg(open), vec_avg(close), vec_avg(open))": "if_else",
        "ts_corr(close, volume, 22) * ts_delay(close, 1)": "ts_corr",
        "": "__none__",
    }
    for expression, expected in cases.items():
        assert extract_first_operator(expression) == expected, expression


def test_stratified_sampling_by_first_operator():
    """sample_catalog_expressions covers multiple first operators (proportional by default)."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db = AlphaDatabase(Path(tmp) / "research.db")
        try:
            expressions = (
                [f"rank(winsorize(ts_backfill(close_{i}, 120), std=4))" for i in range(6)]
                + [f"ts_rank(close_{i}, 22)" for i in range(6)]
                + [f"ts_delta(close_{i}, 252)/ts_delay(close_{i}, 252)" for i in range(4)]
            )
            sampled = db.sample_catalog_expressions(expressions, limit=8, seed=1, dedup_isomorphic=False)
            assert len(sampled) == 8
            covered = {extract_first_operator(e) for e in sampled}
            assert covered >= {"rank", "ts_rank", "ts_delta"}
        finally:
            db.close()
            import gc
            gc.collect()


def test_save_result_with_checks_writes_ra_ppa():
    """save_result_with_checks persists RA/PPA failure counts matching count_failed_gates."""
    with tempfile.TemporaryDirectory() as tmp:
        db = AlphaDatabase(Path(tmp) / "research.db")
        checks = [
            {"name": "LOW_SHARPE", "result": "FAIL", "value": 0.5},
            {"name": "LOW_TURNOVER", "result": "FAIL", "value": 0.01},
            {"name": "HIGH_TURNOVER", "result": "PASS", "value": 0.1},
            {"name": "PROD_CORRELATION", "result": "FAIL", "value": 0.8},
            {"name": "LOW_FITNESS", "result": "WARNING", "value": 1.1},
        ]
        is_block = {"sharpe": 1.2, "fitness": 1.1, "checks": checks,
                    "selfCorrelation": 0.5, "prodCorrelation": 0.8}
        db.save_result_with_checks("alpha_x", is_block, {"region": "GBR", "universe": "TOP700", "delay": 1})
        detail = db.query_alphas(limit=1)[0]
        gate = count_failed_gates(checks)
        assert detail.ra_failed == gate.failed_ra
        assert detail.ppa_failed == gate.failed_ppa
        assert detail.ra_failed >= 1 and detail.ppa_failed >= 1
        db.close()


def test_datafields_upsert_aggregates_universes():
    """Same field upserted under different universes aggregates into one row."""
    with tempfile.TemporaryDirectory() as tmp:
        db = AlphaDatabase(Path(tmp) / "research.db")
        db.upsert_datafield(
            {"id": "close", "dataset": {"id": "pv1", "name": "PV"}, "region": "GBR",
             "delay": 1, "universe": "TOP700", "type": "MATRIX",
             "coverage": 0.9, "userCount": 3, "alphaCount": 10, "description": "close"},
            expression_shas=["s1"],
        )
        db.upsert_datafield(
            {"id": "close", "dataset": {"id": "pv1", "name": "PV"}, "region": "GBR",
             "delay": 1, "universe": "TOP3000", "type": "MATRIX",
             "coverage": 0.95, "userCount": 5, "alphaCount": 12, "description": "close"},
            expression_shas=["s2"],
        )
        fields = db.get_datafields(region="GBR")
        assert len(fields) == 1
        f = fields[0]
        assert f.universes == ["TOP3000", "TOP700"]
        assert set(f.expression_shas) == {"s1", "s2"}
        assert f.coverage == 0.95  # last write wins
        db.close()


def test_missing_datafield_candidates():
    """Fields used by alphas but absent from datafields are ingestion candidates."""
    with tempfile.TemporaryDirectory() as tmp:
        db = AlphaDatabase(Path(tmp) / "research.db")

        class FakeTask:
            expression = "rank(winsorize(ts_backfill(close, 120), std=4))"
            family = "first_order"
            template_index = 0
            fields_per_alpha = 1
            base_fields = ("close",)
            meta = {}
            expression_origin = "first_order"

        db.catalog_tasks([FakeTask()], stage="first_order")
        assert "close" in db.missing_datafield_candidates(region="GBR", delay=1)
        db.upsert_datafield({"id": "close", "region": "GBR", "delay": 1, "universe": "TOP700",
                             "dataset": {"id": "pv1", "name": "PV"}, "type": "MATRIX"})
        assert "close" not in db.missing_datafield_candidates(region="GBR", delay=1)
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


def test_super_alpha_candidates_are_gated_bounded_and_canonical():
    """Super Alpha candidates use quality-gated components and deterministic hashes."""
    components = [
        {"alpha_id": "good-a", "expression": "rank(close)", "sharpe": 2.0, "fitness": 1.1,
         "turnover": 0.20, "sc_value": 0.2, "pc_value": 0.3},
        {"alpha_id": "good-b", "expression": "rank(volume)", "sharpe": 1.8, "fitness": 1.0,
         "turnover": 0.24, "sc_value": 0.3, "pc_value": 0.4},
        {"alpha_id": "weak", "expression": "rank(low)", "sharpe": 0.2, "fitness": 0.1,
         "turnover": 0.20, "sc_value": 0.2, "pc_value": 0.3},
    ]
    config = SuperAlphaConfig(min_sharpe=1.0, min_fitness=0.8, max_candidates=4)
    settings = {"region": "GBR", "universe": "TOP700", "delay": 1, "decay": 6}

    candidates = build_super_candidates(components, config, settings)

    assert len(candidates) == 4
    assert all(candidate["component_ids"] == ["good-a", "good-b"] for candidate in candidates)
    assert len({candidate["candidate_sha"] for candidate in candidates}) == 4
    assert {candidate["selection_name"] for candidate in candidates} >= {"baseline", "quality_turnover"}
    payload = super_simulation_payload(candidates[0], {**settings, "simulation_type": "SUPER"})
    assert payload["type"] == "SUPER"
    assert payload["selection"] == candidates[0]["selection"]
    assert payload["combo"] == candidates[0]["combo"]
    assert payload["settings"]["region"] == "GBR"
    assert "simulation_type" not in payload["settings"]


def test_super_alpha_candidate_and_batch_are_durable():
    """SUPER work stores its complete payload and remains resumable after restart."""
    with tempfile.TemporaryDirectory() as tmp:
        db = AlphaDatabase(Path(tmp) / "super.db")
        try:
            candidate = {"candidate_sha": "candidate-1", "component_ids": ["a", "b"],
                         "selection_name": "baseline", "selection": "1",
                         "combo_name": "equal_weight", "combo": "1"}
            db.save_super_candidates([candidate], {"region": "GBR", "universe": "TOP700", "delay": 1})
            assert db.get_super_candidates() == [candidate]
            batch_id = db.create_simulation_batch([candidate], {"region": "GBR"}, simulation_type="SUPER")
            batch = db.get_simulation_batch(batch_id)
            task = db.get_simulation_results(batch_id)[0]
            assert batch["simulation_type"] == "SUPER"
            assert json.loads(task["task_json"])["selection"] == "1"
        finally:
            db.close()


def test_super_alpha_preparation_reads_regular_details():
    """The command adapter builds stored SUPER hypotheses from the regular-alpha ledger."""
    import alpha_machine
    with tempfile.TemporaryDirectory() as tmp:
        db = AlphaDatabase(Path(tmp) / "super-prepare.db")
        try:
            db._get_connection().executemany(
                """INSERT INTO alpha_details (alpha_id, expression_sha, alpha_sha, expression, sharpe, fitness, turnover,
                sc_value, pc_value, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [("a", "a", "a", "rank(close)", 2, 1, .2, .2, .2, "now", "now"),
                 ("b", "b", "b", "rank(volume)", 2, 1, .2, .2, .2, "now", "now")],
            )
            db._get_connection().commit()
            candidates = alpha_machine.prepare_super_candidates(db, {"region": "GBR", "universe": "TOP700", "delay": 1})
            assert len(candidates) == 6
            assert db.get_super_candidates()[0]["component_ids"] == ["a", "b"]
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
    assert (database_dir / "schema" / "003_simulation_batches.sql").is_file()
    assert (database_dir / "schema" / "004_super_alpha.sql").is_file()
    assert (database_dir / "schema" / "005_datafields_and_expression_pipeline.sql").is_file()
    assert (database_dir / "schema" / "006_alpha_wf_stage.sql").is_file()
    assert (database_dir / "schema" / "007_template_library.sql").is_file()
    assert (database_dir / "schema" / "latest_schema.sql").is_file()


def test_latest_schema_initializes_current_database():
    """The current schema snapshot must initialize a fresh SQLite database by itself."""
    schema_path = ROOT / "alpha_operator_framework" / "database" / "schema" / "latest_schema.sql"

    with tempfile.TemporaryDirectory() as temp_dir:
        connection = sqlite3.connect(Path(temp_dir) / "fresh.db")
        try:
            connection.executescript(schema_path.read_text(encoding="utf-8"))
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            assert {
                "alpha_expressions",
                "alpha_details",
                "alpha_checks",
                "datafields",
                "template_library",
                "simulation_batches",
                "simulation_results",
                "super_alpha_candidates",
                "alpha_optimization_queue",
                "alpha_submission_candidates",
                "field_signal_stats",
            } <= tables

            expression_columns = {
                row[1] for row in connection.execute("PRAGMA table_info(alpha_expressions)")
            }
            detail_columns = {row[1] for row in connection.execute("PRAGMA table_info(alpha_details)")}
            result_columns = {row[1] for row in connection.execute("PRAGMA table_info(simulation_results)")}
            assert {"expression_origin"} <= expression_columns
            assert {"batch_id", "fields", "status", "first_operator"} <= expression_columns
            assert {"alpha_sha"} <= detail_columns
            assert {"ra_failed", "ppa_failed"} <= detail_columns
            assert {"wf_stage"} <= detail_columns
            assert {"alpha_sha", "platform_child_url"} <= result_columns
            assert {"simulation_type"} <= {
                row[1] for row in connection.execute("PRAGMA table_info(simulation_batches)")
            }
            datafield_columns = {row[1] for row in connection.execute("PRAGMA table_info(datafields)")}
            assert {"field_id", "dataset_id", "description", "type", "region", "delay",
                    "universes_json", "category"} <= datafield_columns
            template_columns = {row[1] for row in connection.execute("PRAGMA table_info(template_library)")}
            assert {"name", "family", "template_type", "expression_template", "categories_json",
                    "field_types_json"} <= template_columns
        finally:
            connection.close()


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


def test_alpha_machine_uses_durable_data_database_by_default():
    """Run artifacts and the long-lived simulation database have separate locations."""
    import alpha_machine

    assert alpha_machine.DEFAULT_DATABASE_PATH == Path("data") / "alpha_research.db"
    assert alpha_machine.database_path(argparse.Namespace(database="custom/state.db")) == Path("custom/state.db")


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


def test_alpha_machine_prepare_super_command_is_available():
    """The CLI exposes a non-network Super Alpha preparation command."""
    source = (ROOT / "alpha_machine.py").read_text(encoding="utf-8")
    assert 'add_parser("prepare-super"' in source
    assert "prepare_super_candidates" in source
    assert 'add_parser("simulate-super"' in source
    assert 'add_parser("poll-super"' in source


def test_package_exports_alpha_source_helpers():
    """Every public Alpha-source helper named in __all__ is available at package level."""
    import alpha_operator_framework as framework

    expected = {
        "get_alphas_from_workflow_result",
        "load_alphas_from_file",
        "fetch_user_alphas",
        "fetch_alpha_by_ids",
        "get_and_filter_alphas",
    }
    assert expected <= set(dir(framework))


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
        test_expression_pipeline_columns_migrate_legacy_database()
        test_wf_stage_defaults_to_pending_validation()
        test_wf_stage_upsert_preserves_existing_stage()
        test_update_wf_stage_validates_values()
        test_mark_alpha_submitted_and_failed()
        test_submission_wf_stage_mapping()
        test_cmd_submit_sc_pc_scenario()
        test_query_alphas_filters_by_wf_stage()
        test_wf_stage_column_migrates_legacy_database()
        test_raw_first_order_task_factory()
        test_raw_first_order_separates_from_preprocessed_in_density()
        test_template_library_seed_and_query()
        test_template_creation_strategy_matches_factories()
        test_template_creation_strategy_filters_by_category()
        test_template_creation_strategy_fixed_and_group_slots()
        test_template_library_knowledge_base_import()
        test_template_library_seed_knowledge_base()
        test_category_pipeline()
        test_survey_template_library_hook()
        test_extract_first_operator()
        test_stratified_sampling_by_first_operator()
        test_save_result_with_checks_writes_ra_ppa()
        test_datafields_upsert_aggregates_universes()
        test_missing_datafield_candidates()
        test_database_creates_missing_parent_directory()
        test_simulation_batch_database_lifecycle()
        test_simulation_tracker_submits_once_and_polls_children()
        test_platform_loader_uses_active_python_environment_only()
        test_database_package_has_models_repository_and_schema_files()
        test_latest_schema_initializes_current_database()
        test_session_manager_imports_on_current_platform()
        test_alpha_machine_write_json_serializes_platform_values()
        test_alpha_machine_uses_durable_data_database_by_default()
        test_alpha_machine_poll_command_is_available()
        test_alpha_machine_prepare_super_command_is_available()
        test_package_exports_alpha_source_helpers()
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
