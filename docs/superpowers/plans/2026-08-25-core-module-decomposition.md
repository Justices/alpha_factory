# Core Module Decomposition Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split the three remaining oversized production modules, delete four obsolete compatibility modules, and preserve canonical APIs, SQL behavior, workflow ordering, and pruning results.

**Architecture:** Use explicit mixins for `AlphaRepository`, delegated services for `StratifiedCarpetMiner`, and standalone pruning algorithm modules. Move CLI entry points into canonical packages, migrate every consumer, then delete the obsolete modules.

**Tech Stack:** Python 3.12, SQLite repositories, dataclasses, asyncio, pytest, Ruff, Mypy, quality ratchet.

## Global Constraints

- No SQL text, transaction boundary, algorithm threshold, sort order, retry/poll behavior, or persistence format changes.
- Preserve canonical class/function/method signatures; tests and extensions patch canonical modules.
- Target sizes: `alpha.py` <180 lines and `carpet/miner.py` <300 lines; component files <350 lines.
- `ai_workflow.py`, `carpet_mining.py`, `orchestrator.py`, and `domain/pruning.py` must not exist after migration.
- Do not commit automatically; the controller owns task commits and reviews.

---

### Task 1: Split AlphaRepository by responsibility

**Files:**
- Create: `alpha_operator_framework/database/repositories/alpha_write.py`
- Create: `alpha_operator_framework/database/repositories/alpha_query.py`
- Create: `alpha_operator_framework/database/repositories/alpha_checks.py`
- Create: `alpha_operator_framework/database/repositories/alpha_analytics.py`
- Modify: `alpha_operator_framework/database/repositories/alpha.py`
- Create: `tests/database/test_alpha_repository_compatibility.py`

**Interfaces:**
- Produces: the canonical `AlphaRepository` class composed from four implementation mixins.

- [ ] **Step 1: Write characterization tests before moving methods**

Use a temporary SQLite database to record representative outputs for expression catalog/upsert, stratified sampling with a fixed seed, detail/check persistence, status transitions, top candidates, and dashboard snapshot. Assert rollback behavior by forcing an exception inside a transaction.

- [ ] **Step 2: Run characterization tests against the existing repository**

Expected: tests pass and establish golden result shapes/order; no production edits yet.

- [ ] **Step 3: Move exact method groups into mixins**

```python
class AlphaRepository(
    AlphaWriteMixin,
    AlphaQueryMixin,
    AlphaCheckMixin,
    AlphaAnalyticsMixin,
    BaseRepository,
):
    compute_sha = staticmethod(compute_sha)
    compute_alpha_sha = classmethod(compute_alpha_sha)
```

Write mixin methods with `self: AlphaRepositoryProtocol`; move existing bodies verbatim. Write/query/check/analytics groups follow the method ranges documented by the current file, without changing SQL strings.

- [ ] **Step 4: Verify API and size gates**

Assert canonical imports resolve the same class, method signatures match the frozen snapshot, golden database tests pass, `alpha.py` is below 180 lines, and each component is below 350 lines.

---

### Task 2: Reduce StratifiedCarpetMiner to a coordinator

**Files:**
- Create: `alpha_operator_framework/carpet/field_catalog.py`
- Create: `alpha_operator_framework/carpet/candidate_generation.py`
- Create: `alpha_operator_framework/carpet/sampling.py`
- Modify: `alpha_operator_framework/carpet/miner.py`
- Modify: `alpha_operator_framework/carpet/__init__.py`
- Create: `tests/test_carpet_coordinator_compatibility.py`

**Interfaces:**
- Produces: `load_available_fields`, `generate_candidate_expressions_by_category`, and `sample_cohort` services plus the unchanged miner methods.

- [ ] **Step 1: Write offline golden tests for service boundaries**

Freeze fixed field fixtures, generated expression order/count, category metadata, cohort seed behavior, stage call order, and canonical-module monkeypatch interception. Tests inject database and simulation fakes.

- [ ] **Step 2: Run tests against existing miner**

Expected: golden tests pass; add one structural size test that fails because `miner.py` exceeds 300 lines.

- [ ] **Step 3: Move algorithms and delegate from the coordinator**

```python
class StratifiedCarpetMiner:
    def load_available_fields(self):
        return load_available_fields(self.config, self.db)

    def generate_candidate_expressions_by_category(self, fields):
        return generate_candidate_expressions_by_category(self.config, fields)

    def sample_cohort(self, candidates):
        return sample_cohort(self.config, candidates, self.db)
```

Keep `run()` as the only stage-order owner and keep existing simulation/optimization/distillation service calls unchanged.

- [ ] **Step 4: Verify canonical API and full carpet tests**

Expected: canonical service imports pass, canonical monkeypatch seam works, exact golden order matches, and `miner.py` is below 300 lines.

---

### Task 3: Split pruning algorithms into canonical components

**Files:**
- Create: `alpha_operator_framework/domain/pruning_components/__init__.py`
- Create: `alpha_operator_framework/domain/pruning_components/semantic.py`
- Create: `alpha_operator_framework/domain/pruning_components/field_topk.py`
- Create: `alpha_operator_framework/domain/pruning_components/self_correlation.py`
- Create: `alpha_operator_framework/domain/pruning_components/correlation.py`
- Create: `alpha_operator_framework/domain/pruning_components/canonical.py`
- Create: `alpha_operator_framework/domain/pruning_components/sandbox.py`
- Modify: `alpha_operator_framework/domain/pruning.py` (temporary forwarding layer deleted in Task 4)
- Create: `tests/test_pruning_components.py`

**Interfaces:**
- Produces: explicit component exports with unchanged function and config signatures.

- [ ] **Step 1: Write result-equivalence and monkeypatch tests**

Cover semantic classification/pruning, field extraction, stable field-top-k ties, self-correlation with mocked PnL fetching, correlation pruning, canonical deduplication, and sandbox filtering. Patch only canonical component modules.

- [ ] **Step 2: Run existing and new pruning tests before moving code**

Expected: behavior tests pass; structural size test fails because `pruning.py` still contains implementations.

- [ ] **Step 3: Move complete algorithm groups verbatim**

The component package index contains explicit canonical exports:

```python
from alpha_operator_framework.domain.pruning_components.semantic import (
    SemanticPruneConfig, classify_field, semantic_prune_fields,
    extract_field_ids, extract_fields,
)
```

Keep only explicit forwarding imports in `domain/pruning.py` during this task so the intermediate tree remains green. Do not create a same-name `domain/pruning/` directory.

- [ ] **Step 4: Verify async and deterministic behavior**

Run pruning, submission, orchestration, and framework tests; assert zero platform calls outside injected fakes and the temporary forwarding file is below 150 lines.

---

### Task 4: Migrate every consumer and delete compatibility modules

**Files:**
- Modify: `alpha_operator_framework/loop.py`
- Modify: `alpha_operator_framework/application/autopilot.py`
- Modify: `alpha_operator_framework/cli/analysis.py`
- Modify: every additional production file found by the facade import scan
- Create: `alpha_operator_framework/orchestration/__main__.py`
- Create: `alpha_operator_framework/workflow/__main__.py`
- Delete: `alpha_operator_framework/ai_workflow.py`
- Delete: `alpha_operator_framework/carpet_mining.py`
- Delete: `alpha_operator_framework/orchestrator.py`
- Delete: `alpha_operator_framework/domain/pruning.py`
- Modify: `pyproject.toml`
- Modify: `quality-baseline.json`
- Delete: `tests/test_carpet_compatibility.py`
- Delete: `tests/test_workflow_compatibility.py`
- Delete: `tests/test_orchestration_compatibility.py`
- Modify: `tests/test_antonyms.py`
- Modify: `tests/test_code_cleanup.py`
- Modify: `tests/test_dual_axis_sampler.py`
- Modify: `tests/test_framework.py`
- Modify: `tests/test_loop.py`
- Modify: `tests/test_template_distillation_loop.py`
- Modify: `tests/test_dependency_direction.py`

**Interfaces:**
- Consumes: canonical `workflow`, `carpet`, `orchestration`, and `pruning_components` APIs.
- Produces: canonical CLI entry points and an AST/file rule preventing obsolete modules from returning.

- [ ] **Step 1: Extend dependency tests and run RED**

Reject every import from `alpha_operator_framework.ai_workflow`, `carpet_mining`, `orchestrator`, and `domain.pruning`. Assert the four module files do not exist.

- [ ] **Step 2: Replace imports only**

Examples:

```python
from alpha_operator_framework.workflow import SurveyConfig, run_survey_with_fields
from alpha_operator_framework.carpet import run_stratified_carpet_mining
from alpha_operator_framework.domain.pruning_components.semantic import semantic_prune_fields
```

Move `orchestrator.py` parser/main to `orchestration/__main__.py` and `ai_workflow.py` CLI main to `workflow/__main__.py`; update module invocation tests. Do not rewrite calling logic.

- [ ] **Step 3: Run final integration verification**

Run dependency tests, all repository/carpet/pruning/workflow tests, full pytest+coverage, strict Ruff/Mypy, full quality ratchet, compileall, CLI help, import latency benchmark, and diff check. Expected: every command passes and all size targets hold.
