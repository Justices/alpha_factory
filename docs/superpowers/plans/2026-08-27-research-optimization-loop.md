# Research Optimization Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make continuous research persist, backtest, prune, and optimize candidates until base and optimization queues are empty.

**Architecture:** `ResearchLoopCoordinator` owns cross-batch decisions. Existing planner and worker retain one-round selection, execution, retry, and evaluation responsibilities; SQLite stores settings-scoped pruning rules and idempotent parent-child lineage.

**Tech Stack:** Python 3.12, pytest, SQLite, SQLAlchemy schema bootstrap.

## Global Constraints

- Signal parent: `sharpe > 1.25` and `fitness > 0.8`.
- Consensus pruning: 3 distinct fields, 4 samples, 80% failures, average Sharpe `<= 0.1`, no signal parent.
- Scope: region, universe, delay, decay, neutralization, truncation.
- Prune only `generated`/`pending`, active expressions; never overwrite backtest lifecycle.
- Stages: `base -> order2 -> dimension2 -> done`.
- All active compatible templates participate; cap is 200 deterministic combinations per template/stage.
- Selection remains 20 per family; platform submissions remain chunks of 8.

---

### Task 1: Persist scoped pruning and lineage

**Files:**

- Modify: `alpha_operator_framework/database/schema.py`
- Modify: `alpha_operator_framework/database/repositories/alpha_write.py`
- Modify: `alpha_operator_framework/database/repositories/alpha_query.py`
- Test: `tests/test_domain_repositories.py`

**Interfaces:**

- `settings_scope_hash(settings: Mapping[str, object]) -> str`
- `upsert_result_prune_rule(scope_hash: str, pattern: str, pattern_type: str, reason: str) -> None`
- `get_result_prune_rules(scope_hash: str) -> list[dict[str, str]]`
- `prune_unbacktested_matching(scope_hash: str, rules: Sequence[Mapping[str, str]]) -> list[str]`
- `record_optimization_lineage(scope_hash: str, parent_alpha_sha: str, child_alpha_sha: str, stage: str) -> bool`

- [ ] **Step 1: Write failing repository tests**

```python
def test_scoped_rule_prunes_only_pending_expressions(tmp_path):
    db = AlphaDatabase(tmp_path / "scoped.db")
    usa = {"region": "USA", "universe": "TOP3000", "delay": 1, "decay": 8,
           "neutralization": "SUBINDUSTRY", "truncation": 0.08}
    eur = {**usa, "region": "EUR", "universe": "TOP2500"}
    db.insert_expression("rank(close)", usa, status="generated")
    db.insert_expression("rank(close)", eur, status="generated")
    db.insert_expression("rank(open)", usa, status="completed")
    scope = db.settings_scope_hash(usa)
    db.upsert_result_prune_rule(scope, "rank(", "prefix", "consensus failure")

    assert db.prune_unbacktested_matching(scope, db.get_result_prune_rules(scope)) == [db.compute_alpha_sha("rank(close)", usa)]
    assert db.get_expression_by_alpha_sha(db.compute_alpha_sha("rank(close)", eur)).pruning_status == "active"
    assert db.get_expression_by_alpha_sha(db.compute_alpha_sha("rank(open)", usa)).status == "completed"


def test_lineage_insert_is_idempotent(tmp_path):
    db = AlphaDatabase(tmp_path / "lineage.db")
    assert db.record_optimization_lineage("scope", "parent", "child", "order2") is True
    assert db.record_optimization_lineage("scope", "parent", "child", "order2") is False
```

- [ ] **Step 2: Verify red**

Run: `pytest tests/test_domain_repositories.py -k "scoped_rule or lineage" -v`

Expected: FAIL because the repository methods do not exist.

- [ ] **Step 3: Implement minimal persistence**

```python
Table("result_prune_rules", metadata, _id(), _text("scope_hash", key=True, nullable=False),
      _text("pattern", key=True, nullable=False), _text("pattern_type", key=True, nullable=False),
      _text("reason", nullable=False), _text("created_at", nullable=False), _text("updated_at", nullable=False),
      UniqueConstraint("scope_hash", "pattern", "pattern_type"))
Table("optimization_lineage", metadata, _id(), _text("scope_hash", key=True, nullable=False),
      _text("parent_alpha_sha", key=True, nullable=False), _text("child_alpha_sha", key=True, nullable=False),
      _text("stage", key=True, nullable=False), _text("created_at", nullable=False), _text("updated_at", nullable=False),
      UniqueConstraint("scope_hash", "parent_alpha_sha", "child_alpha_sha", "stage"))
```

Build the scope hash from exactly the six configured setting keys. Use `ON CONFLICT` for writes. Pruning must load active `generated`/`pending` rows from the matching serialized settings and use existing `matches_prune_rule` before updating `alpha_expressions` and linked `round_candidates`.

- [ ] **Step 4: Verify green**

Run: `pytest tests/test_domain_repositories.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

Run: `git add alpha_operator_framework/database/schema.py alpha_operator_framework/database/repositories/alpha_write.py alpha_operator_framework/database/repositories/alpha_query.py tests/test_domain_repositories.py && git commit -m "feat: persist scoped pruning and optimization lineage"`

### Task 2: Classify signals and derive consensus rules

**Files:**

- Create: `alpha_operator_framework/research/optimization.py`
- Test: `tests/research/test_optimization.py`

**Interfaces:**

- `is_signal_parent(result: BacktestResult) -> bool`
- `derive_consensus_prune_rules(rows: Sequence[CompletedExpression]) -> list[ResultPruneRule]`

- [ ] **Step 1: Write failing pure-function tests**

```python
def test_signal_thresholds_are_strict():
    assert not is_signal_parent(_result(1.25, 0.81))
    assert not is_signal_parent(_result(1.26, 0.8))
    assert is_signal_parent(_result(1.26, 0.81))


def test_consensus_pruning_requires_cross_field_failures_and_gold_shield():
    failures = [_row(f"rank(f{i})", (f"f{i}",), 0.0, 0.0) for i in range(4)]
    assert derive_consensus_prune_rules(failures) == [ResultPruneRule("rank(", "prefix")]
    assert derive_consensus_prune_rules([*failures, _row("rank(winner)", ("winner",), 1.26, 0.81)]) == []
```

- [ ] **Step 2: Verify red**

Run: `pytest tests/research/test_optimization.py -v`

Expected: FAIL because the module does not exist.

- [ ] **Step 3: Implement pure policy**

```python
SIGNAL_SHARPE = 1.25
SIGNAL_FITNESS = 0.8

def is_signal_parent(result: BacktestResult) -> bool:
    return result.sharpe > SIGNAL_SHARPE and result.fitness > SIGNAL_FITNESS
```

Group completed rows by the existing template skeleton abstraction. Emit stable prefix rules only when all confirmed thresholds are met. A signal parent shields its complete skeleton from pruning.

- [ ] **Step 4: Verify green**

Run: `pytest tests/research/test_optimization.py tests/experiment/test_mutation.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

Run: `git add alpha_operator_framework/research/optimization.py tests/research/test_optimization.py && git commit -m "feat: derive signal and pruning decisions"`

### Task 3: Generate order-two and dimension-two candidates

**Files:**

- Modify: `alpha_operator_framework/research/construction.py`
- Test: `tests/research/test_construction.py`

**Interfaces:**

- `build_order2(parent: Candidate, templates: Sequence[Template], limit_per_template: int = 200) -> list[Candidate]`
- `build_dimension2(parent: Candidate, fields: Sequence[FieldSpec], templates: Sequence[Template], limit_per_template: int = 200, seed: int | None = None) -> list[Candidate]`

- [ ] **Step 1: Write failing builder tests**

```python
def test_order2_uses_all_compatible_templates_and_excludes_vector_neut():
    candidates = AstCandidateBuilder().build_order2(_parent(), _templates(), limit_per_template=200)
    assert {candidate.template_id for candidate in candidates} == {"rank_template", "zscore_template"}
    assert all("vector_neut" not in candidate.expression for candidate in candidates)


def test_dimension2_uses_only_different_same_category_fields_and_caps_each_template():
    candidates = AstCandidateBuilder().build_dimension2(_parent(), _fields(300), _pair_templates(), seed=7)
    assert len(candidates) == 200
    assert all("close" in candidate.fields and "open" in candidate.fields for candidate in candidates)
    assert all("volume" not in candidate.fields for candidate in candidates)
```

- [ ] **Step 2: Verify red**

Run: `pytest tests/research/test_construction.py -k "order2 or dimension2" -v`

Expected: FAIL because the builder methods do not exist.

- [ ] **Step 3: Implement bounded generation**

```python
def build_order2(self, parent, templates, *, limit_per_template=200):
    return self._build_optimization_tasks(parent, (), templates, "order2", limit_per_template)

def build_dimension2(self, parent, fields, templates, *, limit_per_template=200, seed=None):
    partners = [field for field in fields if field.category == self._parent_category(parent) and field.id not in parent.fields]
    return self._build_optimization_tasks(parent, preprocess_fields_rotated(partners, seed=seed), templates, "dimension2", limit_per_template)
```

Reuse `template_creation_strategy`, existing AST validation, canonicalization, and candidate identity. Emit `optimization_order2` or `optimization_dimension2` families. Reject `vector_neut`, self-pairs, invalid ASTs, and duplicates.

- [ ] **Step 4: Verify green**

Run: `pytest tests/research/test_construction.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

Run: `git add alpha_operator_framework/research/construction.py tests/research/test_construction.py && git commit -m "feat: generate optimization candidates"`

### Task 4: Coordinate the closed loop

**Files:**

- Create: `alpha_operator_framework/application/research_loop.py`
- Test: `tests/application/test_research_loop.py`

**Interfaces:**

- `ResearchLoopCoordinator(runtime: ResearchRuntime)`
- `run(policy: ResearchPolicy, fields: Sequence[FieldSpec], base_candidates: Sequence[Candidate], seed: int, execute: bool) -> ResearchLoopSummary`

- [ ] **Step 1: Write failing coordinator tests**

```python
def test_loop_runs_base_then_order2_then_dimension2_and_exhausts(runtime, fields):
    summary = ResearchLoopCoordinator(runtime).run(POLICY, fields, [_base()], seed=7, execute=True)
    assert summary.status == "EXHAUSTED"
    assert _backtested_families(runtime) == ["base", "optimization_order2", "optimization_dimension2"]


def test_loop_prunes_only_unbacktested_matches_after_evaluation(runtime, fields):
    summary = ResearchLoopCoordinator(runtime).run(POLICY, fields, _failed_rank_candidates(), seed=7, execute=True)
    assert summary.pruned_count == 1
    assert _completed(runtime, "rank(f0)").pruning_status == "active"
    assert _pending(runtime, "rank(unseen)").pruning_status == "pruned"


def test_loop_stops_failed_round_without_pruning_or_promotion(runtime, fields):
    summary = ResearchLoopCoordinator(runtime).run(POLICY, fields, [_base()], seed=7, execute=True)
    assert summary.status == "FAILED"
    assert summary.generated_optimization_count == 0
```

- [ ] **Step 2: Verify red**

Run: `pytest tests/application/test_research_loop.py -v`

Expected: FAIL because the coordinator does not exist.

- [ ] **Step 3: Implement coordinator iterations**

```python
while True:
    candidates = self._load_optimization_candidates(policy) or self._load_base_candidates(policy, base_candidates)
    if not candidates:
        return ResearchLoopSummary("EXHAUSTED", round_ids, completed, pruned, generated)
    summary = self._plan_and_process(policy, candidates, seed, execute)
    if summary.status != "COMPLETED":
        return ResearchLoopSummary(summary.status, round_ids, completed, pruned, generated)
    pruned += self._apply_consensus_pruning(policy)
    generated += self._generate_missing_stages(policy, fields, summary.round_id, seed)
```

Read optimized candidates before base candidates. Persist every generated child before inserting its idempotent lineage edge. Load completed results by full settings scope, then use Task 2 rules. Generate `order2` from base signal parents and `dimension2` from signal order2 parents only.

- [ ] **Step 4: Verify green**

Run: `pytest tests/application/test_research_loop.py tests/application/test_research_worker.py tests/application/test_research_cycle.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

Run: `git add alpha_operator_framework/application/research_loop.py tests/application/test_research_loop.py && git commit -m "feat: coordinate continuous research optimization"`

### Task 5: Delegate continuous CLI execution to the coordinator

**Files:**

- Modify: `alpha_operator_framework/cli/research.py`
- Test: `tests/cli/test_research_command.py`

- [ ] **Step 1: Write failing CLI tests**

```python
def test_continue_research_delegates_to_closed_loop(monkeypatch, capsys):
    coordinator = FakeCoordinator("EXHAUSTED", 24)
    monkeypatch.setattr(research, "ResearchLoopCoordinator", lambda runtime: coordinator)
    research.command_research_cycle(_args(continue_research=True, execute=True))
    assert coordinator.calls == 1
    assert "EXHAUSTED" in capsys.readouterr().out


def test_continue_research_requires_execute():
    with pytest.raises(ValueError, match="requires --execute"):
        research.command_research_cycle(_args(continue_research=True, execute=False))
```

- [ ] **Step 2: Verify red**

Run: `pytest tests/cli/test_research_command.py -k continue_research -v`

Expected: FAIL because the CLI owns the loop.

- [ ] **Step 3: Replace CLI loop with delegation**

```python
if args.continue_research:
    if not args.execute:
        raise ValueError("--continue-research requires --execute")
    summary = ResearchLoopCoordinator(runtime).run(policy, fields, candidates, seed=options.get("seed", 42), execute=True)
else:
    summary = runtime.plan(ResearchCycleRequest(base_round_id, options.get("seed", 42), policy, runtime.knowledge_base.snapshot(), candidates, args.execute))
    if args.execute:
        summary = runtime.process_round(summary.round_id)
```

Remove the dynamic exhausted `type("Summary", ...)` fallback. Preserve the command's output format.

- [ ] **Step 4: Verify green**

Run: `pytest tests/cli/test_research_command.py tests/cli/test_command_registry.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

Run: `git add alpha_operator_framework/cli/research.py tests/cli/test_research_command.py && git commit -m "feat: delegate continuous research loop"`

### Task 6: Verify end-to-end behavior

**Files:**

- Modify: `docs/superpowers/specs/2026-08-27-research-optimization-loop-design.md`

- [ ] **Step 1: Run focused regressions**

Run: `pytest tests/test_domain_repositories.py tests/research/test_optimization.py tests/research/test_construction.py tests/application/test_research_loop.py tests/application/test_research_worker.py tests/application/test_research_cycle.py tests/cli/test_research_command.py tests/cli/test_command_registry.py -v`

Expected: PASS.

- [ ] **Step 2: Compile production code**

Run: `python -m compileall -q alpha_operator_framework`

Expected: exit code 0.

- [ ] **Step 3: Record evidence**

```markdown
## Implementation Verification

- Focused pytest suite: passed on 2026-08-27.
- Python compilation: passed on 2026-08-27.
```

- [ ] **Step 4: Commit verification record**

Run: `git add docs/superpowers/specs/2026-08-27-research-optimization-loop-design.md && git commit -m "docs: record research loop verification"`
