# Quality Task 3R Report — Schema v2 without code coverage

## Outcome

- Removed the coverage dependency, configuration tables, adapter, snapshot/baseline fields, tool version, comparison state, CLI output, and normal fixture values.
- Bumped `SCHEMA_VERSION` from 1 to 2. Persisted baselines now require exactly `schema_version`, `tool_versions`, `ruff`, `mypy`, `vulture`, and `file_count`; schema-v1 or extra-field baselines fail closed before tools run.
- `ComparisonResult` now contains only `new_issues`, `file_count_ok`, and `passed`. A file-count regression is a normal failed comparison rather than a malformed-baseline exception.
- Preserved stable fingerprints, bounded Mypy shards, Ruff/Vulture exit semantics, atomic baseline writes and cleanup, and summary-only CLI output.

## TDD record

- RED: rewrote the schema/public-API/config/CLI contracts first. Focused run produced 30 expected failures and 21 passes because the old implementation still required and executed coverage.
- GREEN before baseline refresh: 50 passed, 1 deselected (the repository baseline still intentionally remained schema v1 at that point).
- GREEN after implementation and real baseline refresh: quality/config suite 51 passed.

## Schema-v2 baseline

- Generated only through `python tools/quality_ratchet.py baseline --update`; fingerprints were not edited or suppressed manually.
- `file_count=181`
- Ruff fingerprints: 256
- Mypy fingerprints: 50
- Vulture fingerprints: 6
- Real check result: `PASS new=0 files=181 baseline_files=181`.
- Tool versions: Ruff 0.12.11, Mypy 1.17.1, Vulture 2.16.

## Validation evidence

- Focused quality/config tests: 51 passed.
- Normal full pytest: 409 passed.
- Representative offline/dry-run tests: 15 passed.
- Configured Ruff: passed.
- Configured Mypy: passed, 29 source files.
- Compileall: passed.
- `alpha_machine.py --help`: passed.
- Real ratchet check: passed with zero new fingerprints.
- `git diff --check`: passed; only existing Windows line-ending notices were emitted.
- Pytest emitted one existing cache-write permission warning for `.pytest_cache`; tests themselves passed.

Execution-order note: the broad checks above completed before the parent task delivered the later instruction to defer broad validation until the final phase. No additional broad or expensive validation was started after that instruction; Quality Task 4 can repeat the final gates after subsequent core refactors.

## Files changed

- `requirements-dev.txt`
- `pyproject.toml`
- `alpha_operator_framework/quality/ratchet.py`
- `alpha_operator_framework/quality/__init__.py`
- `tools/quality_ratchet.py`
- `quality-baseline.json`
- `tests/quality/test_quality_ratchet.py`
- `tests/quality/test_quality_ratchet_cli.py`
- `tests/quality/test_quality_baseline.py`

## Self-review

- Production/configuration/baseline paths contain no coverage reference.
- The baseline has the six exact schema-v2 keys and no raw tool logs.
- Schema-v1 and unexpected-key baselines are rejected before adapter invocation.
- No network/platform/Brain operations were performed by tests or workflows. Missing local dev tools and a damaged local `orjson` install were repaired from pip's local wheel cache so the requested real adapters could run.
- `.superpowers/sdd/progress.md` was already modified on entry and was preserved without staging or editing.
