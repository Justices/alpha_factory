# Alpha Factory Research-Round Domain Design

> Supersedes the four-bounded-context proposal in `2026-08-23-ddd-research-cycle-design.md`. The earlier proposal is retained as history, but is not an implementation target.

## Decision

The system will not model every workflow stage as a bounded context. It will use three domain modules based on the objects that users actually reason about:

1. `ResearchRound` — what to investigate, how to construct candidates, what to select, and what to prune.
2. `ExperimentBatch` — what was sent to backtest and what the platform returned.
3. `KnowledgeBase` — what the factory learned and what may influence a future round or submission.

`application/` and `infrastructure/` are cross-cutting technical layers, not repeated inside every module.

## Target Structure

```text
alpha_operator_framework/
  research/
    models.py              # ResearchRound, ResearchPolicy, Candidate, decisions
    field_profile.py       # field eligibility and profile calculation
    candidate_factory.py   # AST-backed field/operator/template construction
    selection.py           # stratified, diversity, Thompson/UCB policies
    pruning.py             # pre/post pruning policies and reason codes
  experiment/
    models.py              # ExperimentBatch, BacktestTask, BacktestResult
    evaluation.py          # hard gates, evidence and Pareto ranking
    mutation.py            # post-result NSGA-style mutation proposals
  knowledge/
    models.py              # KnowledgeBase and immutable KnowledgeSnapshot
    distillation.py        # field/operator/template/pruning evidence aggregation
    submission.py          # SubmissionCase and fail-closed approval
  application/
    research_cycle.py      # ordered use cases; no domain rules
  infrastructure/
    sqlite.py              # repository implementations
    brain.py               # platform gateways
    local_fields.py        # local catalogue adapter
  cli.py                   # argument parsing and output only
```

## Domain Modules

### Research

`ResearchRound` is the primary aggregate. It captures the market setting, complete policy, immutable field and knowledge snapshots, seed, candidate lineage, and every selection or pruning decision.

Field profiling, AST construction, selection, and pruning belong here because they answer one domain question: **which hypotheses deserve one unit of backtest budget?** They must be pure functions. A selection policy proposes candidates; pruning policies accept or reject them with structured reasons; neither touches a database or platform client.

The round has two pruning moments:

- **Before backtest:** ineligible fields, incompatible types, invalid AST, canonical duplicates, learned prohibited patterns, and hard budget limits.
- **After backtest:** failed platform results, hard quality gates, correlation or redundancy, turnover/capacity constraints, and template-level negative evidence.

Selection and pruning are not separate bounded contexts. They are collaborating policies in the same aggregate and write one coherent audit trail.

### Experiment

`ExperimentBatch` begins only after `ResearchRound` produces its selected cohort. It owns idempotency keys, tasks, platform lifecycle, normalized immutable results, evaluation records, and Pareto ranks.

The experiment module has no knowledge of field discovery or future sampling. It can tell the application layer which results are accepted, rejected, or good mutation parents. NSGA-style mutation starts here, after real results exist; it creates lineage-bearing proposals for a future `ResearchRound`, never a first-round selection algorithm.

### Knowledge

`KnowledgeBase` accumulates positive and negative evidence across completed batches: field, operator, template, pair, and pruning statistics. It emits immutable `KnowledgeSnapshot` values used by a new round.

It also owns template distillation and `SubmissionCase`. Submission remains fail-closed: a case needs verified platform evidence, all required checks, correlation and capacity evidence, lineage, and explicit approval before an infrastructure gateway may submit it.

## Application Flow

```text
refresh FieldSnapshot + KnowledgeSnapshot
  → create ResearchRound
  → profile fields and construct AST candidates
  → pre-prune and select cohort
  → create ExperimentBatch and run backtests
  → post-prune, evaluate and Pareto-rank results
  → create mutation proposals for the next round
  → distill results and pruning decisions into KnowledgeBase
  → optionally construct and submit approved SubmissionCases
```

The application layer controls this order and execution authorization. It performs no AST generation, scoring, thresholding, or direct SQL access.

## Policy and Algorithm Configuration

`ResearchPolicy` is immutable and stored as a complete snapshot. It includes market settings; budgets; field/operator/template/novelty/uncertainty weights; family quotas; selection-policy name and parameters; ordered pruning rules; evaluation thresholds; and post-result mutation budget.

Supported first-round selection policies are weighted stratified sampling, diversity selection, and Thompson/UCB exploration. All consume the same `KnowledgeSnapshot`, obey the same quotas, and return explanations. Diversity selection uses a candidate feature vector; Thompson/UCB learn evidence for field, operator, and template separately. NSGA-style evolution is post-result only.

## Ports and Infrastructure

The domain defines only five ports: `FieldCatalog`, `ResearchRepository`, `ExperimentRepository`, `KnowledgeRepository`, and `BacktestGateway`/`SubmissionGateway`. SQLite and BRAIN implement them under `infrastructure/`.

Dry-run must never instantiate BRAIN infrastructure. Real backtests require explicit execution authorization. Production submission is unavailable until the adapter calls and verifies the real platform endpoint.

## Persistence and Audit

Persist aggregate snapshots plus append-only decision records. A replay needs the field snapshot version, knowledge snapshot version, full policy, seed, candidate AST hash and lineage, selection decisions, pruning reasons, and normalized results.

Every selected or rejected candidate must be answerable in one query: its candidate source, policy components, selection decision, pruning decisions, and any learned evidence used.

## Acceptance Criteria

1. No `ddd/` directory remains after migration; the new three-module structure is the only active workflow.
2. `ResearchRound` can run pure selection/pruning tests without SQLite, BRAIN, HTTP, time, or non-deterministic randomness.
3. A fixed field snapshot, knowledge snapshot, policy, and seed reproduce selected candidate order and reason codes.
4. A dry-run produces a planned `ResearchRound` and no BRAIN adapter instance.
5. A completed batch updates `KnowledgeBase`; a subsequent round demonstrably consumes that snapshot.
6. NSGA-style mutation receives only evaluated, non-pruned parents and produces AST-valid lineage-bearing proposals.
7. Submission cannot proceed through an unverified adapter or incomplete evidence.
