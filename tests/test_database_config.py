"""Test Centralized Database Configuration & Storage Decoupling."""

import os
from pathlib import Path
from alpha_operator_framework.database.config import (
    DatabaseConfig,
    get_database_config,
    get_database_path,
    set_database_config,
    DEFAULT_SQLITE_PATH,
)
from alpha_operator_framework.database.repository import AlphaDatabase


def test_default_database_config():
    """Verify default database config returns expected standard path."""
    set_database_config(DEFAULT_SQLITE_PATH)
    config = get_database_config()
    assert config.driver == "sqlite"
    assert config.sqlite_path == DEFAULT_SQLITE_PATH
    assert get_database_path() == DEFAULT_SQLITE_PATH


def test_custom_database_path_override(tmp_path):
    """Verify custom database configuration override."""
    custom_db = tmp_path / "custom_alpha.db"
    set_database_config(custom_db)

    assert get_database_path() == custom_db
    db = AlphaDatabase()
    assert db.db_path == custom_db
    db.close()

    # Reset
    set_database_config(DEFAULT_SQLITE_PATH)


def test_database_config_from_url():
    """Verify URL parsing for future MySQL / PostgreSQL migration."""
    cfg_sqlite = DatabaseConfig.from_url("sqlite:///data/test.db")
    assert cfg_sqlite.driver == "sqlite"
    assert cfg_sqlite.sqlite_path == Path("data/test.db")

    cfg_mysql = DatabaseConfig.from_url("mysql://quant_user:secret@localhost:3306/alpha_db")
    assert cfg_mysql.driver == "mysql"
    assert cfg_mysql.host == "localhost"
    assert cfg_mysql.port == 3306
    assert cfg_mysql.username == "quant_user"
    assert cfg_mysql.password == "secret"
    assert cfg_mysql.database == "alpha_db"


def test_database_config_from_env(monkeypatch, tmp_path):
    """Verify environment variable configuration loading."""
    env_db = tmp_path / "env_alpha.db"
    monkeypatch.setenv("ALPHA_DATABASE_PATH", str(env_db))

    cfg = DatabaseConfig.from_env()
    assert cfg.sqlite_path == env_db
