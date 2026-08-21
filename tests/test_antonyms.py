"""相反词配对发现 (antonyms) 单元测试."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from alpha_operator_framework.domain.antonyms import (
    DIFFERENCE_ANTONYMS,
    discover_antonym_pairs,
    antonym_pair_tasks,
)
from alpha_operator_framework.domain.fields import FieldSpec


def _f(fid, ds="ds1", ftype="MATRIX"):
    # coverage/date_coverage 给足, 让测试字段通过 survey 的双闸 (min_coverage=0.5, min_date_coverage=0.9)
    return FieldSpec(id=fid, dataset_id=ds, type=ftype, coverage=1.0, date_coverage=1.0)


def test_discover_bullish_bearish():
    fields = [
        _f("senti_bullish_flag"),
        _f("senti_bearish_flag"),
        _f("unrelated_field"),
    ]
    pairs = discover_antonym_pairs(fields)
    assert len(pairs) == 1
    spec = pairs[0]
    assert spec.kind == "difference"
    assert spec.left == "senti_bullish_flag"
    assert spec.right == "senti_bearish_flag"
    assert spec.source == "antonym"


def test_discover_up_down():
    fields = [
        _f("anl_dps_gr_12m_up"),
        _f("anl_dps_gr_12m_down"),
    ]
    pairs = discover_antonym_pairs(fields)
    assert len(pairs) == 1
    assert {pairs[0].left, pairs[0].right} == {"anl_dps_gr_12m_up", "anl_dps_gr_12m_down"}


def test_no_cross_dataset():
    fields = [
        _f("senti_bullish_flag", ds="ds1"),
        _f("senti_bearish_flag", ds="ds2"),  # 不同 dataset → 不配对
    ]
    assert discover_antonym_pairs(fields) == []


def test_skip_word_embedded_in_other_word():
    # "up" 是 "group"/"sup" 的子串时不应误配 (词边界保护)
    fields = [
        _f("group_up_xxx"),  # up 前面是 p (group) → 不视为含 up
        _f("sup_xxx"),
    ]
    assert discover_antonym_pairs(fields) == []


def test_skip_field_with_both_words():
    # 字段同时含 a 和 b → 跳过, 避免自我配对
    fields = [
        _f("flow_inflow_outflow_ratio"),  # 同时含 inflow 和 outflow
    ]
    assert discover_antonym_pairs(fields) == []


def test_antonym_pair_tasks_generate():
    fields = [
        _f("senti_bullish_flag"),
        _f("senti_bearish_flag"),
    ]
    tasks = antonym_pair_tasks(fields)
    assert len(tasks) >= 1
    assert tasks[0].family == "paired_base"
    assert tasks[0].expression_origin == "paired_base"
    # 表达式含两个字段的差值
    assert "bullish_flag" in tasks[0].expression and "bearish_flag" in tasks[0].expression


def test_default_antonyms_exclude_existing_mechanisms():
    # 默认词库刻意排除已有机制覆盖的 positive/negative、raised/lowered、high/low
    flat = [w for pair in DIFFERENCE_ANTONYMS for w in pair]
    assert "positive" not in flat and "negative" not in flat
    assert "raisednum" not in flat and "lowerednum" not in flat
    assert "high" not in flat and "low" not in flat


def test_survey_includes_antonym_pairs():
    import asyncio
    import json
    import tempfile
    from pathlib import Path

    from alpha_operator_framework.ai_workflow import run_survey_with_fields, SurveyConfig

    fields = [
        _f("senti_bullish_flag"),
        _f("senti_bearish_flag"),
    ]
    # 只保留 antonym 配对 (关掉 unary/semantic/template), 聚焦验证 antonym 接入
    config = SurveyConfig(
        region="GBR", universe="TOP700", delay=1, sample_n=2,
        include_unary=False, include_semantic_pairs=False,
        include_antonym_pairs=True, use_template_library=False,
    )
    with tempfile.TemporaryDirectory() as tmp:
        result = asyncio.run(run_survey_with_fields(fields, config, Path(tmp), execute=False))
        assert result.success
        assert result.tasks_generated >= 1

        # dry-run 会写 tasks_file, 验证任务确实含相反词配对表达式
        tasks_file = result.tasks_file
        assert tasks_file and tasks_file.exists()
        payload = json.loads(tasks_file.read_text(encoding="utf-8"))
        tasks = payload if isinstance(payload, list) else payload.get("tasks", [])
        exprs = [t.get("expression", "") for t in tasks]
        assert any("bullish_flag" in e and "bearish_flag" in e for e in exprs)


def test_survey_can_disable_antonym_pairs():
    import asyncio
    import tempfile
    from pathlib import Path

    from alpha_operator_framework.ai_workflow import run_survey_with_fields, SurveyConfig

    fields = [_f("senti_bullish_flag"), _f("senti_bearish_flag")]
    config = SurveyConfig(
        region="GBR", universe="TOP700", delay=1, sample_n=2,
        include_unary=False, include_semantic_pairs=False,
        include_antonym_pairs=False, use_template_library=False,
    )
    with tempfile.TemporaryDirectory() as tmp:
        result = asyncio.run(run_survey_with_fields(fields, config, Path(tmp), execute=False))
        # 全关 → 无任务
        assert result.tasks_generated == 0


# ---------------------------------------------------------------------------
# P2: long/short 后缀配对 (歧义处理)
# ---------------------------------------------------------------------------

def test_long_short_suffix_pairs():
    from alpha_operator_framework.domain.antonyms import discover_long_short_pairs

    fields = [
        _f("anl_shift_7d_long"),
        _f("anl_shift_7d_short"),
    ]
    pairs = discover_long_short_pairs(fields)
    assert len(pairs) == 1
    assert {pairs[0].left, pairs[0].right} == {"anl_shift_7d_long", "anl_shift_7d_short"}
    assert pairs[0].source == "long_short"


def test_long_short_excludes_term_horizon():
    from alpha_operator_framework.domain.antonyms import discover_long_short_pairs

    fields = [
        _f("growth_long_term"),     # long_term → 排除
        _f("growth_short_term"),    # short_term → 排除
        _f("earn_long_horizon"),    # long_horizon → 排除
        _f("earn_short_horizon"),   # short_horizon → 排除
    ]
    assert discover_long_short_pairs(fields) == []


def test_long_short_no_cross_dataset():
    from alpha_operator_framework.domain.antonyms import discover_long_short_pairs

    fields = [
        _f("anl_shift_7d_long", ds="ds1"),
        _f("anl_shift_7d_short", ds="ds2"),  # 不同 dataset → 不配对
    ]
    assert discover_long_short_pairs(fields) == []


def test_antonym_pair_tasks_include_long_short():
    from alpha_operator_framework.domain.antonyms import antonym_pair_tasks

    fields = [
        _f("anl_shift_7d_long"),
        _f("anl_shift_7d_short"),
    ]
    tasks = antonym_pair_tasks(fields)
    assert len(tasks) >= 1
    assert any("anl_shift_7d_long" in t.expression and "anl_shift_7d_short" in t.expression
               for t in tasks)
