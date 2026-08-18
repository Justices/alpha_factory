# Super Alpha Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a durable, bounded Super Alpha research workflow.

**Architecture:** A focused `super_alpha` module owns template manifests, candidate construction, and BRAIN payload encoding. SQLite owns candidates and augments durable batch rows with simulation type and task JSON; the CLI delegates submission/polling to the existing tracker.

**Tech Stack:** Python 3.12, SQLite, existing managed BRAIN client.

## Global Constraints

- Never store credentials or automatically submit an alpha to production.
- Default database: `data/alpha_research.db`.
- Super Alpha pilot batches contain 4--6 candidates unless explicitly overridden.
- Every schema update includes an incremental migration and `latest_schema.sql`.

---

### Task 1: Candidate factory

**Files:** Create `alpha_operator_framework/super_alpha.py`; modify `tests/test_framework.py`.

- [ ] Write failing tests for source gating, hash deduplication, bounded templates, and SUPER payload shape.
- [ ] Implement immutable configuration/template records and pure candidate factory.
- [ ] Run the focused test.

### Task 2: Durable storage

**Files:** Modify `database/models.py`, `database/repository.py`, schema migrations and snapshot; modify tests.

- [ ] Write failing tests for candidate rows and SUPER batch type.
- [ ] Add minimal SQLite schema, repository methods, migration `004_super_alpha.sql`, and refresh snapshot.
- [ ] Run focused persistence tests.

### Task 3: CLI and polling

**Files:** Modify `alpha_machine.py`, `simulation_tracker.py`, package exports, tests, and usage documentation.

- [ ] Write failing CLI/adapter tests.
- [ ] Implement prepare, submit, and poll commands with existing managed client.
- [ ] Compile and run the full suite.
