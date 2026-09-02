# 文献研究 LLM 配置

## 目标

让 `alpha_machine.py research` 能从运行时 YAML 统一读取文献研究的 LLM 启用状态和 LLM JSON 配置文件路径，同时保留命令行显式覆盖。

## 配置

`configs/alpha-factory.yaml` 的 `research` 下新增 `literature_llm`：

```yaml
research:
  literature_llm:
    enabled: false
    config_path: configs/llm_config.json
    provider: null
    model: null
```

`config_path` 指向 LLM JSON；JSON 继续保存 API 连接、默认 provider 和默认模型。YAML 的 `provider` 与 `model` 是文献研究流水线的可选默认覆盖。

## 命令行与优先级

`research` 命令提供：

```text
--use-llm true|false
--llm-config <path>
--provider <name>
--model <name>
```

优先级由高到低：命令行显式值、`research.literature_llm` YAML 值、LLM JSON 中的 provider/model 默认值。`--use-llm` 默认 `None`，所以未传时保持 YAML 行为；没有 YAML 配置时保持既有规则提炼行为。

## 边界与验收

仅改动 `research` 文献流水线及其配置解析，不改 `research-cycle` 的 LLM strategy 配置。测试覆盖：YAML 默认生效、CLI 显式 `true`/`false` 覆盖、CLI 配置路径覆盖，以及旧 YAML 缺失该块时仍关闭 LLM。
