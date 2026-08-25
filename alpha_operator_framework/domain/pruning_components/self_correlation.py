"""Local self-correlation precheck."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Sequence

from .correlation import pnl_returns


@dataclass(frozen=True)
class LocalCheckConfig:
    sc_threshold: float = 0.7
    sc_marginal: float = 0.05
    pc_threshold: float = 0.7
    pc_marginal: float = 0.05
    years_window: int = 4
    min_periods: int = 100
    concurrency: int = 4


async def _fetch_pnl_series(alpha_id: str) -> Any:
    from cnhkmcp.untracked.platform_functions import brain_client
    try:
        return pnl_returns(await brain_client.get_alpha_pnl(alpha_id))
    except Exception:
        return None


async def compute_self_correlation(candidate_ids: Sequence[str], submitted_ids: Sequence[str], config: LocalCheckConfig = LocalCheckConfig()) -> dict[str, dict[str, Any]]:
    if not candidate_ids:
        return {}
    import pandas as pd
    from cnhkmcp.untracked.platform_functions import brain_client

    await brain_client.ensure_authenticated()
    semaphore = asyncio.Semaphore(max(config.concurrency, 1))
    async def fetch(alpha_id: str):
        async with semaphore:
            return alpha_id, await _fetch_pnl_series(alpha_id)
    candidates = {alpha_id: series for alpha_id, series in await asyncio.gather(*(fetch(alpha_id) for alpha_id in candidate_ids)) if series is not None and len(series) >= config.min_periods}
    submitted = {alpha_id: series for alpha_id, series in await asyncio.gather(*(fetch(alpha_id) for alpha_id in submitted_ids)) if series is not None and len(series) >= config.min_periods}
    if not (all_series := {**candidates, **submitted}):
        return {alpha_id: {"sc": None, "grade": "unknown", "error": "no_pnl"} for alpha_id in candidate_ids}
    end = pd.Timestamp.now()
    frame = pd.DataFrame(all_series)
    frame = frame[(frame.index >= end - pd.DateOffset(years=config.years_window)) & (frame.index <= end)]
    matrix = frame.corr(min_periods=config.min_periods)
    results: dict[str, dict[str, Any]] = {}
    for alpha_id in candidate_ids:
        if alpha_id not in candidates:
            results[alpha_id] = {"sc": None, "grade": "unknown", "error": "no_pnl"}
            continue
        maximum, counterpart = 0.0, ""
        for submitted_id in submitted:
            if submitted_id == alpha_id:
                continue
            try:
                value = matrix.loc[alpha_id, submitted_id]
            except KeyError:
                continue
            if pd.notna(value) and abs(float(value)) > maximum:
                maximum, counterpart = abs(float(value)), submitted_id
        grade = "green" if maximum >= config.sc_threshold else "yellow" if maximum >= config.sc_threshold - config.sc_marginal else "blue"
        results[alpha_id] = {"sc": round(maximum, 4), "grade": grade, "max_corr_with": counterpart}
    return results


async def local_sc_precheck(candidates: Sequence[dict[str, Any]], submitted_ids: Sequence[str] = (), config: LocalCheckConfig = LocalCheckConfig()) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    alpha_ids = [row["alpha_id"] for row in candidates if row.get("alpha_id")]
    by_id = {row["alpha_id"]: row for row in candidates if row.get("alpha_id")}
    results = await compute_self_correlation(alpha_ids, submitted_ids, config)
    blue: list[dict[str, Any]] = []
    yellow: list[dict[str, Any]] = []
    green: list[dict[str, Any]] = []
    for alpha_id in alpha_ids:
        result = results.get(alpha_id, {})
        row = {**by_id[alpha_id], "local_sc": result.get("sc"), "local_sc_grade": result.get("grade", "unknown")}
        grade = str(result.get("grade", "unknown"))
        {"blue": blue, "yellow": yellow, "green": green}.get(grade, yellow).append(row)
    return blue, yellow, green
