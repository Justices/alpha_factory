# Template Promotion Chain Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan inline. The user requires production code first, tests afterward, and one final commit; this overrides per-task TDD and frequent commits.

**Goal:** Complete the durable feedback loop from qualified Alpha results to reusable `database_template` candidates using only `template_library`.

**Architecture:** `ResearchBatchWorker` distills qualified results and sends complete `DistilledTemplate` evidence to `AlphaDatabase.save_abstracted_template()`. The repository merges evidence into the deterministic `template_library` row, while `ResearchLoopCoordinator` continues loading active catalog rows into the unified construction registry.

**Tech Stack:** Python, SQLite/SQLAlchemy schema facade, typed dataclasses, pytest.

## Global Constraints

- `template_library` is the only template-promotion source of truth.
- Do not restore `template_promotions` or `SqlAlchemyTemplatePromotionRepository`.
- Complete all production code before adding or running tests.
- Run verification once after all test changes, then create one final commit.
- Preserve static template behavior and existing database rows.

---

### Task 1: Merge Durable Promotion Evidence

**Files:**
- Modify: `alpha_operator_framework/database/repositories/template.py`
- Modify: `alpha_operator_framework/application/research_worker.py`

**Interfaces:**
- Change: `save_abstracted_template(..., source_task_ids: Sequence[str] = ()) -> bool`
- Preserve: deterministic `evolved_<hash>` identity and active `Template` row.

- [ ] Normalize source task IDs to a sorted unique list.
- [ ] Load the existing deterministic row before writing.
- [ ] Merge existing and incoming IDs; make support the maximum of legacy support and merged evidence size.
- [ ] Update `source_json`, description, and timestamps without replacing the first non-empty example expression.
- [ ] Pass every `DistilledTemplate.source_task_ids` value from the worker.
- [ ] Remove the unused optional promotion-repository write and runtime dependency.

### Task 2: Remove the Obsolete Parallel Projection

**Files:**
- Modify: `alpha_operator_framework/application/research_runtime.py`
- Modify: `alpha_operator_framework/application/research_worker.py`
- Modify: `alpha_operator_framework/infrastructure/runtime_factory.py`
- Delete: `tests/infrastructure/test_template_promotion_repository.py`

**Interfaces:**
- `ResearchRuntime` no longer exposes `template_repository`.
- `ResearchBatchWorker` no longer accepts a second promotion repository.

- [ ] Remove the dead constructor/dataclass argument and all `None` wiring.
- [ ] Keep event emission and `template_library` persistence as the single worker path.
- [ ] Delete only the test that imports the removed compatibility repository.

### Task 3: Add End-to-End Persistence and Consumption Tests

**Files:**
- Modify: `tests/test_domain_repositories.py`
- Modify: `tests/application/test_research_worker.py`
- Modify: `tests/application/test_research_runtime.py`
- Modify: `tests/research/test_strategies.py`
- Create: `tests/application/test_template_promotion_chain.py`

**Interfaces:**
- Verify repository reopen durability.
- Verify `DatabaseTemplateStrategy.generate()` consumes the promoted row.

- [ ] Test duplicate source IDs are idempotent and new IDs merge.
- [ ] Test legacy support remains a lower bound after evidence upgrade.
- [ ] Test the worker passes the full task lineage into `source_json`.
- [ ] Test an evolved row loaded from `template_library` renders through `database_template` and shared acceptance.
- [ ] Update runtime/worker fixtures for the removed compatibility argument.

### Task 4: Final Verification and Single Commit

**Files:** all files above plus the design and plan documents.

- [ ] Run focused repository, worker, runtime, strategy, and chain tests with `D:\quant-venv\Scripts\python.exe` and a unique `--basetemp`.
- [ ] Run full pytest collection and the broader affected suite; report unrelated failures separately.
- [ ] Run `python -m compileall -q alpha_operator_framework` and `git diff --check`.
- [ ] Confirm no temporary files or unrelated changes are staged.
- [ ] Commit once with `fix: complete template promotion feedback loop`.
