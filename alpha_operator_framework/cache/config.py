"""数据缓存配置."""

from pathlib import Path

# 项目根目录
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# 数据目录
DATA_DIR = PROJECT_ROOT / "data"

# 缓存根目录（金字塔、Universe、操作符等）
CACHE_ROOT = DATA_DIR / "cache"

# 各类型缓存目录
PYRAMIDS_CACHE = CACHE_ROOT / "pyramids.json"
UNIVERSES_CACHE = CACHE_ROOT / "universes"
OPERATORS_CACHE = CACHE_ROOT / "operators.json"
DATASETS_CACHE = CACHE_ROOT / "datasets"

# 数据字段缓存根目录（实际字段文件位于 {region}/{delay}/{universe}/datafields/）
DATAFIELDS_DIR = DATA_DIR
SCOPE_DIRECTORY_TEMPLATE = "{region}/{delay}/{universe}"
UNIVERSE_INDEX_TEMPLATE = "{region}/{delay}/universe.json"
DATASET_INDEX_TEMPLATE = "{region}/{delay}/{universe}/dataset.json"
DATAFIELDS_DIRECTORY_TEMPLATE = "{region}/{delay}/{universe}/datafields"
DATAFIELD_FILE_TEMPLATE = "{region}/{delay}/{universe}/datafields/{dataset}.json"


def render_datafield_cache_path(root: Path, template: str, **values: object) -> Path:
    """Render a datafield-cache path from one of the relative layout templates."""
    return root / Path(template.format(**values))

# 默认缓存过期时间（秒），0 表示永不过期
DEFAULT_TTL = 0

__all__ = [
    "PROJECT_ROOT",
    "DATA_DIR",
    "CACHE_ROOT",
    "PYRAMIDS_CACHE",
    "UNIVERSES_CACHE",
    "DATAFIELDS_DIR",
    "SCOPE_DIRECTORY_TEMPLATE",
    "UNIVERSE_INDEX_TEMPLATE",
    "DATASET_INDEX_TEMPLATE",
    "DATAFIELDS_DIRECTORY_TEMPLATE",
    "DATAFIELD_FILE_TEMPLATE",
    "render_datafield_cache_path",
    "OPERATORS_CACHE",
    "DATASETS_CACHE",
    "DEFAULT_TTL",
]
