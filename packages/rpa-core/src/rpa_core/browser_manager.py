"""Runtime-owned DrissionPage browser isolation and lifecycle management.

Business applications receive only ``BrowserActions``.  This module owns the
concrete Chromium object, one persistent profile lock, and one local debugging
port lease for the lifetime of a browser session.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
import errno
import json
import os
from pathlib import Path
import re
import socket
import stat
from typing import Any
from uuid import uuid4

from .drission_browser import DrissionBrowserActions
from .runtime import RunAlreadyActiveError, RunDirectoryLock, RunLockError


_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,127}$")
_RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class BrowserManagerError(RuntimeError):
    error_code = "browser_manager_error"


class BrowserConfigurationError(BrowserManagerError):
    error_code = "browser_configuration_invalid"


class BrowserProfileActiveError(BrowserManagerError):
    error_code = "browser_profile_already_active"


class BrowserPortLeaseError(BrowserManagerError):
    error_code = "browser_port_lease_failed"


class BrowserStartError(BrowserManagerError):
    error_code = "browser_start_failed"

    def __init__(
        self,
        message: str,
        *,
        real_browser_launched: bool = False,
    ) -> None:
        super().__init__(message)
        self.real_browser_launched = real_browser_launched


class BrowserLifecycleError(BrowserManagerError):
    error_code = "browser_lifecycle_failed"


class BrowserLifecyclePolicy(StrEnum):
    KEEP_OPEN = "keep_open"
    REUSE_UNTIL_IDLE = "reuse_until_idle"
    TERMINATE_ON_FINISH = "terminate_on_finish"


@dataclass(frozen=True, slots=True)
class BrowserLaunchSpec:
    account_id: str
    profile_id: str
    profile_dir: Path | str
    requested_port: int = 0
    browser_path: Path | str | None = None
    lifecycle: BrowserLifecyclePolicy | str = BrowserLifecyclePolicy.KEEP_OPEN

    def __post_init__(self) -> None:
        if not _IDENTIFIER_PATTERN.fullmatch(self.account_id):
            raise BrowserConfigurationError(f"invalid account_id: {self.account_id!r}")
        if not _IDENTIFIER_PATTERN.fullmatch(self.profile_id):
            raise BrowserConfigurationError(f"invalid profile_id: {self.profile_id!r}")
        profile_dir = Path(self.profile_dir)
        if profile_dir.name in {"", ".", ".."}:
            raise BrowserConfigurationError("profile_dir must identify one directory")
        if profile_dir.is_symlink():
            raise BrowserConfigurationError("profile_dir must not be a symbolic link")
        object.__setattr__(self, "profile_dir", profile_dir)

        if not isinstance(self.requested_port, int) or isinstance(self.requested_port, bool):
            raise BrowserConfigurationError("requested_port must be an integer")
        if self.requested_port != 0 and not 1024 <= self.requested_port <= 65535:
            raise BrowserConfigurationError("requested_port must be 0 or between 1024 and 65535")

        browser_path = None if self.browser_path is None else Path(self.browser_path)
        if browser_path is not None and (
            browser_path.is_symlink() or not browser_path.is_file()
        ):
            raise BrowserConfigurationError("browser_path must be one existing regular file")
        object.__setattr__(self, "browser_path", browser_path)
        try:
            lifecycle = BrowserLifecyclePolicy(self.lifecycle)
        except ValueError as error:
            raise BrowserConfigurationError(
                f"unsupported browser lifecycle: {self.lifecycle!r}"
            ) from error
        object.__setattr__(self, "lifecycle", lifecycle)


@dataclass(slots=True)
class PortLease:
    pool: "PortLeasePool"
    port: int
    path: Path
    token: str
    released: bool = field(default=False, init=False)

    def release(self) -> None:
        if self.released:
            return
        self.pool._release(self)
        self.released = True

    def __enter__(self) -> "PortLease":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.release()


class PortLeasePool:
    """Allocate local debugging ports with a process-visible lease registry."""

    def __init__(
        self,
        root: Path | str,
        *,
        start_port: int = 9600,
        end_port: int = 9699,
        port_available: Callable[[int], bool] | None = None,
    ) -> None:
        self.root = Path(root)
        if not 1024 <= start_port <= end_port <= 65535:
            raise BrowserConfigurationError("invalid port pool range")
        self.start_port = start_port
        self.end_port = end_port
        self._port_available = port_available or _port_is_available

    def acquire(
        self,
        *,
        run_id: str,
        profile_id: str,
        requested_port: int = 0,
    ) -> PortLease:
        if not _RUN_ID_PATTERN.fullmatch(run_id):
            raise BrowserConfigurationError(f"invalid run_id: {run_id!r}")
        if not _IDENTIFIER_PATTERN.fullmatch(profile_id):
            raise BrowserConfigurationError(f"invalid profile_id: {profile_id!r}")
        if requested_port != 0 and not 1024 <= requested_port <= 65535:
            raise BrowserConfigurationError("requested_port must be 0 or between 1024 and 65535")

        _ensure_directory(self.root, "port lease root")
        candidates = (
            (requested_port,)
            if requested_port
            else range(self.start_port, self.end_port + 1)
        )
        try:
            with RunDirectoryLock(self.root / ".pool.lock"):
                for port in candidates:
                    lease_path = self.root / f"{port}.json"
                    if lease_path.exists() or lease_path.is_symlink():
                        if not self._reclaim_if_stale(lease_path, port):
                            continue
                    if not self._port_available(port):
                        continue
                    token = uuid4().hex
                    payload = {
                        "schema_version": 1,
                        "port": port,
                        "run_id": run_id,
                        "profile_id": profile_id,
                        "owner_pid": os.getpid(),
                        "token": token,
                        "leased_at": datetime.now(timezone.utc).isoformat(),
                    }
                    _create_json_exclusive(lease_path, payload)
                    return PortLease(self, port, lease_path, token)
        except RunLockError as error:
            raise BrowserPortLeaseError("cannot acquire the port pool lock") from error
        target = f"requested port {requested_port}" if requested_port else "port pool"
        raise BrowserPortLeaseError(f"no available debugging port in {target}")

    def _reclaim_if_stale(self, path: Path, port: int) -> bool:
        payload = _read_json_regular(path, "port lease")
        if payload.get("port") != port:
            raise BrowserPortLeaseError(f"port lease identity mismatch: {path.name}")
        owner_pid = payload.get("owner_pid")
        if not isinstance(owner_pid, int) or owner_pid <= 0:
            raise BrowserPortLeaseError(f"invalid port lease owner: {path.name}")
        if _pid_is_alive(owner_pid) or not self._port_available(port):
            return False
        path.unlink()
        return True

    def _release(self, lease: PortLease) -> None:
        try:
            with RunDirectoryLock(self.root / ".pool.lock"):
                if not lease.path.exists() and not lease.path.is_symlink():
                    return
                payload = _read_json_regular(lease.path, "port lease")
                if payload.get("token") != lease.token or payload.get("port") != lease.port:
                    raise BrowserPortLeaseError("refusing to release a replaced port lease")
                lease.path.unlink()
        except RunLockError as error:
            raise BrowserPortLeaseError("cannot lock the port pool for release") from error


@dataclass(slots=True)
class BrowserSession:
    account_id: str
    profile_id: str
    port: int
    lifecycle: BrowserLifecyclePolicy
    actions: DrissionBrowserActions
    _browser: Any = field(repr=False)
    _profile_lock: RunDirectoryLock = field(repr=False)
    _port_lease: PortLease = field(repr=False)
    _owner_token: str = field(repr=False)
    active: bool = field(default=True, init=False)


class BrowserManager:
    """Start isolated Chromium sessions and retain every owned resource."""

    def __init__(
        self,
        runtime_root: Path | str,
        *,
        port_range: tuple[int, int] = (9600, 9699),
        options_factory: Callable[[], Any] | None = None,
        chromium_factory: Callable[[Any], Any] | None = None,
        port_available: Callable[[int], bool] | None = None,
    ) -> None:
        self.runtime_root = Path(runtime_root)
        self.port_pool = PortLeasePool(
            self.runtime_root / "port-leases",
            start_port=port_range[0],
            end_port=port_range[1],
            port_available=port_available,
        )
        self._options_factory = options_factory or _default_options_factory
        self._chromium_factory = chromium_factory or _default_chromium_factory
        self._owner_token = uuid4().hex
        self._sessions: dict[str, BrowserSession] = {}

    @property
    def active_sessions(self) -> tuple[BrowserSession, ...]:
        return tuple(self._sessions.values())

    def start(
        self,
        spec: BrowserLaunchSpec,
        *,
        run_id: str,
        run_dir: Path | str,
        action_timeout: float = 10.0,
        download_timeout: float = 120.0,
    ) -> BrowserSession:
        if spec.profile_id in self._sessions:
            raise BrowserProfileActiveError(
                f"profile is already active in this manager: {spec.profile_id}"
            )
        run_path = Path(run_dir)
        _ensure_safe_run_directory(run_path, run_id)
        if action_timeout <= 0 or download_timeout <= 0:
            raise BrowserConfigurationError(
                "browser action and download timeouts must be positive"
            )
        _ensure_directory(self.runtime_root, "browser runtime root")
        _ensure_directory(spec.profile_dir, "browser profile")
        profile_lock = RunDirectoryLock(
            spec.profile_dir.parent / f".{spec.profile_dir.name}.profile.lock"
        )
        port_lease: PortLease | None = None
        browser: Any = None
        try:
            profile_lock.acquire()
        except RunAlreadyActiveError as error:
            raise BrowserProfileActiveError(
                f"profile is already active: {spec.profile_id}"
            ) from error
        except RunLockError as error:
            raise BrowserManagerError(f"cannot lock profile: {spec.profile_id}") from error

        try:
            port_lease = self.port_pool.acquire(
                run_id=run_id,
                profile_id=spec.profile_id,
                requested_port=spec.requested_port,
            )
            options = self._options_factory()
            options.set_local_port(port_lease.port)
            options.set_user_data_path(str(spec.profile_dir))
            if spec.browser_path is not None:
                options.set_browser_path(str(spec.browser_path))
            browser = self._chromium_factory(options)
            tab = browser.latest_tab
            if not tab:
                raise BrowserStartError("Chromium did not expose a usable latest tab")
            session = BrowserSession(
                account_id=spec.account_id,
                profile_id=spec.profile_id,
                port=port_lease.port,
                lifecycle=spec.lifecycle,
                actions=DrissionBrowserActions(
                    tab,
                    run_path,
                    action_timeout=action_timeout,
                    download_timeout=download_timeout,
                ),
                _browser=browser,
                _profile_lock=profile_lock,
                _port_lease=port_lease,
                _owner_token=self._owner_token,
            )
            self._sessions[spec.profile_id] = session
            return session
        except Exception as error:
            if browser is not None:
                try:
                    browser.quit()
                except Exception:
                    pass
            if port_lease is not None:
                port_lease.release()
            profile_lock.release()
            if isinstance(error, BrowserStartError):
                if browser is not None and not error.real_browser_launched:
                    raise BrowserStartError(
                        str(error),
                        real_browser_launched=True,
                    ) from error
                raise
            if isinstance(error, BrowserManagerError):
                raise
            raise BrowserStartError(
                f"cannot start profile: {spec.profile_id}",
                real_browser_launched=browser is not None,
            ) from error

    def finish(self, session: BrowserSession) -> None:
        self._require_owned_active(session)
        if session.lifecycle is BrowserLifecyclePolicy.TERMINATE_ON_FINISH:
            self.close(session)

    def close(self, session: BrowserSession) -> None:
        self._require_owned_active(session)
        lifecycle_error: Exception | None = None
        try:
            session._browser.quit()
        except Exception as error:
            lifecycle_error = error
        finally:
            self._release_resources(session)
        if lifecycle_error is not None:
            raise BrowserLifecycleError(
                f"browser quit failed for profile: {session.profile_id}"
            ) from lifecycle_error

    def shutdown(self) -> None:
        errors: list[BrowserLifecycleError] = []
        for session in tuple(self._sessions.values()):
            try:
                self.close(session)
            except BrowserLifecycleError as error:
                errors.append(error)
        if errors:
            raise BrowserLifecycleError(
                f"failed to close {len(errors)} browser session(s)"
            ) from errors[0]

    def _require_owned_active(self, session: BrowserSession) -> None:
        if session._owner_token != self._owner_token:
            raise BrowserLifecycleError("browser session belongs to another manager")
        if not session.active or self._sessions.get(session.profile_id) is not session:
            raise BrowserLifecycleError("browser session is not active")

    def _release_resources(self, session: BrowserSession) -> None:
        self._sessions.pop(session.profile_id, None)
        session.active = False
        port_error: Exception | None = None
        try:
            session._port_lease.release()
        except Exception as error:
            port_error = error
        finally:
            session._profile_lock.release()
        if port_error is not None:
            raise BrowserLifecycleError(
                f"cannot release port {session.port} for profile: {session.profile_id}"
            ) from port_error

    def __enter__(self) -> "BrowserManager":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.shutdown()


def _default_options_factory() -> Any:
    from DrissionPage import ChromiumOptions

    return ChromiumOptions()


def _default_chromium_factory(options: Any) -> Any:
    from DrissionPage import Chromium

    return Chromium(addr_or_opts=options)


def _ensure_directory(path: Path, label: str) -> None:
    if path.is_symlink():
        raise BrowserConfigurationError(f"{label} must not be a symbolic link")
    path.mkdir(parents=True, exist_ok=True)
    if path.is_symlink() or not path.is_dir():
        raise BrowserConfigurationError(f"{label} must be one directory")


def _ensure_safe_run_directory(path: Path, run_id: str) -> None:
    if not _RUN_ID_PATTERN.fullmatch(run_id):
        raise BrowserConfigurationError(f"invalid run_id: {run_id!r}")
    if path.name != run_id:
        raise BrowserConfigurationError("run directory name must match run_id")
    parent = path.parent
    if parent.is_symlink() or path.is_symlink():
        raise BrowserConfigurationError(
            "browser run directory paths must not be symbolic links"
        )
    _ensure_directory(path, "browser run directory")
    if parent.is_symlink() or path.is_symlink():
        raise BrowserConfigurationError(
            "browser run directory paths changed while creating them"
        )


def _port_is_available(port: int) -> bool:
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
        probe.bind(("127.0.0.1", port))
    except OSError:
        return False
    finally:
        probe.close()
    return True


def _pid_is_alive(pid: int) -> bool:
    if pid == os.getpid():
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError as error:
        return error.errno == errno.EPERM
    return True


def _create_json_exclusive(path: Path, payload: dict[str, object]) -> None:
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor: int | None = None
    try:
        descriptor = os.open(path, flags, 0o600)
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1:
            raise BrowserPortLeaseError("port lease target is not one regular file")
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        os.write(descriptor, encoded)
        os.fsync(descriptor)
    except FileExistsError as error:
        raise BrowserPortLeaseError(f"port lease appeared concurrently: {path.name}") from error
    except OSError as error:
        raise BrowserPortLeaseError(f"cannot create port lease: {path.name}") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _read_json_regular(path: Path, label: str) -> dict[str, Any]:
    descriptor: int | None = None
    try:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        opened = os.fstat(descriptor)
        linked = os.lstat(path)
        if (
            stat.S_ISLNK(linked.st_mode)
            or not stat.S_ISREG(linked.st_mode)
            or not stat.S_ISREG(opened.st_mode)
        ):
            raise BrowserPortLeaseError(f"{label} must be one regular file")
        if linked.st_nlink != 1 or opened.st_nlink != 1:
            raise BrowserPortLeaseError(f"{label} must not be a hard link")
        if (linked.st_dev, linked.st_ino) != (opened.st_dev, opened.st_ino):
            raise BrowserPortLeaseError(f"{label} changed while opening")
        with os.fdopen(descriptor, "r", encoding="utf-8") as source:
            descriptor = None
            data = json.load(source)
    except BrowserPortLeaseError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise BrowserPortLeaseError(f"cannot read {label}: {path.name}") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)
    if not isinstance(data, dict):
        raise BrowserPortLeaseError(f"{label} must contain one JSON object")
    return data


__all__ = [
    "BrowserConfigurationError",
    "BrowserLaunchSpec",
    "BrowserLifecycleError",
    "BrowserLifecyclePolicy",
    "BrowserManager",
    "BrowserManagerError",
    "BrowserPortLeaseError",
    "BrowserProfileActiveError",
    "BrowserSession",
    "BrowserStartError",
    "PortLease",
    "PortLeasePool",
]
