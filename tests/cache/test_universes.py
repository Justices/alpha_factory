import asyncio
import json
import sys
import types

from alpha_operator_framework.cache.universes import UniverseCache


def test_universe_cache_saves_an_unmodified_simulations_options_snapshot(monkeypatch, tmp_path) -> None:
    raw_options = {"actions": {"POST": {"settings": {"children": {"Universe": {"value": ["TOP2500"]}}}}}}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return raw_options

    class Session:
        def options(self, url):
            assert url == "https://brain.example/simulations"
            return Response()

    class Client:
        base_url = "https://brain.example"
        session = Session()

        async def ensure_authenticated(self):
            return None

    module = types.ModuleType("cnhkmcp.untracked.platform_functions")
    module.brain_client = Client()
    monkeypatch.setitem(sys.modules, "cnhkmcp.untracked.platform_functions", module)
    cache = UniverseCache()
    monkeypatch.setattr(cache, "_cache_path", lambda key="": tmp_path / f"{key}.json")

    assert cache.get_raw_platform_options(force_refresh=True) == raw_options
    assert json.loads((tmp_path / "simulations_options.json").read_text(encoding="utf-8")) == raw_options


def test_universe_map_refresh_also_saves_the_raw_options_snapshot(monkeypatch, tmp_path) -> None:
    raw_options = {"actions": {"POST": {}}}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return raw_options

    class Session:
        def options(self, url):
            return Response()

    class Client:
        base_url = "https://brain.example"
        session = Session()

        async def ensure_authenticated(self):
            return None

        async def get_platform_setting_options(self):
            return {"instrument_options": []}

    module = types.ModuleType("cnhkmcp.untracked.platform_functions")
    module.brain_client = Client()
    monkeypatch.setitem(sys.modules, "cnhkmcp.untracked.platform_functions", module)
    cache = UniverseCache()
    monkeypatch.setattr(cache, "_cache_path", lambda key="": tmp_path / f"{key}.json")

    assert cache.get_universe_map(force_refresh=True) == {}
    assert json.loads((tmp_path / "simulations_options.json").read_text(encoding="utf-8")) == raw_options


def test_universe_cache_extracts_all_region_universes_from_platform_settings(monkeypatch) -> None:
    class Client:
        async def get_platform_setting_options(self):
            return {
                "instrument_options": [
                    {"InstrumentType": "EQUITY", "Region": "EUR", "Delay": 1, "Universe": ["TOP2500", "TOP1200"]},
                    {"InstrumentType": "EQUITY", "Region": "EUR", "Delay": 0, "Universe": ["TOP2500", "TOP800"]},
                    {"InstrumentType": "EQUITY", "Region": "USA", "Delay": 1, "Universe": ["TOP3000"]},
                ]
            }

    module = types.ModuleType("cnhkmcp.untracked.platform_functions")
    module.brain_client = Client()
    monkeypatch.setitem(sys.modules, "cnhkmcp.untracked.platform_functions", module)

    assert asyncio.run(UniverseCache().fetch_platform_settings()) == {
        "EUR": {"1": ["TOP2500", "TOP1200"], "0": ["TOP2500", "TOP800"]},
        "USA": {"1": ["TOP3000"]},
    }
    assert asyncio.run(UniverseCache().fetch_platform("EUR")) == [
        {"id": "TOP2500"}, {"id": "TOP1200"}, {"id": "TOP800"},
    ]
