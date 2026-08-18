# Automatic Paired Field Discovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automatically discover strict analyst-revision and dispersion field groups and feed them into paired signal construction.

**Architecture:** Add deterministic discovery in `paired_bases.py`; Survey combines discovered and explicit specifications before calling only the paired base factory. Grouped fields stop at their binary base expression; only ordinary fields enter unary and first-order generation. Pair source is carried through task metadata and JSON annotations.

**Tech Stack:** Python standard library, existing `FieldSpec` and `Task` dataclasses.

## Global Constraints

- Discovery must remain local and deterministic.
- Only fields from one dataset and an exact normalized key may be paired.
- Explicit `--pair` values supplement, rather than disable, automatic discovery.
- Grouped fields must not create `paired_unary_template` or `paired_first_order` tasks.

---

### Task 1: Pair discovery and metadata

**Files:**
- Modify: `alpha_operator_framework/paired_bases.py`
- Test: `tests/test_framework.py`

**Interfaces:**
- Produces: `discover_pair_specs(fields: Sequence[FieldSpec]) -> list[PairSpec]`
- Produces: `PairSpec.source: str`, defaulting to `"explicit"`

- [ ] **Step 1: Write the failing test**

```python
specs = discover_pair_specs([
    FieldSpec("est_12m_ebi_raisednum_4wks", "analyst7", "MATRIX"),
    FieldSpec("est_12m_ebi_lowerednum_4wks", "analyst7", "MATRIX"),
    FieldSpec("est_12m_ebi_num", "analyst7", "MATRIX"),
])
assert specs == [PairSpec("net_revision", "est_12m_ebi_raisednum_4wks", "est_12m_ebi_lowerednum_4wks", "est_12m_ebi_num", "auto")]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `$env:PYTHONIOENCODING='utf-8'; python tests/test_framework.py`

Expected: import failure because `discover_pair_specs` does not exist.

- [ ] **Step 3: Write minimal implementation**

```python
def discover_pair_specs(fields):
    # group by dataset and exact `<key>_<window>` / `<key>` naming keys
    # return revision and dispersion triples with source="auto"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `$env:PYTHONIOENCODING='utf-8'; python tests/test_framework.py`

Expected: all tests pass.

### Task 2: Survey integration and local verification

**Files:**
- Modify: `alpha_operator_framework/orchestrator.py`
- Modify: `README.md`
- Test: `tests/test_framework.py`

**Interfaces:**
- Consumes: `discover_pair_specs(field_specs)` and `parse_pair_specs(args.pairs)`
- Produces: JSON annotations with `pair_source`

- [ ] **Step 1: Write the failing test**

```python
base = paired_base_task_factory(discover_pair_specs(fields), fields)[0]
assert base.meta["pair_source"] == "auto"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `$env:PYTHONIOENCODING='utf-8'; python tests/test_framework.py`

Expected: missing `pair_source` assertion failure.

- [ ] **Step 3: Write minimal integration**

```python
pair_specs = dedupe_pair_specs(discover_pair_specs(field_specs) + parse_pair_specs(args.pairs))
paired_base_tasks = paired_base_task_factory(pair_specs, field_specs, ...)
# Do not call paired_unary_task_factory or paired_first_order_task_factory.
```

- [ ] **Step 4: Run local dry-run**

Run: `python -m alpha_operator_framework.orchestrator survey --field-source local --region GBR --universe TOP700 --delay 1 --dataset analyst7 --sample 1 --backtest-sample 1 --no-semantic-pairs`

Expected: only `paired_base` task origins are present for field groups, and no
platform request occurs.
