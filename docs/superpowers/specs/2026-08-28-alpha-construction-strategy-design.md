# Alpha Construction Strategy Design

## Goal

Build Alpha candidates through an explicitly configured combination of construction strategies while keeping validation, identity, quotas, persistence, backtesting, and recovery in one deterministic pipeline.

The first supported strategy kinds are:

1. database-template instantiation;
2. higher-order construction by operator nesting depth;
3. multi-field construction by distinct raw-field count;
4. paper/LLM-driven hypothesis and template extraction.

Higher order and multiple fields are independent structural dimensions. A candidate may therefore target, for example, operator depth three and two distinct raw fields. They are not fixed lifecycle stages and must not be modeled as `base -> order2 -> dimension2`.

## Confirmed Definitions

- `order_depth` is the maximum number of operator nodes on any root-to-leaf path in the validated expression AST. Literal, parameter, and field nodes do not add operator depth.
- `field_count` is the number of distinct raw data-field identifiers referenced by the validated AST. Repeated use of one field still counts as one.
- Both dimensions accept either an exact value or an inclusive minimum/maximum range.
- Strategies are selected explicitly for each research task. The runtime does not silently enable, disable, or substitute strategies based on historical performance.
- Multiple strategies may run in the same research task.
- `quota_per_leaf_family` means that at most eight candidates from each leaf family are selected for platform backtesting in one research round. It is not a generation cap.
- Platform submission remains sliced into batches of at most eight candidates. Four leaf families with a quota of eight can therefore select at most 32 unique candidates and submit them as four batches.

## Architecture

Introduce a small strategy boundary around candidate proposal:

```text
ResearchStrategyConfig
        |
        v
ConstructionStrategyRegistry
        |
        +-- DatabaseTemplateStrategy
        +-- DepthConstructionStrategy
        +-- FieldCompositionStrategy
        +-- LiteratureHypothesisStrategy
        |
        v
CandidateDraft stream
        |
        v
AST validation -> structural measurement -> canonical deduplication
        -> provenance and lineage persistence -> leaf-family selection
        -> platform shards -> evaluation
```

Every strategy implements one interface whose only responsibility is to propose `CandidateDraft` values. Strategies do not allocate platform quota, assign final candidate identity, bypass AST validation, write simulation state, or submit work to BRAIN.

The shared construction pipeline owns:

- validated AST creation;
- measured `order_depth` and `field_count` enforcement;
- canonical expression identity;
- cross-strategy deduplication;
- provenance and parent-child lineage;
- leaf-family allocation and quota;
- persistence before selection;
- platform shard creation and restart-safe execution.

The existing research planner and batch worker retain selection/evaluation and one-batch execution responsibilities. Cross-batch orchestration consumes the unified candidate catalog instead of interpreting `order2` and `dimension2` as fixed stages.

## Strategy Responsibilities

### DatabaseTemplateStrategy

Loads active, compatible templates from the database template library, binds raw fields, and emits drafts. Template labels are advisory only: the shared pipeline recomputes depth and field count from the rendered AST.

### DepthConstructionStrategy

Builds candidates toward the configured operator-depth target. Its inputs may be raw fields or eligible parent candidates, according to explicit configuration. It uses compatible active templates and never assumes that a label such as `order2` proves the resulting depth.

### FieldCompositionStrategy

Builds candidates toward the configured distinct-field target. It rejects self-pairs and repeated-field combinations that do not reach the measured target. Operator depth remains independently constrained by the same strategy configuration.

### LiteratureHypothesisStrategy

Parses a specified paper or report and uses the configured LLM only to produce structured hypotheses and parameterized templates. It cannot directly create a trusted final expression. Its templates pass through deterministic field binding and the same AST, structural, operator-access, deduplication, quota, and persistence rules as every other strategy.

LLM credentials remain in the existing environment/configuration mechanism and are never stored inside a research strategy document or candidate record.

## Explicit Configuration

The configuration is part of the persisted research task and participates in the task identity. A representative shape is:

```yaml
construction:
  strategies:
    - kind: database_template
      families: [ts_unary]
      order_depth: {min: 1, max: 2}
      field_count: {exact: 1}
      quota_per_leaf_family: 8

    - kind: depth_construction
      source: raw_and_qualified_candidates
      families: [higher_order]
      order_depth: {exact: 3}
      field_count: {min: 1, max: 2}
      quota_per_leaf_family: 8

    - kind: field_composition
      source: raw_and_qualified_candidates
      families: [multi_field]
      order_depth: {min: 1, max: 3}
      field_count: {exact: 2}
      quota_per_leaf_family: 8

    - kind: literature_llm
      document: docs/papers/example.pdf
      llm_profile: research_default
      families: [paper_hypothesis]
      order_depth: {min: 1, max: 3}
      field_count: {min: 1, max: 2}
      quota_per_leaf_family: 8

  parent_gate:
    sharpe: {operator: gt, value: 1.25}
    fitness: {operator: gt, value: 0.8}
  platform_batch_size: 8
```

An exact value and a range for the same dimension are mutually exclusive. Missing strategy kind, invalid bounds, zero/negative quota, unsupported source, unavailable document, or unsupported LLM profile fails configuration validation before candidate generation begins.

Strategy list order is the explicit priority order used when the same canonical candidate is proposed by more than one leaf family.

## Candidate and Persistence Model

`CandidateDraft` is transient and contains:

- expression or parameterized template plus resolved bindings;
- strategy kind and strategy-instance identifier;
- template family and template identifier, when applicable;
- hypothesis identifier, when applicable;
- parent candidate identities;
- generation seed;
- proposed metadata that is not trusted until validation.

After validation, the canonical candidate retains the existing expression-plus-complete-settings identity. Add provenance records rather than duplicating the candidate when multiple strategies produce the same canonical expression.

Each provenance record contains:

- canonical candidate identity and complete settings scope;
- strategy kind and strategy-instance identifier;
- template family and leaf-family identifier;
- template/hypothesis identifiers;
- measured operator depth and distinct field count;
- generation seed and creation time.

Parent-child relationships are stored separately from provenance. The relationship records the parent identity, child identity, transform kind, strategy instance, and settings scope. It replaces the new runtime's dependence on stage-limited `order2`/`dimension2` lineage. Existing historical lineage may remain readable as historical evidence but is not interpreted as equivalent to the new structural definitions.

The leaf-family identifier is deterministic:

```text
<strategy-kind>/<template-family>/depth-<measured-depth>/fields-<measured-field-count>
```

A canonical candidate can have several provenance records but is submitted only once. During quota allocation, the first eligible leaf family in explicit strategy order claims the candidate; ties are resolved by stable leaf-family identifier and canonical candidate identity. Later provenance remains visible but does not consume another quota or platform slot.

## Data Flow

1. Parse and validate the complete explicit construction configuration.
2. Persist the research task, strategy instances, settings scope, and deterministic seed.
3. Run enabled strategies in configuration order and collect candidate drafts.
4. Parse and validate each AST, reject inaccessible or unknown operators, compute structural measures, and enforce the configured exact values/ranges.
5. Canonicalize and deduplicate expressions across all strategies while preserving every valid provenance edge.
6. Persist canonical candidates, provenance, and lineage before selection.
7. Group eligible candidates by deterministic leaf family and select at most eight unique candidates per leaf family.
8. Split the union of selected candidates into deterministic platform batches of at most eight.
9. Persist, execute, evaluate, and resume batches through the existing worker lifecycle.
10. If a configured strategy allows qualified parents, apply the explicit `parent_gate`, create only missing transformations, and return the resulting drafts to step 4.
11. Stop when every configured strategy is exhausted and no retryable or selected batch remains.

Generation may produce more than eight drafts per leaf family. Candidate generation limits needed for combinatorial safety are separate deterministic safety limits and do not change the meaning of the backtest quota.

## Failure and Recovery Semantics

- Invalid top-level configuration fails the task before any strategy runs.
- Invalid individual drafts are rejected with structured reason codes; they never reach selection.
- No valid candidates after deterministic filtering means that strategy instance is exhausted, not failed.
- Failure of one requested strategy preserves candidates and results from other strategies but marks the research task `PARTIAL_FAILED`; it cannot be reported as complete.
- LLM timeout, malformed structured output, missing document, or unavailable configured provider fails the literature strategy. The runtime does not replace it with heuristic expressions unless that fallback was explicitly configured as a separate strategy.
- Platform transport and rate-limit failures retain the worker's persisted retry semantics.
- Candidate, provenance, lineage, selection, and batch writes are idempotent. Restarting the same research task cannot create duplicate identities or resubmit a completed canonical candidate.
- A parent candidate is eligible for structural transformation only when its persisted result satisfies the configured quality gate. Boundary operators such as `gt` remain exact and are not silently weakened.

## Verification and Acceptance

Automated tests must cover:

- exact and range configuration parsing, including contradictory bounds;
- AST operator-depth measurement independent of field count;
- distinct-field counting with repeated references;
- combinations such as depth three with two fields;
- recomputation that rejects incorrect template labels;
- invalid, inaccessible, and unknown operator rejection;
- structured LLM output passing through the deterministic compiler;
- malformed LLM output failing closed;
- canonical deduplication with multiple preserved provenance records;
- deterministic duplicate ownership across leaf families;
- at most eight selected candidates per leaf family;
- at most eight candidates per platform batch;
- settings-scoped identity and isolation;
- configurable parent-gate boundaries;
- lineage idempotency and restart recovery;
- partial failure when one explicitly requested strategy fails;
- exhaustion only after every configured strategy and batch is terminal.

Completion requires focused regression tests for the unified construction path and compilation of changed modules. Full-suite results must be reported separately and honestly if an unrelated pre-existing collection or environment failure remains.

## Migration Boundary

- Keep `alpha_expressions` as the canonical candidate catalog.
- Add provenance and generalized construction-lineage persistence without destructively rewriting historical results.
- Stop new orchestration from assigning semantic meaning to fixed `order2` and `dimension2` stages.
- Adapt the existing literature pipeline behind `LiteratureHypothesisStrategy`; do not maintain a second trusted validation/quota/submission path.
- Preserve the existing planner, batch worker, evaluation rules, platform authorization, and submission evidence gates unless a change is strictly required by the unified strategy contract.

## Out of Scope

- An automatic strategy recommender or automatic quota reallocation.
- A general workflow/DAG language.
- Unbounded recursive expression evolution.
- Letting an LLM directly submit or bless final expressions.
- Changing BRAIN submission authorization or production evidence requirements.
- Refactoring unrelated CLI, storage, evaluation, or platform code.
