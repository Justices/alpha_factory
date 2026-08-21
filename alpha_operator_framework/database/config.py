"""全局数据库配置与存储介质抽象模块 (Database Configuration & Storage Abstraction).

集中管理数据库连接配置、存储驱动 (SQLite / MySQL / PostgreSQL) 与环境变量适配，
为后续平滑迁移至 MySQL / PostgreSQL 或分布式存储介质提供统一配置中心与解耦支持。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional, Union
from urllib.parse import urlparse

# 默认全局 SQLite 存储路径
DEFAULT_SQLITE_PATH = Path("data") / "alpha_research.db"


@dataclass
class DatabaseConfig:
    """全局数据库配置实体."""

    driver: str = "sqlite"  # sqlite / mysql / postgresql
    database: str = str(DEFAULT_SQLITE_PATH)
    host: Optional[str] = None
    port: Optional[int] = None
    username: Optional[str] = None
    password: Optional[str] = None
    url: Optional[str] = None
    timeout: float = 30.0
    wal_mode: bool = True
    cache_size_mb: int = 64
    options: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_env(cls) -> DatabaseConfig:
        """从环境变量或全局默认值加载数据库配置."""
        # 1. 优先读取完整 URL 连接串 (如 mysql://user:pass@localhost:3306/alpha_db)
        db_url = os.environ.get("ALPHA_DATABASE_URL") or os.environ.get("DATABASE_URL")
        if db_url:
            return cls.from_url(db_url)

        # 2. 读取驱动与文件路径
        driver = os.environ.get("ALPHA_DB_DRIVER", "sqlite").lower()
        db_path = os.environ.get("ALPHA_DATABASE_PATH") or os.environ.get("ALPHA_DB_PATH") or str(DEFAULT_SQLITE_PATH)

        timeout = float(os.environ.get("ALPHA_DB_TIMEOUT", 30.0))
        wal_mode = os.environ.get("ALPHA_DB_WAL", "true").lower() in ("true", "1", "yes")
        cache_mb = int(os.environ.get("ALPHA_DB_CACHE_MB", 64))

        return cls(
            driver=driver,
            database=db_path,
            host=os.environ.get("ALPHA_DB_HOST"),
            port=int(os.environ.get("ALPHA_DB_PORT")) if os.environ.get("ALPHA_DB_PORT") else None,
            username=os.environ.get("ALPHA_DB_USER"),
            password=os.environ.get("ALPHA_DB_PASSWORD"),
            timeout=timeout,
            wal_mode=wal_mode,
            cache_size_mb=cache_mb,
        )

    @classmethod
    def from_url(cls, url: str) -> DatabaseConfig:
        """从 URL 解析数据库配置 (支持 sqlite:///, mysql://, postgresql://)."""
        parsed = urlparse(url)
        scheme = parsed.scheme.lower()

        if scheme in ("sqlite", ""):
            raw_path = parsed.path
            if raw_path.startswith("/") and len(raw_path) > 2 and raw_path[2] == ":":
                db_path = raw_path.lstrip("/")
            elif raw_path.startswith("/"):
                db_path = raw_path.lstrip("/")
            else:
                db_path = raw_path

            if not db_path:
                db_path = str(DEFAULT_SQLITE_PATH)
            return cls(driver="sqlite", database=db_path, url=url)

        driver = "mysql" if "mysql" in scheme else ("postgresql" if "postgres" in scheme else scheme)
        return cls(
            driver=driver,
            database=parsed.path.lstrip("/"),
            host=parsed.hostname,
            port=parsed.port,
            username=parsed.username,
            password=parsed.password,
            url=url,
        )

    @property
    def sqlite_path(self) -> Path:
        """获取 SQLite 本地存储路径."""
        return Path(self.database)


# 全局单例配置
_GLOBAL_DB_CONFIG: Optional[DatabaseConfig] = None


def get_database_config() -> DatabaseConfig:
    """获取当前生效的全局数据库配置."""
    global _GLOBAL_DB_CONFIG
    if _GLOBAL_DB_CONFIG is None:
        _GLOBAL_DB_CONFIG = DatabaseConfig.from_env()
    return _GLOBAL_DB_CONFIG


def set_database_config(config: Union[DatabaseConfig, str, Path]) -> DatabaseConfig:
    """显式设置或覆盖全局数据库配置."""
    global _GLOBAL_DB_CONFIG
    if isinstance(config, (str, Path)):
        _GLOBAL_DB_CONFIG = DatabaseConfig(database=str(config))
    elif isinstance(config, DatabaseConfig):
        _GLOBAL_DB_CONFIG = config
    else:
        raise TypeError(f"Invalid config type: {type(config)}")
    return _GLOBAL_DB_CONFIG


def get_database_path(configured_path: Optional[Union[str, Path]] = None) -> Path:
    """解析并返回有效的数据库路径 (支持入参覆盖 > 环境变量 > 默认配置)."""
    if configured_path is not None:
        return Path(configured_path)
    return get_database_config().sqlite_path
