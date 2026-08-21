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

from alpha_operator_framework.domain.fields import FieldSpec


def default_fields_directory(project_root: str | Path, region: str, delay: int, universe: str) -> Path:
    """Return the conventional local field-data directory."""
    return Path(project_root) / "data" / "fields" / region / str(delay) / universe


def default_dataset_file(
    project_root: str | Path, region: str, delay: int, universe: str, dataset_id: str, file_type: str,
) -> Path:
    """Return the conventional file path for one dataset export."""
    if file_type not in ("csv", "json"):
        raise ValueError(f"dataset file type 必须是 csv/json，收到: {file_type}")
    return default_fields_directory(project_root, region, delay, universe) / f"{dataset_id}.{file_type}"

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


def extract_category(row: dict) -> str:
    """从平台字段原始行提取 category id (兼容嵌套 dict 与 CSV JSON 字符串)."""
    cat = row.get("category")
    if isinstance(cat, dict):
        return str(cat.get("id") or "")
    if isinstance(cat, str) and cat.strip():
        parsed = _as_dict(cat)
        if parsed.get("id"):
            return str(parsed["id"])
        return cat
    return str(cat or "")


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
        payload = json.loads(file_path.read_text(encoding="utf-8-sig"))
        if isinstance(payload, dict):
            return [payload]
        if not isinstance(payload, list):
            raise ValueError(f"JSON 字段文件必须是对象或对象数组: {file_path}")
        if not all(isinstance(row, dict) for row in payload):
            raise ValueError(f"JSON 字段文件包含非对象元素: {file_path}")
        return payload
    raise ValueError(f"只支持 CSV 或 JSON 字段文件，收到: {file_path.suffix or '无扩展名'}")


def load_local_field_specs(
    path: str | Path,
    *,
    file_type: str = "auto",
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
    file_path = Path(path)
    kind = file_type.lower()
    if kind not in ("auto", "csv", "json"):
        raise ValueError(f"fields file type 必须是 auto/csv/json，收到: {file_type}")
    if kind != "auto" and file_path.suffix.lower() != f".{kind}":
        raise ValueError(f"字段文件类型与 --fields-file-type 不一致: {file_path}")
    rows = read_local_field_rows(file_path)
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
            date_coverage=_as_float(row.get("dateCoverage")),
            user_count=_as_int(row.get("userCount")),
            alpha_count=_as_int(row.get("alphaCount")),
            name=str(row.get("name") or ""),
            description=description,
            economic_type=str(row.get("economic_type") or ""),
            frequency=str(row.get("frequency") or ""),
            signedness=str(row.get("signedness") or ""),
            scale=str(row.get("scale") or ""),
            category=extract_category(row),
        ))
    return selected


def load_local_field_directory(
    directory: str | Path,
    *,
    file_type: str = "auto",
    **filters,
) -> List[FieldSpec]:
    """Load and de-duplicate all CSV or JSON field files in one local scope."""
    directory_path = Path(directory)
    kind = file_type.lower()
    if kind not in ("auto", "csv", "json"):
        raise ValueError(f"fields file type 必须是 auto/csv/json，收到: {file_type}")
    suffixes = {".csv", ".json"} if kind == "auto" else {f".{kind}"}
    out: dict[str, FieldSpec] = {}
    for path in sorted(directory_path.glob("*")):
        if path.is_file() and path.suffix.lower() in suffixes:
            for field in load_local_field_specs(path, **filters):
                out.setdefault(field.id, field)
    return list(out.values())


__all__ = [
    "default_dataset_file", "default_fields_directory", "read_local_field_rows", "load_local_field_directory",
    "load_local_field_specs", "extract_category",
]
