# Progressive Quality Ratchet — Task 2 Report

## Result

Implemented deterministic Ruff, Mypy, Coverage, and Vulture adapters behind an injected command runner, plus the `check` and explicit `baseline --update` CLI flows. Adapter tests use fake runners only; this task did not run the adapters against the repository tree and did not create `quality-baseline.json`.

## RED / GREEN

- Initial RED: `tests/quality/test_quality_ratchet_cli.py` failed during collection because `CommandResult` and the adapter API did not exist.
- Self-review RED: an unexpected runner exception escaped instead of becoming `ToolFailure`, and `python tools/quality_ratchet.py --help` could not import the sibling package.
- GREEN: 25 focused quality tests pass, including both self-review regressions.

## Command and exit semantics

- `python tools/quality_ratchet.py check --baseline quality-baseline.json`
  - exits `0` only when no new fingerprint exists, coverage does not decrease, and the package Python-file count does not decrease;
  - exits `1` for malformed/missing baseline, missing scan target, new issue, coverage/file-count regression, timeout, traceback, invalid report, or runner/tool crash;
  - prints one `[QUALITY]` summary and at most ten new fingerprints.
- `python tools/quality_ratchet.py baseline --update --baseline quality-baseline.json`
  - requires `--update` explicitly;
  - writes sorted schema-v1 JSON using a same-directory temporary file and `Path.replace`;
  - prints counts and coverage only.
- Ruff/Mypy/Vulture exit code `1` is accepted only with parseable findings. Tool exit codes outside the supported finding range fail closed.

## Files

- Modified `alpha_operator_framework/quality/ratchet.py`
- Added `tools/quality_ratchet.py`
- Added `tests/quality/test_quality_ratchet_cli.py`
- Added this report

## Verification

- Focused quality tests: `25 passed`.
- Existing configured Ruff: passed.
- Changed-file Ruff with `--isolated`: passed.
- Existing configured Mypy: `26 source files`, passed.
- Changed production files with Mypy `--strict`: `2 source files`, passed.
- Compileall for package, tools, quality tests, and entry point: passed.
- Full pytest, run once with the unusable workspace cache provider disabled: `385 passed`.
- `git diff --check` for the implementation file: passed (Git reported only the repository's LF/CRLF conversion warning).

## Self-review

- Python files under `alpha_operator_framework` are sorted and split into bounded Mypy shards; each explicit file is submitted once.
- Tool output is reduced to normalized `Issue` objects and stable, line-independent fingerprints; raw output is never printed by the CLI.
- Coverage reports use a system temporary directory outside the repository and missing/invalid reports fail closed.
- Baseline output contains schema version, sorted tool versions/fingerprints, coverage, and file count; repeated writes with identical inputs are byte-identical.
- Existing unrelated workspace changes in `.superpowers/sdd/progress.md` and `test.py` were not modified or included.

## Concern

The workspace `.pytest_cache` directory is not writable, so verification used `-p no:cacheprovider`. This affects pytest caching only; all 385 tests executed. Real baseline collection remains intentionally deferred to Task 3.
