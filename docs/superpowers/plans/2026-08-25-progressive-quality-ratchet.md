# Progressive Quality Ratchet Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Scan the entire Python tree and prevent new lint, type, coverage, or dead-code debt without rewriting existing unrelated code.

**Architecture:** Keep the current zero-error scoped checks, then run full-tree tools through a deterministic fingerprinting script and compare results to a committed baseline. Coverage uses a numeric floor; tool crashes fail closed.

**Tech Stack:** Python 3.12, Ruff 0.12.11, Mypy 1.17.1, coverage.py 7.15.4, Vulture 2.16, pytest 8.4.2.

## Global Constraints

- Existing debt is baselined, never silently deleted or auto-fixed; deleted compatibility files are removed from strict scopes and the baseline.
- CI fails on a new fingerprint, coverage decrease, missing scan target, malformed baseline, or tool crash.
- Baseline updates require the explicit `baseline --update` command and are never performed by CI.
- Chat and CI output contain summaries, not full raw tool logs.
- Each reviewed task may create one focused local commit; never push.

---

### Task 1: Define the baseline schema and comparison contract

**Files:**
- Create: `alpha_operator_framework/quality/__init__.py`
- Create: `alpha_operator_framework/quality/ratchet.py`
- Create: `tests/quality/test_quality_ratchet.py`

**Interfaces:**
- Produces: `Issue(tool, path, code, line, message)`, `fingerprint(issue)`, `compare(current, baseline)`, and JSON schema version `1`.

- [ ] **Step 1: Write failing unit tests for normalization and regressions**

```python
def test_compare_rejects_only_new_issue_fingerprints():
    baseline = {"ruff": ["a.py|F401|unused import"]}
    current = {"ruff": ["a.py|F401|unused import", "b.py|F821|missing"]}
    result = compare(current, baseline)
    assert result.new_issues == {"ruff": ["b.py|F821|missing"]}
    assert not result.passed


def test_compare_rejects_coverage_drop():
    result = compare({"coverage": 71.9}, {"coverage": 72.0})
    assert not result.passed
```

Also cover path separator normalization, line-number-independent fingerprints, schema mismatch, missing tool output, and stable JSON ordering.

- [ ] **Step 2: Run RED verification**

Run the new unit test file. Expected: import failure because the quality package does not exist.

- [ ] **Step 3: Implement immutable result models and comparison**

Use frozen dataclasses, `Path.as_posix()`, sorted sets, and a `BaselineError` for invalid schema. Fingerprints are `path|code|normalized_message`; exclude line numbers so harmless movement does not invalidate history.

- [ ] **Step 4: Run GREEN verification**

Expected: all comparison tests pass without invoking external tools.

---

### Task 2: Add deterministic tool adapters and CLI

**Files:**
- Create: `tools/quality_ratchet.py`
- Modify: `alpha_operator_framework/quality/ratchet.py`
- Create: `tests/quality/test_quality_ratchet_cli.py`

**Interfaces:**
- Produces: `check --baseline quality-baseline.json` and `baseline --update --baseline quality-baseline.json`.

- [ ] **Step 1: Write failing subprocess-adapter tests**

Inject a command runner and assert Ruff JSON, per-file Mypy text, coverage JSON, and Vulture text normalize into Issues. Assert nonzero tool exit with parseable findings is accepted as findings, while timeout, invalid output, or traceback becomes `ToolFailure`.

- [ ] **Step 2: Implement adapters**

Run:

```text
python -m ruff check --isolated --output-format json alpha_operator_framework tests tools
python -m mypy <one package/file shard> --follow-imports skip --ignore-missing-imports --no-incremental
python -m coverage json -o <temporary-file>
python -m vulture alpha_operator_framework tools --min-confidence 80
```

Enumerate Mypy shards with `rg --files alpha_operator_framework -g '*.py'`; each file appears exactly once. Use `tempfile.TemporaryDirectory` outside the repository for transient reports.

- [ ] **Step 3: Implement CLI exit semantics**

`check` returns `0` only when there are no new fingerprints and coverage meets the baseline; `baseline --update` writes schema version, tool versions, sorted fingerprints, coverage floor, and scan file count using atomic replacement.

- [ ] **Step 4: Verify focused CLI tests**

Tests use fake runners only and never depend on the current repository debt.

---

### Task 3: Add coverage/dead-code dependencies and establish the baseline

**Files:**
- Modify: `requirements-dev.txt`
- Modify: `pyproject.toml`
- Create: `quality-baseline.json`
- Create: `tests/quality/test_quality_baseline.py`

**Interfaces:**
- Consumes: the CLI from Task 2.
- Produces: pinned reproducible tools and current baseline.

- [ ] **Step 1: Add a failing configuration contract test**

Assert exact pins `coverage==7.15.4` and `vulture==2.16`, branch coverage enabled, source set to `alpha_operator_framework`, and baseline schema/file count match the repository.

- [ ] **Step 2: Add pins and coverage configuration**

```toml
[tool.coverage.run]
branch = true
source = ["alpha_operator_framework"]

[tool.coverage.report]
show_missing = true
skip_covered = true
```

- [ ] **Step 3: Measure coverage and generate the initial baseline**

Run full pytest under coverage, then `quality_ratchet.py baseline --update`. Set the absolute coverage floor to the measured percentage rounded down to the nearest whole number; never invent a higher threshold.

- [ ] **Step 4: Prove the ratchet fails on a synthetic regression**

Copy the baseline to a temporary directory, inject one fake fingerprint through the runner seam, and assert exit code `1`; leave the committed baseline unchanged.

---

### Task 4: Wire the ratchet into CI and documentation

**Files:**
- Modify: `.github/workflows/recovery-drill.yml`
- Modify: `tests/test_quality_configuration.py`
- Modify: `README.md`

**Interfaces:**
- Produces: one local/CI command for full quality verification.

- [ ] **Step 1: Extend the failing CI contract test**

Assert CI runs full pytest through coverage before `python tools/quality_ratchet.py check --baseline quality-baseline.json`, while existing scoped Ruff/Mypy commands remain.

- [ ] **Step 2: Update workflow and concise developer commands**

Document `check`, explicit baseline update, and the rule that baseline updates require reviewing removed/added fingerprints.

- [ ] **Step 3: Run complete verification**

Install pinned dev dependencies, run strict Ruff/Mypy, full pytest+coverage, ratchet check, compileall, and diff check. Expected: all commands exit zero.
