# DDD Selection Governance Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the DDD cycle safe in dry-run mode, reproducible, and compliant with the approved selection–pruning–feedback design.

**Architecture:** Application use cases select an explicit execution gateway and pass immutable policy plus knowledge snapshot into pure selection policies. Pre- and post-backtest pruning decisions become append-only facts that update the next round's knowledge snapshot. NSGA-II runs only after real result evaluation.

**Tech Stack:** Python 3.10+, dataclasses, existing Alpha AST validator/canonicalizer, SQLite, pytest.

## Global Constraints

- Dry-run is the default and must not instantiate or call BRAIN adapters.
- `--execute` enables real backtests; `--authorize-submission` also requires `--execute`.
- Field snapshot, complete policy, knowledge snapshot, and seed reproduce every decision.
- Domain code has no I/O dependency.
- Do not edit working-tree changes outside DDD, its tests, `alpha_machine.py`, and docs.

---

### Task 1: Enforce execution authorization

**Files:**

- Modify: `alpha_operator_framework/ddd/application/models.py`
- Modify: `alpha_operator_framework/ddd/application/use_cases/orchestrator.py:155-197, 337-425`
- Modify: `alpha_operator_framework/ddd/infrastructure/gateways/in_memory_gateways.py`
- Modify: `alpha_operator_framework/ddd/infrastructure/gateways/brain_gateway.py:23-74`
- Modify: `alpha_machine.py:789-878`
- Create: `tests/ddd/test_execution_authorization.py`

**Interfaces:** `DryRunBacktestGateway.submit_and_poll_batch(...) -> []`; `validate_execution_flags(execute_platform, authorize_submission) -> None`.

- [ ] **Step 1: Write the failing test**

```python
def test_dry_run_never_calls_live_gateway(cycle_with_spies):
    summary = cycle_with_spies.execute(ResearchCycleRequest(execute_platform=False))
    assert summary.status == "PLANNED"
    assert cycle_with_spies.live_gateway.submitted_batches == []

def test_submission_requires_live_execution():
    with pytest.raises(ValueError, match="--authorize-submission requires --execute"):
        validate_execution_flags(execute_platform=False, authorize_submission=True)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/ddd/test_execution_authorization.py -q`

Expected: FAIL because all cycles call `submit_and_poll_batch`.

- [ ] **Step 3: Implement the minimal behavior**

```python
class DryRunBacktestGateway(BacktestGatewayPort):
    def submit_and_poll_batch(self, tasks, settings, idempotency_key):
        return []

def validate_execution_flags(*, execute_platform, authorize_submission):
    if authorize_submission and not execute_platform:
        raise ValueError("--authorize-submission requires --execute")
```

Select this gateway in `command_research_cycle`. For a dry run, stop after selection and return `PLANNED`; do not evaluate, optimize, submit, distill, or feed back. Make `BrainPlatformGateway.submit_approved_case` raise `NotImplementedError` until it calls a verified platform submit endpoint.

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/ddd/test_execution_authorization.py tests/ddd/test_research_cycle_use_case.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

Run: `git add alpha_machine.py alpha_operator_framework/ddd/application alpha_operator_framework/ddd/infrastructure/gateways tests/ddd; git commit -m "fix: enforce ddd execution authorization"`

### Task 2: Make policy and AST decisions reproducible

**Files:**

- Modify: `alpha_operator_framework/ddd/domain/candidate_exploration/models.py`
- Modify: `alpha_operator_framework/ddd/domain/candidate_exploration/services.py`
- Modify: `alpha_operator_framework/ddd/infrastructure/persistence/sqlite_repositories.py:135-177`
- Modify: `tests/ddd/test_pre_post_pruning.py`
- Modify: `tests/ddd/test_sqlite_persistence.py`

**Interfaces:** `SamplingWeights`, `PruningRules`, `ResearchPolicy.to_dict()`, `ResearchPolicy.from_dict()`, and `SelectionKnowledgeSnapshot`.

- [ ] **Step 1: Write the failing tests**

```python
def test_policy_round_trip_preserves_all_decision_inputs():
    policy = ResearchPolicy(
        budget=Budget(max_backtested=7),
        weights=SamplingWeights(field=2.0, operator=0.5, template=1.5),
        pruning=PruningRules(prohibited_patterns=("ts_delta(ts_delta",)),
    )
    assert ResearchPolicy.from_dict(policy.to_dict()) == policy

def test_pre_pruning_uses_ast_canonical_equivalence():
    kept, rejected = pre_prune(["add(a,b)", "add(b,a)"])
    assert rejected[0].reason_code == "AST_CANONICAL_DUPLICATE"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/ddd/test_pre_post_pruning.py tests/ddd/test_sqlite_persistence.py -q`

Expected: FAIL because current persistence stores four policy fields and pruning hashes whitespace-normalized text.

- [ ] **Step 3: Implement the minimal behavior**

```python
@dataclass(frozen=True)
class SamplingWeights:
    field: float = 1.0
    operator: float = 1.0
    template: float = 1.0
    novelty: float = 1.0
    uncertainty: float = 1.0
```

Use `validate_expression` and `to_canonical_string` from the existing AST package before hashing. Serialize `asdict(policy)` and reconstruct nested `Budget`, `SamplingWeights`, and `PruningRules`; add knowledge snapshot version and payload to the selection-round record.

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/ddd/test_pre_post_pruning.py tests/ddd/test_sqlite_persistence.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

Run: `git add alpha_operator_framework/ddd/domain/candidate_exploration alpha_operator_framework/ddd/infrastructure/persistence tests/ddd; git commit -m "feat: persist reproducible ddd selection policy"`

### Task 3: Close the selection–pruning–feedback loop

**Files:**

- Modify: `alpha_operator_framework/ddd/domain/candidate_exploration/{models,services}.py`
- Modify: `alpha_operator_framework/ddd/domain/candidate_exploration/policies/{stratified,d_optimal,thompson}.py`
- Modify: `alpha_operator_framework/ddd/domain/knowledge_and_submission/{models,services}.py`
- Modify: `alpha_operator_framework/ddd/application/use_cases/orchestrator.py:120-150, 308-334, 390-402`
- Create: `tests/ddd/test_feedback_loop.py`
- Modify: `tests/ddd/test_selection_policies.py`

**Interfaces:** `SelectionKnowledgeSnapshot(field_stats, operator_stats, template_stats, prune_rules, version)` supplies all selection policies; every selection decision returns component scores.

- [ ] **Step 1: Write the failing tests**

```python
def test_weighted_sampling_prefers_positive_evidence():
    decisions = policy.select(candidates, research_policy, rng, knowledge)
    assert selected_ids(decisions) == {"high_evidence_candidate"}

def test_pruning_feedback_changes_next_round():
    feedback = feedback_builder.build_feedback(results, post_prunes, distilled)
    assert "noisy_template" in feedback.knowledge_snapshot.prune_rules
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/ddd/test_selection_policies.py tests/ddd/test_feedback_loop.py -q`

Expected: FAIL because current sampling ignores weights and receives no knowledge; pruning rules are passed as an empty list.

- [ ] **Step 3: Implement the minimal behavior**

```python
score = (
    policy.weights.field * knowledge.field_score(candidate.fields)
    + policy.weights.operator * knowledge.operator_score(candidate.operators)
    + policy.weights.template * knowledge.template_score(candidate.template_id)
    + policy.weights.novelty * candidate.novelty_score
    + policy.weights.uncertainty * knowledge.uncertainty(candidate)
)
```

Add `operators`, `template_id`, and `novelty_score` to `Candidate`; populate them in `CandidateFactory`. Use scores inside family quotas for weighted sampling. Make D-optimal use candidate feature vectors and determinant gain; make Thompson/UCB aggregate posterior evidence for field, operator, and template. Load KnowledgeBase before selection, pass its immutable snapshot to the selection use case, then build and persist feedback from both results and post-pruning decisions.

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/ddd/test_selection_policies.py tests/ddd/test_feedback_loop.py -q`

Expected: PASS; fixed inputs and seed remain deterministic while evidence changes the next round.

- [ ] **Step 5: Commit**

Run: `git add alpha_operator_framework/ddd/domain alpha_operator_framework/ddd/application tests/ddd; git commit -m "feat: close ddd selection pruning feedback loop"`

### Task 4: Move NSGA-II after evaluation

**Files:**

- Replace: `alpha_operator_framework/ddd/domain/candidate_exploration/policies/nsga2.py`
- Modify: `alpha_operator_framework/ddd/domain/experiment_governance/services.py`
- Modify: `alpha_operator_framework/ddd/application/use_cases/orchestrator.py:225-238, 369-378`
- Modify: `alpha_machine.py:789`
- Modify: `tests/ddd/test_selection_policies.py`
- Modify: `tests/ddd/test_research_cycle_use_case.py`

**Interfaces:** `NsgaMutationService.propose(batch, candidate_lookup, random_source) -> MutationProposal[]`; consumes only evaluated, unpruned Pareto rank-1 results.

- [ ] **Step 1: Write the failing tests**

```python
def test_nsga_mutates_only_ready_non_pruned_parents():
    proposals = mutation_service.propose(batch, candidates, rng)
    assert {p.parent_task_id for p in proposals} == {"ready_non_pruned_task"}

def test_nsga_is_not_a_first_round_cli_sampler():
    assert "nsga2" not in research_cycle_algorithm_choices()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/ddd/test_selection_policies.py tests/ddd/test_research_cycle_use_case.py -q`

Expected: FAIL because NSGA-II is currently selected before any results exist.

- [ ] **Step 3: Implement the minimal behavior**

Use non-dominated sorting over Sharpe (max), Fitness (max), turnover (min), margin (max), and correlation (min when available); use crowding distance only to break ties. Mutate one typed AST operator or parameter per selected parent, validate and canonicalize each child, and record `lineage_parent_id`. Remove `nsga2` from `--algorithm`; expose its mutation budget in ResearchPolicy and run it only after evaluation.

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/ddd/test_selection_policies.py tests/ddd/test_research_cycle_use_case.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

Run: `git add alpha_machine.py alpha_operator_framework/ddd/domain alpha_operator_framework/ddd/application tests/ddd; git commit -m "fix: run nsga evolution after ddd evaluation"`

### Task 5: Verify replay and correct documentation

**Files:**

- Modify: `README.md`
- Modify: `QUICKSTART.md`
- Modify: `tests/ddd/test_research_cycle_use_case.py`

- [ ] **Step 1: Write the failing replay test**

```python
def test_same_snapshots_policy_and_seed_replay_same_selection(cycle_factory):
    first = cycle_factory().execute(request(seed=7, execute_platform=False))
    second = cycle_factory().execute(request(seed=7, execute_platform=False))
    assert first.decisions_audit == second.decisions_audit
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/ddd/test_research_cycle_use_case.py -q`

Expected: FAIL until the summary exposes persisted decisions and snapshot versions.

- [ ] **Step 3: Implement audit output and accurate docs**

Expose policy version, knowledge version, seed, selected IDs, and pruning reason counts in `ResearchCycleSummary.decisions_audit`. Describe dry-run as planning only and describe production submission as unavailable until the BRAIN submit adapter is verified.

- [ ] **Step 4: Run all verification**

Run: `python -m pytest tests/ddd -q`

Expected: PASS.

Run: `python -m pytest -q`

Expected: all existing and DDD tests PASS.

- [ ] **Step 5: Commit**

Run: `git add README.md QUICKSTART.md alpha_operator_framework/ddd tests/ddd; git commit -m "test: verify ddd research cycle replay"`

## Self-Review

- Coverage: Tasks cover dry-run safety, platform boundaries, complete replayable policy, AST validation, weighted and evidence-driven selection, pruning feedback, post-result NSGA-II, persistence, tests, and documentation.
- Scope: The plan changes only the DDD path and its CLI adapter; legacy workflow is not modified.
- Consistency: The same `SelectionKnowledgeSnapshot` is persisted with `SelectionRound`, consumed by policies, and regenerated only after completed post-backtest pruning.
