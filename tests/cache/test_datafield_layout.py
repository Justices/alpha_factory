import json
from pathlib import Path

from alpha_operator_framework.cache.config import (
    DATAFIELDS_DIRECTORY_TEMPLATE,
    DATASET_INDEX_TEMPLATE,
    UNIVERSE_INDEX_TEMPLATE,
    render_datafield_cache_path,
)
from alpha_operator_framework.cache.datafields import DataFieldCache


def test_datafield_cache_path_templates_render_a_scope(tmp_path: Path) -> None:
    values = {"region": "EUR", "delay": 1, "universe": "TOP2500"}

    assert render_datafield_cache_path(tmp_path, UNIVERSE_INDEX_TEMPLATE, **values) == tmp_path / "EUR" / "1" / "universe.json"
    assert render_datafield_cache_path(tmp_path, DATASET_INDEX_TEMPLATE, **values) == tmp_path / "EUR" / "1" / "TOP2500" / "dataset.json"
    assert render_datafield_cache_path(tmp_path, DATAFIELDS_DIRECTORY_TEMPLATE, **values) == tmp_path / "EUR" / "1" / "TOP2500" / "datafields"


def test_scoped_cache_writes_universe_dataset_and_datafield_indexes(tmp_path: Path) -> None:
    cache = DataFieldCache(root=tmp_path)
    scope = tmp_path / "CHN" / "0"
    (scope / "TOP2000U").mkdir(parents=True)
    (scope / "universe.json").write_text("", encoding="utf-8")
    (scope / "TOP2000U" / "dataset.json").write_text("", encoding="utf-8")
    cache.save_dataset("CHN", 0, "TOP2000U", "pv1", [{"id": "returns", "dataset": {"id": "pv1", "name": "Price Volume"}, "category": {"id": "price_volume", "name": "Price Volume"}}])

    assert (scope / "universe.json").read_text(encoding="utf-8") == ""
    assert json.loads((scope / "TOP2000U" / "dataset.json").read_text(encoding="utf-8")) == [{"id": "pv1", "name": "Price Volume", "category": {"id": "price_volume", "name": "Price Volume"}}]
    assert json.loads((scope / "TOP2000U" / "datafields" / "pv1.json").read_text(encoding="utf-8"))[0]["id"] == "returns"
