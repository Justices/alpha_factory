"""Connection-type drivers that build database URLs from storage configuration."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Mapping, Protocol
from urllib.parse import quote

from sqlalchemy import URL, make_url


_ENVIRONMENT_VARIABLE = re.compile(r"\$(?:\{(?P<braced>[^}]+)\}|(?P<plain>\w+))|%(?P<windows>[^%]+)%")


def _environment_value(value: object) -> str:
    expanded = _ENVIRONMENT_VARIABLE.sub(
        lambda match: os.environ.get(match.group("braced") or match.group("plain") or match.group("windows"), match.group(0)),
        str(value),
    )
    if _ENVIRONMENT_VARIABLE.search(expanded):
        raise ValueError("storage configuration contains an unresolved environment variable")
    return expanded


class ConnectionDriver(Protocol):
    def build_url(self, database_type: str, dialect_driver: str | None, data: Mapping[str, Any], base_path: Path | None) -> str: ...


class FileConnectionDriver:
    def build_url(self, database_type: str, dialect_driver: str | None, data: Mapping[str, Any], base_path: Path | None) -> str:
        if database_type != "sqlite" or dialect_driver not in {None, "sqlite"}:
            raise ValueError("storage.connection_type=file requires the sqlite driver")
        location = data.get("path") or data.get("url")
        if not location:
            raise ValueError("storage.url is required for file connections")
        path = Path(_environment_value(location))
        if not path.is_absolute() and base_path is not None:
            path = (base_path / path).resolve()
        return f"sqlite:///{path.as_posix()}"


class UrlConnectionDriver:
    _structured_fields = {"username", "password", "path", "database"}

    def build_url(self, database_type: str, dialect_driver: str | None, data: Mapping[str, Any], base_path: Path | None) -> str:
        if self._structured_fields & data.keys():
            if data.get("url"):
                raise ValueError("storage.url cannot be combined with structured URL connection fields")
            missing = {"path", "database"} - data.keys()
            if missing:
                raise ValueError(f"storage URL connection is missing: {', '.join(sorted(missing))}")
            drivername = database_type if not dialect_driver or dialect_driver == database_type else f"{database_type}+{dialect_driver}"
            endpoint = _environment_value(data["path"])
            endpoint_url = make_url(endpoint if "://" in endpoint else f"{database_type}://{endpoint}")
            if not endpoint_url.host:
                raise ValueError("storage.path must be a host:port endpoint or URL")
            return URL.create(
                drivername,
                username=_environment_value(data["username"]) if data.get("username") is not None else None,
                password=_environment_value(data["password"]) if data.get("password") is not None else None,
                host=endpoint_url.host,
                port=endpoint_url.port,
                database=_environment_value(data["database"]),
            ).render_as_string(hide_password=False)

        raw_url = data.get("url")
        if not raw_url:
            raise ValueError("storage.url is required for URL connections")
        template = str(raw_url)
        authority_start = template.find("://") + 3
        user_info_end = template.find("@", authority_start) if authority_start >= 3 else -1

        def replace(match: re.Match[str]) -> str:
            value = os.environ.get(match.group("braced") or match.group("plain") or match.group("windows"))
            if value is None:
                return match.group(0)
            return quote(value, safe="") if authority_start <= match.start() < user_info_end else value

        url = _ENVIRONMENT_VARIABLE.sub(replace, template)
        if _ENVIRONMENT_VARIABLE.search(url):
            raise ValueError("storage.url contains an unresolved environment variable")
        parsed = make_url(url)
        if database_type != parsed.get_backend_name():
            raise ValueError("storage.database_type must match storage.url")
        url_driver = parsed.drivername.partition("+")[2] or parsed.get_backend_name()
        if dialect_driver and dialect_driver != url_driver:
            raise ValueError("storage.driver must match storage.url")
        if database_type == "sqlite" and parsed.database and parsed.database != ":memory:" and not Path(parsed.database).is_absolute() and base_path is not None:
            return str(parsed.set(database=str((base_path / parsed.database).resolve())))
        return url


CONNECTION_DRIVERS: Mapping[str, ConnectionDriver] = {"file": FileConnectionDriver(), "url": UrlConnectionDriver()}


def build_storage_url(database_type: str, dialect_driver: str | None, connection_type: str, data: Mapping[str, Any], base_path: Path | None) -> str:
    try:
        driver = CONNECTION_DRIVERS[connection_type]
    except KeyError as error:
        raise ValueError("storage.connection_type must select a registered connection driver") from error
    return driver.build_url(database_type, dialect_driver, data, base_path)
