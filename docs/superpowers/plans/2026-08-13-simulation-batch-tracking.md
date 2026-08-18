# Simulation Batch Tracking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Record BRAIN multi-simulation batches and results, then poll platform batches asynchronously and resumably.

**Architecture:** SQLite batch/result tables are managed by `AlphaDatabase`. A new simulation tracker submits a batch once, persists its platform location, and polls children until each row reaches a terminal state.

**Tech Stack:** Python stdlib, SQLite, requests-backed BRAIN client.

## Global Constraints

- `alpha_details` remains the latest Alpha snapshot only.
- Existing platform batch IDs must be resumed, never resubmitted.
- Result payloads must be JSON-safe before database persistence.

---

### Task 1: Persist batch and result lifecycle

**Files:**
- Modify: `alpha_operator_framework/database/models.py`
- Modify: `alpha_operator_framework/database/repository.py`
- Create: `alpha_operator_framework/database/schema/003_simulation_batches.sql`
- Test: `tests/test_framework.py`

- [ ] Write a failing SQLite lifecycle test for create batch, attach platform ID, update a result, and complete the batch.
- [ ] Add tables, models, repository lifecycle methods, and indexes.
- [ ] Run `python tests/test_framework.py`.

### Task 2: Submit and poll asynchronously

**Files:**
- Create: `alpha_operator_framework/simulation_tracker.py`
- Modify: `alpha_machine.py`
- Test: `tests/test_framework.py`

- [ ] Write failing tests against injected submit/get/detail callables.
- [ ] Implement submit-once and poll/resume state transitions.
- [ ] Keep CLI-compatible `simulate` behavior while persisting batches.
- [ ] Run full tests and compile checks.
