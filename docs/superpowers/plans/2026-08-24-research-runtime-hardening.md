# Research Runtime Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans or superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore test collection and close the identified retry, replay, and submission-evidence gaps without changing public CLI commands.

**Architecture:** Add immutable retry settings to `ResearchPolicy`, emit enough event facts to reconstruct a partially failed batch, and validate evidence records at the existing approval boundary. Keep the current repositories and CLI adapters unchanged except where they must pass the new policy facts.

**Tech Stack:** Python 3.12, pytest, dataclasses, existing event store and SQLAlchemy repositories.

## Global Constraints

- Preserve existing CLI command names and default behavior unless a policy explicitly overrides it.
- Treat only source-backed, unexpired evidence as submission eligible.
- Use test-first red/green cycles; do not change unrelated modules.

---

### Task 1: Restore full test discovery

**Files:**
- Modify: `tests/test_framework.py:1,730`

- [ ] Move the misplaced legacy-machine import to module scope.
- [ ] Run `D:\quant-venv\Scripts\python.exe -m py_compile tests/test_framework.py` and verify exit code 0.

### Task 2: Make batch retry policy explicit

**Files:**
- Modify: `alpha_operator_framework/research/round.py`
- Modify: `alpha_operator_framework/application/research_worker.py`
- Test: `tests/application/test_research_worker.py`

- [ ] Add tests proving policy retry limits and a `Retry-After` exception override fixed exponential delay.
- [ ] Run the new tests and verify they fail against the fixed 3-attempt implementation.
- [ ] Add `max_retry_attempts` and bounded retry delay values to `ResearchPolicy`; make the worker consume them.
- [ ] Run `D:\quant-venv\Scripts\python.exe -m pytest tests/application/test_research_worker.py -q`.

### Task 3: Rebuild durable retry state and knowledge metadata

**Files:**
- Modify: `alpha_operator_framework/application/research_worker.py`
- Modify: `alpha_operator_framework/application/research_rebuild.py`
- Test: `tests/application/test_research_rebuild.py`

- [ ] Add failing tests for replaying retry facts, partial failure state, and snapshot lineage metadata.
- [ ] Emit retry events containing task ids, attempts, retry time, and error; replay them into the batch.
- [ ] Persist snapshot metadata from the event when rebuilding knowledge.
- [ ] Run `D:\quant-venv\Scripts\python.exe -m pytest tests/application/test_research_rebuild.py -q`.

### Task 4: Enforce complete, fresh submission evidence

**Files:**
- Modify: `alpha_operator_framework/domain/evidence.py`
- Test: `tests/test_evidence_boundaries.py`

- [ ] Add failing tests for too-few checks and expired/missing-source evidence records.
- [ ] Require 18 named PASS checks and a source, verification time, expiry time, receipt reference, and summary before approval.
- [ ] Run `D:\quant-venv\Scripts\python.exe -m pytest tests/test_evidence_boundaries.py -q`.

### Task 5: Verify the integrated runtime

**Files:**
- Test: `tests/`

- [ ] Run targeted suites for Tasks 1-4.
- [ ] Run `D:\quant-venv\Scripts\python.exe -m pytest -q` with a fresh temporary cache directory.
- [ ] Inspect `git diff --check` and report only verified results.
