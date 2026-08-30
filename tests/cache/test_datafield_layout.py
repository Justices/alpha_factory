import json
import asyncio
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


def test_initial_scope_fetch_populates_main_and_group_caches_together(monkeypatch, tmp_path: Path) -> None:
    cache = DataFieldCache(root=tmp_path)
    calls = []

    async def fake_fetch(**kwargs):
        calls.append(kwargs)
        if kwargs.get("data_type") == "GROUP":
            return {"items": [{"id": "industry", "type": "GROUP"}]}
        return {"items": [{"id": "returns", "type": "MATRIX", "dataset": {"id": "pv1"}}]}

    monkeypatch.setattr(cache, "fetch_platform", fake_fetch)

    fields = asyncio.run(cache.aget_datafields("GBR", "TOP700", 1))

    assert fields == [{"id": "returns", "type": "MATRIX", "dataset": {"id": "pv1"}}]
    assert {call.get("data_type", "") for call in calls} == {"", "GROUP"}
    assert cache.load_dataset("GBR", 1, "TOP700", "pv1") == fields
    assert cache.load_group_fields("GBR", 1, "TOP700") == [{"id": "industry", "type": "GROUP"}]
