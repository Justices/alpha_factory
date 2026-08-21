"""蒸馏层 (distill) 单元测试 — 研究闭环 P0/P1 纯函数验证."""

import sys
import tempfile
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from alpha_operator_framework.distill import (
    FieldSignalStat,
    aggregate_field_signals,
    weighted_field_sample,
    abstract_template,
    abstract_templates,
    to_template,
    distill_templates_into_library,
)


def _row(expression, sharpe, fitness=1.0):
    return {
        "expression": expression,
        "sharpe": sharpe,
        "fitness": fitness,
        "pnl": 5_000_000,
        "longCount": 60,
        "shortCount": 60,
    }


def test_aggregate_field_signals_basic():
    rows = [
        _row("rank(close)", 1.5),           # close 信号
        _row("ts_delta(close, 5)", 0.5),    # close 非信号 (sharpe 0.5 < 0.7)
        _row("rank(volume)", 1.2),          # volume 信号
        _row("rank(volume)", -1.3),         # volume 信号 (负 sharpe, abs > 0.7)
    ]
    stats = aggregate_field_signals(rows, region="EUR", universe="TOP2500", round_n=0)
    by_field = {s.field_id: s for s in stats}

    assert by_field["close"].trials == 2
    assert by_field["close"].signal_count == 1
    assert by_field["close"].hit_rate == 0.5
    assert by_field["close"].max_sharpe == 1.5

    assert by_field["volume"].trials == 2
    assert by_field["volume"].signal_count == 2
    assert by_field["volume"].hit_rate == 1.0
    assert by_field["volume"].max_sharpe == 1.2
    assert by_field["volume"].min_sharpe == -1.3
    assert abs(by_field["volume"].avg_sharpe - (-0.05)) < 1e-9  # (1.2 + (-1.3)) / 2


def test_aggregate_field_signals_explicit_field_ids():
    # field_ids 显式覆盖表达式提取
    rows = [
        {"expression": "group_neutralize(x, sector)", "field_ids": ["x", "sector"],
         "sharpe": 1.0, "fitness": 1.0, "pnl": 5_000_000, "longCount": 60, "shortCount": 60},
    ]
    stats = aggregate_field_signals(rows, region="EUR", universe="TOP2500", round_n=0)
    assert {s.field_id for s in stats} == {"x", "sector"}
    assert all(s.trials == 1 and s.signal_count == 1 for s in stats)


def test_weighted_field_sample_prefers_high_hit_rate():
    stats = [
        FieldSignalStat(field_id="hot", trials=10, signal_count=9, hit_rate=0.9),
        FieldSignalStat(field_id="mid", trials=10, signal_count=5, hit_rate=0.5),
        FieldSignalStat(field_id="cold", trials=10, signal_count=1, hit_rate=0.1),
    ]
    counter = Counter()
    for seed in range(300):
        picked = weighted_field_sample(stats, sample_n=1, min_trials=1, cold_boost=0.0, seed=seed)
        counter[picked[0]] += 1
    # 冷启动权重为 0 时, 命中率越高越常被抽中
    assert counter["hot"] > counter["mid"] > counter["cold"]


def test_weighted_field_sample_filters_min_trials():
    stats = [
        FieldSignalStat(field_id="noisy", trials=0, signal_count=0, hit_rate=1.0),
        FieldSignalStat(field_id="solid", trials=5, signal_count=5, hit_rate=1.0),
    ]
    picked = weighted_field_sample(stats, sample_n=10, min_trials=1, cold_boost=0.5, seed=0)
    assert "noisy" not in picked


def test_abstract_template_replaces_fields():
    tpl = abstract_template("ts_delta(close, 5) + rank(volume)")
    assert "{a}" in tpl and "{b}" in tpl
    assert "close" not in tpl and "volume" not in tpl


def test_abstract_template_no_substring_collision():
    # 显式传字段顺序, 验证边界匹配不误伤子串
    tpl = abstract_template("rank(cap) / rank(market_cap)", field_ids=["market_cap", "cap"])
    assert tpl == "rank({b}) / rank({a})"


def test_abstract_templates_support_dedup():
    exprs = [
        "ts_delta(close, 5)",
        "ts_delta(volume, 5)",
        "ts_delta(open, 5)",
        "rank(close)",
    ]
    abstractions = abstract_templates(exprs, min_support=1)
    by_tpl = {a.expression_template: a for a in abstractions}

    assert by_tpl["ts_delta({a}, 5)"].support == 3
    assert by_tpl["rank({a})"].support == 1
    # 按 support 降序
    assert abstractions[0].expression_template == "ts_delta({a}, 5)"


def test_abstract_templates_min_support():
    abstractions = abstract_templates(["rank(close)", "rank(volume)", "ts_delta(close, 5)"], min_support=2)
    # 只有 "rank({a})" 出现 2 次
    assert [a.expression_template for a in abstractions] == ["rank({a})"]


# ---------------------------------------------------------------------------
# P1: 蒸馏模板回填 template_library
# ---------------------------------------------------------------------------

def test_to_template_builds_library_record():
    abs_list = abstract_templates(["ts_delta(close, 5)", "ts_delta(volume, 5)"], min_support=1)
    tpl = to_template(abs_list[0], round_n=2)
    assert tpl.family == "distilled"
    assert tpl.template_type == "placeholder"
    assert tpl.name.startswith("distilled_")
    assert tpl.slot_count == 1
    assert tpl.placeholders == {"a": {"role": "scalar", "type": "data_field"}}
    assert tpl.source["type"] == "distilled"
    assert tpl.source["round"] == 2
    assert tpl.source["support"] == 2  # ts_delta(close) + ts_delta(volume) = 2 次


def test_distill_templates_into_library_roundtrip():
    from alpha_operator_framework.database import AlphaDatabase
    with tempfile.TemporaryDirectory() as tmp:
        db = AlphaDatabase(str(Path(tmp) / "research.db"))
        try:
            exprs = ["rank(close)", "rank(volume)", "rank(open)", "ts_delta(close, 5)"]
            distill_templates_into_library(db, exprs, round_n=1, min_support=1)
            distilled = db.list_templates(families=["distilled"])
            # rank({a}) support=3, ts_delta({a},5) support=1 → 2 个骨架
            assert len(distilled) == 2

            # 幂等: 再次回填相同表达式, 骨架数不变
            distill_templates_into_library(db, exprs, round_n=1, min_support=1)
            assert len(db.list_templates(families=["distilled"])) == 2
        finally:
            db.close()


def test_distilled_template_consumable():
    from alpha_operator_framework.database import AlphaDatabase
    from alpha_operator_framework.domain.fields import ScalarField
    from alpha_operator_framework.generation.template_library import (
        template_creation_strategy, TemplateStrategyConfig,
    )
    with tempfile.TemporaryDirectory() as tmp:
        db = AlphaDatabase(str(Path(tmp) / "research.db"))
        try:
            distill_templates_into_library(db, ["rank(close)", "rank(volume)"], round_n=1)
            templates = db.list_templates(families=["distilled"])
            assert templates

            scalar_fields = [
                ScalarField(expr="winsorize(ts_backfill(close,120),std=4)", category="pv", field_id="close"),
                ScalarField(expr="winsorize(ts_backfill(volume,120),std=4)", category="pv", field_id="volume"),
            ]
            config = TemplateStrategyConfig(families=("distilled",))
            tasks = template_creation_strategy(templates, scalar_fields, [], config)
            # rank({a}) 骨架 × 2 个字段 → 2 个 task
            assert len(tasks) == 2
            assert all("rank(" in t.expression for t in tasks)
        finally:
            db.close()


def test_distill_templates_round_from_results():
    from alpha_operator_framework.database import AlphaDatabase
    from alpha_operator_framework.loop import LoopConfig, distill_templates_round

    with tempfile.TemporaryDirectory() as tmp:
        db = AlphaDatabase(str(Path(tmp) / "research.db"))
        try:
            results = [
                {"expression": "rank(close)", "sharpe": 1.5, "fitness": 1.0,
                 "pnl": 5_000_000, "longCount": 60, "shortCount": 60},   # 达标
                {"expression": "rank(volume)", "sharpe": 1.2, "fitness": 1.0,
                 "pnl": 5_000_000, "longCount": 60, "shortCount": 60},  # 达标
                {"expression": "rank(open)", "sharpe": 0.3, "fitness": 1.0,
                 "pnl": 5_000_000, "longCount": 60, "shortCount": 60},  # 不达标
            ]
            config = LoopConfig(distill_templates=True)
            n = distill_templates_round(db, results=results, config=config, round_n=0)
            # rank(close)+rank(volume) 达标 → rank({a}) support=2 → 1 个骨架
            assert n == 1
            distilled = db.list_templates(families=["distilled"])
            assert len(distilled) == 1
            assert distilled[0].expression_template == "rank({a})"
        finally:
            db.close()


# ---------------------------------------------------------------------------
# P2: 配对信号沉淀 (pair_signals)
# ---------------------------------------------------------------------------

def test_aggregate_pair_signals():
    from alpha_operator_framework.distill import aggregate_pair_signals

    results = [
        # 配对 A: bullish-bearish 差值, 2 次都达标
        {"pair_spec": "difference:senti_bullish:senti_bearish", "pair_kind": "difference",
         "expression": "senti_bullish - senti_bearish", "sharpe": 1.5, "fitness": 1.0,
         "pnl": 5_000_000, "longCount": 60, "shortCount": 60},
        {"pair_spec": "difference:senti_bullish:senti_bearish", "pair_kind": "difference",
         "expression": "senti_bullish - senti_bearish", "sharpe": 1.3, "fitness": 1.0,
         "pnl": 5_000_000, "longCount": 60, "shortCount": 60},
        # 配对 B: 不达标
        {"pair_spec": "difference:up:down", "pair_kind": "difference",
         "expression": "up - down", "sharpe": 0.3, "fitness": 1.0,
         "pnl": 5_000_000, "longCount": 60, "shortCount": 60},
        # 非配对行 → 忽略
        {"expression": "rank(close)", "sharpe": 1.5, "fitness": 1.0,
         "pnl": 5_000_000, "longCount": 60, "shortCount": 60},
    ]
    stats = aggregate_pair_signals(results, region="GBR", universe="TOP700", round_n=0)
    by_spec = {s.pair_spec: s for s in stats}

    assert set(by_spec.keys()) == {"difference:senti_bullish:senti_bearish", "difference:up:down"}
    a = by_spec["difference:senti_bullish:senti_bearish"]
    assert a.trials == 2
    assert a.signal_count == 2
    assert a.hit_rate == 1.0
    assert a.pair_kind == "difference"


def test_distill_pairs_round():
    from alpha_operator_framework.database import AlphaDatabase
    from alpha_operator_framework.loop import LoopConfig, distill_pairs_round

    with tempfile.TemporaryDirectory() as tmp:
        db = AlphaDatabase(str(Path(tmp) / "research.db"))
        try:
            results = [
                {"pair_spec": "difference:senti_bullish:senti_bearish", "pair_kind": "difference",
                 "expression": "senti_bullish - senti_bearish", "sharpe": 1.5, "fitness": 1.0,
                 "pnl": 5_000_000, "longCount": 60, "shortCount": 60},
            ]
            config = LoopConfig(distill_pairs=True, region="GBR")
            n = distill_pairs_round(db, results=results, config=config, round_n=0)
            assert n == 1
            got = db.get_pair_signal_stats(region="GBR")
            assert len(got) == 1
            assert got[0]["pair_spec"] == "difference:senti_bullish:senti_bearish"
            assert got[0]["signal_count"] == 1
        finally:
            db.close()


def test_abstract_templates_skips_vec_skeletons():
    # vec_ 骨架不再粗暴跳过, 而是保留并标注「槽位类型」: 被 vec_* 直接包裹的槽
    # 是 vector 槽 (消费时只能填裸 VECTOR 字段), 从源头杜绝 vec_count(matrix_expr)
    # 双重嵌套 —— 这是生成期类型约束的依据, 而非生成后过滤。
    exprs = [
        "ts_delta(winsorize(ts_backfill(vec_count(close),120),std=4.0),120)",
        "rank(close)",
        "ts_delta(close, 5)",
    ]
    ab = abstract_templates(exprs, min_support=1)
    by_tpl = {a.expression_template: a for a in ab}
    # vec_ 骨架保留, 且槽位标注为 vector
    vec_tpl = "ts_delta(winsorize(ts_backfill(vec_count({a}),120),std=4.0),120)"
    assert vec_tpl in by_tpl
    assert by_tpl[vec_tpl].slot_types.get("a") == "vector"
    # 非 vec_ 的槽位标注 scalar
    assert by_tpl["rank({a})"].slot_types.get("a") == "scalar"
    assert by_tpl["ts_delta({a}, 5)"].slot_types.get("a") == "scalar"


def test_template_creation_vector_slot_requires_vector_fields():
    """生成期类型约束: vec_ 槽位只填裸 VECTOR 字段, 从源头杜绝双重 vec 嵌套.

    - 无 vector_fields 候选 → 含 vec_ 槽位的模板整个跳过 (0 任务)
    - 有 vector_fields 候选 → 生成 vec_count(rsk60_last) 这类合法表达式 (裸字段)
    - 普通 scalar 模板不受影响
    """
    from alpha_operator_framework.database import AlphaDatabase
    from alpha_operator_framework.domain.fields import ScalarField
    from alpha_operator_framework.distill import distill_templates_into_library
    from alpha_operator_framework.generation.template_library import (
        template_creation_strategy, TemplateStrategyConfig,
    )

    with tempfile.TemporaryDirectory() as tmp:
        db = AlphaDatabase(str(Path(tmp) / "research.db"))
        try:
            # 蒸馏一个含 vec_ 的骨架 (槽位 {a} 应标注 vector)
            distill_templates_into_library(
                db,
                ["ts_delta(winsorize(ts_backfill(vec_count(rsk60_last),120),std=4.0),120)"],
                round_n=1, min_support=1,
            )
            templates = db.list_templates(families=["distilled"])
            assert len(templates) == 1
            assert templates[0].placeholders["a"]["role"] == "vector", templates[0].placeholders

            scalar_fields = [
                ScalarField(expr="winsorize(ts_backfill(close,120),std=4.0)", category="pv", field_id="close"),
            ]
            config = TemplateStrategyConfig(families=("distilled",))

            # 1) 无 vector 候选 → vec_ 模板跳过, 0 任务 (源头不生成非法表达式)
            assert template_creation_strategy(templates, scalar_fields, [], config) == []

            # 2) 有 vector 候选 → 生成合法表达式: vec_count 参数是裸 VECTOR 字段
            tasks = template_creation_strategy(
                templates, scalar_fields, [], config,
                vector_fields=["rsk60_last"],
            )
            assert len(tasks) == 1
            expr = tasks[0].expression
            # vector 槽填裸 VECTOR 字段: vec_count 参数是裸字段 id (非表达式)
            assert "vec_count(rsk60_last)" in expr, expr
        finally:
            db.close()
