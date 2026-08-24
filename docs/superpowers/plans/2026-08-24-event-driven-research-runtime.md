# Event-Driven Research Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the DDD research cycle event-led, recoverable by a worker, and assembled through one production composition root.

**Architecture:** `ResearchCycleUseCase` becomes a planning command that appends intent events and persists a batch projection. `ResearchBatchWorker` rehydrates a non-terminal batch, executes only unfinished tasks, evaluates and updates knowledge/template projections. `ResearchRuntime` owns all adapters used by both CLI and production script.

**Tech Stack:** Python 3.12, SQLite, existing EventStore, pytest.

## Global Constraints

- Platform submission remains explicit: evidence plus authorization are required before an outbox entry is created.
- The EventStore is the audit ledger; SQLite batch and knowledge tables are rebuildable projections.
- Worker retries must be idempotent by task result and batch state.

---

### Task 1: Persist planning intent without synchronously backtesting

**Files:**
- Modify: `alpha_operator_framework/application/research_cycle.py`
- Test: `tests/application/test_research_cycle.py`

**Interfaces:**
- Produces a `SUBMITTED` `ExperimentBatch` and `SimulationRequested` events for selected tasks.
- Does not invoke `backtest_gateway.run_backtests()`.

- [ ] **Step 1: Write a failing test**

```python
def test_execute_cycle_submits_a_recoverable_batch_without_running_gateway():
    summary = use_case.execute(request)
    assert summary.status == "SUBMITTED"
    assert gateway.calls == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/application/test_research_cycle.py::test_execute_cycle_submits_a_recoverable_batch_without_running_gateway -q`

- [ ] **Step 3: Implement minimal planner-only execution**

```python
if request.execute_platform:
    self._transition(batch, BatchState.SUBMITTED)
    return ResearchCycleSummary("SUBMITTED", round_.round_id, audit)
```

- [ ] **Step 4: Run focused tests**

Run: `python -m pytest tests/application/test_research_cycle.py -q`

### Task 2: Add idempotent event-driven batch worker

**Files:**
- Create: `alpha_operator_framework/application/research_worker.py`
- Test: `tests/application/test_research_worker.py`

**Interfaces:**
- Consumes `EventStore`, experiment/research/knowledge repositories and a backtest gateway.
- Produces terminal batch projection, simulation/validation/decision events, knowledge and template updates.

- [ ] **Step 1: Write failing recovery test**

```python
def test_worker_resumes_submitted_batch_and_runs_only_missing_tasks():
    worker.process_round("round-1")
    assert repository.load_batch("round-1").state is BatchState.EVALUATED
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/application/test_research_worker.py -q`

- [ ] **Step 3: Implement `ResearchBatchWorker.process_round`**

```python
batch = experiment_repository.load_batch(round_id)
tasks = [task for task in batch.tasks.values() if task.task_id not in batch.results]
for result in gateway.run_backtests(tasks):
    batch.record_result(result)
```

- [ ] **Step 4: Run focused tests**

Run: `python -m pytest tests/application/test_research_worker.py -q`

### Task 3: Introduce the shared production composition root

**Files:**
- Create: `alpha_operator_framework/application/research_runtime.py`
- Modify: `alpha_machine.py`, `scripts/prod_pipeline_matrix.sh`
- Test: `tests/application/test_research_runtime.py`

**Interfaces:**
- `ResearchRuntime.create(db_path, ...)` owns EventStore, repositories, telemetry, outbox and worker.
- Both `research-cycle` and `research-worker` CLI commands use the same runtime.

- [ ] **Step 1: Write failing composition test**

```python
def test_runtime_shares_one_database_backed_event_store_and_projections(tmp_path):
    runtime = ResearchRuntime.create(tmp_path / "research.db")
    assert runtime.event_store.is_persistent
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/application/test_research_runtime.py -q`

- [ ] **Step 3: Implement runtime and wire entry points**

```python
runtime = ResearchRuntime.create(db_path, execute_platform=args.execute)
summary = runtime.plan(request)
if args.execute:
    summary = runtime.worker.process_round(summary.round_id)
```

- [ ] **Step 4: Run full suite**

Run: `python -m pytest -q`
