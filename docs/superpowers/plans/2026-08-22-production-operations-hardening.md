# Production Operations Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fail closed before quota is consumed and make stale platform simulations operationally visible from the production CLI.

**Architecture:** Keep `SimulationTracker` as the sole authority for batch state. The CLI performs one stored-Location poll and optionally runs the existing non-resubmitting TTL watchdog; field preprocessing reduces EVENT and VECTOR inputs to scalar expressions before any time-series operator is generated.

**Tech Stack:** Python 3.12, pytest, SQLite/WAL, WorldQuant BRAIN REST gateway.

## Global Constraints

- Do not submit, retry, or cancel any real BRAIN simulation.
- A persisted platform Location is immutable; a stale batch is marked `stalled` and escalated, never reposted.
- Only scalar expressions may enter the first-order factory.
- `submission_ready` remains dependent on explicit locked-OOS evidence.

---

### Task 1: Expose the stale-batch watchdog through `poll-simulation`

**Files:**
- Modify: `alpha_machine.py`
- Modify: `tests/test_framework.py`

**Interfaces:**
- Consumes: `SimulationTracker.mark_stalled_if_expired(batch_id, max_idle_seconds, now=None) -> bool`
- Produces: `poll_simulation_batch(..., stale_after_seconds: float | None = None) -> dict[str, Any]`

- [ ] Write a failing test that calls the polling helper with a TTL and asserts the helper passes that TTL to the tracker after a poll.
- [ ] Run `python -m pytest tests/test_framework.py::test_alpha_machine_poll_command_marks_stale_batch_when_ttl_is_set -q` and observe failure because the helper has no TTL argument.
- [ ] Add optional `--stale-after-seconds` (positive float) to `poll-simulation`; before a stored-Location poll, call `mark_stalled_if_expired` and return the persisted `stalled` batch when it expires.
- [ ] Re-run the focused test and verify it passes.

### Task 2: Reduce EVENT inputs before factor generation

**Files:**
- Modify: `alpha_machine.py`
- Modify: `alpha_operator_framework/domain/fields.py`
- Modify: `tests/test_framework.py`

**Interfaces:**
- Consumes: `FieldSpec.type` values `MATRIX`, `VECTOR`, `EVENT`, `GROUP`.
- Produces: scalar expressions; EVENT expressions use `vec_avg(field_id)` before `ts_backfill`.

- [ ] Write failing tests asserting an EVENT field produces exactly one expression containing `vec_avg(<field>)` in both preprocessing entry points.
- [ ] Run the focused tests and observe failure because EVENT fields are currently discarded.
- [ ] Treat EVENT as vector-like but deterministically use `vec_avg` only; preserve existing MATRIX, VECTOR, and GROUP behavior.
- [ ] Re-run the focused tests and verify they pass.

### Task 3: Prevent unattended autopilot from implying a submission-ready route

**Files:**
- Modify: `alpha_machine.py`
- Modify: `tests/test_auto_pilot.py`

**Interfaces:**
- Consumes: `SubmissionApprovalEngine.evaluate(..., evidence_level=PLATFORM_IS, oos_metrics=None)`.
- Produces: `needs_optimization` for an IS-only candidate, never `submission_ready`.

- [ ] Write a failing test using one high-IS database row with passing checks and correlations; assert dry-run autopilot does not put it into `submission_ready` without a locked-OOS record.
- [ ] Run `python -m pytest tests/test_auto_pilot.py::test_auto_pilot_keeps_is_only_candidate_out_of_submission_ready -q` and observe the desired fail-closed behavior is not proven.
- [ ] Make the autopilot pass its actual grade into the approval engine and retain the existing no-OOS fail-closed decision; remove any unconditional READY fallback.
- [ ] Re-run the focused test and verify it passes.

## Final verification

- [ ] Run `python -m pytest tests/test_framework.py tests/test_storage_concurrency.py tests/test_recovery_drill.py tests/test_auto_pilot.py -q`.
- [ ] Run `git diff --check`.
