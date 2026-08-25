# Alpha Machine System Entry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn `alpha_machine.py` into the stable Alpha Factory composition root and command-domain router while keeping business logic modular.

**Architecture:** `cli.router` owns parser registration and structured domain metadata. `alpha_machine.py` delegates parsing/dispatch and exposes a small explicit compatibility facade through lazy imports.

**Tech Stack:** Python 3.12, argparse, pytest.

## Global Constraints

- Do not move business algorithms into `alpha_machine.py`.
- Preserve existing command names and CLI defaults.
- Avoid wildcard exports and import cycles.
- Add tests before production changes.

---

### Task 1: Define the system-entry contract

**Files:**
- Create: `tests/cli/test_alpha_machine_entry.py`
- Modify: `alpha_operator_framework/cli/router.py`
- Modify: `alpha_machine.py`

**Interfaces:**
- Produces: `command_domains()`, `build_parser()`, `route(argv=None)`, `main(argv=None)`.

- [ ] Add failing tests for domain metadata, parser coverage, argv-based dispatch and root exports.
- [ ] Run the focused tests and confirm failures are missing entry features.
- [ ] Add immutable command-domain metadata and argv-aware dispatch to the router.
- [ ] Make the root module delegate the four entry interfaces.
- [ ] Run the focused tests and confirm they pass.

### Task 2: Restore the explicit compatibility facade

**Files:**
- Modify: `tests/cli/test_alpha_machine_entry.py`
- Modify: `alpha_machine.py`

**Interfaces:**
- Produces: lazy explicit exports for platform, field, filtering, JSON and polling helpers used by repository callers.

- [ ] Add failing tests for every compatibility name referenced by production modules.
- [ ] Implement lazy explicit symbol resolution without wildcard imports.
- [ ] Run entry, framework and orchestration tests.

### Task 3: Verify the system entry

**Files:**
- Test: `tests/`

- [ ] Run `python alpha_machine.py --help` and verify domain commands are visible.
- [ ] Run focused CLI and compatibility tests.
- [ ] Run the full pytest suite without the broken workspace cache provider.
- [ ] Run `git diff --check` and inspect the final diff.
