# Production Research Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a restart-safe, configurable research loop whose execution, optimization, learning, and submission decisions are auditable.

**Architecture:** The three current domain modules remain the only decision owners. Typed application ports isolate SQLite, BRAIN, outbox, and telemetry; each batch state transition is persisted as an append-only fact.

**Tech Stack:** Python 3.12, dataclasses, SQLite, pytest, existing BRAIN simulator.

## Global Constraints

- No domain module imports SQLite, BRAIN, HTTP, filesystem, clocks, or ambient random state.
- All behavior changes are test-first; live execution requires explicit `--execute`.
- Every persisted record carries a batch/round id, idempotency key, policy version, and timestamp supplied by infrastructure.
- Submission remains disabled until its outbox adapter is complete.

---

### Task 1: Durable ExperimentBatch State Machine

**Files:**
- Modify: `alpha_operator_framework/experiment/models.py`
- Create: `alpha_operator_framework/experiment/lifecycle.py`
- Create: `tests/experiment/test_batch_state_machine.py`

**Interfaces:** `transition(batch, event) -> BatchTransition`; states are `PLANNED`, `SUBMITTED`, `RUNNING`, `COMPLETED`, `PARTIAL_FAILED`, `FAILED`, `EVALUATED`.

- [ ] **Step 1: Write failing state-transition tests**

```python
def test_batch_rejects_transition_that_skips_submission():
    assert transition(batch, "COMPLETED").accepted is False

def test_batch_replay_keeps_task_idempotency_keys():
    assert replayed.tasks == batch.tasks
```

- [ ] **Step 2: Run `python -m pytest tests/experiment/test_batch_state_machine.py -q`**

Expected: FAIL because lifecycle types do not exist.

- [ ] **Step 3: Add immutable `BatchTransition` and transition table**

```python
def transition(batch: ExperimentBatch, target: BatchState) -> BatchTransition:
    return BatchTransition(batch.batch_id, batch.state, target, target in ALLOWED[batch.state])
```

- [ ] **Step 4: Run focused tests; commit `feat: add durable experiment lifecycle`**

### Task 2: Persist Batch Facts and Resume Execution

**Files:**
- Create: `alpha_operator_framework/application/ports.py`
- Modify: `alpha_operator_framework/infrastructure/sqlite.py`
- Modify: `alpha_operator_framework/application/research_cycle.py`
- Create: `tests/infrastructure/test_experiment_replay.py`
- Modify: `tests/application/test_research_cycle.py`

**Interfaces:** `ExperimentRepository.save_batch`, `load_batch`, `append_transition`; `ResearchCycleUseCase.execute` resumes an existing non-terminal batch by idempotency key.

- [ ] **Step 1: Write failing replay test**

```python
def test_repository_replays_results_and_transitions(tmp_path):
    repository.save_batch(completed_batch)
    assert repository.load_batch("batch") == completed_batch
```

- [ ] **Step 2: Run `python -m pytest tests/infrastructure/test_experiment_replay.py -q`**

Expected: FAIL because `ExperimentRepository` is absent.

- [ ] **Step 3: Implement SQLite payload persistence and typed ports; inject repository into use case**

```python
class ExperimentRepository(Protocol):
    def save_batch(self, batch: ExperimentBatch) -> None: ...
    def load_batch(self, batch_id: str) -> ExperimentBatch | None: ...
```

- [ ] **Step 4: Run focused tests; commit `feat: persist and resume experiment batches`**

### Task 3: Evaluate, Rank, and Feed Mutation Forward

**Files:**
- Modify: `alpha_operator_framework/experiment/evaluation.py`
- Modify: `alpha_operator_framework/experiment/mutation.py`
- Modify: `alpha_operator_framework/application/research_cycle.py`
- Create: `tests/experiment/test_pareto_evaluation.py`
- Modify: `tests/application/test_research_cycle.py`

**Interfaces:** `evaluate_batch(batch, policy) -> list[EvaluationRecord]`; `propose_mutations` returns only rank-1, non-pruned parents.

- [ ] **Step 1: Write failing dominance test**

```python
def test_dominated_result_receives_lower_pareto_rank():
    assert evaluate_batch(batch)["weak"].pareto_rank > 1
```

- [ ] **Step 2: Run `python -m pytest tests/experiment/test_pareto_evaluation.py -q`**

Expected: FAIL because batch ranking is not implemented.

- [ ] **Step 3: Implement hard gates then non-dominated rank over Sharpe, fitness, turnover, and margin; pass proposals into next-round request**

- [ ] **Step 4: Run focused tests; commit `feat: add pareto evaluation and mutation handoff`**

### Task 4: Versioned Policy and Multiple Selectors

**Files:**
- Modify: `alpha_operator_framework/research/round.py`
- Modify: `alpha_operator_framework/research/selection.py`
- Create: `alpha_operator_framework/research/policy.py`
- Modify: `alpha_machine.py`
- Create: `tests/research/test_policy_selection.py`

**Interfaces:** `PolicySnapshot.from_mapping(mapping)`, `build_selector(policy)`, and policy-selected `weighted_stratified`, `thompson`, `ucb`, `diversity` selectors.

- [ ] **Step 1: Write failing configuration and deterministic selector tests**
- [ ] **Step 2: Run `python -m pytest tests/research/test_policy_selection.py -q`**
- [ ] **Step 3: Implement immutable policy versioning and selector factory; persist the snapshot with each round**
- [ ] **Step 4: Run focused tests; commit `feat: add versioned exploration policies`**

### Task 5: Knowledge Evidence, Template Promotion, and Submission Outbox

**Files:**
- Modify: `alpha_operator_framework/knowledge/models.py`
- Modify: `alpha_operator_framework/knowledge/distillation.py`
- Modify: `alpha_operator_framework/knowledge/submission.py`
- Create: `alpha_operator_framework/infrastructure/submission.py`
- Create: `tests/knowledge/test_evidence_aggregation.py`
- Create: `tests/infrastructure/test_submission_outbox.py`

**Interfaces:** `KnowledgeBase.apply_batch` updates field/operator/template/pair evidence; `SubmissionGateway.enqueue(case)` accepts only an approved case and raises `SubmissionNotAvailable` until the real endpoint exists.

- [ ] **Step 1: Write failing operator evidence and rejected-outbox tests**
- [ ] **Step 2: Run the two focused test files**
- [ ] **Step 3: Implement evidence aggregation, promotion thresholds, append-only outbox record, and fail-closed gateway**
- [ ] **Step 4: Run focused tests; commit `feat: add governed knowledge and submission outbox`**

### Task 6: Operational Metrics and Release Verification

**Files:**
- Create: `alpha_operator_framework/infrastructure/telemetry.py`
- Create: `tests/infrastructure/test_telemetry.py`
- Modify: `README.md`
- Modify: `QUICKSTART.md`

**Interfaces:** `ResearchTelemetry.record_batch(batch, transition)` emits counts for state, retry, pruning reason, and quota consumption without domain imports.

- [ ] **Step 1: Write failing telemetry test**
- [ ] **Step 2: Implement in-memory telemetry adapter and wire it at composition root**
- [ ] **Step 3: Run `python -m pytest -q`; verify no active imports from legacy `ddd`**
- [ ] **Step 4: Commit `feat: add production research-loop operations`**
