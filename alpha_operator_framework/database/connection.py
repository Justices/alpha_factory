"""Driver-neutral connection lifecycle for legacy aggregate repositories."""

from __future__ import annotations

import threading
import re
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generator, Set

from alpha_operator_framework.infrastructure.storage import StorageConfig, create_storage_engine


def translate_sql(statement: str, driver: str) -> str:
    """Keep legacy repositories portable without leaking dialect branches into them."""
    if driver != "mysql":
        return statement
    translated = statement.replace("?", "%s").replace("INSERT OR IGNORE", "INSERT IGNORE").replace("INSERT OR REPLACE", "REPLACE")
    translated = re.sub(r"\s+ON\s+CONFLICT\s*\([^)]*\)\s+DO\s+NOTHING", " ON DUPLICATE KEY UPDATE id=id", translated, flags=re.IGNORECASE)
    translated = re.sub(r"\s+ON\s+CONFLICT\s*\([^)]*\)\s+DO\s+UPDATE\s+SET\s+(.+)$", lambda match: " ON DUPLICATE KEY UPDATE " + re.sub(r"excluded\.([A-Za-z_]+)", r"VALUES(\1)", match.group(1)), translated, flags=re.IGNORECASE | re.DOTALL)
    return translated


class _Cursor:
    def __init__(self, cursor: Any, driver: str) -> None:
        self._cursor, self._driver = cursor, driver

    def execute(self, statement: str, parameters: Any = None):
        self._cursor.execute(translate_sql(statement, self._driver), () if parameters is None else parameters)
        return self

    def executemany(self, statement: str, parameters: Any):
        self._cursor.executemany(translate_sql(statement, self._driver), parameters)
        return self

    def _map_row(self, row: Any) -> Any:
        if row is None or not isinstance(row, tuple):
            return row
        columns = [column[0] for column in self._cursor.description or ()]
        return _MappingRow(columns, row)

    def fetchone(self):
        return self._map_row(self._cursor.fetchone())

    def fetchall(self):
        return [self._map_row(row) for row in self._cursor.fetchall()]

    def __iter__(self):
        return (self._map_row(row) for row in self._cursor)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._cursor, name)


class _MappingRow(dict):
    """Expose tuple-returning DB-API rows through the legacy mapping contract."""

    def __init__(self, columns: list[str], values: tuple[Any, ...]) -> None:
        super().__init__(zip(columns, values))
        self._values = values

    def __getitem__(self, key: Any) -> Any:
        return self._values[key] if isinstance(key, int) else super().__getitem__(key)


class _Connection:
    def __init__(self, connection: Any, driver: str) -> None:
        self._connection, self._driver = connection, driver

    def cursor(self) -> _Cursor:
        return _Cursor(self._connection.cursor(), self._driver)

    def execute(self, statement: str, parameters: Any = None) -> _Cursor:
        return self.cursor().execute(statement, parameters)

    def executemany(self, statement: str, parameters: Any) -> _Cursor:
        return self.cursor().executemany(statement, parameters)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._connection, name)


class DatabaseConnectionManager:
    """Own one SQLAlchemy engine and open DB-API connections lazily per thread."""

    def __init__(self, storage: StorageConfig | Path | str, timeout: float = 30.0, wal_mode: bool = True, cache_size_mb: int = 64) -> None:
        self.storage = storage if isinstance(storage, StorageConfig) else StorageConfig.from_mapping(
            {"driver": "sqlite", "path": str(storage)}
        )
        self.engine = create_storage_engine(self.storage)
        self.db_path = Path(self.engine.url.database) if self.storage.driver == "sqlite" else self.storage.url
        self.timeout, self.wal_mode, self.cache_size_mb = timeout, wal_mode, cache_size_mb
        self._local = threading.local()
        self._all_connections: Set[Any] = set()
        self._lock = threading.Lock()

    def _init_connection(self, connection: Any) -> None:
        if self.storage.driver != "sqlite":
            return
        driver_connection = getattr(connection, "driver_connection", connection)
        row_factory = getattr(getattr(self.engine.dialect, "dbapi", None), "Row", None)
        if row_factory is not None and hasattr(driver_connection, "row_factory"):
            driver_connection.row_factory = row_factory
        cursor = connection.cursor()
        try:
            if self.wal_mode:
                cursor.execute("PRAGMA journal_mode = WAL;")
            cursor.execute(f"PRAGMA busy_timeout = {int(self.timeout * 1000)};")
            cursor.execute("PRAGMA synchronous = NORMAL;")
            cursor.execute(f"PRAGMA cache_size = -{int(self.cache_size_mb * 1000)};")
            cursor.execute("PRAGMA temp_store = MEMORY;")
            cursor.execute("PRAGMA foreign_keys = ON;")
        finally:
            cursor.close()

    def get_connection(self) -> Any:
        connection = getattr(self._local, "conn", None)
        if connection is None:
            raw_connection = self.engine.raw_connection()
            self._init_connection(raw_connection)
            connection = _Connection(raw_connection, self.storage.driver)
            self._local.conn = connection
            with self._lock:
                self._all_connections.add(connection)
        return connection

    @contextmanager
    def cursor(self) -> Generator[Any, None, None]:
        cursor = self.get_connection().cursor()
        try:
            yield cursor
        finally:
            cursor.close()

    @contextmanager
    def transaction(self) -> Generator[Any, None, None]:
        connection = self.get_connection()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise

    def close_current_thread(self) -> None:
        connection = getattr(self._local, "conn", None)
        if connection is not None:
            connection.close()
            self._local.conn = None
            with self._lock:
                self._all_connections.discard(connection)

    def close_all(self) -> None:
        with self._lock:
            for connection in list(self._all_connections):
                connection.close()
            self._all_connections.clear()
        self._local.conn = None
        self.engine.dispose()
