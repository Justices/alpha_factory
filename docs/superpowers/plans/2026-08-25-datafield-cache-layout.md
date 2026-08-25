# Datafield Cache Layout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` to implement this plan task-by-task.

**Goal:** Store scoped BRAIN metadata under `data/{region}/{delay}/{universe}` with explicit universe and dataset indexes.

**Architecture:** `data/{region}/{delay}/universe.json` lists cached universes for that scope. Each `data/{region}/{delay}/{universe}/dataset.json` lists datasets; field payloads remain isolated under the sibling `datafields/` directory. The cache facade and research loader use the same path helpers; legacy `data/fields` is read only as a one-time migration source.

**Tech Stack:** Python, JSON, pytest.

### Task 1: Define and test scoped paths

**Files:**
- Modify: `alpha_operator_framework/cache/config.py`
- Modify: `alpha_operator_framework/cache/datafields.py`
- Test: `tests/cache/test_datafield_layout.py`

- [ ] Test exact paths: universe index is `data/CHN/0/universe.json`, dataset index is `data/CHN/1/TOP2000U/dataset.json`, fields are under `data/CHN/1/TOP2000U/datafields/{dataset}.json`.
- [ ] Implement shared path helpers and make `DataFieldCache` use them.

### Task 2: Maintain indexes when writing data

**Files:**
- Modify: `alpha_operator_framework/cache/datafields.py`
- Modify: `alpha_operator_framework/research/field_loader.py`
- Test: `tests/cache/test_datafield_layout.py`

- [ ] Test a field sync writes deduplicated `universe.json` and `dataset.json` entries.
- [ ] Update cache writes and `cache_platform_fields` to write fields and both indexes atomically per logical file.

### Task 3: Read new layout and migrate old field cache

**Files:**
- Modify: `alpha_operator_framework/cache/datafields.py`
- Modify: `alpha_operator_framework/research/field_loader.py`
- Test: `tests/cache/test_datafield_layout.py`

- [ ] Test first read copies legacy `data/fields/{region}/{delay}/{universe}` data into the new layout and then reads only the new layout.
- [ ] Implement the idempotent migration without deleting legacy files.

### Task 4: Verify consumers and document layout

**Files:**
- Modify: `alpha_operator_framework/cache/config.py`
- Test: `tests/research/test_field_loader_scope.py`

- [ ] Run focused cache and research-loader tests and verify strict EUR/TOP2500 loading still excludes unscoped fields.
