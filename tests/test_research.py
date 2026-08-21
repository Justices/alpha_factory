"""Unit tests for Literature & Research Mining Engine (research/)."""

import pytest

from alpha_operator_framework.domain.fields import FieldSpec
from alpha_operator_framework.research import (
    DocumentType,
    IdeaExtractor,
    PaperIdea,
    PaperToASTTranslator,
    ParsedDocument,
    SemanticFieldGrounder,
    clean_literature_text,
    extract_formulas_from_text,
    ingest_literature_to_alphas,
    parse_document,
)


def test_document_parser_and_cleaner():
    sample_text = """
    # 海通证券金工：特质波动率与反转因子深度解析

    ## 摘要
    本报告探讨了特质波动率对短期反转因子的增强效应。我们发现剥离特质波动率后，反转因子在全市场的夏普比率显著提升。

    ## 核心公式
    我们定义修正反转因子如下：
    ```python
    rank(close) / (rank(volume) + 0.01)
    ```

    ## 免责声明
    本报告仅供机构投资者参考，本公司不承担任何直接或间接投资损失责任。
    """

    doc = parse_document(sample_text, doc_type=DocumentType.RESEARCH_REPORT)

    assert "海通证券金工" in doc.title
    assert "特质波动率" in doc.abstract
    assert len(doc.formulas_found) >= 1
    assert "rank(close)" in doc.formulas_found[0]
    # 免责声明应被清洗过滤
    assert "本公司不承担" not in doc.clean_text


def test_idea_extractor_llm_json_parsing():
    sample_llm_json = """
    ```json
    [
      {
        "title": "特质波动率修正反转",
        "category": "liquidity_volatility",
        "rationale": "高特质波动率抑制动量持续，促成更强的短期均值回归。",
        "abstract_formula": "group_neutralize(rank(momentum) / (rank(volatility) + 0.01), industry)",
        "variable_roles": {
          "momentum": "20日收盘价动量",
          "volatility": "60日特质波动率"
        },
        "recommended_decay": 5
      }
    ]
    ```
    """

    ideas = IdeaExtractor.parse_llm_response(sample_llm_json, source_title="Test Report")
    assert len(ideas) == 1
    idea = ideas[0]
    assert idea.title == "特质波动率修正反转"
    assert idea.category == "liquidity_volatility"
    assert "momentum" in idea.variable_roles
    assert idea.recommended_decay == 5


def test_semantic_field_grounder():
    grounder = SemanticFieldGrounder()
    fields = [
        FieldSpec(id="returns", dataset_id="pv1", type="MATRIX", description="Daily return rate"),
        FieldSpec(id="volume", dataset_id="pv1", type="MATRIX", description="Daily trade volume"),
        FieldSpec(id="operating_cashflow", dataset_id="fund1", type="MATRIX", description="Operating cashflow"),
        FieldSpec(id="est_eps_up", dataset_id="analyst1", type="MATRIX", description="Analyst upward revisions"),
    ]

    # 1. 对齐动量 -> returns
    grounded_mom = grounder.ground_variable("momentum_20", "20-day return momentum", fields)
    assert grounded_mom == "returns"

    # 2. 对齐波动率/成交量 -> volume
    grounded_vol = grounder.ground_variable("volatility", "historical volatility", fields)
    assert grounded_vol in ("volume", "returns")

    # 3. 对齐分析师预期 -> est_eps_up
    grounded_analyst = grounder.ground_variable("analyst_score", "analyst revision ratio", fields)
    assert grounded_analyst == "est_eps_up"


def test_paper_to_ast_translator():
    translator = PaperToASTTranslator()
    idea = PaperIdea(
        idea_id="idea_01",
        title="动量流动性背离",
        category="momentum_reversal",
        rationale="量价背离与动量衰竭",
        abstract_formula="rank(momentum) / (rank(volume) + 0.01)",
        variable_roles={"momentum": "收益率", "volume": "成交量"},
        recommended_decay=6,
    )
    grounded_vars = {"momentum": "returns", "volume": "volume"}

    tasks = translator.translate_idea_to_tasks(idea, grounded_vars)
    assert len(tasks) == 1
    task = tasks[0]

    assert task.family == "literature"
    assert "returns" in task.expression
    assert "volume" in task.expression
    assert task.meta["paper_title"] == "动量流动性背离"


def test_end_to_end_literature_pipeline():
    paper_content = """
    # 中信证券：量价背离与反转因子构建

    ## 摘要
    本文通过构建成交量加权的动量反转因子，在全市场获得显著超额收益。

    ## 公式
    ```python
    rank(returns) - rank(volume)
    ```
    """
    fields = [
        FieldSpec(id="returns", dataset_id="pv1", type="MATRIX", description="Return rate"),
        FieldSpec(id="volume", dataset_id="pv1", type="MATRIX", description="Volume"),
    ]

    tasks = ingest_literature_to_alphas(
        literature_text=paper_content,
        available_fields=fields,
        run_sandbox_prefilter=False,
    )

    assert len(tasks) >= 1
    assert "paper_" in tasks[0].expression_origin
    assert "returns" in tasks[0].expression

