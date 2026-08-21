"""真实市场字段动态采集与加载器 (Dynamic Market Field Loader).

功能:
  1. 依据目标市场 (Region), 宇宙 (Universe), 延迟 (Delay) 动态从本地缓存与数据库载入真实字段
  2. 支持按数据集名称 (Dataset IDs 如 analyst7, risk68, acquisition_model) 进行精细筛选
  3. 自动注入基准量价矩阵字段与向量行业分类字段
  4. 为文献研发流水线提供丰富的真实字段池，杜绝固定写死字段
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Union

from alpha_operator_framework.cache.config import DATAFIELDS_DIR
from alpha_operator_framework.domain.fields import FieldSpec

logger = logging.getLogger(__name__)

# 平台基准基础量价与行业分类字段 (已移除平台不再支持的 close/open/high/low 字段)
BASE_CORE_FIELDS: List[FieldSpec] = [
    FieldSpec(id="returns", dataset_id="pv1", type="MATRIX", description="Daily Returns"),
    FieldSpec(id="volume", dataset_id="pv1", type="MATRIX", description="Daily Trading Volume"),
    FieldSpec(id="vwap", dataset_id="pv1", type="MATRIX", description="Volume Weighted Average Price"),
    FieldSpec(id="subindustry", dataset_id="pv1", type="VECTOR", description="Subindustry Group Classification"),
    FieldSpec(id="industry", dataset_id="pv1", type="VECTOR", description="Industry Group Classification"),
    FieldSpec(id="sector", dataset_id="pv1", type="VECTOR", description="Sector Group Classification"),
    FieldSpec(id="market_cap", dataset_id="fnd1", type="MATRIX", description="Market Capitalization"),
    FieldSpec(id="sharesout", dataset_id="fnd1", type="MATRIX", description="Shares Outstanding"),
]


def load_real_market_fields(
    region: str = "GBR",
    universe: str = "TOP700",
    delay: int = 1,
    datasets: Optional[Sequence[str]] = None,
    custom_dir: Optional[Union[str, Path]] = None,
    max_fields: int = 500,
) -> List[FieldSpec]:
    """动态加载真实市场字段池 (严格过滤 close 等平台不推荐/不支持字段).

    Args:
        region: 目标区域 (如 GBR, USA, EUR)
        universe: 股票宇宙 (如 TOP700, TOP3000)
        delay: 延迟 (0 或 1)
        datasets: 指定加载的数据集 ID 列表 (如 ["analyst7", "risk68"])，若为 None 则加载全部本地可用数据集
        custom_dir: 自定义字段目录，默认为 data/fields/{region}/{delay}/{universe}
        max_fields: 最大载入字段数量

    Returns:
        FieldSpec 规格对象列表 (去重且包含基准字段)
    """
    fields_map: Dict[str, FieldSpec] = {f.id.lower(): f for f in BASE_CORE_FIELDS}

    target_dir = Path(custom_dir) if custom_dir else (DATAFIELDS_DIR / region / str(delay) / universe)
    if not target_dir.exists():
        # 尝试查找不同 delay 或 fallback 目录
        alt_dirs = list(DATAFIELDS_DIR.glob(f"{region}/*/{universe}"))
        if alt_dirs:
            target_dir = alt_dirs[0]

    if target_dir.exists():
        json_files = list(target_dir.glob("*.json"))
        for jf in json_files:
            ds_name = jf.stem
            if ds_name.startswith("_"):
                continue
            if datasets and ds_name not in datasets and f"{ds_name}.json" not in datasets:
                continue

            try:
                content = jf.read_text(encoding="utf-8-sig")
                if not content.strip():
                    continue
                data = json.loads(content)
                items = data if isinstance(data, list) else data.get("items", [])

                for row in items:
                    fid = row.get("id") or row.get("name")
                    if not fid:
                        continue
                    if str(fid).lower() in ("close", "open", "high", "low"):
                        continue
                    ftype = str(row.get("type") or "MATRIX").upper()
                    fdesc = str(row.get("description") or "")
                    cov = float(row.get("coverage") or 0.0)
                    user_c = int(row.get("userCount") or row.get("user_count") or 0)
                    alpha_c = int(row.get("alphaCount") or row.get("alpha_count") or 0)
                    cat = row.get("category") or ""
                    if isinstance(cat, dict):
                        cat = str(cat.get("id") or "")

                    spec = FieldSpec(
                        id=fid,
                        dataset_id=ds_name,
                        type=ftype,
                        coverage=cov,
                        user_count=user_c,
                        alpha_count=alpha_c,
                        category=str(cat),
                        description=fdesc,
                    )
                    fields_map[fid.lower()] = spec

                    if len(fields_map) >= max_fields:
                        break

            except Exception as e:
                logger.warning(f"读取数据集文件 {jf} 失败: {e}")

            if len(fields_map) >= max_fields:
                break

    return list(fields_map.values())
