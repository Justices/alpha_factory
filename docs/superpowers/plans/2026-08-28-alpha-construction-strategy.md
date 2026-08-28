# Unified Alpha Construction Strategy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan inline. The user explicitly requires all production code to be completed first, all tests to be written and run afterward, and one final commit only; that instruction overrides the skill defaults for per-task TDD and frequent commits.

**Goal:** Replace fixed database-template plus `order2`/`dimension2` orchestration with explicitly configured, composable Alpha construction strategies that share deterministic validation, structural measurement, deduplication, provenance, quotas, persistence, and recovery.

**Architecture:** A typed construction plan feeds a strategy registry. Strategy adapters emit untrusted drafts; one pipeline validates ASTs, measures operator depth and distinct raw fields, canonicalizes candidates, assigns deterministic leaf families, and preserves multi-source provenance. The existing research planner and worker receive the accepted canonical candidates, while generalized lineage replaces fixed-stage semantics.

**Tech Stack:** Python 3.11+, dataclasses and protocols, existing typed Alpha AST, SQLAlchemy portable schema with repository mixins, YAML runtime configuration, pytest.

## Global Constraints

- Complete all production-code changes before adding or running tests.
- Run tests only after implementation is complete.
- Create one final commit after tests and final diff review; do not make intermediate commits.
- Strategies are always explicit in `research.construction.strategies`; no automatic strategy substitution or historical-performance activation.
- `order_depth` and `field_count` are independent AST-derived dimensions and support exact or inclusive range constraints.
- The default and maximum per-leaf-family selection quota is 8 for this implementation.
- Platform batch size is exactly 8 and is not the candidate-generation cap.
- Literature/LLM output is untrusted and must pass the shared deterministic construction pipeline.
- Preserve existing user work and do not refactor unrelated CLI, evaluation, platform, or storage code.

---

## File Map

- Create `alpha_operator_framework/research/strategy_config.py`: typed structural constraints, strategy instances, parent gate, construction plan, and strict YAML mapping parser.
- Create `alpha_operator_framework/research/structure.py`: AST operator-depth and distinct-field measurement.
- Create `alpha_operator_framework/research/strategies.py`: draft/provenance domain types, strategy protocol, four adapters, registry, and shared acceptance pipeline.
- Modify `alpha_operator_framework/research/construction.py`: expose generic parent/template rendering instead of fixed `order2` and `dimension2` semantics.
- Modify `alpha_operator_framework/research/round.py`: carry measured structure and provenance-aware leaf-family metadata on candidates.
- Modify `alpha_operator_framework/research/pipeline.py`: expose literature hypothesis generation as an adapter-safe function and route generated expressions through shared acceptance.
- Modify `alpha_operator_framework/application/research_loop.py`: consume a construction plan, qualified parents, and generalized transformations; remove fixed stage transitions.
- Modify `alpha_operator_framework/cli/research.py`: construct candidates through the registry and derive leaf-family quotas from accepted candidates.
- Modify `alpha_operator_framework/infrastructure/runtime_factory.py`: resolve and validate the construction mapping with the runtime configuration.
- Modify `alpha_operator_framework/database/schema.py`: add task, strategy-instance, provenance, and generalized lineage tables.
- Modify `alpha_operator_framework/database/models.py`: add typed provenance/lineage records.
- Modify `alpha_operator_framework/database/repositories/alpha_write.py`: persist research task configuration, strategy outcomes, provenance, and generalized lineage idempotently.
- Modify `alpha_operator_framework/database/repositories/alpha_query.py`: reconstruct candidates with their claimed leaf family and query existing provenance/lineage.
- Modify `configs/alpha-factory.yaml`: add the explicit default database-template strategy and quota/batch settings.
- Modify `README.md` and `USAGE_GUIDE.md`: document explicit combined-strategy configuration and structural definitions.
- Create/modify focused tests under `tests/research`, `tests/application`, `tests/infrastructure`, and `tests` only after production code is complete.

---

### Task 1: Typed Explicit Construction Configuration

**Files:**
- Create: `alpha_operator_framework/research/strategy_config.py`
- Modify: `alpha_operator_framework/infrastructure/runtime_factory.py`
- Modify: `configs/alpha-factory.yaml`

**Interfaces:**
- Produces: `StructuralConstraint.contains(value: int) -> bool`
- Produces: `ConstructionStrategyConfig`
- Produces: `ParentGate.passes(sharpe: float, fitness: float) -> bool`
- Produces: `ConstructionPlan.from_mapping(value: Mapping[str, Any]) -> ConstructionPlan`
- Produces: `resolve_construction_plan(config_path: Path) -> ConstructionPlan`

- [ ] Create immutable config types with strict validation.

```python
@dataclass(frozen=True)
class StructuralConstraint:
    exact: int | None = None
    minimum: int | None = None
    maximum: int | None = None

    def contains(self, value: int) -> bool:
        if self.exact is not None:
            return value == self.exact
        return (self.minimum is None or value >= self.minimum) and (
            self.maximum is None or value <= self.maximum
        )

@dataclass(frozen=True)
class ConstructionStrategyConfig:
    strategy_id: str
    kind: str
    families: tuple[str, ...]
    order_depth: StructuralConstraint
    field_count: StructuralConstraint
    quota_per_leaf_family: int = 8
    source: str = "raw_fields"
    document: str | None = None
    llm_profile: str | None = None

@dataclass(frozen=True)
class ConstructionPlan:
    strategies: tuple[ConstructionStrategyConfig, ...]
    parent_gate: ParentGate
    platform_batch_size: int = 8
```

- [ ] Reject missing/duplicate strategy IDs, unknown kinds, exact-plus-range conflicts, inverted/non-positive bounds, quota values other than 1..8, unsupported sources, missing literature documents/profiles, empty strategy lists, and any platform batch size other than 8.
- [ ] Add `resolve_construction_plan()` without changing storage or ordinary research-option resolution.
- [ ] Replace the implicit YAML-only `sample_per_family` construction meaning with an explicit `research.construction` block containing a default database-template strategy and quota 8.

### Task 2: AST Structural Measurement and Candidate Metadata

**Files:**
- Create: `alpha_operator_framework/research/structure.py`
- Modify: `alpha_operator_framework/research/round.py`

**Interfaces:**
- Produces: `ExpressionStructure(order_depth: int, fields: tuple[str, ...])`
- Produces: `measure_expression_structure(expression: str, known_fields: set[str] | None = None) -> ExpressionStructure`
- Changes: `Candidate` gains `origin_strategy`, `leaf_family`, `order_depth`, `field_count`, and `provenance_ids` with backward-compatible defaults for persisted historical candidates.

- [ ] Traverse typed AST nodes so each function, unary operator, binary operator, and ternary node adds one operator layer on the deepest child; literals and variables add zero.
- [ ] Derive fields from validated AST `fields_used`, sort/deduplicate them, and return `field_count == len(fields)`.
- [ ] Raise on invalid AST rather than returning guessed structural values.
- [ ] Define deterministic leaf family creation:

```python
def leaf_family(strategy_kind: str, template_family: str, structure: ExpressionStructure) -> str:
    return f"{strategy_kind}/{template_family}/depth-{structure.order_depth}/fields-{structure.field_count}"
```

### Task 3: Strategy Registry and Shared Acceptance Pipeline

**Files:**
- Create: `alpha_operator_framework/research/strategies.py`
- Modify: `alpha_operator_framework/research/construction.py`
- Modify: `alpha_operator_framework/research/pipeline.py`

**Interfaces:**
- Produces: `CandidateDraft`
- Produces: `CandidateProvenance`
- Produces protocol: `ConstructionStrategy.generate(context: ConstructionContext, config: ConstructionStrategyConfig) -> Sequence[CandidateDraft]`
- Produces: `ConstructionStrategyRegistry.generate(plan, context) -> ConstructionOutcome`
- Produces: `CandidateAcceptancePipeline.accept(drafts, plan, known_fields) -> ConstructionOutcome`
- Produces generic builder: `AstCandidateBuilder.build_transform(parent, fields, templates, *, target_depth, target_field_count, limit_per_template, seed) -> list[CandidateDraft]`

- [ ] Add draft, provenance, context, strategy-result, and overall-outcome dataclasses. A failed requested strategy records its error and makes the outcome partial; an exhausted strategy has no error.
- [ ] Implement `DatabaseTemplateStrategy` using `build_template_library()` and translate its candidates into untrusted drafts.
- [ ] Replace fixed one-slot/two-slot stage methods internally with generic compatible-template binding that measures the rendered AST and filters by independent target constraints.
- [ ] Implement `DepthConstructionStrategy` and `FieldCompositionStrategy` over the generic builder. Sources are `raw_fields`, `qualified_candidates`, or `raw_and_qualified_candidates`; self-pairs and repeated fields that miss the configured target are rejected.
- [ ] Implement `LiteratureHypothesisStrategy` by reading only its configured document and calling `ingest_literature_to_alphas(literature_text, context.fields, title_hint=path.stem, use_llm=True, provider=config.llm_profile)`. Map tasks to drafts and never invoke platform execution from the adapter.
- [ ] In the shared pipeline: validate known fields and inaccessible operators; compute structure; enforce both constraints; canonicalize; deduplicate globally; preserve every provenance; claim duplicates by explicit strategy order; emit one canonical `Candidate` per expression.
- [ ] Expose a helper in `pipeline.py` that returns structured literature tasks without sandbox, platform, database, or report side effects so both old reporting and the new adapter share extraction/compiler code.

### Task 4: Provenance and Generalized Lineage Persistence

**Files:**
- Modify: `alpha_operator_framework/database/schema.py`
- Modify: `alpha_operator_framework/database/models.py`
- Modify: `alpha_operator_framework/database/repositories/alpha_write.py`
- Modify: `alpha_operator_framework/database/repositories/alpha_query.py`

**Interfaces:**
- Produces: `save_construction_task(task_id, settings, plan_json, seed, status) -> None`
- Produces: `save_strategy_outcome(task_id, strategy_id, kind, status, error) -> None`
- Produces: `record_candidate_provenance(settings, candidate_sha, provenance) -> bool`
- Produces: `record_construction_lineage(settings, parent_sha, child_sha, transform_kind, strategy_id) -> bool`
- Produces: `load_candidate_provenance(settings, candidate_sha) -> list[CandidateProvenanceRecord]`

- [ ] Add portable SQLAlchemy tables with unique keys:

```text
construction_tasks(task_id)
construction_strategy_runs(task_id, strategy_id)
candidate_provenance(scope_hash, candidate_sha, strategy_id, leaf_family, template_id, hypothesis_id, parent_sha)
construction_lineage(scope_hash, parent_sha, child_sha, transform_kind, strategy_id)
```

- [ ] Store complete settings-scope hashes, measured depth/field count, seed, timestamps, status, and structured error text.
- [ ] Use explicit unique-key `ON CONFLICT DO NOTHING` for provenance/lineage and `ON CONFLICT DO UPDATE` for task/strategy status so restart is idempotent and multiple provenance records coexist for one canonical candidate.
- [ ] Load active unbacktested candidates from claimed provenance rather than `MIN(round_candidates.family)`; preserve a deterministic historical fallback only for rows without new provenance, without treating old stages as new structural definitions.
- [ ] Keep `optimization_lineage` untouched as historical evidence; stop all new writes through `record_optimization_lineage()`.

### Task 5: Unified Orchestration and CLI Integration

**Files:**
- Modify: `alpha_operator_framework/application/research_loop.py`
- Modify: `alpha_operator_framework/cli/research.py`
- Modify: `alpha_operator_framework/infrastructure/runtime_factory.py`

**Interfaces:**
- Changes: `ResearchLoopCoordinator.run(policy, fields, base_candidates, *, construction_plan: ConstructionPlan, seed: int, execute: bool, base_round_id: str = "research-loop") -> ResearchLoopSummary`
- Produces: `ResearchLoopSummary.strategy_statuses` and partial-failure status propagation.

- [ ] Resolve the construction plan before fields and before candidate generation; invalid explicit configuration fails before side effects.
- [ ] For a new task, build a `ConstructionContext` from exact-scope fields, active database templates, and no parents; run the registry and persist task, strategies, candidates, provenance, and lineage before selection.
- [ ] For continuation, load canonical active candidates and existing provenance; do not regenerate completed identities.
- [ ] Derive policy family quotas from accepted candidate leaf families, each set to configured quota with a hard maximum of 8. `max_backtests` is their sum.
- [ ] Keep platform batches at eight by running deterministic slices while preserving per-leaf-family round quota over the complete research task.
- [ ] After each completed batch, load qualified parents using the explicit gate; run only configured parent-consuming strategy instances whose lineage edge is missing; do not infer `order2` or `dimension2` from family text.
- [ ] Mark one requested strategy failure as `PARTIAL_FAILED`, preserve successful work, and never print `COMPLETED`/`EXHAUSTED` for the overall task while a requested strategy failed.
- [ ] Keep `--continue-research` explicit and platform-only; do not broaden submission authorization.

### Task 6: Documentation and Runtime Example

**Files:**
- Modify: `README.md`
- Modify: `USAGE_GUIDE.md`
- Modify: `configs/alpha-factory.yaml`

- [ ] Document the four strategy kinds, independent structural axes, exact/range syntax, leaf-family quota semantics, platform shard size, parent sources/gate, and paper/LLM trust boundary.
- [ ] Show a combined explicit configuration using database templates, depth construction, field composition, and literature/LLM.
- [ ] Remove documentation that describes `base -> order2 -> dimension2` as the new runtime model; preserve historical release notes only when clearly labeled historical.

### Task 7: Add All Automated Tests After Production Code Is Complete

**Files:**
- Create: `tests/research/test_strategy_config.py`
- Create: `tests/research/test_structure.py`
- Create: `tests/research/test_strategies.py`
- Modify: `tests/research/test_construction.py`
- Create: `tests/database/test_construction_provenance.py`
- Modify: `tests/application/test_research_loop.py`
- Modify: `tests/application/test_research_cycle_command.py`
- Modify: `tests/infrastructure/test_research_runtime_factory.py`

- [ ] Add config tests for exact/range constraints, every invalid mapping, explicit strategy ordering, quota maximum 8, literature requirements, and fixed platform batch size.
- [ ] Add structural tests including `rank(close)` depth 1/field 1, `ts_rank(rank(close), 20)` depth 2/field 1, `ts_corr(rank(close), volume, 20)` depth 2/field 2, repeated `close` counting once, arithmetic/ternary operator layers, and invalid AST failure.
- [ ] Add registry tests for each adapter, independent depth/field combinations, inaccessible-operator rejection, cross-strategy deduplication, multi-provenance retention, deterministic duplicate ownership, exhausted versus failed strategies, and malformed LLM output.
- [ ] Add persistence tests for schema presence, provenance coexistence, generalized lineage idempotency, settings isolation, claimed leaf-family loading, and historical rows without provenance.
- [ ] Replace fixed-stage loop assertions with configured parent strategy assertions, missing-lineage recovery, per-leaf-family quota 8, platform slices of 8, and partial failure.
- [ ] Update CLI/runtime fixtures to include explicit construction config and assert that missing/invalid construction fails before fields/platform work.

### Task 8: Run Tests, Review the Final Diff, and Commit Once

**Files:**
- Verify all modified files from Tasks 1-7.

- [ ] Run focused construction tests with the project interpreter and a unique writable temp directory:

```powershell
$env:PYTHONPATH='D:\quant\alpha_factory'
D:\quant-venv\Scripts\python.exe -m pytest tests\research\test_strategy_config.py tests\research\test_structure.py tests\research\test_strategies.py tests\research\test_construction.py tests\database\test_construction_provenance.py tests\application\test_research_loop.py tests\application\test_research_cycle_command.py tests\infrastructure\test_research_runtime_factory.py --basetemp D:\quant\alpha_factory\.test-tmp\construction-strategy -p no:cacheprovider -q
```

Expected: all focused tests pass; no live BRAIN call is made.

- [ ] Run the broader research regression suite:

```powershell
D:\quant-venv\Scripts\python.exe -m pytest tests\research tests\application tests\infrastructure --basetemp D:\quant\alpha_factory\.test-tmp\construction-regression -p no:cacheprovider -q
```

Expected: all collected tests pass, or any unrelated pre-existing collection blocker is captured and reported separately without weakening focused acceptance.

- [ ] Compile changed production modules:

```powershell
D:\quant-venv\Scripts\python.exe -m compileall -q alpha_operator_framework
```

Expected: exit code 0.

- [ ] Review `git diff --check`, `git status --short`, and the complete diff. Confirm no credentials, generated browser companion files, temporary test files, unrelated user changes, or raw logs are staged.
- [ ] Stage only the implementation, tests, configuration, documentation, and this plan; create one commit:

```powershell
git add alpha_operator_framework configs tests README.md USAGE_GUIDE.md docs/superpowers/plans/2026-08-28-alpha-construction-strategy.md
git commit -m "feat: unify alpha construction strategies"
```
