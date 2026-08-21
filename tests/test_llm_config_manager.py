"""Unit tests for Unified LLM Configuration Manager, Multi-Provider, and Model List."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from alpha_operator_framework.domain.fields import FieldSpec
from alpha_operator_framework.research import (
    DocumentType,
    LLMConfig,
    LLMConfigManager,
    ProviderConfig,
    UnifiedLLMClient,
    ingest_literature_to_alphas,
    parse_document,
)


def test_llm_config_manager_load_and_list(tmp_path):
    custom_cfg = {
        "default_provider": "openai",
        "providers": {
            "openai": {
                "base_url": "https://api.openai.com/v1",
                "api_key": "sk-custom-openai",
                "default_model": "gpt-4o",
                "models": ["gpt-4o", "gpt-4o-mini"],
            },
            "deepseek": {
                "base_url": "https://api.deepseek.com/v1",
                "api_key": "sk-custom-deepseek",
                "default_model": "deepseek-chat",
                "models": ["deepseek-chat", "deepseek-reasoner"],
            }
        },
        "temperature": 0.3,
        "timeout_seconds": 60,
    }
    cfg_file = tmp_path / "llm_config.json"
    cfg_file.write_text(json.dumps(custom_cfg), encoding="utf-8")

    mgr = LLMConfigManager(config_path=cfg_file)

    assert "openai" in mgr.list_providers()
    assert "deepseek" in mgr.list_providers()
    assert mgr.config.default_provider == "openai"

    models_openai = mgr.list_models("openai")
    assert models_openai == ["gpt-4o", "gpt-4o-mini"]

    models_deepseek = mgr.list_models("deepseek")
    assert models_deepseek == ["deepseek-chat", "deepseek-reasoner"]

    prov = mgr.get_provider_config("deepseek")
    assert prov.api_key == "sk-custom-deepseek"
    assert prov.base_url == "https://api.deepseek.com/v1"


def test_llm_config_env_overrides(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env-openai-key")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-env-deepseek-key")
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-reasoner")

    mgr = LLMConfigManager()
    prov_openai = mgr.get_provider_config("openai")
    prov_deepseek = mgr.get_provider_config("deepseek")

    assert prov_openai.api_key == "sk-env-openai-key"
    assert prov_deepseek.api_key == "sk-env-deepseek-key"
    assert prov_deepseek.default_model == "deepseek-reasoner"


def test_unified_llm_client_multi_provider_switching():
    mock_resp_deepseek = json.dumps({
        "choices": [{"message": {"role": "assistant", "content": "DeepSeek response"}}]
    }).encode("utf-8")

    mock_resp_openai = json.dumps({
        "choices": [{"message": {"role": "assistant", "content": "OpenAI response"}}]
    }).encode("utf-8")

    client = UnifiedLLMClient()

    # 1. 模拟 DeepSeek 调用
    mock_resp = MagicMock()
    mock_resp.read.return_value = mock_resp_deepseek
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
        ans1 = client.chat("Hello DeepSeek", provider="deepseek", model="deepseek-chat")
        assert ans1 == "DeepSeek response"
        req = mock_urlopen.call_args[0][0]
        assert "deepseek" in req.get_full_url()

    # 2. 模拟切换到 OpenAI 调用
    mock_resp.read.return_value = mock_resp_openai
    with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
        ans2 = client.chat("Hello OpenAI", provider="openai", model="gpt-4o")
        assert ans2 == "OpenAI response"
        req = mock_urlopen.call_args[0][0]
        assert "openai" in req.get_full_url()


def test_pipeline_with_provider_and_model_switching(monkeypatch):
    monkeypatch.setenv("QWEN_API_KEY", "sk-mock-qwen-key")
    sample_llm_json = json.dumps([
        {
            "title": "Qwen 提炼：分析师盈余修正",
            "category": "analyst_dispersion",
            "rationale": "分析师一致预期上修产生显著公告后漂移效应",
            "abstract_formula": "group_neutralize(rank(returns) - rank(volume), subindustry)",
            "variable_roles": {"returns": "日收益率", "volume": "成交量"},
            "recommended_decay": 8,
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
            literature_text="# 研报内容...",
            available_fields=fields,
            use_llm=True,
            provider="qwen",
            model="qwen-max",
        )

        assert len(tasks) >= 1
        assert "returns" in tasks[0].expression
        assert tasks[0].meta["paper_title"] == "Qwen 提炼：分析师盈余修正"
