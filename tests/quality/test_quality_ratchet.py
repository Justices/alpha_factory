import json

import pytest

from alpha_operator_framework.quality.ratchet import (
    SCHEMA_VERSION,
    BaselineError,
    Issue,
    compare,
    fingerprint,
)


def _snapshot(**overrides):
    value = {
        "schema_version": SCHEMA_VERSION,
        "ruff": (),
        "mypy": (),
        "vulture": (),
        "coverage": 72.0,
        "file_count": 10,
    }
    value.update(overrides)
    return value


def test_compare_rejects_only_new_issue_fingerprints():
    baseline = _snapshot(ruff=("a.py|F401|unused import",))
    current = _snapshot(
        ruff=("a.py|F401|unused import", "b.py|F821|missing"),
    )

    result = compare(current, baseline)

    assert result.new_issues == {"ruff": ("b.py|F821|missing",)}
    assert not result.passed


def test_compare_rejects_coverage_drop():
    result = compare(_snapshot(coverage=71.9), _snapshot(coverage=72.0))

    assert result.coverage_delta == pytest.approx(-0.1)
    assert not result.coverage_ok
    assert not result.passed


def test_fingerprint_normalizes_paths_lines_and_message_whitespace():
    issue = Issue("ruff", r"src\module.py", "E501", 42, "  line   is\ttoo long  ")

    assert fingerprint(issue) == "src/module.py|E501|line is too long"
    assert fingerprint(Issue("ruff", "src/module.py", "E501", 99, "line is too long")) == fingerprint(issue)


def test_compare_requires_schema_and_all_scan_outputs():
    with pytest.raises(BaselineError, match="schema"):
        compare(_snapshot(schema_version=2), _snapshot())

    missing = _snapshot()
    del missing["vulture"]
    with pytest.raises(BaselineError, match="vulture"):
        compare(missing, _snapshot())


def test_compare_rejects_missing_schema_version():
    missing = _snapshot()
    del missing["schema_version"]

    with pytest.raises(BaselineError, match="schema"):
        compare(missing, _snapshot())


def test_compare_rejects_missing_scan_target():
    with pytest.raises(BaselineError, match="file_count"):
        compare(_snapshot(file_count=0), _snapshot(file_count=10))


def test_result_is_immutable_and_serializes_with_stable_order():
    result = compare(
        _snapshot(mypy=("z.py|E2|z",), ruff=("a.py|E1|a",)),
        _snapshot(),
    )

    with pytest.raises((AttributeError, TypeError)):
        result.passed = True
    assert result.new_issues == {"mypy": ("z.py|E2|z",), "ruff": ("a.py|E1|a",)}
    assert json.dumps(result.as_dict(), sort_keys=True) == (
        '{"coverage_delta": 0.0, "coverage_ok": true, "new_issues": '
        '{"mypy": ["z.py|E2|z"], "ruff": ["a.py|E1|a"]}, "passed": false}'
    )
