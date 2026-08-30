"""Pairwise PnL-correlation pruning."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Sequence

from .common import metric, number


@dataclass(frozen=True)
class CorrelationPruneConfig:
    threshold: float = 0.7
    min_periods: int = 100
    concurrency: int = 4
    drop_if_pnl_missing: bool = False
    order_by: str = "sharpe"


@dataclass(frozen=True)
class MultiChannelCorrelationConfig:
    """Greedy correlation pruning in several metric-ranked channels."""

    channels: tuple[str, ...] = ("sharpe", "fitness", "margin")
    first_band_size: int = 5
    second_band_size: int = 5
    first_threshold: float = 0.85
    second_threshold: float = 0.80
    final_threshold: float = 0.75
    min_periods: int = 100
    concurrency: int = 4
    max_consecutive_flat_days: int = 200
    max_tail_flat_ratio: float = 0.30
    drop_if_pnl_missing: bool = False

    def threshold_for_rank(self, rank_index: int) -> float:
        if rank_index < self.first_band_size:
            return self.first_threshold
        if rank_index < self.first_band_size + self.second_band_size:
            return self.second_threshold
        return self.final_threshold


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


def flat_pnl_reason(values: Any, config: MultiChannelCorrelationConfig) -> str | None:
    """Detect factory/flat PnL from daily PnL changes."""
    if values is None or len(values) == 0:
        return None
    zero = values.abs().le(1e-12)
    longest = current = 0
    for is_zero in zero.tolist():
        current = current + 1 if bool(is_zero) else 0
        longest = max(longest, current)
    if longest > config.max_consecutive_flat_days:
        return "pnl_flat_run"
    trailing = 0
    for is_zero in reversed(zero.tolist()):
        if not bool(is_zero):
            break
        trailing += 1
    if trailing / len(zero) > config.max_tail_flat_ratio:
        return "pnl_flat_tail"
    return None


async def multi_channel_correlation_prune(
    candidates: Sequence[dict[str, Any]],
    config: MultiChannelCorrelationConfig = MultiChannelCorrelationConfig(),
    *,
    pnl_fetcher: Callable[[str], Awaitable[dict[str, Any]]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Keep the union of Sharpe/Fitness/Margin correlation-pruned channels.

    PnL is fetched once per platform Alpha. Rows without local/platform PnL are
    retained by default and annotated, so a transient read failure cannot erase
    an otherwise qualified research branch.
    """
    if not candidates:
        return [], []
    import pandas as pd

    identified = [row for row in candidates if row.get("alpha_id")]
    unidentified = [row for row in candidates if not row.get("alpha_id")]
    if not identified:
        return [dict(row) for row in candidates], []

    if pnl_fetcher is None:
        from cnhkmcp.untracked.platform_functions import brain_client

        await brain_client.ensure_authenticated()
        pnl_fetcher = brain_client.get_alpha_pnl

    semaphore = asyncio.Semaphore(max(config.concurrency, 1))

    async def fetch(row: dict[str, Any]) -> tuple[str, Any, str | None]:
        alpha_id = str(row["alpha_id"])
        async with semaphore:
            try:
                return alpha_id, pnl_returns(await pnl_fetcher(alpha_id)), None
            except Exception as exc:
                return alpha_id, None, str(exc)

    fetched = await asyncio.gather(*(fetch(row) for row in identified))
    series = {alpha_id: values for alpha_id, values, _ in fetched if values is not None}
    errors = {alpha_id: error for alpha_id, values, error in fetched if values is None and error}

    invalid: dict[str, str] = {}
    for alpha_id, values in series.items():
        if reason := flat_pnl_reason(values, config):
            invalid[alpha_id] = reason
    valid_rows = [row for row in identified if str(row["alpha_id"]) not in invalid]
    valid_series = {
        alpha_id: values for alpha_id, values in series.items() if alpha_id not in invalid
    }
    matrix = pd.DataFrame(valid_series).corr(min_periods=config.min_periods) if valid_series else pd.DataFrame()

    kept_channels: dict[str, set[str]] = {}
    conflict_details: dict[str, list[dict[str, Any]]] = {}
    for channel in config.channels:
        ranked = sorted(
            valid_rows,
            key=lambda row: (
                number(metric(row, channel)), number(metric(row, "sharpe")),
                number(metric(row, "fitness")), str(row.get("alpha_id")),
            ),
            reverse=True,
        )
        channel_kept: list[str] = []
        for rank_index, row in enumerate(ranked):
            alpha_id = str(row["alpha_id"])
            if alpha_id not in valid_series:
                if not config.drop_if_pnl_missing:
                    channel_kept.append(alpha_id)
                continue
            threshold = config.threshold_for_rank(rank_index)
            conflicts: list[dict[str, Any]] = []
            for prior_id in channel_kept:
                if prior_id not in valid_series:
                    continue
                value = matrix.loc[alpha_id, prior_id]
                if pd.notna(value) and abs(float(value)) >= threshold:
                    conflicts.append({
                        "id": prior_id, "corr": round(float(value), 4),
                        "threshold": threshold, "channel": channel,
                    })
            if conflicts:
                conflict_details.setdefault(alpha_id, []).extend(conflicts)
            else:
                channel_kept.append(alpha_id)
        for alpha_id in channel_kept:
            kept_channels.setdefault(alpha_id, set()).add(channel)

    kept: list[dict[str, Any]] = []
    pruned: list[dict[str, Any]] = []
    for row in identified:
        alpha_id = str(row["alpha_id"])
        if alpha_id in invalid:
            pruned.append({**row, "prune_reason": invalid[alpha_id]})
        elif alpha_id in kept_channels:
            note: dict[str, Any] = {"selection_channels": sorted(kept_channels[alpha_id])}
            if alpha_id not in series:
                note.update({"prune_note": "pnl_unavailable", "prune_detail": errors.get(alpha_id)})
            kept.append({**row, **note})
        else:
            pruned.append({
                **row,
                "prune_reason": "multi_channel_corr",
                "prune_conflicts": conflict_details.get(alpha_id, []),
            })
    kept.extend(dict(row) for row in unidentified)
    return kept, pruned


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
