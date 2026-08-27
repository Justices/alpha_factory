# Research Optimization Loop Design

## Goal

Turn `research-cycle --continue-research --execute` into a restart-safe closed loop:

1. Persist every generated candidate before selection.
2. Select and backtest candidates.
3. Persist backtest completion independently from pruning state.
4. Derive pruning decisions from completed results and prune only matching, unbacktested candidates.
5. Promote signal-bearing expressions through one higher-order stage and one two-field stage.
6. Return to the base candidate pool after the promoted branch is exhausted.
7. Stop only when the base pool and optimization queue are both empty.

## Confirmed Rules

- A result is a signal parent only when `sharpe > 1.25` and `fitness > 0.8`.
- Signal-parent selection does not overwrite backtest or pruning status.
- Consensus pruning requires all of:
  - at least three distinct fields;
  - at least four completed samples;
  - failure rate of at least 80%;
  - average Sharpe no greater than 0.1;
  - no result in the structure reaching the signal threshold (gold-shield immunity).
- Pruning is isolated by the complete settings tuple: `region`, `universe`, `delay`, `decay`, `neutralization`, and `truncation`.
- Pruning updates only unbacktested expressions whose structure matches a derived rule. Completed expressions remain completed and are not marked pruned by this step.
- Optimization stages are bounded to `base -> order2 -> dimension2 -> done`.
- `order2` applies compatible active templates to a signal expression.
- `dimension2` combines the signal expression with another raw field from the same category.
- Every active template is considered, with at most 200 deterministic combinations per template and stage.
- All candidates within that bound are persisted and deduplicated before selection.
- Selection keeps the existing weighted-stratified policy and selects 20 candidates per family/category when available.
- Platform submissions remain chunked into groups of eight; a final partial group is allowed.
- Optimization candidates have priority over the remaining base pool.

## Architecture

Introduce `ResearchLoopCoordinator` as an application service. The CLI starts the coordinator and prints its final summary. The existing research planner remains responsible for candidate persistence and selection, while `ResearchBatchWorker` remains responsible for one batch's submission, result persistence, evaluation, retries, and events.

The coordinator owns only cross-batch decisions:

- loading the next active queue;
- prioritizing optimization work;
- deriving setting-scoped consensus pruning rules;
- applying those rules to active unbacktested expressions;
- creating the next optimization stage;
- deciding when the loop is exhausted.

This keeps the worker independently retryable and prevents the CLI from becoming the source of workflow state.

## Persistence Model

Keep `alpha_expressions` as the complete candidate catalog and its composite expression-plus-settings hash as the expression identity. Keep backtest lifecycle in `status` and pruning lifecycle in `pruning_status`.

Add a lightweight optimization-lineage projection containing:

- settings scope hash;
- parent alpha hash;
- child alpha hash;
- stage (`order2` or `dimension2`);
- generation state;
- created and updated timestamps.

The unique identity is `(settings_scope_hash, parent_alpha_sha, child_alpha_sha, stage)`. It makes candidate generation idempotent after interruption and provides an explicit terminal stage without encoding workflow state in expression text.

Prune rules must carry the same settings scope hash. Existing global/static rules remain generation-time validation rules; result-derived rules are matched only within their settings scope.

## Data Flow

For each coordinator iteration:

1. Resume any non-terminal batch before creating new work.
2. Load active unbacktested optimization candidates; if present, select them first.
3. Otherwise load active unbacktested base candidates.
4. Plan a round, persist its selected tasks, and let the worker execute it in platform chunks of eight.
5. If the worker has not reached `EVALUATED`, stop the iteration without pruning or promotion and let retry state control resumption.
6. Query completed results in the exact settings scope and derive consensus structural failures.
7. Persist the scoped rules and mark only matching unbacktested expressions as pruned.
8. For each newly completed signal parent, generate its next missing stage:
   - `base` produces `order2` children;
   - an eligible `order2` result produces `dimension2` children;
   - `dimension2` produces no further children.
9. Persist and deduplicate generated children and lineage before the next selection.
10. Repeat until no active optimization candidate and no active base candidate remain.

## Candidate Generation

Generation consumes all active compatible templates from `template_library`; it does not restore CLI hard-coded templates. VECTOR and EVENT fields keep the existing preprocessing path before participating in templates.

`order2` treats the parent expression as the primary typed input and applies compatible one-step higher-order templates. `dimension2` uses the parent signal plus a different raw field from the same dataset category, then validates the resulting field types and AST.

Each template/stage emits at most 200 combinations in deterministic seed order. Invalid ASTs, `vector_neut`, duplicate composite identities, self-pairs, and already-recorded lineage edges are discarded before persistence.

## Pruning Semantics

Result-driven pruning aggregates completed samples by normalized template skeleton within one settings scope. A structure is prunable only after satisfying the confirmed sample, field-diversity, failure-rate, mean-Sharpe, and immunity rules.

Applying a rule changes only `pruning_status` on matching expressions whose backtest `status` is `generated` or `pending`. It also updates the corresponding active `round_candidates` projections. It never changes a completed or failed backtest status and never marks the expressions used to derive the rule as pruned.

## Recovery and Failure Handling

- Platform timeouts, rate limits, partial responses, and retry exhaustion retain the existing worker semantics.
- A batch must reach `EVALUATED` before the coordinator performs pruning or promotion.
- Candidate and lineage writes are idempotent, so restarting the same command cannot regenerate the same child edge.
- A terminal failed batch stops the loop and reports failure; it is not treated as exhaustion.
- Exhaustion means both active queues are empty, not merely that one selection returned no rows.

## Verification

Tests will be written before implementation and will cover:

- strict signal boundaries (`1.25` and `0.8` are not sufficient because the rule uses `>`);
- consensus pruning thresholds and gold-shield immunity;
- complete-settings isolation of result-derived prune rules;
- pruning only active unbacktested candidates;
- preservation of completed status and independent pruning state;
- optimization priority over base candidates;
- `base -> order2 -> dimension2 -> done` stage transitions;
- same-category raw-field pairing and self-pair rejection;
- all active templates with a 200-combination cap;
- lineage idempotency after restart;
- per-family selection and platform chunks of eight;
- coordinator exhaustion and retry/failure behavior;
- CLI delegation to the coordinator.

## Out of Scope

- Database migration from an existing validation database; a fresh initialization is acceptable.
- Third-order or three-field recursive evolution.
- Cross-settings pruning.
- Changing submission authorization or evidence checks.
- Refactoring unrelated legacy workflows.

## Implementation Verification

- Focused regression suite: 57 passed on 2026-08-27.
- Python compilation: passed on 2026-08-27.
- The workspace denies writes to `.pytest_cache`; this produces a pytest cache warning only.
