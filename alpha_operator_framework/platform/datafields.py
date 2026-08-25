"""Platform adapter for paged BRAIN data-field retrieval."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any


def retry_after_seconds(response: Any, *, fallback: float) -> float:
    raw = (response.headers or {}).get("Retry-After")
    try:
        return max(float(raw), 0.0)
    except (TypeError, ValueError):
        try:
            return max((parsedate_to_datetime(raw) - datetime.now(timezone.utc)).total_seconds(), 0.0)
        except (TypeError, ValueError, IndexError, OverflowError):
            return fallback


async def fetch_datafields(region: str, universe: str, delay: int, dataset_id: str = "", search: str = "", data_type: str = "", page_delay: float = 0.5, max_retries: int = 5, max_rows: int | None = None) -> list[dict[str, Any]]:
    from cnhkmcp.untracked.platform_functions import brain_client

    await brain_client.ensure_authenticated()
    params: dict[str, str] = {"instrumentType": "EQUITY", "region": region, "universe": universe, "delay": str(delay), "limit": "50", "offset": "0"}
    if dataset_id: params["dataset.id"] = dataset_id
    if search: params["search"] = search
    if data_type: params["type"] = data_type.upper()
    rows: list[dict[str, Any]] = []
    total: int | None = None
    while (total is None or len(rows) < total) and (max_rows is None or len(rows) < max_rows):
        if rows and page_delay > 0:
            await asyncio.sleep(page_delay)
        params["offset"] = str(len(rows))
        for _ in range(max_retries + 1):
            response = brain_client.session.get(f"{brain_client.base_url}/data-fields", params=params)
            if response.status_code != 429:
                break
            await asyncio.sleep(retry_after_seconds(response, fallback=page_delay + 1.0))
        response.raise_for_status()
        payload = response.json()
        total = int(payload.get("count") or 0)
        page = payload.get("results") or []
        if not page:
            break
        rows.extend(page[:max_rows - len(rows)] if max_rows is not None else page)
    return rows
