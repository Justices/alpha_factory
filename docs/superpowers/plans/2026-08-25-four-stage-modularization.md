# Alpha Factory Four-Stage Modularization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make routing, dependencies, quality checks, orchestration, carpet mining, and AI workflow independently maintainable without breaking public behavior.

**Architecture:** Use a compatibility-preserving strangler approach. New focused packages own implementations while existing modules re-export stable symbols.

**Tech Stack:** Python 3.12, argparse, pytest, Ruff, Mypy.

## Global Constraints

- Preserve every current CLI command, default, dry-run guard, and public import.
- Do not issue real BRAIN platform requests during tests.
- Do not rewrite business algorithms while moving them.
- Use explicit exports; no wildcard imports.
- Do not commit automatically.

---

### Task 1: Declarative command registry

**Files:**
- Create: `alpha_operator_framework/cli/command_registry.py`
- Create: `tests/cli/test_command_registry.py`
- Modify: `alpha_operator_framework/cli/router.py`
- Modify: `tests/cli/test_alpha_machine_entry.py`

**Interfaces:**
- Produces: frozen `CommandSpec(name, domain, configure, handler)` and `command_specs()`.

- [ ] Add a failing test that every specification has a unique name, valid domain, callable handler, and parser route.
- [ ] Run `pytest tests/cli/test_command_registry.py tests/cli/test_alpha_machine_entry.py -q` and confirm the registry is missing.
- [ ] Move parser configuration into named configure functions and construct the parser only by iterating `command_specs()`.
- [ ] Generate `command_domains()` from the same specifications.
- [ ] Re-run the focused tests and `python alpha_machine.py --help`.

### Task 2: Remove internal root-entry imports

**Files:**
- Modify: `alpha_operator_framework/ai_workflow.py`
- Modify: `alpha_operator_framework/orchestrator.py`
- Modify: `alpha_operator_framework/cache/datafields.py`
- Modify: `alpha_operator_framework/platform/datafield_ingest.py`
- Modify: `alpha_operator_framework/platform/alpha_source.py`
- Create: `tests/test_dependency_direction.py`

**Interfaces:**
- Consumes: direct functions from `cli.simulation`, `cli.field_pipeline`, `platform.datafields`, and `cnhkmcp.untracked.platform_functions`.

- [ ] Add a failing AST test forbidding production imports of `alpha_machine` below the root entry.
- [ ] Replace lazy root imports with direct leaf-module imports while preserving call signatures.
- [ ] Run dependency, workflow, orchestration, and platform tests.

### Task 3: Add the quality stack

**Files:**
- Create: `pyproject.toml`
- Create: `requirements-dev.txt`
- Modify: `.github/workflows/recovery-drill.yml`
- Create: `tests/test_quality_configuration.py`

**Interfaces:**
- Produces: `pytest`, `ruff check`, and scoped `mypy` commands.

- [ ] Add a failing test requiring pytest markers, Ruff target Python 3.12, and Mypy package scope.
- [ ] Add tool configuration and pinned development dependencies.
- [ ] Extend CI with syntax, Ruff, scoped Mypy, and full pytest commands.
- [ ] Run configuration tests and all locally available tools; report unavailable tools as skipped.

### Task 4: Split orchestrator

**Files:**
- Create: `alpha_operator_framework/orchestration/__init__.py`
- Create: `alpha_operator_framework/orchestration/survey.py`
- Create: `alpha_operator_framework/orchestration/deepen.py`
- Create: `alpha_operator_framework/orchestration/submission.py`
- Create: `alpha_operator_framework/orchestration/commands.py`
- Modify: `alpha_operator_framework/orchestrator.py`
- Create: `tests/test_orchestration_compatibility.py`

**Interfaces:**
- Produces: `cmd_survey`, `cmd_deepen`, `cmd_submit`, `cmd_run_all`; old module re-exports them.

- [ ] Add failing identity/behavior tests for old and new imports.
- [ ] Move functions with their private helpers to the owning module and use explicit imports between stages.
- [ ] Reduce `orchestrator.py` to parser construction, `main`, and compatibility exports.
- [ ] Run orchestration and framework tests.

### Task 5: Split carpet mining

**Files:**
- Create: `alpha_operator_framework/carpet/__init__.py`
- Create: `alpha_operator_framework/carpet/models.py`
- Create: `alpha_operator_framework/carpet/miner.py`
- Create: `alpha_operator_framework/carpet/simulation.py`
- Create: `alpha_operator_framework/carpet/optimization.py`
- Create: `alpha_operator_framework/carpet/distillation.py`
- Modify: `alpha_operator_framework/carpet_mining.py`
- Create: `tests/test_carpet_compatibility.py`

**Interfaces:**
- Produces: unchanged `CarpetMiningConfig`, `CarpetMiningResult`, `StratifiedCarpetMiner`, and `run_stratified_carpet_mining` imports.

- [ ] Add failing compatibility tests for public symbols and dry-run results.
- [ ] Move models first, then simulation, optimization, and distillation stages.
- [ ] Keep `StratifiedCarpetMiner` as a coordinator using the extracted services.
- [ ] Convert the old module to explicit re-exports and run carpet/template tests.

### Task 6: Split AI workflow

**Files:**
- Create: `alpha_operator_framework/workflow/__init__.py`
- Create: `alpha_operator_framework/workflow/models.py`
- Create: `alpha_operator_framework/workflow/branches.py`
- Create: `alpha_operator_framework/workflow/survey.py`
- Create: `alpha_operator_framework/workflow/full.py`
- Modify: `alpha_operator_framework/ai_workflow.py`
- Modify: `alpha_operator_framework/__init__.py`
- Create: `tests/test_workflow_compatibility.py`

**Interfaces:**
- Produces: unchanged workflow configs/results and public run functions under old and new module paths.

- [ ] Add failing compatibility tests for symbol identity and a mocked survey flow.
- [ ] Move dataclasses, branch logic, survey logic, and full-flow logic in that order.
- [ ] Convert the old module to explicit re-exports plus its CLI `main`.
- [ ] Run workflow, loop, antonym, package-export, and full pytest suites.

### Task 7: Final verification

**Files:**
- Test: `tests/`

- [ ] Run `python -m compileall -q alpha_operator_framework alpha_machine.py`.
- [ ] Run `ruff check .` and scoped `mypy` when installed.
- [ ] Run the complete pytest suite, splitting only for the known command execution window.
- [ ] Run `git diff --check`, inspect compatibility modules, and report uncommitted files.
