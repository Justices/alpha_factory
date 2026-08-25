# Quality Task 1 report

## RED/GREEN evidence

- RED: `python -m pytest tests/quality/test_quality_ratchet.py -q -p no:cacheprovider` failed during collection with `ModuleNotFoundError: No module named 'alpha_operator_framework.quality'`.
- GREEN: the focused suite passes: 6 tests passed.

## API decisions

- `Issue` and `ComparisonResult` are frozen, slotted dataclasses.
- Fingerprints use normalized POSIX paths, code, and collapsed message whitespace; line numbers and tool names are excluded.
- Snapshots require schema version 1, `ruff`, `mypy`, `vulture`, `coverage`, and `file_count`.
- A scan with fewer files than the baseline is rejected as a missing scan target. Coverage must not decrease.
- Comparison issue collections and result serialization are sorted and immutable at the result boundary.

## Files

- `alpha_operator_framework/quality/__init__.py`
- `alpha_operator_framework/quality/ratchet.py`
- `tests/quality/test_quality_ratchet.py`

## Verification

- Focused tests: 6 passed.
- Full suite: 366 passed.
- Ruff: passed.
- Mypy: passed (2 source files).
- Compileall: passed.

## Self-review and concerns

The implementation is pure and does not invoke tools or write a baseline. `compare` accepts fingerprint strings as produced by later adapters and also accepts `Issue` objects for model-level use. No unrelated files were changed; the pre-existing `.superpowers/sdd/progress.md` remains dirty and was not included.

## Review fix

- RED: added `test_compare_rejects_missing_schema_version`; it initially failed because validation defaulted a missing schema to version 1.
- GREEN: schema validation now requires an explicit `schema_version` equal to 1. Focused suite: 7 passed; Ruff, Mypy, and compileall passed.
