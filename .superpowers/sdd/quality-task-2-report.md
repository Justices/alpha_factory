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
- Ruff/Mypy exit code `1` and Vulture 2.16 exit code `3` are accepted only with parseable findings. Tool exit codes outside each tool's supported finding range fail closed.

## Files

- Modified `alpha_operator_framework/quality/ratchet.py`
- Added `tools/quality_ratchet.py`
- Modified `tests/quality/test_quality_ratchet.py` in the reviewer follow-up
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

## Reviewer-blocking fixes

- Corrected Vulture 2.16 semantics to accept only exit codes `0` and `3`; exit codes `1`, `2`, and other values fail closed.
- Tightened persisted baseline validation: schema version must be exact integer `1`; coverage must be finite and real; file count must be a nonnegative exact integer; booleans are rejected for all numeric fields; issue collections must be list/tuple string fingerprints; and `tool_versions` must contain string versions for Ruff, Mypy, Coverage, and Vulture.
- Validated the baseline before collecting tools, so a semantically malformed baseline returns `1` without executing a runner.
- Generalized Vulture parsing to normalized `unused`, `unreachable`, and `unsatisfiable` findings in `path:line: message (N% confidence)` form, while rejecting blank descriptions or invalid confidence.
- Assigned the same-directory temporary path immediately after creation so serialization, flush, fsync, and replace failures all reach cleanup; a serialization-failure regression test proves the original baseline remains unchanged and no temp file remains.

Follow-up RED: the first focused run produced `16 failed, 28 passed` across the four reviewer findings. A separate safety probe reproduced the blank Vulture description as an escaping `IndexError`. Follow-up GREEN and exact verification commands:

```text
D:\quant-venv\Scripts\python.exe -m pytest tests/quality -q -p no:cacheprovider
exit 0 — 45 passed in 0.83s

D:\quant-venv\Scripts\python.exe -m ruff check .
exit 0 — All checks passed

D:\quant-venv\Scripts\python.exe -m ruff check --isolated alpha_operator_framework/quality/ratchet.py tools/quality_ratchet.py tests/quality/test_quality_ratchet.py tests/quality/test_quality_ratchet_cli.py
exit 0 — All checks passed

D:\quant-venv\Scripts\python.exe -m mypy
exit 0 — Success: no issues found in 26 source files

D:\quant-venv\Scripts\python.exe -m mypy alpha_operator_framework/quality/ratchet.py tools/quality_ratchet.py --follow-imports skip --ignore-missing-imports --no-incremental --strict
exit 0 — Success: no issues found in 2 source files

D:\quant-venv\Scripts\python.exe -m compileall -q alpha_operator_framework tools tests/quality alpha_machine.py
exit 0
```
