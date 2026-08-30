from __future__ import annotations

from alpha_operator_framework.cache.datafields import DataFieldCache
from alpha_operator_framework.research.field_loader import load_cached_group_fields, load_or_fetch_group_fields


def test_cached_group_fields_use_exact_research_scope(tmp_path) -> None:
    cache = DataFieldCache(tmp_path)
    cache.save_group_fields("GBR", 1, "TOP700", [
        {"id": "industry", "type": "GROUP", "coverage": 1.0},
        {"id": "returns", "type": "MATRIX"},
        {"id": "sector", "type": "GROUP", "dataset_id": "pv1"},
    ])

    groups = load_cached_group_fields("GBR", "TOP700", 1, cache=cache)

    assert [(field.id, field.dataset_id, field.type) for field in groups] == [
        ("industry", "group-cache", "GROUP"),
        ("sector", "pv1", "GROUP"),
    ]
    assert load_cached_group_fields("USA", "TOP3000", 1, cache=cache) == []


def test_group_cache_fetches_once_and_persists_an_empty_result(monkeypatch, tmp_path) -> None:
    cache = DataFieldCache(tmp_path)
    calls = []

    async def fake_fetch(**kwargs):
        calls.append(kwargs)
        return {"items": []}

    monkeypatch.setattr(cache, "fetch_platform", fake_fetch)

    assert load_or_fetch_group_fields("USA", "TOP3000", 1, cache=cache) == []
    assert load_or_fetch_group_fields("USA", "TOP3000", 1, cache=cache) == []
    assert calls == [{"region": "USA", "universe": "TOP3000", "delay": 1, "data_type": "GROUP", "page_delay": 0.5}]
    assert cache.load_group_fields("USA", 1, "TOP3000") == []
