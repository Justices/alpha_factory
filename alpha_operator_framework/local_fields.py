"""本地数据字段文件读取与筛选。

支持两种离线文件格式：
* CSV：平台字段导出，其中 ``dataset``/``category`` 等嵌套对象可为 JSON 字符串。
* JSON：字段对象组成的 JSON 数组。

读取后统一转换为 ``FieldSpec``，不请求平台。
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Iterable, List, Optional

from .fields import FieldSpec


def _as_dict(value: Any) -> dict:
    """兼容 JSON 对象、CSV 中的 JSON 字符串和空值。"""
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value) if value not in (None, "") else default
    except (TypeError, ValueError):
        return default


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value)) if value not in (None, "") else default
    except (TypeError, ValueError):
        return default


def read_local_field_rows(path: str | Path) -> List[dict]:
    """读取本地 CSV 或 JSON 数组，返回原始字段对象列表。"""
    file_path = Path(path)
    if not file_path.is_file():
        raise FileNotFoundError(f"字段文件不存在: {file_path}")

    suffix = file_path.suffix.lower()
    if suffix == ".csv":
        with file_path.open("r", encoding="utf-8-sig", newline="") as fh:
            return list(csv.DictReader(fh))
    if suffix == ".json":
        payload = json.loads(file_path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise ValueError(f"JSON 字段文件必须是对象数组: {file_path}")
        if not all(isinstance(row, dict) for row in payload):
            raise ValueError(f"JSON 字段文件包含非对象元素: {file_path}")
        return payload
    raise ValueError(f"只支持 CSV 或 JSON 字段文件，收到: {file_path.suffix or '无扩展名'}")


def load_local_field_specs(
    path: str | Path,
    *,
    region: Optional[str] = None,
    universe: Optional[str] = None,
    delay: Optional[int] = None,
    dataset_id: str = "",
    search: str = "",
    data_type: str = "",
) -> List[FieldSpec]:
    """读取并按研究设置预筛选本地字段文件。

    ``region``、``universe``、``delay``、``dataset_id``、``search`` 和
    ``data_type`` 均为可选精确筛选；空值表示不限制该条件。
    """
    rows = read_local_field_rows(path)
    selected: List[FieldSpec] = []
    search_text = search.lower().strip()
    type_filter = data_type.upper().strip()

    for row in rows:
        dataset = _as_dict(row.get("dataset"))
        row_dataset_id = str(dataset.get("id") or row.get("dataset_id") or "")
        field_id = str(row.get("id") or "").strip()
        field_type = str(row.get("type") or "").upper().strip()
        description = str(row.get("description") or "")
        row_region = str(row.get("region") or "")
        row_universe = str(row.get("universe") or "")
        row_delay = _as_int(row.get("delay"), default=-1)

        if not field_id:
            continue
        if region and row_region != region:
            continue
        if universe and row_universe != universe:
            continue
        if delay is not None and row_delay != delay:
            continue
        if dataset_id and row_dataset_id != dataset_id:
            continue
        if type_filter and field_type != type_filter:
            continue
        if search_text and search_text not in f"{field_id} {description}".lower():
            continue

        selected.append(FieldSpec(
            id=field_id,
            dataset_id=row_dataset_id,
            type=field_type,
            coverage=_as_float(row.get("coverage")),
            user_count=_as_int(row.get("userCount")),
            alpha_count=_as_int(row.get("alphaCount")),
            name=str(row.get("name") or ""),
            description=description,
        ))
    return selected


__all__ = ["read_local_field_rows", "load_local_field_specs"]
