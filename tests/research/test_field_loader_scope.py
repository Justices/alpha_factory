from pathlib import Path
import json

import pytest

import alpha_operator_framework.research.field_loader as field_loader
from alpha_operator_framework.research.field_loader import load_real_market_fields


def test_cached_universe_index_defaults_to_first_value_and_rejects_unknown_value(monkeypatch, tmp_path: Path) -> None:
    index = tmp_path / "EUR" / "1" / "universe.json"
    index.parent.mkdir(parents=True)
    index.write_text(json.dumps(["TOP2500", "TOP1000"]), encoding="utf-8")
    monkeypatch.setattr(field_loader, "DATAFIELDS_DIR", tmp_path)

    assert field_loader.resolve_cached_universe("EUR", 1, None) == "TOP2500"
    assert field_loader.resolve_cached_universe("EUR", 1, "TOP1000") == "TOP1000"
    with pytest.raises(ValueError, match="not available"):
        field_loader.resolve_cached_universe("EUR", 1, "TOP3000")


def test_cached_universe_index_is_refreshed_from_platform_for_the_region(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / "EUR" / "1" / "TOP2500" / "datafields").mkdir(parents=True)
    monkeypatch.setattr(field_loader, "DATAFIELDS_DIR", tmp_path)
    monkeypatch.setattr(
        "alpha_operator_framework.cache.universes.UniverseCache.get_universe_map",
        lambda self: {"EUR": {"1": ["TOP3000", "TOP1000"]}},
    )

    assert field_loader.resolve_cached_universe("EUR", 1, None) == "TOP3000"
    assert json.loads((tmp_path / "EUR" / "1" / "universe.json").read_text(encoding="utf-8")) == ["TOP3000", "TOP1000"]


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
