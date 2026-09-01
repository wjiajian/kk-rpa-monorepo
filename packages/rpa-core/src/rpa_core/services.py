"""Side-effect service boundaries used by the first offline implementation.

Preview mode never reaches the backend.  Live mode requires a narrowly scoped,
unexpired, single-use grant and validates it again immediately before crossing
the backend boundary.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
from threading import Lock
from types import MappingProxyType
from typing import Any, Iterable, Mapping, Sequence
from uuid import uuid4

from .contracts import RunMode


_SAFE_STEP_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")


def _enum_value(value: object) -> str:
    return str(getattr(value, "value", value)).casefold()


def _json_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_value(item) for item in value]
    return value


def _canonical(value: object) -> str:
    return json.dumps(
        _json_value(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _freeze_json(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze_json(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item) for item in value)
    return value


class ServiceAuthorizationError(PermissionError):
    """Stable authorization failure raised before an external write."""

    def __init__(self, message: str, *, error_code: str = "live_write_not_authorized") -> None:
        super().__init__(message)
        self.error_code = error_code


class PreviewWriteError(RuntimeError):
    error_code = "preview_write_failed"


@dataclass(frozen=True, slots=True)
class ApprovalContext:
    """The exact operation presented to a live-write authorization boundary."""

    app_id: str
    run_id: str
    account_id: str
    step_id: str
    target: str
    data_scope: Mapping[str, Any]
    expected_count: int
    mode: RunMode | str = RunMode.LIVE

    def __post_init__(self) -> None:
        for name in ("app_id", "run_id", "account_id", "step_id", "target"):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"{name} must not be empty")
        if self.expected_count < 0:
            raise ValueError("expected_count must be non-negative")
        # Copy user-owned dictionaries so their mutation cannot broaden a grant.
        frozen_scope = json.loads(_canonical(dict(self.data_scope)))
        object.__setattr__(self, "data_scope", _freeze_json(frozen_scope))


@dataclass(frozen=True, slots=True)
class LiveWriteGrant:
    """A narrowly scoped, in-memory, single-use live-write grant."""

    app_id: str
    run_id: str
    account_id: str
    step_ids: frozenset[str]
    target: str
    data_scope: Mapping[str, Any]
    expected_count: int
    expires_at: datetime
    grant_id: str = field(default_factory=lambda: str(uuid4()))
    _consumed: bool = field(default=False, init=False, repr=False)
    _lock: Lock = field(default_factory=Lock, init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "step_ids", frozenset(self.step_ids))
        if not self.step_ids:
            raise ValueError("step_ids must not be empty")
        if self.expected_count < 0:
            raise ValueError("expected_count must be non-negative")
        if self.expires_at.tzinfo is None:
            raise ValueError("expires_at must include a timezone")
        frozen_scope = json.loads(_canonical(dict(self.data_scope)))
        object.__setattr__(self, "data_scope", _freeze_json(frozen_scope))

    @classmethod
    def issue(cls, context: ApprovalContext, *, expires_at: datetime) -> "LiveWriteGrant":
        """Issue a grant scoped exactly to one approval context."""

        if _enum_value(context.mode) != _enum_value(RunMode.LIVE):
            raise ServiceAuthorizationError(
                "a live-write grant must be issued from a live approval context",
                error_code="live_write_mode_mismatch",
            )

        return cls(
            app_id=context.app_id,
            run_id=context.run_id,
            account_id=context.account_id,
            step_ids=frozenset({context.step_id}),
            target=context.target,
            data_scope=context.data_scope,
            expected_count=context.expected_count,
            expires_at=expires_at,
        )

    @property
    def consumed(self) -> bool:
        with self._lock:
            return self._consumed

    def _validate_unlocked(self, context: ApprovalContext, now: datetime) -> None:
        if self._consumed:
            raise ServiceAuthorizationError(
                "live-write grant has already been consumed",
                error_code="live_write_grant_consumed",
            )
        if _enum_value(context.mode) != _enum_value(RunMode.LIVE):
            raise ServiceAuthorizationError(
                "live-write grant can only authorize live mode",
                error_code="live_write_mode_mismatch",
            )
        if now.tzinfo is None:
            raise ValueError("authorization time must include a timezone")
        if now >= self.expires_at:
            raise ServiceAuthorizationError(
                "live-write grant has expired",
                error_code="live_write_grant_expired",
            )

        comparisons = {
            "app_id": (self.app_id, context.app_id),
            "run_id": (self.run_id, context.run_id),
            "account_id": (self.account_id, context.account_id),
            "target": (self.target, context.target),
            "expected_count": (self.expected_count, context.expected_count),
        }
        mismatches = [name for name, (allowed, actual) in comparisons.items() if allowed != actual]
        if context.step_id not in self.step_ids:
            mismatches.append("step_id")
        if _canonical(self.data_scope) != _canonical(context.data_scope):
            mismatches.append("data_scope")
        if mismatches:
            raise ServiceAuthorizationError(
                "live-write grant scope mismatch: " + ", ".join(mismatches),
                error_code="live_write_scope_mismatch",
            )

    def validate(self, context: ApprovalContext, *, now: datetime | None = None) -> None:
        """Validate without consuming; useful for an early adapter check."""

        checked_at = now or datetime.now(timezone.utc)
        with self._lock:
            self._validate_unlocked(context, checked_at)

    def consume(self, context: ApprovalContext, *, now: datetime | None = None) -> None:
        """Revalidate and atomically claim the grant immediately before writing."""

        checked_at = now or datetime.now(timezone.utc)
        with self._lock:
            self._validate_unlocked(context, checked_at)
            object.__setattr__(self, "_consumed", True)


@dataclass(frozen=True, slots=True)
class WriteResult:
    mode: str
    target: str
    record_count: int
    preview_path: Path | None = None
    backend_result: Any = None


class FakeFeishuBackend:
    """An in-memory backend proving whether a real-write boundary was crossed."""

    def __init__(self) -> None:
        self.write_calls = 0
        self.writes: list[dict[str, Any]] = []

    @property
    def real_write_count(self) -> int:
        return self.write_calls

    def upsert_base(
        self,
        records: Sequence[Mapping[str, Any]],
        *,
        target: str,
        data_scope: Mapping[str, Any],
    ) -> dict[str, Any]:
        self.write_calls += 1
        snapshot = {
            "target": target,
            "data_scope": json.loads(_canonical(dict(data_scope))),
            "records": json.loads(_canonical(list(records))),
        }
        self.writes.append(snapshot)
        return {"written": len(records), "call": self.write_calls}


class PreviewFeishuService:
    """Feishu write adapter with preview isolation and live authorization."""

    preview_filename_prefix = "feishu-base-upsert"

    @classmethod
    def preview_filename_for(cls, step_id: str) -> str:
        if not _SAFE_STEP_ID_PATTERN.fullmatch(step_id):
            raise PreviewWriteError(
                "step_id must use 1-128 letters, digits, dots, underscores, or hyphens"
            )
        return f"{cls.preview_filename_prefix}--{step_id}.json"

    def __init__(
        self,
        *,
        mode: RunMode | str,
        app_id: str,
        run_id: str,
        account_id: str,
        run_dir: str | Path,
        backend: FakeFeishuBackend | None = None,
        live_grant: LiveWriteGrant | None = None,
    ) -> None:
        self.mode = mode
        self.app_id = app_id
        self.run_id = run_id
        self.account_id = account_id
        self.run_dir = Path(run_dir)
        self.backend = backend or FakeFeishuBackend()
        self.live_grant = live_grant

    def upsert_base(
        self,
        records: Iterable[Mapping[str, Any]],
        *,
        step_id: str,
        target: str,
        data_scope: Mapping[str, Any] | None = None,
        expected_count: int | None = None,
    ) -> WriteResult:
        materialized = [dict(record) for record in records]
        actual_count = len(materialized)
        approved_count = actual_count if expected_count is None else expected_count
        if approved_count != actual_count:
            raise ServiceAuthorizationError(
                f"expected_count {approved_count} does not match payload count {actual_count}",
                error_code="write_record_count_mismatch",
            )
        scope = dict(data_scope or {})
        context = ApprovalContext(
            app_id=self.app_id,
            run_id=self.run_id,
            account_id=self.account_id,
            step_id=step_id,
            target=target,
            data_scope=scope,
            expected_count=actual_count,
            mode=self.mode,
        )

        if _enum_value(self.mode) == _enum_value(RunMode.PREVIEW):
            preview_path = self._preview_path(step_id)
            payload = {
                "schema_version": 1,
                "mode": "preview",
                "write_executed": False,
                "app_id": self.app_id,
                "run_id": self.run_id,
                "account_id": self.account_id,
                "step_id": step_id,
                "target": target,
                "data_scope": scope,
                "expected_count": actual_count,
                "records": materialized,
            }
            self._write_preview(preview_path, payload)
            return WriteResult(
                mode="preview",
                target=target,
                record_count=actual_count,
                preview_path=preview_path,
            )

        if _enum_value(self.mode) != _enum_value(RunMode.LIVE):
            raise ValueError(f"unsupported run mode: {self.mode!r}")
        if self.live_grant is None:
            raise ServiceAuthorizationError(
                "live mode requires a LiveWriteGrant",
                error_code="live_write_grant_missing",
            )

        # First check: fail fast at the service API.  Second check and atomic
        # claim: immediately before the backend call, preventing grant replay.
        self.live_grant.validate(context)
        self.live_grant.consume(context)
        backend_result = self.backend.upsert_base(
            materialized,
            target=target,
            data_scope=scope,
        )
        return WriteResult(
            mode="live",
            target=target,
            record_count=actual_count,
            backend_result=backend_result,
        )

    @staticmethod
    def _write_preview(path: Path, payload: Mapping[str, Any]) -> None:
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        try:
            with temporary.open("w", encoding="utf-8") as stream:
                json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if temporary.exists():
                temporary.unlink()

    def _preview_path(self, step_id: str) -> Path:
        preview_filename = self.preview_filename_for(step_id)
        if self.run_dir.is_symlink():
            raise PreviewWriteError("run_dir must not be a symbolic link")
        runs_root = self.run_dir.parent
        if runs_root.name != "runs":
            raise PreviewWriteError("run_dir must be a direct child of a runs directory")
        if runs_root.is_symlink():
            raise PreviewWriteError("runs directory must not be a symbolic link")
        resolved_runs_root = runs_root.resolve()
        run_dir = self.run_dir.resolve()
        if self.run_dir.name != self.run_id or run_dir.parent != resolved_runs_root:
            raise PreviewWriteError("run_dir escapes the runs directory or mismatches run_id")
        preview_dir = self.run_dir / "write-previews"
        if preview_dir.is_symlink():
            raise PreviewWriteError("write-previews must not be a symbolic link")
        preview_dir.mkdir(parents=True, exist_ok=True)
        if (
            self.run_dir.is_symlink()
            or runs_root.is_symlink()
            or preview_dir.is_symlink()
            or self.run_dir.resolve() != run_dir
            or runs_root.resolve() != resolved_runs_root
            or preview_dir.resolve() != run_dir / "write-previews"
        ):
            raise PreviewWriteError("write-previews escapes the run directory")
        return preview_dir / preview_filename


# Explicit alias for code that wants the service name without implying its mode.
FeishuService = PreviewFeishuService
