"""统一 LLM 配置管理器与多 Provider 客户端 (Unified LLM Config & Client).

功能:
  1. 统一配置文件 (configs/llm_config.json) 集中管理多厂商 (DeepSeek / OpenAI / Qwen / Ollama)
  2. 结构化维护各 Provider 的 base_url, api_key, default_model 与可用 models 列表
  3. 双引擎智能适配: 优先使用原生 openai.OpenAI SDK (若已安装); 未安装时无缝使用标准库 urllib 请求 (零外部依赖)
  4. 环境变量优先覆盖机制 (如 $env:OPENAI_API_KEY, $env:DEEPSEEK_API_KEY)
  5. 双轨降级保护: 无 Key 或网络异常自动降级为离线启发式规则
"""

from __future__ import annotations

import json
import os
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from alpha_operator_framework.domain.fields import FieldSpec
from alpha_operator_framework.research.document_parser import ParsedDocument
from alpha_operator_framework.research.idea_extractor import IdeaExtractor, PaperIdea


@dataclass
class ProviderConfig:
    """单个模型提供商配置."""

    name: str
    base_url: str
    api_key: str = ""
    default_model: str = ""
    models: List[str] = field(default_factory=list)


@dataclass
class LLMConfig:
    """全量 LLM 配置快照."""

    default_provider: str = "deepseek"
    providers: Dict[str, ProviderConfig] = field(default_factory=dict)
    temperature: float = 0.2
    timeout_seconds: int = 45
    system_prompt: str = "你是一名顶级量化对冲基金的首席金工分析师，擅长从研报和学术论文中提炼 Alpha 因子与数学表达式。"


# 默认内置提供商配置预设
_DEFAULT_PROVIDERS = {
    "deepseek": ProviderConfig(
        name="deepseek",
        base_url="https://api.deepseek.com/v1",
        api_key="",
        default_model="deepseek-chat",
        models=["deepseek-chat", "deepseek-reasoner"],
    ),
    "openai": ProviderConfig(
        name="openai",
        base_url="https://api.openai.com/v1",
        api_key="",
        default_model="gpt-4o-mini",
        models=["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-3.5-turbo"],
    ),
    "qwen": ProviderConfig(
        name="qwen",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        api_key="",
        default_model="qwen-plus",
        models=["qwen-max", "qwen-plus", "qwen-turbo"],
    ),
    "ollama": ProviderConfig(
        name="ollama",
        base_url="http://localhost:11434/v1",
        api_key="ollama",
        default_model="llama3.1",
        models=["llama3.1", "qwen2.5:14b", "deepseek-r1:14b"],
    ),
}


class LLMConfigManager:
    """LLM 统一配置管理器."""

    DEFAULT_CONFIG_PATHS = [
        Path("configs/llm_config.json"),
        Path("configs/config.json"),
        Path("llm_config.json"),
    ]

    def __init__(self, config_path: Optional[str | Path] = None):
        self.config_path = Path(config_path) if config_path else None
        self.config = self._load_and_merge_config()

    def _load_and_merge_config(self) -> LLMConfig:
        """加载配置文件并合并环境变量覆盖."""
        payload: Dict[str, Any] = {}

        # 1. 尝试从指定或默认路径读取 JSON
        paths_to_try = [self.config_path] if self.config_path else self.DEFAULT_CONFIG_PATHS
        for p in paths_to_try:
            if p and p.exists():
                try:
                    payload = json.loads(p.read_text(encoding="utf-8"))
                    break
                except Exception:
                    pass

        default_provider = str(payload.get("default_provider") or "deepseek").lower()
        temperature = float(payload.get("temperature", 0.2))
        timeout_seconds = int(payload.get("timeout_seconds", 45))
        sys_prompt = str(payload.get("system_prompt") or "你是一名顶级量化对冲基金的首席金工分析师，擅长从研报和学术论文中提炼 Alpha 因子与数学表达式。")

        providers: Dict[str, ProviderConfig] = {}

        # 2. 解析 providers 列表
        raw_providers = payload.get("providers") or {}
        # 先载入默认预设
        for pname, pdef in _DEFAULT_PROVIDERS.items():
            providers[pname] = ProviderConfig(
                name=pdef.name,
                base_url=pdef.base_url,
                api_key=pdef.api_key,
                default_model=pdef.default_model,
                models=list(pdef.models),
            )

        # 用配置文件覆盖
        for pname, pdata in raw_providers.items():
            pname_clean = str(pname).lower()
            base_url = str(pdata.get("base_url") or providers.get(pname_clean, _DEFAULT_PROVIDERS["deepseek"]).base_url)
            api_key = str(pdata.get("api_key") or "")
            def_model = str(pdata.get("default_model") or "")
            models = list(pdata.get("models") or [])
            if def_model and def_model not in models:
                models.insert(0, def_model)

            providers[pname_clean] = ProviderConfig(
                name=pname_clean,
                base_url=base_url,
                api_key=api_key,
                default_model=def_model or (models[0] if models else "default"),
                models=models,
            )

        # 3. 环境变量覆盖 (具有最高优先级)
        # DeepSeek
        if os.environ.get("DEEPSEEK_API_KEY"):
            if "deepseek" not in providers:
                providers["deepseek"] = ProviderConfig("deepseek", "https://api.deepseek.com/v1")
            providers["deepseek"].api_key = os.environ["DEEPSEEK_API_KEY"].strip()
        if os.environ.get("DEEPSEEK_BASE_URL"):
            providers["deepseek"].base_url = os.environ["DEEPSEEK_BASE_URL"].strip()
        if os.environ.get("DEEPSEEK_MODEL"):
            providers["deepseek"].default_model = os.environ["DEEPSEEK_MODEL"].strip()

        # OpenAI
        if os.environ.get("OPENAI_API_KEY"):
            if "openai" not in providers:
                providers["openai"] = ProviderConfig("openai", "https://api.openai.com/v1")
            providers["openai"].api_key = os.environ["OPENAI_API_KEY"].strip()
        if os.environ.get("OPENAI_BASE_URL"):
            providers["openai"].base_url = os.environ["OPENAI_BASE_URL"].strip()
        if os.environ.get("OPENAI_MODEL"):
            providers["openai"].default_model = os.environ["OPENAI_MODEL"].strip()

        # Qwen
        if os.environ.get("DASHSCOPE_API_KEY") or os.environ.get("QWEN_API_KEY"):
            q_key = (os.environ.get("DASHSCOPE_API_KEY") or os.environ.get("QWEN_API_KEY") or "").strip()
            if "qwen" not in providers:
                providers["qwen"] = ProviderConfig("qwen", "https://dashscope.aliyuncs.com/compatible-mode/v1")
            providers["qwen"].api_key = q_key

        return LLMConfig(
            default_provider=default_provider,
            providers=providers,
            temperature=temperature,
            timeout_seconds=timeout_seconds,
            system_prompt=sys_prompt,
        )

    def list_providers(self) -> List[str]:
        """列出全部可用提供商名称."""
        return list(self.config.providers.keys())

    def list_models(self, provider_name: Optional[str] = None) -> List[str]:
        """列出指定提供商支持的模型列表."""
        pname = (provider_name or self.config.default_provider).lower()
        prov = self.config.providers.get(pname)
        if prov:
            return list(prov.models)
        return []

    def get_provider_config(self, provider_name: Optional[str] = None) -> ProviderConfig:
        """获取指定提供商配置 (若未提供则返回 default_provider)."""
        pname = (provider_name or self.config.default_provider).lower()
        if pname in self.config.providers:
            return self.config.providers[pname]
        return self.config.providers.get("deepseek", _DEFAULT_PROVIDERS["deepseek"])

    def set_api_key(self, provider_name: str, api_key: str):
        """动态设置提供商 API Key."""
        pname = provider_name.lower()
        if pname in self.config.providers:
            self.config.providers[pname].api_key = api_key.strip()

    def save_config(self, path: Optional[str | Path] = None):
        """保存配置到文件."""
        target = Path(path) if path else (self.config_path or Path("configs/llm_config.json"))
        target.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "default_provider": self.config.default_provider,
            "providers": {
                name: {
                    "base_url": p.base_url,
                    "api_key": p.api_key,
                    "default_model": p.default_model,
                    "models": p.models,
                }
                for name, p in self.config.providers.items()
            },
            "temperature": self.config.temperature,
            "timeout_seconds": self.config.timeout_seconds,
            "system_prompt": self.config.system_prompt,
        }
        target.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _http_chat_request(
    base_url: str,
    api_key: str,
    model: str,
    prompt: str,
    system_prompt: str,
    temperature: float = 0.2,
    timeout_seconds: int = 45,
) -> str:
    """使用标准库 urllib 发起 OpenAI 兼容 HTTP 请求."""
    url = base_url.rstrip("/")
    if not url.endswith("/chat/completions"):
        if url.endswith("/v1"):
            url = f"{url}/chat/completions"
        else:
            url = f"{url}/v1/chat/completions"

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        "temperature": temperature,
    }

    req_data = json.dumps(payload).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "AlphaFactory-UnifiedLLM/1.0",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    req = urllib.request.Request(url, data=req_data, headers=headers, method="POST")

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    try:
        with urllib.request.urlopen(req, timeout=timeout_seconds, context=ctx) as response:
            res_body = response.read().decode("utf-8")
            res_json = json.loads(res_body)

            choices = res_json.get("choices") or []
            if not choices:
                raise RuntimeError(f"LLM 响应缺少 choices: {res_body[:200]}")

            content = choices[0].get("message", {}).get("content") or ""
            return content.strip()

    except urllib.error.HTTPError as e:
        err_msg = e.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"LLM HTTP {e.code} 请求失败: {err_msg[:300]}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"LLM 网络连接失败 ({url}): {e.reason}") from e
    except Exception as e:
        raise RuntimeError(f"LLM 调用异常: {e}") from e


class UnifiedLLMClient:
    """统一多模型客户端 (支持 OpenAI SDK 与标准库双引擎)."""

    def __init__(self, config_manager: Optional[LLMConfigManager] = None):
        self.mgr = config_manager or LLMConfigManager()

    def chat(
        self,
        prompt: str,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        system_prompt: Optional[str] = None,
    ) -> str:
        """执行 Chat Completions 推理."""
        p_cfg = self.mgr.get_provider_config(provider)
        target_model = model or p_cfg.default_model or (p_cfg.models[0] if p_cfg.models else "default")
        sys_p = system_prompt or self.mgr.config.system_prompt

        # 1. 尝试使用官方 openai.OpenAI SDK
        try:
            from openai import OpenAI
            client = OpenAI(api_key=p_cfg.api_key or "ollama", base_url=p_cfg.base_url)
            response = client.chat.completions.create(
                model=target_model,
                messages=[
                    {"role": "system", "content": sys_p},
                    {"role": "user", "content": prompt},
                ],
                temperature=self.mgr.config.temperature,
                timeout=self.mgr.config.timeout_seconds,
            )
            content = response.choices[0].message.content or ""
            return content.strip()
        except ImportError:
            pass
        except Exception as e:
            # SDK 运行异常时回退到 HTTP 标准库请求
            pass

        # 2. 使用标准库 HTTP 引擎 (零依赖)
        return _http_chat_request(
            base_url=p_cfg.base_url,
            api_key=p_cfg.api_key,
            model=target_model,
            prompt=prompt,
            system_prompt=sys_p,
            temperature=self.mgr.config.temperature,
            timeout_seconds=self.mgr.config.timeout_seconds,
        )


def load_llm_config_from_env() -> LLMConfig:
    """从系统环境变量自动读取并合并 LLM 统一配置."""
    return LLMConfigManager().config


def call_openai_compatible_chat(
    prompt: str,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    config: Optional[LLMConfig] = None,
    system_prompt: Optional[str] = None,
) -> str:
    """统一便捷函数: 发送 Chat 请求."""
    client = UnifiedLLMClient()
    return client.chat(prompt, provider=provider, model=model, system_prompt=system_prompt)


def extract_ideas_with_llm(
    doc: ParsedDocument,
    available_fields: Optional[Sequence[FieldSpec]] = None,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    client: Optional[UnifiedLLMClient] = None,
) -> List[PaperIdea]:
    """使用统一 LLM 客户端自动提炼研报假说，无 Key 或网络故障时自动降级."""
    llm_client = client or UnifiedLLMClient()
    p_cfg = llm_client.mgr.get_provider_config(provider)

    # 1. 若无 Key 且非本地 Ollama，自动触发离线规则降级
    is_local = "localhost" in p_cfg.base_url or "127.0.0.1" in p_cfg.base_url
    if not p_cfg.api_key and not is_local:
        return IdeaExtractor.extract_from_text_rule_based(doc)

    prompt = IdeaExtractor.build_extraction_prompt(doc, available_fields)

    try:
        response_text = llm_client.chat(prompt, provider=provider, model=model)
        ideas = IdeaExtractor.parse_llm_response(response_text, source_title=doc.title)
        if ideas:
            return ideas
    except Exception:
        pass

    return IdeaExtractor.extract_from_text_rule_based(doc)
