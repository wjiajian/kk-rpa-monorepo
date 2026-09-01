"""Structured, append-only event logging for RPA runs.

The logger intentionally accepts plain mappings instead of runtime objects.  This
keeps observability independent from the runner and makes the JSONL file usable
by small offline tools as well as a future central collector.
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import date, datetime, timezone
from enum import Enum
import json
import os
from pathlib import Path
import stat
from threading import Lock
from typing import Any, Mapping


_REDACTED = "***REDACTED***"
_SENSITIVE_KEY_PARTS = (
    "authorization",
    "cookie",
    "credential",
    "password",
    "secret",
    "token",
)


class EventLogError(RuntimeError):
    """Raised before an event could be appended to a safe regular file."""

    error_code = "event_log_unsafe_path"


def _is_sensitive_key(key: object) -> bool:
    normalized = str(key).casefold().replace("-", "_")
    return any(part in normalized for part in _SENSITIVE_KEY_PARTS)


def sanitize_event_value(value: Any) -> Any:
    """Return a JSON-safe copy with common credential fields redacted."""

    if is_dataclass(value) and not isinstance(value, type):
        value = asdict(value)
    if isinstance(value, Mapping):
        return {
            str(key): _REDACTED if _is_sensitive_key(key) else sanitize_event_value(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple, set, frozenset)):
        return [sanitize_event_value(item) for item in value]
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return repr(value)


class JsonlEventLogger:
    """Write one sanitized JSON object per line.

    A single ``os.write`` is used for every event while holding a process-local
    lock.  This avoids interleaved lines between threads and leaves a durable,
    easy-to-recover audit trail after every flush.
    """

    schema_version = 1

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        if self.path.is_symlink():
            raise EventLogError("event log must not be a symbolic link")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.is_symlink():
            raise EventLogError("event log must not be a symbolic link")
        self._lock = Lock()

    def emit(
        self,
        event_type: str,
        *,
        app_id: str,
        run_id: str,
        program_id: str | None = None,
        program_version: str | None = None,
        step_id: str | None = None,
        status: str | Enum | None = None,
        attempt: int | None = None,
        duration_ms: int | None = None,
        error_code: str | None = None,
        evidence_refs: list[str] | tuple[str, ...] | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        event: dict[str, Any] = {
            "schema_version": self.schema_version,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_type": event_type,
            "app_id": app_id,
            "run_id": run_id,
        }
        optional = {
            "program_id": program_id,
            "program_version": program_version,
            "step_id": step_id,
            "status": status.value if isinstance(status, Enum) else status,
            "attempt": attempt,
            "duration_ms": duration_ms,
            "error_code": error_code,
            "evidence_refs": list(evidence_refs) if evidence_refs is not None else None,
            "details": details,
        }
        event.update({key: value for key, value in optional.items() if value is not None})
        sanitized = sanitize_event_value(event)
        encoded = (json.dumps(sanitized, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")

        flags = os.O_APPEND | os.O_CREAT | os.O_WRONLY
        no_follow = getattr(os, "O_NOFOLLOW", 0)
        flags |= no_follow
        with self._lock:
            try:
                descriptor = os.open(self.path, flags, 0o600)
            except OSError as error:
                raise EventLogError(f"cannot safely open event log: {self.path}") from error
            try:
                opened = os.fstat(descriptor)
                if not stat.S_ISREG(opened.st_mode):
                    raise EventLogError("event log target must be a regular file")
                if opened.st_nlink != 1:
                    raise EventLogError("event log must not be a hard link")
                try:
                    linked = os.lstat(self.path)
                except OSError as error:
                    raise EventLogError("event log path changed while opening") from error
                if stat.S_ISLNK(linked.st_mode):
                    raise EventLogError("event log must not be a symbolic link")
                if (opened.st_dev, opened.st_ino) != (linked.st_dev, linked.st_ino):
                    raise EventLogError("event log path changed while opening")
                os.write(descriptor, encoded)
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        return sanitized


# Keep the conventional all-caps acronym available without duplicating logic.
JSONLEventLogger = JsonlEventLogger
