# Lazy Package Bootstrap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve the package-root API while reducing cold package and CLI help startup from about 4.9 seconds to below 1.5 seconds locally.

**Architecture:** Replace eager package-root imports with one declarative export registry and PEP 562 lazy attribute resolution. Production modules import defining modules directly; compatibility remains at the package root.

**Tech Stack:** Python 3.12, importlib, subprocess, pytest, Ruff, Mypy.

## Global Constraints

- Preserve every current name in `alpha_operator_framework.__all__` through canonical modules; no export may target a deleted compatibility module.
- Unknown attributes raise `AttributeError`; resolved attributes are cached in package globals.
- CI performance ceiling is 2.5 seconds; local median target is 1.5 seconds over three cold subprocesses.
- No network, database, credential, or platform access in import tests.
- Each reviewed task may create one focused local commit; never push.

---

### Task 1: Freeze package-root compatibility and startup budget

**Files:**
- Create: `tests/fixtures/package_root_exports.json`
- Create: `tests/test_lazy_package_bootstrap.py`

**Interfaces:**
- Consumes: current `alpha_operator_framework.__all__` and public attributes.
- Produces: immutable export snapshot and subprocess timing helpers used by Task 2.

- [ ] **Step 1: Generate the compatibility snapshot before production changes**

Run a one-off Python command that imports the current package and writes sorted records with `name`, `module`, and `qualname`; module exports use `"<module>"` as qualname. Keep the resulting JSON as a test fixture.

- [ ] **Step 2: Write compatibility and failing performance tests**

```python
def test_package_root_matches_frozen_export_snapshot():
    package = importlib.import_module("alpha_operator_framework")
    expected = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert sorted(package.__all__) == [row["name"] for row in expected]
    for row in expected:
        value = getattr(package, row["name"])
        assert export_location(value) == (row["module"], row["qualname"])


def test_package_root_cold_import_stays_under_ci_budget():
    samples = [cold_import_seconds("import alpha_operator_framework") for _ in range(3)]
    assert statistics.median(samples) < 2.5
```

Also assert `getattr(package, "__definitely_missing__")` raises `AttributeError` and a second access returns the same object.

- [ ] **Step 3: Run RED verification**

Run: `D:\quant-venv\Scripts\python.exe -m pytest tests/test_lazy_package_bootstrap.py -q -p no:cacheprovider`

Expected: the compatibility assertions pass and the cold-import budget fails near 4.9 seconds.

---

### Task 2: Replace eager imports with a declarative lazy registry

**Files:**
- Create: `alpha_operator_framework/_lazy_exports.py`
- Modify: `alpha_operator_framework/__init__.py`
- Test: `tests/test_lazy_package_bootstrap.py`

**Interfaces:**
- Produces: `EXPORTS: dict[str, tuple[str, str | None]]`, `__all__`, `__getattr__`, and `__dir__`.

- [ ] **Step 1: Build the explicit export table from the frozen snapshot**

Each entry maps the public name to its defining module and attribute. Module exports use `None`, for example:

```python
EXPORTS = {
    "SurveyConfig": ("alpha_operator_framework.workflow", "SurveyConfig"),
    "families": ("alpha_operator_framework.domain.families", None),
    "research": ("alpha_operator_framework.research", None),
}
```

Populate every fixture name exactly once; reject duplicate keys in the table-construction test.

- [ ] **Step 2: Implement the minimal lazy package root**

```python
from importlib import import_module
from typing import Any
from alpha_operator_framework._lazy_exports import EXPORTS

__all__ = sorted(EXPORTS)

def __getattr__(name: str) -> Any:
    target = EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attribute = target
    module = import_module(module_name)
    value = module if attribute is None else getattr(module, attribute)
    globals()[name] = value
    return value

def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
```

- [ ] **Step 3: Run GREEN verification and inspect loaded modules**

Run the focused test and a subprocess printing `len(sys.modules)` after package import. Expected: all tests pass, median below 2.5 seconds, and heavy optional modules are absent.

---

### Task 3: Remove internal package-root imports and verify CLI latency

**Files:**
- Modify: production files reported by `rg "from alpha_operator_framework import" alpha_operator_framework -g '*.py'`
- Modify: `tests/test_dependency_direction.py`
- Test: `tests/test_lazy_package_bootstrap.py`

**Interfaces:**
- Consumes: defining modules listed in `EXPORTS`.
- Produces: an AST rule forbidding production imports from the package root.

- [ ] **Step 1: Add a failing dependency-direction test**

Parse production ASTs and reject `ImportFrom(module="alpha_operator_framework")`, except `_lazy_exports.py` and `__init__.py`. Also reject lazy targets containing `ai_workflow`, `carpet_mining`, `orchestrator`, or `domain.pruning`. The failure output lists exact files and imported names.

- [ ] **Step 2: Migrate each reported import to its defining module**

Use explicit imports such as:

```python
from alpha_operator_framework.domain import families, fields
from alpha_operator_framework.workflow import SurveyConfig
```

Do not change call sites or algorithms.

- [ ] **Step 3: Verify package, CLI, and full suite**

Run focused dependency/import tests, three cold `alpha_machine.py --help` samples, Ruff, Mypy, compileall, and the full pytest suite. Expected local medians are below 1.5 seconds and all correctness checks pass.
