# Lazy Package Bootstrap Task 3 Report

## Scope

- Added an AST dependency-direction guard for production package-root imports, allowing only `__init__.py` and `_lazy_exports.py`.
- Added lazy-export guards for the retired `ai_workflow`, `carpet_mining`, and `orchestrator` targets.
- Asserted that the temporary `alpha_operator_framework.domain.pruning` compatibility target has exactly 12 exports.
- Added an isolated three-sample `alpha_machine.py --help` latency and command-list regression test.
- Replaced eager CLI handler imports with `LazyCommandHandler` references that import the target module only during dispatch; kept `func`/`handler` dispatch attributes and `__name__` compatibility.
- Added a subprocess proof that root help does not load any command-handler modules.

## Evidence

- Package-root production import scan: no residual matches.
- Pre-fix characterization: eager `command_registry` import accounted for approximately 4.5s of the cold help process; CLI latency samples were 4.65s, 4.70s, 4.71s (median 4.70s).
- Focused dependency/bootstrap/CLI run after fix: 17 passed; extended CLI/orchestration compatibility run: 23 passed.
- Post-fix CLI help samples: 0.187s, 0.169s, 0.186s (median 0.186s), with all 22 commands present.
- Post-fix subprocess module proof: no command-handler modules loaded while rendering root help.
- Ruff on modified source/tests: passed.
- Full pytest: 359 passed in 138.24s.
- Full Ruff: passed.
- Mypy: passed (`Success: no issues found in 26 source files`).
- Compileall: passed.
- Diff check: passed.
- Reviewer P2 follow-up: extended the package-root AST guard to reject exact `ast.Import` aliases such as `import alpha_operator_framework as af`, while allowing submodule imports; focused command `D:\quant-venv\Scripts\python.exe -m pytest tests/test_dependency_direction.py tests/test_lazy_package_bootstrap.py tests/cli/test_command_registry.py -q -p no:cacheprovider` passed (13 tests).

## Full verification

- `python -m compileall -q alpha_operator_framework alpha_machine.py`: passed.
- `python -m ruff check .`: passed.
- `python -m mypy`: passed (`Success: no issues found in 26 source files`).
- `python -m pytest -q -p no:cacheprovider`: passed (359 tests).
- `git diff --check`: passed.

## Self-review

- Changes are limited to the requested registry lazy-loading fix, tests, and this report.
- The frozen 212-name package-root export fixture was not modified.
- No network, database, credential, platform, or external repository access was used.
