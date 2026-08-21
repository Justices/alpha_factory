"""数据库连接管理模块 — SQLite WAL 模式、连接池与事务管理器.

功能:
  1. 开启 SQLite WAL 模式 (Write-Ahead Logging): 支持非阻塞并发读与串行写
  2. 线程安全连接管理 (Thread-Local): 每个线程拥有独立 Connection，杜绝跨线程操作冲突
  3. 连接级 PRAGMA 性能调优 (busy_timeout=30s, synchronous=NORMAL, 64MB 缓存)
  4. 事务上下文管理器: 异常自动 ROLLBACK，正常退出自动 COMMIT
"""

from __future__ import annotations

import os
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Generator, List, Optional, Set


class DatabaseConnectionManager:
    """线程安全、WAL 模式优化的 SQLite 连接管理器."""

    def __init__(
        self,
        db_path: Path | str,
        timeout: float = 30.0,
        wal_mode: bool = True,
        cache_size_mb: int = 64,
    ):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.timeout = timeout
        self.wal_mode = wal_mode
        self.cache_size_mb = cache_size_mb

        self._local = threading.local()
        self._all_connections: Set[sqlite3.Connection] = set()
        self._lock = threading.Lock()

        # 确保初始主连接建立
        self.get_connection()

    def _init_pragmas(self, conn: sqlite3.Connection) -> None:
        """为连接配置关键 PRAGMA 参数."""
        cursor = conn.cursor()
        try:
            if self.wal_mode:
                try:
                    current_mode = cursor.execute("PRAGMA journal_mode;").fetchone()
                    if current_mode and str(current_mode[0]).lower() != "wal":
                        cursor.execute("PRAGMA journal_mode = WAL;")
                except Exception:
                    pass
            try:
                cursor.execute(f"PRAGMA busy_timeout = {int(self.timeout * 1000)};")
                cursor.execute("PRAGMA synchronous = NORMAL;")
                cursor.execute(f"PRAGMA cache_size = -{int(self.cache_size_mb * 1000)};")
                cursor.execute("PRAGMA temp_store = MEMORY;")
                cursor.execute("PRAGMA foreign_keys = ON;")
            except Exception:
                pass
        finally:
            cursor.close()

    def get_connection(self) -> sqlite3.Connection:
        """获取当前线程专属的数据库连接."""
        conn = getattr(self._local, "conn", None)
        if conn is None:
            # 创建新连接
            conn = sqlite3.connect(
                self.db_path,
                timeout=self.timeout,
                check_same_thread=False,
            )
            conn.row_factory = sqlite3.Row
            self._init_pragmas(conn)
            self._local.conn = conn

            with self._lock:
                self._all_connections.add(conn)

        return conn

    @contextmanager
    def cursor(self) -> Generator[sqlite3.Cursor, None, None]:
        """获取当前线程连接的 Cursor 上下文."""
        conn = self.get_connection()
        cur = conn.cursor()
        try:
            yield cur
        finally:
            cur.close()

    @contextmanager
    def transaction(self) -> Generator[sqlite3.Connection, None, None]:
        """事务上下文管理器: 正常退出自动 COMMIT，异常自动 ROLLBACK."""
        conn = self.get_connection()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    def close_current_thread(self) -> None:
        """关闭当前线程持有的连接."""
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
            self._local.conn = None
            with self._lock:
                self._all_connections.discard(conn)

    def close_all(self) -> None:
        """关闭所有线程已注册的活跃连接."""
        with self._lock:
            for conn in list(self._all_connections):
                try:
                    conn.close()
                except Exception:
                    pass
            self._all_connections.clear()
        self._local.conn = None
