"""Workspace-wide, process-safe BRAIN session persistence.

``requests.Session`` objects cannot cross process boundaries, so the manager
shares only the authenticated cookie jar. Credentials remain in the existing
MCP config and are never copied into the session state file.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import requests
from requests.cookies import create_cookie

try:
    import fcntl
except ImportError:  # Windows does not expose POSIX flock.
    fcntl = None
    import msvcrt


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STATE_PATH = ROOT / ".brain_session.json"


class BrainSessionManager:
    """Persist and coordinate the cookie jar used by all workspace clients."""

    def __init__(self, state_path: Path | None = None) -> None:
        self.state_path = Path(state_path or os.environ.get("BRAIN_SESSION_FILE", DEFAULT_STATE_PATH))
        self.lock_path = self.state_path.with_suffix(self.state_path.suffix + ".lock")
        self._thread_lock = threading.RLock()
        self._lock_depth = threading.local()

    @contextmanager
    def locked(self) -> Iterator[None]:
        with self._thread_lock:
            depth = getattr(self._lock_depth, "value", 0)
            self._lock_depth.value = depth + 1
            if depth:
                try:
                    yield
                finally:
                    self._lock_depth.value -= 1
                return
            self.lock_path.parent.mkdir(parents=True, exist_ok=True)
            with self.lock_path.open("a+", encoding="utf-8") as lock_file:
                self._lock_file(lock_file)
                try:
                    yield
                finally:
                    self._lock_depth.value -= 1
                    self._unlock_file(lock_file)

    @staticmethod
    def _lock_file(lock_file: Any) -> None:
        if fcntl is not None:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            return
        lock_file.seek(0)
        if not lock_file.read(1):
            lock_file.write("0")
            lock_file.flush()
        lock_file.seek(0)
        msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)

    @staticmethod
    def _unlock_file(lock_file: Any) -> None:
        if fcntl is not None:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            return
        lock_file.seek(0)
        msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)

    def hydrate(self, session: requests.Session) -> bool:
        with self.locked():
            if not self.state_path.exists():
                return False
            try:
                payload = json.loads(self.state_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return False
        cookies = payload.get("cookies", [])
        if not isinstance(cookies, list):
            return False
        session.cookies.clear()
        for item in cookies:
            if not isinstance(item, dict) or not item.get("name"):
                continue
            try:
                session.cookies.set_cookie(create_cookie(**item))
            except (TypeError, ValueError):
                continue
        return bool(session.cookies)

    def persist(self, session: requests.Session) -> None:
        cookies: list[dict[str, Any]] = []
        for cookie in session.cookies:
            cookies.append({"name": cookie.name, "value": cookie.value, "domain": cookie.domain,
                            "path": cookie.path, "secure": cookie.secure, "expires": cookie.expires,
                            "discard": cookie.discard, "comment": cookie.comment,
                            "comment_url": cookie.comment_url, "rest": dict(cookie._rest),
                            "rfc2109": cookie.rfc2109})
        payload = {"version": 1, "saved_at": int(time.time()), "cookies": cookies}
        with self.locked():
            fd, temporary_name = tempfile.mkstemp(prefix=self.state_path.name + ".", dir=self.state_path.parent)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as temporary_file:
                    if hasattr(os, "fchmod"):
                        os.fchmod(temporary_file.fileno(), 0o600)
                    json.dump(payload, temporary_file, separators=(",", ":"))
                    temporary_file.flush()
                    os.fsync(temporary_file.fileno())
                os.replace(temporary_name, self.state_path)
                if os.name != "nt":
                    os.chmod(self.state_path, 0o600)
            finally:
                if os.path.exists(temporary_name):
                    os.unlink(temporary_name)

    def credentials(self) -> tuple[str, str]:
        config_path = Path(os.environ.get("MCP_CONFIG_FILE", ROOT / ".brain.json"))
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise RuntimeError(f"BRAIN credentials config is unavailable: {config_path}") from error
        credentials = config.get("credentials") or config
        email = credentials.get("email") if isinstance(credentials, dict) else None
        password = credentials.get("password") if isinstance(credentials, dict) else None
        if not email or not password:
            raise RuntimeError("BRAIN credentials are missing from configured MCP_CONFIG_FILE")
        return str(email), str(password)


class ManagedRequestsSession(requests.Session):
    """Checkpoint refreshed cookies after every successful HTTP response."""

    def __init__(self, manager: BrainSessionManager) -> None:
        super().__init__()
        self._brain_session_manager = manager

    def send(self, request: Any, **kwargs: Any) -> requests.Response:
        response = super().send(request, **kwargs)
        self._brain_session_manager.persist(self)
        return response


def make_managed_client(real_client_class: type, manager: BrainSessionManager | None = None) -> Any:
    """Create a vendor-compatible client backed by the shared cookie state."""
    session_manager = manager or BrainSessionManager()

    class ManagedBrainApiClient(real_client_class):
        def __init__(self) -> None:
            super().__init__()
            previous = self.session
            session = ManagedRequestsSession(session_manager)
            session.headers.update(previous.headers)
            self.session = session
            session_manager.hydrate(session)

        async def is_authenticated(self) -> bool:
            session_manager.hydrate(self.session)
            return await real_client_class.is_authenticated(self)

        async def authenticate(self, email: str | None = None, password: str | None = None) -> dict[str, Any]:
            if not email or not password:
                email, password = session_manager.credentials()
            with session_manager.locked():
                session_manager.hydrate(self.session)
                if await real_client_class.is_authenticated(self):
                    self.auth_credentials = {"email": email, "password": password}
                    return {"user": {"email": email}, "status": "authenticated",
                            "message": "Reused shared BRAIN session", "reused_session": True}
                result = await real_client_class.authenticate(self, email, password)
                session_manager.persist(self.session)
                return result

        async def ensure_authenticated(self) -> None:
            if await self.is_authenticated():
                return
            email, password = session_manager.credentials()
            await self.authenticate(email, password)

    return ManagedBrainApiClient()
