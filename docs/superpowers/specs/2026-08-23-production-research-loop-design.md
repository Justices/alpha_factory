# Production Research Loop Design

## Goal

Make every research round recoverable, auditable, and safe to operate against the BRAIN platform without changing domain decisions through infrastructure code.

## Delivery Order

1. Durable `ExperimentBatch`: explicit lifecycle, idempotency, append-only facts, and restart-safe persistence.
2. Evaluation loop: hard gates, Pareto rank, mutation lineage, and a next-round candidate handoff.
3. Configured exploration: versioned selection/pruning/evaluation policy snapshots, including weighted-stratified, Thompson, UCB, and diversity strategies.
4. Production governance: persistent knowledge evidence, controlled template promotion, submission outbox, observability, and operator approval.

## Boundaries

- `research` constructs candidates and decides pre-backtest selection only.
- `experiment` owns task lifecycle, normalized results, evaluation, ranking, and mutation proposals.
- `knowledge` owns cross-round evidence, template distillation, and submission approval.
- `application` coordinates state transitions through typed ports and contains no scoring or platform rules.
- `infrastructure` implements SQLite, BRAIN, outbox, and metrics adapters.

## Required Invariants

- A task is submitted at most once for an idempotency key; retries reuse the same key.
- A batch transition is valid only from its preceding state and is persisted atomically with its fact.
- A `KnowledgeSnapshot` is immutable for the duration of a round.
- Only evaluated, non-pruned Pareto-rank-1 results can mutate into a future candidate.
- A submission requires platform evidence, correlation, capacity, lineage, and explicit authorization; absent evidence rejects it.
- Dry-run never constructs a live platform gateway.

## Rollout

Run the durable batch path in dry-run and replay mode first. Enable live execution per batch only after retry/idempotency metrics are healthy. Keep submission disabled until its outbox adapter and approval evidence are complete.
