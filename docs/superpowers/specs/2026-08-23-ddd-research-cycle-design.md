# Alpha Factory DDD Research Cycle Design

## Goal

Replace the coupled research framework with a non-compatible DDD architecture that makes every research round reproducible, configurable, and independently testable. The new system must support multiple field/operator/template selection algorithms and manage them together with multi-stage pruning through an explicit feedback loop.

## Scope

The target lifecycle is:

```text
FieldResearch → CandidateGeneration → PrePrune → SelectionRound
→ BacktestBatch → PostBacktestPrune → Evaluate / Optimize
→ SubmissionCase → DistillKnowledge → SelectionFeedback
```

Pre-pruning is limited to invalid inputs, prohibited or incompatible field/operator combinations, AST-invalid candidates, exact canonical duplicates, and hard budget limits. Business-quality pruning remains after backtest so the required ordering of selection, backtest, pruning, evaluation, optimization, submission, and distillation is preserved.

This change deliberately does not preserve existing Python APIs, CLI command names, package imports, or database schema compatibility. It replaces the legacy workflow after the new workflow is validated.

## Bounded Contexts

### Field Research

**Aggregate root:** `FieldUniverse`

Owns the immutable field snapshot for a market setting and the research-derived profile of each field. A field profile contains eligibility, coverage, crowding, novelty, semantic category, evidence counts, and current sampling weight.

**Domain services:** field profiling, field eligibility rules, field-weight updates.

**Ports:** `FieldCatalog`, `FieldProfileRepository`.

### Candidate Exploration

**Aggregate root:** `SelectionRound`

Owns one planned exploration round. It persists the `ResearchPolicy` snapshot, seed, budget, candidate pool snapshot, all selection decisions, and the reason a candidate was selected or rejected before backtest.

**Domain services:** AST candidate factory, candidate canonicalizer, `SelectionPolicy`, pre-pruning policies, budget allocator.

**Ports:** `CandidateRepository`, `RandomSource`.

### Experiment Governance

**Aggregate root:** `ExperimentBatch`

Owns the lifecycle of a submitted backtest batch and its immutable returned results. It applies post-backtest pruning, quality evaluation, multi-objective optimization, and transition to a submission case.

**Domain services:** result normalizer, post-backtest pruning policies, evaluator, Pareto optimizer, evidence gate.

**Ports:** `BacktestGateway`, `ExperimentRepository`.

### Knowledge and Submission

**Aggregate roots:** `KnowledgeBase`, `SubmissionCase`

`KnowledgeBase` accumulates field, operator, template, pair, and pruning-rule evidence. `SubmissionCase` owns fail-closed evidence approval and the platform submission state.

**Domain services:** signal distillation, feedback builder, submission approval.

**Ports:** `KnowledgeRepository`, `SubmissionGateway`.

## Dependency Rule

Domain code depends only on its own types and ports. Application use cases may depend on several contexts through their ports. Infrastructure implements ports and is the only layer allowed to use SQLite, local files, BRAIN clients, HTTP, time, or non-deterministic random generators. The CLI adapts arguments to a use case and renders a result; it contains no workflow rule.

No context imports another context's infrastructure. Cross-context facts use value objects or persisted domain events, never direct repository-table access.

## Selection and Pruning Governance

Selection and pruning are strongly managed together but remain independently replaceable pure policies.

```text
SelectionPolicy proposes candidates
        ↓
PrePruningPolicy rejects infeasible or duplicate candidates
        ↓
SelectionRound records selected/rejected decisions and reasons
        ↓
BacktestGateway evaluates accepted candidates
        ↓
PostBacktestPruningPolicy rejects failed, redundant, or unsafe results
        ↓
SelectionFeedback updates field/operator/template/pruning evidence
```

Every pruning result has `stage`, `decision`, `reason_code`, `evidence`, and `policy_version`. A selection decision has `candidate_id`, `score_components`, `algorithm`, `policy_version`, and `seed`. These records make a round explainable without inspecting strategy internals.

## Research Policy

`ResearchPolicy` is a versioned, immutable value object saved with every `SelectionRound`:

- Market setting: region, universe, delay and simulation settings.
- Budget: maximum generated, pre-pruned, backtested, optimized, and submitted candidates.
- Field, operator, template, novelty, uncertainty, and diversification weights.
- Per-kind quotas and maximum reuse limits for fields, operators, templates, and structural families.
- Selection-policy name and parameters.
- Ordered pre- and post-backtest pruning policies and their thresholds.
- Evaluation objectives and submission hard gates.

The policy does not store mutable learned state. Learned evidence belongs to `KnowledgeBase`; a policy explicitly selects the evidence snapshot it uses.

## Selection Policies

All policies implement one domain interface conceptually equivalent to `select(pool, knowledge, policy, random_source) -> SelectionDecision[]`. They must respect policy quotas and produce deterministic results for the same snapshots and seed.

1. **Weighted stratified random** is the baseline and cold-start policy. It samples fields, operators, and templates using configured weights while preserving category and family quotas.
2. **D-optimal diversity selection** is a cold-start or exploration policy. It selects a batch that maximizes feature-space information and prevents a budget from concentrating on near-identical candidates.
3. **Thompson/UCB combinatorial pure exploration** is the adaptive policy. It uses uncertainty and observed field/operator/template effects to explore promising combinations while retaining explicit exploration.
4. **NSGA-II candidate evolution** is used only after real results exist. It produces Pareto-diverse mutations from winners for objectives such as Sharpe, Fitness, turnover, margin, novelty, and correlation; it is not a first-round sampler.

The initial implementation treats algorithm choice as policy configuration, allowing controlled A/B comparison under identical field snapshots, budget, and seed protocol.

## Application Use Cases

`ResearchCycleUseCase` is the sole full-cycle orchestrator. It calls narrow use cases in lifecycle order and returns a persisted round summary:

1. `RefreshFieldUniverseUseCase`
2. `ResearchFieldsUseCase`
3. `GenerateCandidatesUseCase`
4. `SelectBacktestBatchUseCase`
5. `RunBacktestsUseCase`
6. `PruneAndEvaluateResultsUseCase`
7. `OptimizeCandidatesUseCase`
8. `SubmitApprovedCandidatesUseCase`
9. `DistillKnowledgeUseCase`
10. `BuildSelectionFeedbackUseCase`

Submission is opt-in. The default cycle ends in dry-run and cannot consume BRAIN quota or submit an alpha. A production cycle requires explicit execution authorization.

## Failure Handling and Invariants

- Invalid AST, duplicate canonical expression, incompatible field/operator type, and budget violation are pre-backtest rejections, never exceptions that abort unrelated candidates.
- A backtest request has an idempotency key. A transient platform failure may retry polling the same request; it must not automatically submit a new backtest request.
- Returned platform failures become normalized failed experiment results with preserved platform evidence.
- A missing required submission evidence item is a rejection. Submission is fail-closed.
- Domain policies perform no I/O and receive a deterministic `RandomSource`.
- No candidate can transition to submission without the evaluation and evidence approval records from the same lineage.

## Persistence and Observability

The new schema stores aggregate snapshots and append-only decisions rather than leaking individual legacy tables across contexts. Required records are:

- field-universe and field-profile snapshots;
- research-policy versions and selection-round snapshots;
- candidate lineage, canonical AST hash, generation strategy, and selection decisions;
- experiment batches, idempotency keys, normalized results, and pruning decisions;
- evaluation records, Pareto ranks, submission cases, and approval evidence;
- knowledge evidence and feedback snapshots.

The CLI summary exposes only decision-level results: candidates selected, pruned by reason, completed, qualified, submission-ready, and top feedback changes. Raw platform payloads remain in artifacts.

## Test Strategy and Acceptance Criteria

Domain tests use fixed fixtures and `DeterministicRandomSource`. They verify weighting, quotas, diversity, feedback updates, pruning reason codes, AST canonical deduplication, and state-transition invariants.

Application tests use in-memory ports and validate every lifecycle transition, including dry-run behavior and failure normalization. Infrastructure tests validate SQLite mappings and BRAIN request/result mappings. An end-to-end dry-run verifies complete lifecycle persistence and reconstruction.

The refactor is accepted only when:

1. A completed round explains why each candidate was selected or pruned and how feedback changes the next round.
2. Replacing a selection or pruning policy changes neither use-case orchestration nor infrastructure adapters.
3. Identical field snapshot, knowledge snapshot, policy, and seed produce identical decision order.
4. No domain module imports BRAIN, SQLite, HTTP, or filesystem code.
5. The new CLI runs the complete dry-run lifecycle and a controlled real-backtest lifecycle without invoking legacy orchestration.

## Migration Boundaries

Implementation creates the new bounded-context package, new persistence schema, and new CLI first. Each vertical slice is testable in isolation. Once all acceptance criteria pass, legacy `alpha_machine.py`, `orchestrator.py`, `ai_workflow.py`, and `loop.py` workflow paths are removed along with no-longer-needed schema and tests. No compatibility facade or dual-write period will be added.
