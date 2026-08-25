# Research Main Chain Implementation Plan

**Goal:** Persist research-cycle expressions in the primary Alpha tables and retain durable execution audit data.

**Architecture:** The runtime composition root will supply an `AlphaDatabase` backed by the same SQLite URL as the event runtime. Research planning catalogs selected tasks before simulation. Worker processing records a platform success in the Alpha detail/check tables, or records failure on the primary expression row while preserving the error in the task snapshot. Snapshot projections gain creation/update timestamps and a durable state/error summary.

**Constraints:** Do not call the platform during verification; modify all code first, then run one unified validation and one commit.

### Task 1: Main expression persistence

- Add focused tests proving selected research tasks create `alpha_expressions` rows with `pending` status.
- Add a small runtime port/adaptor so planning catalogs each selected task with its settings and lineage metadata.

### Task 2: Result and failure propagation

- Add focused tests for successful Alpha detail persistence and failed result status/error persistence.
- Preserve simulator failure information in `BacktestResult`; treat failed platform results as retryable failures rather than completed evaluations.

### Task 3: Snapshot audit migration

- Add migration-backed tests for `created_at`, `updated_at`, `status`, and `error` on both snapshot projections.
- Update repository save/load operations and add an idempotent migration.

### Task 4: Unified validation

- Run the targeted runtime tests, full tests, static checks, and offline research-cycle flow once after all modifications.
- Commit only intended files, excluding user configuration changes.
