from pathlib import Path
import json

from alpha_operator_framework.research.field_loader import load_real_market_fields


def test_strict_scope_does_not_inject_unverified_base_fields(tmp_path: Path) -> None:
    fields = load_real_market_fields(
        region="EUR", universe="TOP2500", delay=1,
        custom_dir=tmp_path / "EUR" / "1" / "TOP2500",
        include_base_fields=False, allow_scope_fallback=False,
    )

    assert fields == []


def test_strict_scope_filters_fields_by_one_category(tmp_path: Path) -> None:
    directory = tmp_path / "EUR" / "1" / "TOP2500"
    directory.mkdir(parents=True)
    (directory / "dataset.json").write_text(json.dumps([
        {"id": "news_field", "type": "MATRIX", "category": {"id": "news"}},
        {"id": "risk_field", "type": "MATRIX", "category": {"id": "risk"}},
    ]), encoding="utf-8")

    fields = load_real_market_fields(
        region="EUR", universe="TOP2500", delay=1, custom_dir=directory,
        include_base_fields=False, allow_scope_fallback=False, category="news",
    )

    assert [field.id for field in fields] == ["news_field"]
