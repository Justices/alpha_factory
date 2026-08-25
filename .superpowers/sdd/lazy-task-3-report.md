# Lazy Package Bootstrap Task 3 Report

## Scope

- Added an AST dependency-direction guard for production package-root imports, allowing only `__init__.py` and `_lazy_exports.py`.
- Added lazy-export guards for the retired `ai_workflow`, `carpet_mining`, and `orchestrator` targets.
- Asserted that the temporary `alpha_operator_framework.domain.pruning` compatibility target has exactly 12 exports.
- Added an isolated three-sample `alpha_machine.py --help` latency and command-list regression test.

## Evidence

- Package-root production import scan: no residual matches.
- Focused dependency/bootstrap run: 8 passed; the CLI latency guard failed because the local median was 4.70s (samples 4.65s, 4.70s, 4.71s), above the 2.5s CI ceiling.
- CLI router/registry tests: 7 passed.
- Ruff on modified tests: passed.
- Full pytest: 357 passed, 1 failed (the same CLI latency guard; samples 5.30s, 4.78s, 4.57s; median 4.78s).
- Full Ruff: passed.
- Mypy: passed (`Success: no issues found in 26 source files`).
- Compileall: passed.
- Diff check: passed.

## Full verification

Not completed because the focused CLI latency guard exposes an existing production startup regression. The heavy imports originate in `alpha_operator_framework.cli.command_registry` and account for approximately 4.5s of the cold `--help` process. The brief restricts production edits to files reported by the package-root residual scan, which returned none, so this task does not change that production path.

## Self-review

- Changes are limited to the requested tests and this report.
- The frozen 212-name package-root export fixture was not modified.
- No network, database, credential, platform, or external repository access was used.
