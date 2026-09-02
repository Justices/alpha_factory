# Implement literature research LLM configuration

## Goal

Implement the approved design in `docs/superpowers/specs/2026-09-02-literature-llm-configuration-design.md`: runtime YAML controls literature-pipeline LLM enablement and LLM JSON path; explicit CLI values override it.

## Allowed Scope

- `alpha_operator_framework/infrastructure/runtime_factory.py`
- `alpha_operator_framework/cli/command_registry.py`
- `alpha_operator_framework/cli/analysis.py`
- `alpha_operator_framework/research/pipeline.py`
- `configs/alpha-factory.yaml`
- `tests/infrastructure/test_runtime_factory.py`
- `tests/cli/test_command_registry.py`
- `tests/research/test_literature_pipeline.py`
- `docs/superpowers/specs/2026-09-02-literature-llm-configuration-design.md`

## Forbidden Actions

- Do not modify `research-cycle`, construction strategies, database schema, credentials, or any unrelated feature.
- Do not run platform simulations or submit Alphas.
- Do not commit, reset, rebase, or discard existing changes.
- Do not create nested delegates or broaden the task.

## Acceptance Criteria

- `research.literature_llm` accepts `enabled`, `config_path`, optional `provider`, and optional `model`.
- Missing the YAML block preserves disabled LLM behavior.
- `research --use-llm true|false` is tri-state, with omitted option represented by `None`.
- `research --llm-config <path>` is supported.
- Explicit CLI `use_llm`, JSON path, provider, and model override YAML values.
- Relative LLM JSON paths resolve relative to the runtime YAML file.
- The chosen LLM JSON path is passed to `LLMConfigManager` in `run_literature_research_pipeline`.
- Focused tests pass and the approved design doc contains an executable command example.

## Verification

1. Write focused tests before production edits and run them once to demonstrate the expected failure.
2. Run `D:\quant-venv\Scripts\python.exe -m pytest tests\infrastructure\test_runtime_factory.py tests\cli\test_command_registry.py tests\research\test_literature_pipeline.py -q` after implementation.
3. Run `git diff --check` after implementation.

## Report Requirements

Use exactly these headings, in this order: Status; Role; Summary; Changed Files; Verification; Findings; Final Result; Risks Or Follow-ups.

`Status` and `Final Result` must be identical and one of `DONE`, `DONE_WITH_CONCERNS`, `NEEDS_CONTEXT`, `BLOCKED`, or `FAIL`. List each actual verification command and outcome. Report test-first evidence and do not include raw credentials.
