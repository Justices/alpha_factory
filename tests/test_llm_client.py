"""Unit tests for Native Zero-Dependency LLM Client and Mode C Integration."""

import io
import json
import os
from unittest.mock import MagicMock, patch
import pytest

from alpha_operator_framework.domain.fields import FieldSpec
from alpha_operator_framework.research import (
    DocumentType,
    LLMConfig,
    LLMConfigManager,
    ProviderConfig,
    UnifiedLLMClient,
    call_openai_compatible_chat,
    extract_ideas_with_llm,
    ingest_literature_to_alphas,
    load_llm_config_from_env,
    parse_document,
)


def test_load_llm_config_from_env(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-openai-123456")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4o-mini")

    cfg = load_llm_config_from_env()
    assert cfg.providers["openai"].api_key == "sk-test-openai-123456"
    assert cfg.providers["openai"].base_url == "https://api.openai.com/v1"
    assert cfg.providers["openai"].default_model == "gpt-4o-mini"

    # 测试 DeepSeek 别名
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-deepseek-key")
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-chat")
    cfg2 = load_llm_config_from_env()
    assert cfg2.providers["deepseek"].api_key == "sk-deepseek-key"
    assert cfg2.providers["deepseek"].default_model == "deepseek-chat"


def test_call_openai_compatible_chat_mocked(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    mock_response_data = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "Hello Quant Trader!",
                }
            }
        ]
    }
    raw_bytes = json.dumps(mock_response_data).encode("utf-8")

    mock_resp = MagicMock()
    mock_resp.read.return_value = raw_bytes
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
        result = call_openai_compatible_chat("Generate an alpha", provider="deepseek", model="deepseek-chat")

        assert result == "Hello Quant Trader!"
        assert mock_urlopen.called
        req = mock_urlopen.call_args[0][0]
        assert req.get_header("Authorization") == "Bearer sk-test"
        assert req.get_full_url() == "https://api.deepseek.com/v1/chat/completions"


def test_extract_ideas_with_llm_success_and_fallback(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-key")
    sample_llm_json = json.dumps([
        {
            "title": "LLM 提炼：流动性冲击因子",
            "category": "liquidity_volatility",
            "rationale": "流动性冲击加剧非理性抛售，促成短期过度偏离后的均值回复",
            "abstract_formula": "rank(close) / (rank(volume) + 0.01)",
            "variable_roles": {"close": "收盘价", "volume": "成交量"},
            "recommended_decay": 7,
        }
    ])

    mock_response_data = {
        "choices": [{"message": {"role": "assistant", "content": sample_llm_json}}]
    }
    raw_bytes = json.dumps(mock_response_data).encode("utf-8")

    mock_resp = MagicMock()
    mock_resp.read.return_value = raw_bytes
    mock_resp.__enter__.return_value = mock_resp

    doc = parse_document("# 流动性冲击研报\n流动性枯竭时的反转策略。")

    # 1. 成功网络响应
    with patch("urllib.request.urlopen", return_value=mock_resp):
        ideas = extract_ideas_with_llm(doc, provider="deepseek")
        assert len(ideas) == 1
        assert ideas[0].title == "LLM 提炼：流动性冲击因子"
        assert ideas[0].recommended_decay == 7

    # 2. 无 Key 时的无缝降级测试
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    # 创建一个没有 key 的 client
    empty_mgr = LLMConfigManager()
    empty_mgr.set_api_key("deepseek", "")
    empty_client = UnifiedLLMClient(config_manager=empty_mgr)

    ideas_fallback = extract_ideas_with_llm(doc, provider="deepseek", client=empty_client)
    assert len(ideas_fallback) >= 1  # 降级为规则抽取成功返回


def test_ingest_literature_to_alphas_with_use_llm(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-deepseek-test")
    sample_llm_json = json.dumps([
        {
            "title": "DeepSeek 挖掘：特质动量因子",
            "category": "momentum_reversal",
            "rationale": "动量持续性在剔除宽基指数 beta 影响后更稳健",
            "abstract_formula": "ts_rank(returns, 22) - ts_rank(volume, 22)",
            "variable_roles": {"returns": "日收益率", "volume": "成交量"},
            "recommended_decay": 5,
        }
    ])

    mock_response_data = {
        "choices": [{"message": {"role": "assistant", "content": sample_llm_json}}]
    }
    raw_bytes = json.dumps(mock_response_data).encode("utf-8")

    mock_resp = MagicMock()
    mock_resp.read.return_value = raw_bytes
    mock_resp.__enter__.return_value = mock_resp

    fields = [
        FieldSpec(id="returns", dataset_id="pv1", type="MATRIX", description="Returns"),
        FieldSpec(id="volume", dataset_id="pv1", type="MATRIX", description="Volume"),
    ]

    with patch("urllib.request.urlopen", return_value=mock_resp):
        tasks = ingest_literature_to_alphas(
            literature_text="# 特质动量深度研报\n内容详情...",
            available_fields=fields,
            use_llm=True,
            provider="deepseek",
            model="deepseek-chat",
        )

        assert len(tasks) >= 1
        assert "returns" in tasks[0].expression
        assert tasks[0].meta["paper_title"] == "DeepSeek 挖掘：特质动量因子"
