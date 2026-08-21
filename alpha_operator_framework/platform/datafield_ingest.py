"""按需采集 datafields — 随机抽一个字段, 串行访问平台, 节流防 429.

设计红线 (用户确认):
  * 每次只随机挑选一个字段访问, 不批量拉全量
  * 即使访问多个也严格串行, 不并发
  * 与 alpha_operator_framework/local_fields.py 的文件缓存共存: DB 表是新的
    增量缓存层, 文件缓存仍供离线批量读取
"""

from __future__ import annotations

import asyncio
import random
from typing import Any, Optional, Sequence


async def ingest_random_datafield(
    db: "AlphaDatabase",
    *,
    region: str,
    universe: str,
    delay: int,
    dataset_id: str = "",
    candidates: Optional[Sequence[str]] = None,
    only_missing: bool = True,
    page_delay: float = 0.5,
    seed: Optional[int] = None,
) -> Optional[dict[str, Any]]:
    """从候选字段池随机抽一个字段, 串行 fetch 其平台元数据并 upsert 到 datafields.

    - candidates 为空时用 ``db.missing_datafield_candidates(region, delay)``
      (已被 alpha 用但未采集的字段)
    - only_missing=True 时再剔除已存在于 datafields 的字段
    - 每次请求前 ``await asyncio.sleep(page_delay)`` 节流; ``fetch_datafields``
      内部翻页同样带 page_delay
    - 平台无返回时写入最小占位行, 避免下次重复抽取同一字段导致请求风暴

    Args:
        db: AlphaDatabase 实例
        region: 区域 (如 GBR/EUR)
        universe: 股票池 (如 TOP700)
        delay: 数据延迟 0/1
        dataset_id: 数据集过滤 (可选)
        candidates: 显式候选字段池 (可选)
        only_missing: 是否只采缺失字段
        page_delay: 请求间隔秒数 (防 429)
        seed: 随机种子

    Returns:
        写入的原始行; 无候选/无写入返回 None
    """
    import alpha_machine  # lazy: 避免顶层循环依赖

    if candidates is not None:
        pool = list(candidates)
    else:
        pool = db.missing_datafield_candidates(region=region, delay=delay)
    if only_missing:
        have = db.get_existing_datafield_ids(region=region, delay=delay)
        pool = [f for f in pool if f not in have]
    if not pool:
        return None

    field_id = random.Random(seed).choice(pool)
    await asyncio.sleep(page_delay)  # 串行节流, 防 429
    rows = await alpha_machine.fetch_datafields(
        region, universe, delay, dataset_id=dataset_id, search=field_id, page_delay=page_delay)
    hit = next((r for r in rows if str(r.get("id")) == field_id), None)
    if not hit:
        # 平台无返回: 写最小占位行, 避免下次重复抽取同一字段
        hit = {"id": field_id, "region": region, "delay": delay, "universe": universe,
               "type": "", "dataset": {"id": dataset_id, "name": ""}}
    db.upsert_datafield(hit)
    return hit


def pick_missing_field(db: "AlphaDatabase", *, region: str, delay: int,
                       seed: Optional[int] = None) -> Optional[str]:
    """同步便捷入口: 返回缺失候选池中随机一个字段 id (不访问平台).

    Args:
        db: AlphaDatabase 实例
        region: 区域
        delay: 数据延迟
        seed: 随机种子

    Returns:
        随机字段 id; 无候选返回 None
    """
    pool = db.missing_datafield_candidates(region=region, delay=delay)
    return random.Random(seed).choice(pool) if pool else None
