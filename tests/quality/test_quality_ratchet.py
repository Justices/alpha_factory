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
        "tool_versions": {"mypy": "test", "ruff": "test", "vulture": "test"},
        "ruff": (),
        "mypy": (),
        "vulture": (),
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


def test_compare_rejects_file_count_regression():
    result = compare(_snapshot(file_count=9), _snapshot(file_count=10))

    assert not result.file_count_ok
    assert not result.passed


def test_fingerprint_normalizes_paths_lines_and_message_whitespace():
    issue = Issue("ruff", r"src\module.py", "E501", 42, "  line   is\ttoo long  ")

    assert fingerprint(issue) == "src/module.py|E501|line is too long"
    assert fingerprint(Issue("ruff", "src/module.py", "E501", 99, "line is too long")) == fingerprint(issue)


def test_compare_requires_schema_and_all_scan_outputs():
    with pytest.raises(BaselineError, match="schema"):
        compare(_snapshot(schema_version=1), _snapshot())

    missing = _snapshot()
    del missing["vulture"]
    with pytest.raises(BaselineError, match="vulture"):
        compare(missing, _snapshot())


def test_compare_rejects_missing_schema_version():
    missing = _snapshot()
    del missing["schema_version"]

    with pytest.raises(BaselineError, match="schema"):
        compare(missing, _snapshot())


@pytest.mark.parametrize(
    ("key", "value", "message"),
    [
        ("schema_version", True, "schema"),
        ("schema_version", 1.0, "schema"),
        ("file_count", True, "file_count"),
        ("file_count", 1.0, "file_count"),
        ("file_count", -1, "file_count"),
        ("ruff", {"a.py|F1|bad"}, "ruff"),
        ("mypy", [1], "mypy"),
        ("vulture", [Issue("vulture", "a.py", "unused", 1, "bad")], "vulture"),
        ("tool_versions", {"ruff": 1}, "tool_versions"),
        ("tool_versions", {"ruff": "1"}, "tool_versions"),
    ],
)
def test_compare_rejects_malformed_baseline_values(key, value, message):
    baseline = _snapshot()
    baseline[key] = value

    with pytest.raises(BaselineError, match=message):
        compare(_snapshot(), baseline)


def test_compare_accepts_issue_objects_only_in_current_snapshot():
    result = compare(
        _snapshot(ruff=(Issue("ruff", "a.py", "F1", 7, "bad"),)),
        _snapshot(),
    )

    assert result.new_issues == {"ruff": ("a.py|F1|bad",)}


def test_compare_rejects_unexpected_baseline_fields():
    baseline = _snapshot()
    baseline["coverage"] = 72

    with pytest.raises(BaselineError, match="unexpected"):
        compare(_snapshot(), baseline)


def test_result_is_immutable_and_serializes_with_stable_order():
    result = compare(
        _snapshot(mypy=("z.py|E2|z",), ruff=("a.py|E1|a",)),
        _snapshot(),
    )

    with pytest.raises((AttributeError, TypeError)):
        result.passed = True
    assert result.new_issues == {"mypy": ("z.py|E2|z",), "ruff": ("a.py|E1|a",)}
    assert json.dumps(result.as_dict(), sort_keys=True) == (
        '{"file_count_ok": true, "new_issues": {"mypy": ["z.py|E2|z"], '
        '"ruff": ["a.py|E1|a"]}, "passed": false}'
    )


def test_schema_version_is_two():
    assert SCHEMA_VERSION == 2
