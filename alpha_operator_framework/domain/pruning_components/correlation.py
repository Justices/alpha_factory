"""Pairwise PnL-correlation pruning."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Sequence

from .common import metric, number


@dataclass(frozen=True)
class CorrelationPruneConfig:
    threshold: float = 0.7
    min_periods: int = 100
    concurrency: int = 4
    drop_if_pnl_missing: bool = False
    order_by: str = "sharpe"


def pnl_returns(payload: dict) -> Any:
    import pandas as pd
    records = payload.get("records") or []
    names = [item.get("name") if isinstance(item, dict) else item for item in (payload.get("schema") or {}).get("properties", [])]
    rows = [record if isinstance(record, dict) else dict(zip(names, record)) for record in records if isinstance(record, dict) or names]
    if not rows:
        return None
    frame = pd.DataFrame(rows)
    if not {"date", "pnl"}.issubset(frame.columns):
        return None
    pnl = frame.assign(date=pd.to_datetime(frame["date"])).sort_values("date").set_index("date")["pnl"].astype(float)
    values = pnl.diff().dropna()
    return values if len(values) >= 2 else None


async def correlation_prune(candidates: Sequence[dict[str, Any]], config: CorrelationPruneConfig = CorrelationPruneConfig()) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not candidates:
        return [], []
    import pandas as pd
    from cnhkmcp.untracked.platform_functions import brain_client
    ranked = sorted(candidates, key=lambda row: (number(metric(row, config.order_by)), number(metric(row, "fitness"))), reverse=True)
    without_id, ranked = [row for row in ranked if not row.get("alpha_id")], [row for row in ranked if row.get("alpha_id")]
    await brain_client.ensure_authenticated()
    semaphore = asyncio.Semaphore(max(config.concurrency, 1))
    async def fetch(row: dict[str, Any]):
        async with semaphore:
            try:
                return row["alpha_id"], pnl_returns(await brain_client.get_alpha_pnl(row["alpha_id"])), None
            except Exception as exc:
                return row["alpha_id"], None, str(exc)
    fetched = await asyncio.gather(*(fetch(row) for row in ranked))
    series = {alpha_id: values for alpha_id, values, _ in fetched if values is not None}
    errors = {alpha_id: error for alpha_id, values, error in fetched if values is None and error}
    matrix = pd.DataFrame(series).corr(min_periods=config.min_periods) if series else pd.DataFrame()
    kept: list[dict[str, Any]] = []
    pruned: list[dict[str, Any]] = []
    for row in ranked:
        alpha_id = row["alpha_id"]
        if alpha_id not in series:
            (pruned if config.drop_if_pnl_missing else kept).append({**row, **({"prune_reason": "pnl_unavailable", "prune_detail": errors.get(alpha_id)} if config.drop_if_pnl_missing else {"prune_note": "pnl_unavailable"})})
            continue
        conflicts = [{"id": prior["alpha_id"], "corr": round(float(value), 4)} for prior in kept if prior.get("alpha_id") in series for value in [matrix.loc[alpha_id, prior["alpha_id"]]] if pd.notna(value) and abs(float(value)) >= config.threshold]
        if conflicts:
            pruned.append({**row, "prune_reason": "pairwise_corr", "prune_conflicts": conflicts})
        else:
            kept.append(row)
    kept.extend(without_id)
    return kept, pruned
