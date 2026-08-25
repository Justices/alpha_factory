import json
from pathlib import Path

from alpha_operator_framework.cache.datafields import DataFieldCache


def test_scoped_cache_writes_universe_dataset_and_datafield_indexes(tmp_path: Path) -> None:
    cache = DataFieldCache(root=tmp_path)
    scope = tmp_path / "CHN" / "0"
    (scope / "TOP2000U").mkdir(parents=True)
    (scope / "universe.json").write_text("", encoding="utf-8")
    (scope / "TOP2000U" / "dataset.json").write_text("", encoding="utf-8")
    cache.save_dataset("CHN", 0, "TOP2000U", "pv1", [{"id": "returns", "dataset": {"id": "pv1", "name": "Price Volume"}}])

    assert json.loads((scope / "universe.json").read_text(encoding="utf-8")) == ["TOP2000U"]
    assert json.loads((scope / "TOP2000U" / "dataset.json").read_text(encoding="utf-8")) == [{"id": "pv1", "name": "Price Volume"}]
    assert json.loads((scope / "TOP2000U" / "datafields" / "pv1.json").read_text(encoding="utf-8"))[0]["id"] == "returns"
