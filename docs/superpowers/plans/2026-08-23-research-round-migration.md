# Research-Round Domain Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the mechanically layered `ddd/` package with the three real domain modules: research, experiment, and knowledge.

**Architecture:** `ResearchRound` owns candidate construction, selection, and pruning. `ExperimentBatch` owns backtest execution and result evaluation. `KnowledgeBase` owns evidence, distillation, and submission approval. Root-level `application/` composes their ports; root-level `infrastructure/` adapts existing SQLite, local-field, and BRAIN capabilities.

**Tech Stack:** Python 3.10+, dataclasses, existing AST module, SQLite, pytest.

## Global Constraints

- The existing `alpha_operator_framework/research/` literature tools remain; new research-round modules are added beside them and must not change the literature pipeline.
- No new code may import `alpha_operator_framework.ddd`.
- Domain modules are pure: no SQLite, BRAIN, HTTP, filesystem, clock, or ambient random imports.
- Dry-run creates a `ResearchRound` plan only; only `--execute` may construct a BRAIN backtest gateway.
- Keep current working-tree changes intact until their replacement is tested; remove `ddd/` only in the final migration task.

---

### Task 1: Establish the ResearchRound aggregate and pure policies

**Files:**

- Create: `alpha_operator_framework/research/round.py`
- Create: `alpha_operator_framework/research/selection.py`
- Create: `alpha_operator_framework/research/pruning.py`
- Create: `tests/research/test_research_round.py`
- Create: `tests/research/test_selection_and_pruning.py`

**Interfaces:**

- Produces `ResearchPolicy`, `ResearchRound`, `Candidate`, `KnowledgeSnapshot`, `SelectionDecision`, and `PruningDecision`.
- `select_candidates(round, snapshot, random_source) -> list[SelectionDecision]`.
- `pre_prune(round) -> list[PruningDecision]`.

- [ ] **Step 1: Write failing aggregate tests**

```python
def test_research_round_replays_same_decisions_for_same_snapshots_and_seed():
    first = build_round(seed=7).select(snapshot, DeterministicRandomSource(7))
    second = build_round(seed=7).select(snapshot, DeterministicRandomSource(7))
    assert first == second

def test_pre_pruning_rejects_ast_equivalent_candidates_with_reason():
    decisions = pre_prune(round_with("rank(rank(close))", "rank(close)"))
    assert decisions[-1].reason_code == "AST_CANONICAL_DUPLICATE"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/research/test_research_round.py tests/research/test_selection_and_pruning.py -q`

Expected: FAIL because the aggregate does not exist.

- [ ] **Step 3: Implement the pure aggregate**

Use `validate_expression` and `to_canonical_string` from `domain.ast`. Keep complete immutable policy values: market setting, all budgets, field/operator/template/novelty/uncertainty weights, quotas, ordered rules, and seed. Implement weighted stratified, diversity, and Thompson/UCB selection as pure strategy objects that return score components and reasons; NSGA-style mutation must not appear here.

- [ ] **Step 4: Run focused tests**

Run: `python -m pytest tests/research/test_research_round.py tests/research/test_selection_and_pruning.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

Run: `git add alpha_operator_framework/research tests/research; git commit -m "feat: add research round aggregate"`

### Task 2: Build ExperimentBatch around real backtest facts

**Files:**

- Create: `alpha_operator_framework/experiment/__init__.py`
- Create: `alpha_operator_framework/experiment/models.py`
- Create: `alpha_operator_framework/experiment/evaluation.py`
- Create: `alpha_operator_framework/experiment/mutation.py`
- Create: `tests/experiment/test_batch_lifecycle.py`
- Create: `tests/experiment/test_mutation.py`

**Interfaces:**

- `ExperimentBatch.create_tasks(cohort, policy) -> list[BacktestTask]`.
- `evaluate_batch(batch) -> list[EvaluationRecord]`.
- `propose_mutations(batch, max_proposals, random_source) -> list[MutationProposal]`.

- [ ] **Step 1: Write failing experiment tests**

```python
def test_only_evaluated_non_pruned_results_are_mutation_parents():
    proposals = propose_mutations(batch_with_ready_and_pruned_results(), 2, rng)
    assert {proposal.parent_task_id for proposal in proposals} == {"ready"}

def test_backtest_task_keeps_candidate_lineage_and_idempotency_key():
    task = ExperimentBatch("batch", "key").create_tasks([candidate], policy)[0]
    assert task.candidate_id == candidate.candidate_id
    assert task.idempotency_key
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/experiment/test_batch_lifecycle.py tests/experiment/test_mutation.py -q`

Expected: FAIL because the experiment module does not exist.

- [ ] **Step 3: Implement experiment domain**

Normalize platform results into immutable result records. Apply post-backtest pruning and hard evaluation before Pareto ranking. Implement non-dominated ranking over Sharpe, Fitness, turnover, margin, and correlation where available; mutation creates AST-valid lineage-bearing proposals only from rank-1 non-pruned results.

- [ ] **Step 4: Run focused tests**

Run: `python -m pytest tests/experiment/test_batch_lifecycle.py tests/experiment/test_mutation.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

Run: `git add alpha_operator_framework/experiment tests/experiment; git commit -m "feat: add experiment batch domain"`

### Task 3: Make KnowledgeBase the only feedback owner

**Files:**

- Create: `alpha_operator_framework/knowledge/__init__.py`
- Create: `alpha_operator_framework/knowledge/models.py`
- Create: `alpha_operator_framework/knowledge/distillation.py`
- Create: `alpha_operator_framework/knowledge/submission.py`
- Create: `tests/knowledge/test_feedback.py`
- Create: `tests/knowledge/test_submission.py`

**Interfaces:**

- `KnowledgeBase.apply_batch(batch, pruning_decisions) -> KnowledgeSnapshot`.
- `KnowledgeSnapshot` is the only feedback value accepted by selection policies.
- `SubmissionCase.approve(evidence) -> ApprovalDecision`.

- [ ] **Step 1: Write failing feedback and approval tests**

```python
def test_pruned_template_is_unavailable_in_next_snapshot():
    snapshot = knowledge.apply_batch(batch, [pruned_template_decision])
    assert snapshot.rejects(template_candidate)

def test_submission_fails_closed_without_verified_platform_evidence():
    assert SubmissionCase.from_result(result_without_oos).approve().is_approved is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/knowledge/test_feedback.py tests/knowledge/test_submission.py -q`

Expected: FAIL because the knowledge module does not exist.

- [ ] **Step 3: Implement knowledge domain**

Aggregate field/operator/template/pair evidence from results and pruning reasons. Distill only qualified expressions. Version each snapshot, preserve source batch IDs, and expose weighted evidence without repositories. Submission approval requires verified live platform evidence and rejects when the live submission adapter is absent.

- [ ] **Step 4: Run focused tests**

Run: `python -m pytest tests/knowledge/test_feedback.py tests/knowledge/test_submission.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

Run: `git add alpha_operator_framework/knowledge tests/knowledge; git commit -m "feat: add knowledge feedback domain"`

### Task 4: Introduce ports and move technical code to adapters

**Files:**

- Create: `alpha_operator_framework/application/ports.py`
- Create: `alpha_operator_framework/infrastructure/__init__.py`
- Create: `alpha_operator_framework/infrastructure/sqlite.py`
- Create: `alpha_operator_framework/infrastructure/brain.py`
- Create: `alpha_operator_framework/infrastructure/local_fields.py`
- Create: `tests/infrastructure/test_sqlite_replay.py`
- Create: `tests/infrastructure/test_execution_guard.py`

**Interfaces:** `FieldCatalog`, `ResearchRepository`, `ExperimentRepository`, `KnowledgeRepository`, `BacktestGateway`, and `SubmissionGateway`.

- [ ] **Step 1: Write failing adapter tests**

```python
def test_dry_run_does_not_construct_brain_gateway():
    dependencies = build_dependencies(execute_platform=False)
    assert isinstance(dependencies.backtest_gateway, DryRunGateway)

def test_sqlite_reloads_complete_research_round_snapshot(tmp_path):
    repository.save_round(round)
    assert repository.load_round(round.round_id) == round
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/infrastructure/test_sqlite_replay.py tests/infrastructure/test_execution_guard.py -q`

Expected: FAIL because the adapters do not exist.

- [ ] **Step 3: Implement adapters by wrapping current capabilities**

Reuse `platform.local_fields`, `platform.platform_simulator`, and database connection primitives internally; do not expose their types to domain modules. Persist full snapshots plus append-only selection, pruning, and evaluation facts. The live submission adapter must raise a clear unsupported error until its real endpoint is implemented.

- [ ] **Step 4: Run focused tests**

Run: `python -m pytest tests/infrastructure/test_sqlite_replay.py tests/infrastructure/test_execution_guard.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

Run: `git add alpha_operator_framework/application/ports.py alpha_operator_framework/infrastructure tests/infrastructure; git commit -m "feat: add research infrastructure adapters"`

### Task 5: Compose the new cycle and replace the legacy DDD entry

**Files:**

- Create: `alpha_operator_framework/application/__init__.py`
- Create: `alpha_operator_framework/application/research_cycle.py`
- Modify: `alpha_machine.py`
- Create: `tests/application/test_research_cycle.py`
- Modify: `README.md`
- Modify: `QUICKSTART.md`

**Interfaces:** `ResearchCycleUseCase.execute(request) -> ResearchCycleSummary`.

- [ ] **Step 1: Write failing end-to-end dry-run test**

```python
def test_cycle_returns_replayable_planned_round_without_live_gateway(dependencies):
    summary = ResearchCycleUseCase(dependencies).execute(request(execute_platform=False, seed=9))
    assert summary.status == "PLANNED"
    assert summary.selection_audit
    assert dependencies.live_gateway_calls == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/application/test_research_cycle.py -q`

Expected: FAIL because the new use case does not exist.

- [ ] **Step 3: Implement composition only**

The use case performs the exact lifecycle from the design doc and delegates all decisions to the domain modules. The CLI maps only arguments and output. Update docs to describe three modules, dry-run safety, and the unavailable real submit adapter.

- [ ] **Step 4: Run focused and full tests**

Run: `python -m pytest tests/application/test_research_cycle.py -q`

Expected: PASS.

Run: `python -m pytest -q`

Expected: PASS.

- [ ] **Step 5: Commit**

Run: `git add alpha_machine.py alpha_operator_framework/application README.md QUICKSTART.md tests/application; git commit -m "feat: add research round application cycle"`

### Task 6: Remove the mechanical DDD package

**Files:**

- Delete: `alpha_operator_framework/ddd/`
- Delete: `tests/ddd/`
- Modify: all imports identified by `rg -n "alpha_operator_framework\.ddd"`
- Create: `tests/architecture/test_dependency_boundaries.py`

- [ ] **Step 1: Write the failing boundary test**

```python
def test_no_active_source_imports_the_removed_ddd_package():
    assert find_python_imports("alpha_operator_framework.ddd") == []

def test_domain_modules_do_not_import_infrastructure():
    assert forbidden_imports(["research", "experiment", "knowledge"]) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/architecture/test_dependency_boundaries.py -q`

Expected: FAIL while the legacy package is still active.

- [ ] **Step 3: Remove only after the new cycle passes**

Delete the `ddd/` package and DDD tests, remove its CLI path, and update exports. Do not retain shims or dual-write code.

- [ ] **Step 4: Verify final migration**

Run: `python -m pytest -q`

Expected: PASS.

Run: `rg -n "alpha_operator_framework\.ddd|ddd/" alpha_operator_framework tests alpha_machine.py`

Expected: no active-source matches.

- [ ] **Step 5: Commit**

Run: `git add -A alpha_operator_framework tests alpha_machine.py README.md QUICKSTART.md; git commit -m "refactor: replace mechanical ddd package"`

## Self-Review

- The plan maps every acceptance criterion in the revised design to a testable task.
- The existing literature research package is preserved; its names are not overwritten.
- The `ddd/` removal happens last, after a fully tested replacement exists.
