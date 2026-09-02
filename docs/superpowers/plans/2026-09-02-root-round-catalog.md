# Root Round Catalog Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Store each generated candidate catalog once under its root round and isolate platform shards under unique batch IDs.

**Architecture:** `ResearchCycleRequest` carries both `round_id` (the unique batch ID) and required `catalog_round_id` (the root directory). The coordinator writes the full catalog once, then uses suffixed batch IDs while `ResearchCycleService` records only selection decisions into the root catalog.

**Tech Stack:** Python, dataclasses, SQLite repositories, pytest.

## Global Constraints

- No legacy fallback: a production request without `catalog_round_id` is invalid.
- Root catalog uses the unmodified base round ID; batch IDs use `-batch-<sequence>`.
- No child batch may create a `round_candidates` directory.

---

### Task 1: Separate root catalog and batch identifiers

**Files:**
- Modify: `alpha_operator_framework/application/research_cycle.py`
- Modify: `alpha_operator_framework/application/research_loop.py`
- Test: `tests/application/test_research_cycle.py`

**Interfaces:**
- `ResearchCycleRequest.catalog_round_id: str` is required.
- `ResearchCycleService.plan()` writes generated candidates only when the root catalog is missing, and always writes decisions to `catalog_round_id`.

- [ ] **Step 1: Write failing tests**

```python
request = ResearchCycleRequest("root-batch-01", 7, policy, knowledge, candidates, True, "root")
summary = service.plan(request)
assert primary.cataloged == []
assert primary.selections[0][0] == "root"
assert primary.batch_round_id == "root-batch-01"
```

- [ ] **Step 2: Run the test to verify failure**

Run: `D:\quant-venv\Scripts\python.exe -m pytest tests\application\test_research_cycle.py -q`

Expected: FAIL because the request lacks the explicit catalog field and planning catalogs under the batch ID.

- [ ] **Step 3: Implement minimal separation**

Add `catalog_round_id` to `ResearchCycleRequest`. Make the coordinator persist the complete pool with `task_id`, read it with that same value, generate IDs as `f"{base_round_id}-batch-{sequence}"`, and pass `catalog_round_id=base_round_id` into each child request. Remove `catalog_research_candidates()` from `ResearchCycleService.plan()`; retain `record_round_selection(request.catalog_round_id, decisions)`.

- [ ] **Step 4: Run the focused test**

Run: `D:\quant-venv\Scripts\python.exe -m pytest tests\application\test_research_cycle.py -q`

Expected: PASS.

### Task 2: Verify one root catalog across shards

**Files:**
- Modify: `tests/application/test_research_loop.py`

- [ ] **Step 1: Write a failing coordinator test**

```python
summary = coordinator.run(policy, fields, candidates, construction_plan=plan, seed=7, execute=True, base_round_id="root")
assert summary.round_ids == ["root-batch-1", "root-batch-2"]
assert database.catalog_calls == [("root", candidates)]
assert database.selection_round_ids == ["root", "root"]
```

- [ ] **Step 2: Run the test to verify failure**

Run: `D:\quant-venv\Scripts\python.exe -m pytest tests\application\test_research_loop.py -q`

Expected: FAIL because the current coordinator uses `-catalog` and unsuffixed first-batch IDs.

- [ ] **Step 3: Run focused regression**

Run: `D:\quant-venv\Scripts\python.exe -m pytest tests\application\test_research_cycle.py tests\application\test_research_loop.py -q`

Expected: PASS.
