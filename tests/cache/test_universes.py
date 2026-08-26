import asyncio
import sys
import types

from alpha_operator_framework.cache.universes import UniverseCache


def test_universe_cache_extracts_simulation_setting_validation_values() -> None:
    raw_options = {
        "actions": {"POST": {"settings": {"children": {
            "decay": {"type": "integer", "label": "Decay", "minValue": 0, "maxValue": 60, "default": 4},
            "neutralization": {
                "type": "string",
                "label": "Neutralization",
                "choices": {"region": {"EUR": [
                    {"value": "NONE", "label": "None"},
                    {"value": "MARKET", "label": "Market"},
                ]}},
            },
            "pasteurization": {"choices": [{"value": "ON"}, {"value": "OFF"}]},
        }}}}
    }

    assert UniverseCache.extract_simulation_settings(raw_options) == {
        "decay": {"minValue": 0, "maxValue": 60, "default": 4},
        "neutralization": {"region": {"EUR": ["NONE", "MARKET"]}},
        "pasteurization": ["ON", "OFF"],
    }


def test_universe_map_refresh_saves_simulation_setting_values(monkeypatch, tmp_path) -> None:
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
    assert cache.get_simulation_settings() == {}


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
