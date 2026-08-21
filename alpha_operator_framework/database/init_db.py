"""数据库表初始化与迁移脚本 (Database Schema Initializer & Verifier).

支持全新初始化、增量迁移、表结构校验与重置。
杜绝直接提交二进制 .db 文件到 Git 代码仓库。
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from alpha_operator_framework.database.config import get_database_path

logger = logging.getLogger("init_db")

# 默认主数据库路径 (支持环境变量配置)
DEFAULT_DB_PATH = get_database_path()
SCHEMA_DIR = Path(__file__).parent / "schema"
LATEST_SCHEMA_FILE = SCHEMA_DIR / "latest_schema.sql"

# 事件溯源日志表 DDL
EVENT_LOG_DDL = """
CREATE TABLE IF NOT EXISTS event_log (
    global_offset INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    stream_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    schema_version INTEGER NOT NULL DEFAULT 1,
    payload TEXT NOT NULL,
    payload_ref TEXT,
    occurred_at TEXT NOT NULL,
    actor TEXT NOT NULL,
    metadata TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_evt_stream ON event_log(stream_id, global_offset);
CREATE INDEX IF NOT EXISTS idx_evt_type ON event_log(event_type, global_offset);
"""


def init_database(
    db_path: Path = DEFAULT_DB_PATH,
    reset: bool = False,
    verbose: bool = True,
) -> Tuple[bool, List[str]]:
    """初始化 SQLite 数据库表结构与索引.

    Args:
        db_path: 数据库文件路径 (默认为 data/alpha_research.db)
        reset: 若为 True，则先删除已有库文件后全新初始化
        verbose: 是否打印详细表信息

    Returns:
        (是否成功, 创建/校验的表名称列表)
    """
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    if reset and db_path.exists():
        if verbose:
            print(f"⚠️  正在重置数据库: 删除已有文件 {db_path} ...")
        # 清理 WAL 伴随文件
        for ext in ("", "-wal", "-shm", "-journal"):
            f = Path(str(db_path) + ext)
            if f.exists():
                f.unlink()

    conn = sqlite3.connect(db_path)
    created_tables: List[str] = []

    try:
        # 1. 启用高并发 WAL 与性能 PRAGMA
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA busy_timeout = 30000")
        conn.execute("PRAGMA foreign_keys = ON")

        # 2. 加载并执行 latest_schema.sql
        if LATEST_SCHEMA_FILE.exists():
            schema_sql = LATEST_SCHEMA_FILE.read_text(encoding="utf-8")
            conn.executescript(schema_sql)
        else:
            raise FileNotFoundError(f"未找到 Schema 文件: {LATEST_SCHEMA_FILE}")

        # 3. 补充执行事件溯源 event_log 表
        conn.executescript(EVENT_LOG_DDL)

        # 4. 写入最新 schema 版本标记
        conn.execute(
            "INSERT OR REPLACE INTO schema_version (version, applied_at) VALUES ('010_event_core', datetime('now'))"
        )
        conn.commit()

        # 5. 自动填充模板库种子
        try:
            from alpha_operator_framework.database.repository import AlphaDatabase
            db_inst = AlphaDatabase(db_path=str(db_path))
            db_inst.seed_template_library()
        except Exception:
            pass

        # 6. 查询所有已创建的用户表与视图
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name, type FROM sqlite_master WHERE type IN ('table', 'view') AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
        rows = cursor.fetchall()
        created_tables = [r[0] for r in rows]

        if verbose:
            print(f"✅ 数据库初始化完成: {db_path.resolve()}")
            print(f"📊 共就绪 {len(created_tables)} 张核心数据表/视图:")
            for t in created_tables:
                cursor.execute(f"PRAGMA table_info({t})")
                col_count = len(cursor.fetchall())
                cursor.execute(f"SELECT COUNT(*) FROM {t}")
                row_count = cursor.fetchone()[0]
                print(f"   • {t:<28} (字段数: {col_count:<2}, 当前行数: {row_count})")

        return True, created_tables

    except Exception as e:
        if verbose:
            print(f"❌ 数据库初始化失败: {e}", file=sys.stderr)
        return False, []
    finally:
        conn.close()


def verify_database(db_path: Path = DEFAULT_DB_PATH) -> bool:
    """校验现有数据库完整性与表结构."""
    db_path = Path(db_path)
    if not db_path.exists():
        print(f"❌ 数据库文件不存在: {db_path}")
        return False

    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("PRAGMA integrity_check")
        status = cursor.fetchone()[0]
        if status != "ok":
            print(f"❌ SQLite 完整性检查未通过: {status}")
            return False

        cursor.execute("SELECT version, applied_at FROM schema_version")
        versions = cursor.fetchall()
        print(f"✅ 数据库完整性检查通过 (PRAGMA integrity_check = ok)")
        print(f"📌 已应用 Schema 版本:")
        for v in versions:
            print(f"   • 版本: {v[0]:<20} (应用时间: {v[1]})")
        return True
    except Exception as e:
        print(f"❌ 校验发生异常: {e}")
        return False
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="Alpha Factory 数据库初始化与校验工具")
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH, help="SQLite 数据库文件路径")
    parser.add_argument("--reset", action="store_true", help="清空并全新重建数据库")
    parser.add_argument("--verify", action="store_true", help="仅校验现有数据库完整性")

    args = parser.parse_args()

    if args.verify:
        success = verify_database(args.db_path)
        sys.exit(0 if success else 1)

    success, _ = init_database(db_path=args.db_path, reset=args.reset)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
