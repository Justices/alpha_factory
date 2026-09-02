# Literature LLM Configuration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Load literature-research LLM defaults and its JSON configuration path from runtime YAML, while explicit CLI values override them.

**Architecture:** A focused resolver reads `research.literature_llm`; CLI parsing supplies only explicit values to it. The literature pipeline receives the resolved JSON path and uses it to build the LLM client.

**Tech Stack:** Python, argparse, PyYAML, pytest.

## Global Constraints

- Do not change `research-cycle` LLM strategy configuration.
- Precedence: explicit CLI value, YAML `research.literature_llm`, LLM JSON defaults.
- Missing `literature_llm` keeps LLM disabled.
- `--use-llm` is a tri-state `true|false` argument; absence is no override.

---

### Task 1: Add a runtime configuration resolver

**Files:**
- Modify: `alpha_operator_framework/infrastructure/runtime_factory.py`
- Modify: `configs/alpha-factory.yaml`
- Test: `tests/infrastructure/test_runtime_factory.py`

**Interfaces:**
- Produces `resolve_literature_llm_options(config_path: Path, overrides: Mapping[str, Any]) -> dict[str, Any]` with `enabled`, `config_path`, `provider`, and `model`.

- [ ] **Step 1: Write failing behavior tests**

```python
options = resolve_literature_llm_options(config_path, {})
assert options["enabled"] is True
assert options["config_path"] == tmp_path / "llm" / "custom.json"
assert options["provider"] == "qwen"
assert options["model"] == "qwen-plus"

overridden = resolve_literature_llm_options(config_path, {
    "enabled": False, "config_path": "cli.json", "provider": "openai", "model": "gpt-4o",
})
assert overridden == {
    "enabled": False, "config_path": tmp_path / "cli.json", "provider": "openai", "model": "gpt-4o",
}
```

- [ ] **Step 2: Run the test and observe failure**

Run: `D:\quant-venv\Scripts\python.exe -m pytest tests\infrastructure\test_runtime_factory.py -q`

Expected: failure because the resolver is absent.

- [ ] **Step 3: Implement the resolver and default YAML block**

```python
values = {"enabled": False, "config_path": None, "provider": None, "model": None, **raw_yaml}
values.update({key: value for key, value in overrides.items() if value is not None})
values["config_path"] = (config_path.parent / values["config_path"]).resolve() if values["config_path"] else None
values["enabled"] = bool(values["enabled"])
```

Add `research.literature_llm` with `enabled: false`, relative `config_path`, and null provider/model to `configs/alpha-factory.yaml`.

- [ ] **Step 4: Run the resolver tests**

Run: `D:\quant-venv\Scripts\python.exe -m pytest tests\infrastructure\test_runtime_factory.py -q`

Expected: PASS.

### Task 2: Wire CLI overrides through to the pipeline

**Files:**
- Modify: `alpha_operator_framework/cli/command_registry.py`
- Modify: `alpha_operator_framework/cli/analysis.py`
- Modify: `alpha_operator_framework/research/pipeline.py`
- Test: `tests/cli/test_command_registry.py`
- Test: `tests/research/test_literature_pipeline.py`

**Interfaces:**
- Consumes `resolve_literature_llm_options` from Task 1.
- Extends `run_literature_research_pipeline` with `llm_config_path: Path | None = None`.

- [ ] **Step 1: Write failing CLI and pipeline tests**

```python
args = build_parser().parse_args(["research", "--paper", "paper.md"])
assert args.use_llm is None
assert args.llm_config is None

args = build_parser().parse_args([
    "research", "--paper", "paper.md", "--use-llm", "false", "--llm-config", "custom.json",
])
assert args.use_llm is False
assert args.llm_config == "custom.json"
```

Mock `pipeline.LLMConfigManager`, enter the LLM path with one parsed idea, and assert it receives the explicit `llm_config_path`.

- [ ] **Step 2: Run the tests and observe failure**

Run: `D:\quant-venv\Scripts\python.exe -m pytest tests\cli\test_command_registry.py tests\research\test_literature_pipeline.py -q`

Expected: failure because `--use-llm` is currently a flag, `--llm-config` is missing, and the pipeline has no path parameter.

- [ ] **Step 3: Implement the wiring**

```python
def _parse_bool(value: str) -> bool:
    normalized = value.lower()
    if normalized not in {"true", "false"}:
        raise argparse.ArgumentTypeError("expected true or false")
    return normalized == "true"

parser.add_argument("--use-llm", type=_parse_bool, default=None)
parser.add_argument("--llm-config")
```

Resolve CLI values before calling the pipeline. Build its client as `UnifiedLLMClient(config_manager=LLMConfigManager(config_path=llm_config_path))` when a path is resolved, otherwise preserve the existing default manager.

- [ ] **Step 4: Run the focused tests**

Run: `D:\quant-venv\Scripts\python.exe -m pytest tests\cli\test_command_registry.py tests\research\test_literature_pipeline.py -q`

Expected: PASS.

### Task 3: Update usage documentation and verify

**Files:**
- Modify: `docs/superpowers/specs/2026-09-02-literature-llm-configuration-design.md`

- [ ] **Step 1: Add the executable example**

```powershell
D:\quant-venv\Scripts\python.exe .\alpha_machine.py research --paper "D:\research\paper.md" --use-llm true --llm-config ".\configs\llm_config.json"
```

- [ ] **Step 2: Run full focused regression**

Run: `D:\quant-venv\Scripts\python.exe -m pytest tests\infrastructure\test_runtime_factory.py tests\cli\test_command_registry.py tests\research\test_literature_pipeline.py -q`

Expected: PASS.

- [ ] **Step 3: Commit**

Run: `git add alpha_operator_framework/infrastructure/runtime_factory.py alpha_operator_framework/cli/command_registry.py alpha_operator_framework/cli/analysis.py alpha_operator_framework/research/pipeline.py configs/alpha-factory.yaml tests/infrastructure/test_runtime_factory.py tests/cli/test_command_registry.py tests/research/test_literature_pipeline.py docs/superpowers/specs/2026-09-02-literature-llm-configuration-design.md && git commit -m "feat: configure literature research LLM"`
