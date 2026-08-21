# Simulation Batch Tracking Design

## Goal

Persist every BRAIN multi-simulation submission and every expression result so
long-running platform work can be polled, resumed, and audited without
resubmitting a batch.

## Data Model

`simulation_batches` owns one platform `POST /simulations` request.  It stores
the platform batch ID, request settings, requested/completed/failed counts,
state, last polling time, raw progress payload, error text, and lifecycle
timestamps.

`simulation_results` owns one expression in a batch.  It stores sequence order,
expression SHA and text, child simulation URL, platform Alpha ID, state, full
Alpha detail JSON, error text, and timestamps.  `(batch_id, sequence_no)` is
unique; each result remains historical even if `alpha_details` later changes.

## Async Flow

1. Create local batch and result rows with state `created`.
2. Submit `POST /simulations`; capture `Location` and batch ID; mark submitted.
3. Poll `GET /simulations/{platform_batch_id}`.  Persist every payload and
   child URL/progress update.
4. For a completed child, get `/alphas/{alpha_id}`, store raw details, and
   synchronize the latest snapshot to `alpha_details`.
5. Mark the batch completed only when every result is terminal; otherwise keep
   it pollable.  A failed network wait never resubmits a batch with an existing
   platform batch ID.
