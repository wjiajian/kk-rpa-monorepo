"""Offline-first program runner, checkpointing, retry, and resume support."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
import errno
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import stat
from threading import Lock
import time
from typing import TYPE_CHECKING, Any, Callable, Mapping, MutableMapping, Sequence
from uuid import uuid4

try:
    import fcntl as _fcntl
except ImportError:  # pragma: no cover - exercised by an explicit fail-closed test
    _fcntl = None

from .contracts import RetryPolicy, ResumePolicy, RunMode, SideEffect, StepStatus
from .events import JsonlEventLogger, sanitize_event_value

if TYPE_CHECKING:
    from .authorization import AuthorizationSession
    from .instructions import InstructionRegistry


_RUN_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")


def _value(value: object) -> str:
    return str(getattr(value, "value", value)).casefold()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_retry_policy() -> RetryPolicy:
    return RetryPolicy()


class RuntimeContractError(ValueError):
    error_code = "runtime_contract_invalid"


class RunLockError(RuntimeError):
    error_code = "run_lock_error"


class RunLockUnsupportedError(RunLockError):
    error_code = "run_lock_unsupported"


class RunAlreadyActiveError(RunLockError):
    error_code = "run_already_active"


class CheckpointError(RuntimeError):
    error_code = "checkpoint_error"


class CheckpointIdentityError(CheckpointError):
    error_code = "checkpoint_identity_mismatch"


class CheckpointAuthorizationMismatchError(CheckpointError):
    error_code = "authorization_scope_mismatch"


class InvalidStepTransition(CheckpointError):
    error_code = "invalid_step_transition"


class ResumeBlockedError(RuntimeError):
    error_code = "resume_blocked"


class ProgramVerificationError(RuntimeError):
    error_code = "program_verification_failed"


class StepTimeoutError(TimeoutError):
    error_code = "step_timeout"

    def __init__(self, step_id: str, timeout_seconds: float) -> None:
        super().__init__(f"step {step_id} exceeded {timeout_seconds:g} seconds")
        self.step_id = step_id
        self.timeout_seconds = timeout_seconds


class StepRunError(RuntimeError):
    """Raised after a step exhausts its retry policy."""

    def __init__(self, step_id: str, error_code: str, message: str) -> None:
        super().__init__(message)
        self.step_id = step_id
        self.error_code = error_code


class RunDirectoryLock:
    """Hold a process-scoped exclusive lock for one run directory."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._descriptor: int | None = None

    @staticmethod
    def ensure_supported() -> None:
        if _fcntl is None:
            raise RunLockUnsupportedError(
                "OS file locking is unavailable; refusing to run without exclusivity"
            )

    def acquire(self) -> None:
        self.ensure_supported()
        if self._descriptor is not None:
            raise RunLockError("run lock is already held by this object")
        if self.path.is_symlink():
            raise RunLockError("run lock must not be a symbolic link")

        flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
        descriptor: int | None = None
        try:
            descriptor = os.open(self.path, flags, 0o600)
        except OSError as error:
            raise RunLockError(f"cannot safely open run lock: {self.path}") from error
        try:
            opened = os.fstat(descriptor)
            if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1:
                raise RunLockError("run lock target must be one regular file")
            try:
                linked = os.lstat(self.path)
            except OSError as error:
                raise RunLockError("run lock path changed while opening") from error
            if stat.S_ISLNK(linked.st_mode):
                raise RunLockError("run lock must not be a symbolic link")
            if (opened.st_dev, opened.st_ino) != (linked.st_dev, linked.st_ino):
                raise RunLockError("run lock path changed while opening")
            try:
                _fcntl.flock(descriptor, _fcntl.LOCK_EX | _fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise RunAlreadyActiveError(
                    f"run is already active: {self.path.parent.name}"
                ) from error
            except OSError as error:
                if error.errno in {errno.EACCES, errno.EAGAIN}:
                    raise RunAlreadyActiveError(
                        f"run is already active: {self.path.parent.name}"
                    ) from error
                raise RunLockError(f"cannot acquire run lock: {self.path}") from error
            locked = os.fstat(descriptor)
            if not stat.S_ISREG(locked.st_mode) or locked.st_nlink != 1:
                raise RunLockError("run lock target changed while acquiring")
            self._descriptor = descriptor
            descriptor = None
        finally:
            if descriptor is not None:
                os.close(descriptor)

    def release(self) -> None:
        descriptor = self._descriptor
        if descriptor is None:
            return
        self._descriptor = None
        try:
            _fcntl.flock(descriptor, _fcntl.LOCK_UN)
        finally:
            os.close(descriptor)

    def __enter__(self) -> "RunDirectoryLock":
        self.acquire()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.release()


@dataclass(frozen=True, slots=True)
class ProgramSpec:
    app_id: str
    program_id: str
    version: str
    requirement_hash: str
    name: str = ""

    def __post_init__(self) -> None:
        for field_name in ("app_id", "program_id", "version", "requirement_hash"):
            if not str(getattr(self, field_name)).strip():
                raise RuntimeContractError(f"{field_name} must not be empty")
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", self.requirement_hash):
            raise RuntimeContractError("requirement_hash must be sha256:<64 lowercase hex>")


@dataclass(frozen=True, slots=True)
class StepSpec:
    step_id: str
    name: str
    retry_policy: RetryPolicy = field(default_factory=_default_retry_policy)
    resume_policy: ResumePolicy = ResumePolicy.VERIFY_THEN_RUN
    side_effect: SideEffect = SideEffect.NONE
    timeout_seconds: float | None = None
    declared_inputs: tuple[str, ...] = ()
    declared_outputs: tuple[str, ...] = ()
    success_conditions: tuple[str, ...] = ()
    recovery: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.step_id.strip():
            raise RuntimeContractError("step_id must not be empty")
        if not self.name.strip():
            raise RuntimeContractError("step name must not be empty")
        if self.retry_policy.max_attempts < 1:
            raise RuntimeContractError("retry_policy.max_attempts must be at least 1")
        if self.retry_policy.delay_seconds < 0:
            raise RuntimeContractError("retry_policy.delay_seconds must be non-negative")
        if self.retry_policy.backoff_multiplier < 1:
            raise RuntimeContractError("retry_policy.backoff_multiplier must be at least 1")
        if self.timeout_seconds is not None and self.timeout_seconds <= 0:
            raise RuntimeContractError("timeout_seconds must be positive")
        for field_name in (
            "declared_inputs",
            "declared_outputs",
            "success_conditions",
            "recovery",
        ):
            raw = tuple(getattr(self, field_name))
            if any(not str(item).strip() for item in raw):
                raise RuntimeContractError(f"{field_name} must not contain empty values")
            if len(set(raw)) != len(raw):
                raise RuntimeContractError(f"{field_name} must not contain duplicates")
            object.__setattr__(self, field_name, raw)


class Step(ABC):
    """One deterministic business step with an explicit success verifier."""

    def __init__(self, spec: StepSpec) -> None:
        self.spec = spec

    @abstractmethod
    def execute(self, context: "ExecutionContext") -> Any:
        """Perform the step and return a candidate result."""

    @abstractmethod
    def verify(self, context: "ExecutionContext", result: Any) -> bool:
        """Return true only after the step's declared success condition holds."""

    def verify_recovery(
        self,
        context: "ExecutionContext",
        checkpoint: Mapping[str, Any],
    ) -> bool:
        """Verify a possibly completed interrupted step before running again."""

        return False


class BaseProgram:
    """Ordered collection of uniquely identified steps."""

    def __init__(self, spec: ProgramSpec, steps: Sequence[Step]) -> None:
        self.spec = spec
        self.steps = tuple(steps)
        if not self.steps:
            raise RuntimeContractError("a program must contain at least one step")
        ids = [step.spec.step_id for step in self.steps]
        duplicates = sorted({step_id for step_id in ids if ids.count(step_id) > 1})
        if duplicates:
            raise RuntimeContractError("duplicate step IDs: " + ", ".join(duplicates))

    def step(self, step_id: str) -> Step:
        for candidate in self.steps:
            if candidate.spec.step_id == step_id:
                return candidate
        raise KeyError(step_id)

    def prepare(self, context: "ExecutionContext") -> None:
        """Validate run inputs and resources before the first business step."""

    def verify(self, context: "ExecutionContext") -> bool | None:
        """Perform program-level final verification; returning false fails the run."""

        return None

    def cleanup(self, context: "ExecutionContext") -> None:
        """Release per-run resources without deciding persistent browser policy."""


@dataclass(slots=True)
class ExecutionContext:
    app_id: str
    program_id: str
    program_version: str
    requirement_hash: str
    run_id: str
    account_id: str
    mode: RunMode | str
    run_dir: Path | str
    services: MutableMapping[str, Any] = field(default_factory=dict)
    metadata: MutableMapping[str, Any] = field(default_factory=dict)
    outputs: MutableMapping[str, Any] = field(default_factory=dict)
    current_step_id: str | None = field(default=None, init=False)
    current_attempt: int | None = field(default=None, init=False)
    current_step_timeout_seconds: float | None = field(default=None, init=False)
    step_deadline_monotonic: float | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        for field_name in (
            "app_id",
            "program_id",
            "program_version",
            "requirement_hash",
            "run_id",
            "account_id",
        ):
            if not str(getattr(self, field_name)).strip():
                raise RuntimeContractError(f"{field_name} must not be empty")
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", self.requirement_hash):
            raise RuntimeContractError("requirement_hash must be sha256:<64 lowercase hex>")
        if not _RUN_ID_PATTERN.fullmatch(self.run_id):
            raise RuntimeContractError(
                "run_id must use 1-128 letters, digits, dots, underscores, or hyphens"
            )
        if _value(self.mode) not in {_value(RunMode.PREVIEW), _value(RunMode.LIVE)}:
            raise RuntimeContractError(f"unsupported run mode: {self.mode!r}")
        self.run_dir = Path(self.run_dir)

    def service(self, name: str) -> Any:
        try:
            return self.services[name]
        except KeyError as error:
            raise RuntimeContractError(f"service is not configured: {name}") from error

    def ensure_step_within_deadline(self) -> None:
        """Enforce the runner's cooperative deadline at safe operation boundaries."""

        deadline = self.step_deadline_monotonic
        timeout = self.current_step_timeout_seconds
        if deadline is None or timeout is None:
            return
        if time.monotonic() > deadline:
            raise StepTimeoutError(self.current_step_id or "unknown", timeout)

    @property
    def browser(self) -> Any:
        return self.service("browser")

    @property
    def authorization(self) -> "AuthorizationSession":
        from .authorization import AuthorizationSession

        session = self.service("authorization")
        if not isinstance(session, AuthorizationSession):
            raise RuntimeContractError(
                "service 'authorization' must be an AuthorizationSession"
            )
        return session

    @property
    def instructions(self) -> "InstructionRegistry":
        from .instructions import InstructionRegistry

        registry = self.service("instructions")
        if not isinstance(registry, InstructionRegistry):
            raise RuntimeContractError(
                "service 'instructions' must be an InstructionRegistry"
            )
        return registry

    @property
    def feishu(self) -> Any:
        return self.service("feishu")

    @property
    def identity(self) -> dict[str, str]:
        return {
            "app_id": self.app_id,
            "program_id": self.program_id,
            "program_version": self.program_version,
            "requirement_hash": self.requirement_hash,
            "run_id": self.run_id,
            "account_id": self.account_id,
            "mode": _value(self.mode),
        }


class CheckpointStore:
    """Persist one checkpoint with same-directory atomic replacement."""

    schema_version = 1

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._lock = Lock()

    def exists(self) -> bool:
        try:
            linked = os.lstat(self.path)
        except FileNotFoundError:
            return False
        if stat.S_ISLNK(linked.st_mode):
            raise CheckpointError("checkpoint must not be a symbolic link")
        if linked.st_nlink != 1:
            raise CheckpointError("checkpoint must not be a hard link")
        return self.path.is_file()

    def load(self) -> dict[str, Any] | None:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        descriptor: int | None = None
        try:
            descriptor = os.open(self.path, flags)
        except FileNotFoundError:
            return None
        except OSError as error:
            raise CheckpointError(f"cannot safely open checkpoint: {self.path}") from error
        try:
            opened = os.fstat(descriptor)
            if not stat.S_ISREG(opened.st_mode):
                raise CheckpointError("checkpoint target must be a regular file")
            if opened.st_nlink != 1:
                raise CheckpointError("checkpoint must not be a hard link")
            try:
                linked = os.lstat(self.path)
            except OSError as error:
                raise CheckpointError("checkpoint path changed while opening") from error
            if stat.S_ISLNK(linked.st_mode):
                raise CheckpointError("checkpoint must not be a symbolic link")
            if (opened.st_dev, opened.st_ino) != (linked.st_dev, linked.st_ino):
                raise CheckpointError("checkpoint path changed while opening")
            with os.fdopen(descriptor, "r", encoding="utf-8") as stream:
                descriptor = None
                payload = json.load(stream)
        except (OSError, json.JSONDecodeError) as error:
            raise CheckpointError(f"cannot read checkpoint: {self.path}") from error
        finally:
            if descriptor is not None:
                os.close(descriptor)
        if not isinstance(payload, dict) or payload.get("schema_version") != self.schema_version:
            raise CheckpointError("unsupported or invalid checkpoint schema")
        return payload

    def save(self, payload: Mapping[str, Any]) -> None:
        safe_payload = sanitize_event_value(dict(payload))
        try:
            linked = os.lstat(self.path)
        except FileNotFoundError:
            linked = None
        if linked is not None:
            if stat.S_ISLNK(linked.st_mode):
                raise CheckpointError("checkpoint must not be a symbolic link")
            if not stat.S_ISREG(linked.st_mode):
                raise CheckpointError("checkpoint target must be a regular file")
            if linked.st_nlink != 1:
                raise CheckpointError("checkpoint must not be a hard link")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.{uuid4().hex}.tmp")
        with self._lock:
            try:
                with temporary.open("w", encoding="utf-8") as stream:
                    json.dump(safe_payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
                    stream.write("\n")
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, self.path)
                # Best effort directory sync makes rename durable on POSIX.
                try:
                    descriptor = os.open(self.path.parent, os.O_RDONLY)
                except OSError:
                    descriptor = None
                if descriptor is not None:
                    try:
                        os.fsync(descriptor)
                    finally:
                        os.close(descriptor)
            finally:
                if temporary.exists():
                    temporary.unlink()

    def initialize(self, context: ExecutionContext, program: BaseProgram) -> dict[str, Any]:
        now = _utc_now()
        payload = {
            "schema_version": self.schema_version,
            "identity": context.identity,
            "status": "running",
            "created_at": now,
            "updated_at": now,
            "steps": {
                step.spec.step_id: {
                    "name": step.spec.name,
                    "status": _value(StepStatus.PENDING),
                    "attempts": 0,
                    "started_at": None,
                    "finished_at": None,
                    "result": None,
                    "error": None,
                    "evidence_refs": [],
                }
                for step in program.steps
            },
        }
        self.save(payload)
        return payload

    @staticmethod
    def validate_identity(payload: Mapping[str, Any], context: ExecutionContext) -> None:
        stored = payload.get("identity")
        if not isinstance(stored, Mapping):
            raise CheckpointIdentityError("checkpoint identity is missing")
        mismatches = [
            key
            for key, actual in context.identity.items()
            if str(stored.get(key)) != str(actual)
        ]
        if mismatches:
            raise CheckpointIdentityError(
                "checkpoint identity mismatch: " + ", ".join(mismatches)
            )


def checkpoint_digest(payload: Mapping[str, Any]) -> str:
    """Return the canonical digest used to bind a Resume Authorization to state."""

    try:
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise CheckpointError("checkpoint must contain finite JSON values") from error
    return f"sha256:{sha256(encoded).hexdigest()}"


@dataclass(frozen=True, slots=True)
class RunResult:
    app_id: str
    run_id: str
    status: str
    completed_steps: tuple[str, ...]
    skipped_steps: tuple[str, ...]
    outputs: Mapping[str, Any]
    checkpoint_path: Path


_ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    _value(StepStatus.PENDING): {_value(StepStatus.RUNNING)},
    _value(StepStatus.RUNNING): {
        _value(StepStatus.VERIFYING),
        _value(StepStatus.RETRY_WAIT),
        _value(StepStatus.FAILED),
    },
    _value(StepStatus.VERIFYING): {
        _value(StepStatus.SUCCEEDED),
        _value(StepStatus.RETRY_WAIT),
        _value(StepStatus.FAILED),
    },
    _value(StepStatus.RETRY_WAIT): {_value(StepStatus.RUNNING), _value(StepStatus.FAILED)},
    _value(StepStatus.FAILED): {_value(StepStatus.RUNNING), _value(StepStatus.VERIFYING)},
    _value(StepStatus.SUCCEEDED): set(),
}


class Runner:
    """Execute a program with retry, verified success, and resumable state."""

    def __init__(
        self,
        checkpoint_store: CheckpointStore | None = None,
        event_logger: JsonlEventLogger | None = None,
        *,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.checkpoint_store = checkpoint_store
        self.event_logger = event_logger
        self._sleep = sleep

    def run(
        self,
        program: BaseProgram,
        context: ExecutionContext,
        *,
        resume: bool = False,
    ) -> RunResult:
        self._validate_program_context(program, context)
        self._validate_run_directory(context)
        self._validate_artifact_paths(context)
        self._validate_bound_services(context)
        RunDirectoryLock.ensure_supported()
        context.run_dir.mkdir(parents=True, exist_ok=True)
        with RunDirectoryLock(context.run_dir / ".run.lock"):
            return self._run_locked(program, context, resume=resume)

    def _run_locked(
        self,
        program: BaseProgram,
        context: ExecutionContext,
        *,
        resume: bool,
    ) -> RunResult:
        store = self.checkpoint_store or CheckpointStore(context.run_dir / "checkpoint.json")
        logger = self.event_logger or JsonlEventLogger(context.run_dir / "events.jsonl")

        existing = store.load()
        if resume:
            if existing is None:
                raise CheckpointError("cannot resume: checkpoint does not exist")
            store.validate_identity(existing, context)
            checkpoint = existing
            self._validate_checkpoint_steps(checkpoint, program)
            self._validate_resume_authorization(checkpoint, program, context)
            event_type = "run.resumed"
        else:
            if existing is not None:
                store.validate_identity(existing, context)
                raise CheckpointError("checkpoint already exists; use resume=True")
            checkpoint = store.initialize(context, program)
            event_type = "run.started"

        logger.emit(
            event_type,
            app_id=context.app_id,
            run_id=context.run_id,
            program_id=context.program_id,
            program_version=context.program_version,
            details={
                "mode": _value(context.mode),
                "account_id": context.account_id,
                "requirement_hash": context.requirement_hash,
            },
        )

        completed: list[str] = []
        skipped: list[str] = []
        cleanup_started = False
        try:
            program.prepare(context)
            logger.emit(
                "run.prepared",
                app_id=context.app_id,
                run_id=context.run_id,
                program_id=context.program_id,
                program_version=context.program_version,
                status="running",
            )
            for step in program.steps:
                step_id = step.spec.step_id
                record = checkpoint["steps"][step_id]
                if _value(record["status"]) == _value(StepStatus.SUCCEEDED):
                    if (
                        resume
                        and _value(step.spec.resume_policy)
                        == _value(ResumePolicy.VERIFY_THEN_RUN)
                        and _value(step.spec.side_effect) == _value(SideEffect.WRITE)
                    ):
                        self._start_step_deadline(context, step, record["attempts"])
                        try:
                            checkpoint_valid = bool(
                                step.verify_recovery(context, record)
                            )
                            context.ensure_step_within_deadline()
                        finally:
                            self._clear_step_deadline(context)
                        if not checkpoint_valid:
                            raise ResumeBlockedError(
                                f"succeeded step {step_id} failed recovery verification"
                            )
                        logger.emit(
                            "step.checkpoint_verified",
                            app_id=context.app_id,
                            run_id=context.run_id,
                            program_id=context.program_id,
                            program_version=context.program_version,
                            step_id=step_id,
                            status=StepStatus.SUCCEEDED,
                            attempt=record["attempts"],
                            evidence_refs=record.get("evidence_refs", []),
                        )
                    skipped.append(step_id)
                    if record.get("result") is not None:
                        context.outputs[step_id] = record["result"]
                    logger.emit(
                        "step.skipped",
                        app_id=context.app_id,
                        run_id=context.run_id,
                        program_id=context.program_id,
                        program_version=context.program_version,
                        step_id=step_id,
                        status=StepStatus.SUCCEEDED,
                        details={"reason": "checkpoint_succeeded"},
                    )
                    continue

                if resume and _value(record["status"]) != _value(StepStatus.PENDING):
                    if self._recover_or_prepare(step, context, checkpoint, record, store, logger):
                        completed.append(step_id)
                        continue

                result = self._run_step(step, context, checkpoint, record, store, logger)
                context.outputs[step_id] = result
                completed.append(step_id)

            logger.emit(
                "run.verifying",
                app_id=context.app_id,
                run_id=context.run_id,
                program_id=context.program_id,
                program_version=context.program_version,
                status="verifying",
            )
            if program.verify(context) is False:
                raise ProgramVerificationError("program final verification returned false")
            cleanup_started = True
            try:
                program.cleanup(context)
            except Exception as caught:
                logger.emit(
                    "run.cleanup_failed",
                    app_id=context.app_id,
                    run_id=context.run_id,
                    program_id=context.program_id,
                    program_version=context.program_version,
                    status="failed",
                    error_code=getattr(caught, "error_code", "program_cleanup_failed"),
                    details={"exception_type": type(caught).__name__},
                )
                raise
            logger.emit(
                "run.cleaned",
                app_id=context.app_id,
                run_id=context.run_id,
                program_id=context.program_id,
                program_version=context.program_version,
                status="succeeded",
            )

            checkpoint["status"] = "succeeded"
            checkpoint["updated_at"] = _utc_now()
            store.save(checkpoint)
            logger.emit(
                "run.succeeded",
                app_id=context.app_id,
                run_id=context.run_id,
                program_id=context.program_id,
                program_version=context.program_version,
                status="succeeded",
                details={"completed_steps": completed, "skipped_steps": skipped},
            )
        except Exception as error:
            cleanup_error: Exception | None = None
            if not cleanup_started:
                cleanup_started = True
                try:
                    program.cleanup(context)
                    logger.emit(
                        "run.cleaned",
                        app_id=context.app_id,
                        run_id=context.run_id,
                        program_id=context.program_id,
                        program_version=context.program_version,
                        status="failed",
                    )
                except Exception as caught:
                    cleanup_error = caught
                    logger.emit(
                        "run.cleanup_failed",
                        app_id=context.app_id,
                        run_id=context.run_id,
                        program_id=context.program_id,
                        program_version=context.program_version,
                        status="failed",
                        error_code=getattr(caught, "error_code", "program_cleanup_failed"),
                        details={"exception_type": type(caught).__name__},
                    )
            checkpoint["status"] = "failed"
            checkpoint["updated_at"] = _utc_now()
            store.save(checkpoint)
            logger.emit(
                "run.failed",
                app_id=context.app_id,
                run_id=context.run_id,
                program_id=context.program_id,
                program_version=context.program_version,
                status="failed",
                error_code=getattr(error, "error_code", "unhandled_runtime_error"),
                details={
                    "exception_type": type(error).__name__,
                    "cleanup_error_type": (
                        type(cleanup_error).__name__ if cleanup_error is not None else None
                    ),
                },
            )
            raise
        finally:
            context.current_step_id = None
            context.current_attempt = None
            context.current_step_timeout_seconds = None
            context.step_deadline_monotonic = None

        return RunResult(
            app_id=context.app_id,
            run_id=context.run_id,
            status="succeeded",
            completed_steps=tuple(completed),
            skipped_steps=tuple(skipped),
            outputs=dict(context.outputs),
            checkpoint_path=store.path,
        )

    def resume(self, program: BaseProgram, context: ExecutionContext) -> RunResult:
        """Resume a compatible checkpoint, skipping every succeeded step."""

        return self.run(program, context, resume=True)

    @staticmethod
    def _validate_program_context(program: BaseProgram, context: ExecutionContext) -> None:
        mismatches = []
        if program.spec.app_id != context.app_id:
            mismatches.append("app_id")
        if program.spec.program_id != context.program_id:
            mismatches.append("program_id")
        if program.spec.version != context.program_version:
            mismatches.append("program_version")
        if program.spec.requirement_hash != context.requirement_hash:
            mismatches.append("requirement_hash")
        if mismatches:
            raise RuntimeContractError("program/context mismatch: " + ", ".join(mismatches))

    @staticmethod
    def _validate_run_directory(context: ExecutionContext) -> None:
        """Reject linked or out-of-root run paths before creating any artifact."""

        if not _RUN_ID_PATTERN.fullmatch(context.run_id):
            raise RuntimeContractError(
                "run_id must use 1-128 letters, digits, dots, underscores, or hyphens"
            )
        if context.run_dir.is_symlink():
            raise RuntimeContractError("run_dir must not be a symbolic link")

        raw_app_dir = context.metadata.get("app_dir")
        if raw_app_dir is None or not str(raw_app_dir).strip():
            raise RuntimeContractError("metadata.app_dir is required")
        declared_app_dir = Path(str(raw_app_dir))
        if declared_app_dir.is_symlink():
            raise RuntimeContractError("metadata.app_dir must not be a symbolic link")
        app_dir = declared_app_dir.resolve()
        declared_runs_root = app_dir / "runs"
        if declared_runs_root.is_symlink():
            raise RuntimeContractError("application runs directory must not be a symbolic link")

        expected_runs_root = app_dir / "runs"
        resolved_runs_root = declared_runs_root.resolve()
        if resolved_runs_root != expected_runs_root:
            raise RuntimeContractError("application runs directory escapes the application")

        expected_run_dir = expected_runs_root / context.run_id
        lexical_run_dir = Path(os.path.abspath(context.run_dir))
        lexical_expected = Path(os.path.abspath(expected_run_dir))
        resolved_run_dir = context.run_dir.resolve()
        if lexical_run_dir != lexical_expected or resolved_run_dir != expected_run_dir:
            raise RuntimeContractError("run_dir escapes the application runs directory")

    def _validate_artifact_paths(self, context: ExecutionContext) -> None:
        """Bind injected persistence services to the validated run directory."""

        expected = {
            "checkpoint": context.run_dir / "checkpoint.json",
            "event log": context.run_dir / "events.jsonl",
        }
        actual = {
            "checkpoint": (
                self.checkpoint_store.path
                if self.checkpoint_store is not None
                else expected["checkpoint"]
            ),
            "event log": (
                self.event_logger.path
                if self.event_logger is not None
                else expected["event log"]
            ),
        }
        for name, candidate in actual.items():
            required = expected[name]
            try:
                linked = os.lstat(candidate)
            except FileNotFoundError:
                linked = None
            if linked is not None:
                if stat.S_ISLNK(linked.st_mode):
                    raise RuntimeContractError(f"{name} must not be a symbolic link")
                if linked.st_nlink != 1:
                    raise RuntimeContractError(f"{name} must not be a hard link")
            if Path(os.path.abspath(candidate)) != Path(os.path.abspath(required)):
                raise RuntimeContractError(f"{name} path must stay inside the current run")
            if candidate.resolve() != required.resolve():
                raise RuntimeContractError(f"{name} path escapes the current run")

    @staticmethod
    def _validate_bound_services(context: ExecutionContext) -> None:
        """Bind path-aware services to the exact identity of this run."""

        expected_scalars = {
            "app_id": context.app_id,
            "run_id": context.run_id,
            "account_id": context.account_id,
        }
        for service_name, service in context.services.items():
            for attribute, required in expected_scalars.items():
                if hasattr(service, attribute) and getattr(service, attribute) != required:
                    raise RuntimeContractError(
                        f"service {service_name!r} {attribute} does not match execution context"
                    )
            if hasattr(service, "mode") and _value(getattr(service, "mode")) != _value(context.mode):
                raise RuntimeContractError(
                    f"service {service_name!r} mode does not match execution context"
                )
            if not hasattr(service, "run_dir"):
                continue
            service_run_dir = Path(getattr(service, "run_dir"))
            if service_run_dir.is_symlink():
                raise RuntimeContractError(
                    f"service {service_name!r} run_dir must not be a symbolic link"
                )
            if Path(os.path.abspath(service_run_dir)) != Path(os.path.abspath(context.run_dir)):
                raise RuntimeContractError(
                    f"service {service_name!r} run_dir does not match execution context"
                )
            if service_run_dir.resolve() != context.run_dir.resolve():
                raise RuntimeContractError(
                    f"service {service_name!r} run_dir escapes execution context"
                )

    @staticmethod
    def _validate_checkpoint_steps(checkpoint: Mapping[str, Any], program: BaseProgram) -> None:
        stored = checkpoint.get("steps")
        if not isinstance(stored, Mapping):
            raise CheckpointError("checkpoint steps are missing")
        expected_ids = {step.spec.step_id for step in program.steps}
        stored_ids = set(stored)
        if expected_ids != stored_ids:
            missing = sorted(expected_ids - stored_ids)
            unexpected = sorted(stored_ids - expected_ids)
            raise CheckpointError(
                f"checkpoint step set mismatch; missing={missing}, unexpected={unexpected}"
            )

    @staticmethod
    def _validate_resume_authorization(
        checkpoint: Mapping[str, Any],
        program: BaseProgram,
        context: ExecutionContext,
    ) -> None:
        """Recheck the claimed Resume scope against the state read under the run lock."""

        if "authorization" not in context.services:
            return

        from .authorization import AuthorizationOperation

        authorization = context.authorization
        authorization.assert_active()
        scope = authorization.scope
        expected_identity = {
            "app_id": context.app_id,
            "program_id": context.program_id,
            "program_version": context.program_version,
            "requirement_hash": context.requirement_hash,
            "run_id": context.run_id,
            "account_id": context.account_id,
            "mode": _value(context.mode),
        }
        scoped_identity = {
            "app_id": scope.app_id,
            "program_id": scope.program_id,
            "program_version": scope.program_version,
            "requirement_hash": scope.requirement_hash,
            "run_id": scope.run_id,
            "account_id": scope.account_id,
            "mode": _value(scope.mode),
        }
        if (
            scope.operation is not AuthorizationOperation.RESUME
            or scoped_identity != expected_identity
        ):
            raise CheckpointAuthorizationMismatchError(
                "claimed authorization does not match the Resume execution context"
            )

        steps = checkpoint.get("steps")
        assert isinstance(steps, Mapping)  # checked by _validate_checkpoint_steps
        actual_resume_step_id: str | None = None
        for step in program.steps:
            record = steps.get(step.spec.step_id)
            if not isinstance(record, Mapping) or "status" not in record:
                raise CheckpointError(
                    f"checkpoint step record is invalid: {step.spec.step_id}"
                )
            if _value(record["status"]) != _value(StepStatus.SUCCEEDED):
                actual_resume_step_id = step.spec.step_id
                break

        if (
            checkpoint_digest(checkpoint) != scope.resume_checkpoint_digest
            or actual_resume_step_id != scope.resume_step_id
        ):
            raise CheckpointAuthorizationMismatchError(
                "checkpoint no longer matches the claimed Resume authorization"
            )

    def _recover_or_prepare(
        self,
        step: Step,
        context: ExecutionContext,
        checkpoint: dict[str, Any],
        record: dict[str, Any],
        store: CheckpointStore,
        logger: JsonlEventLogger,
    ) -> bool:
        policy = _value(step.spec.resume_policy)
        if policy == _value(ResumePolicy.MANUAL):
            raise ResumeBlockedError(
                f"step {step.spec.step_id} requires manual recovery confirmation"
            )

        if policy == _value(ResumePolicy.VERIFY_THEN_RUN):
            current = _value(record["status"])
            if _value(StepStatus.VERIFYING) not in _ALLOWED_TRANSITIONS.get(current, set()):
                if _value(StepStatus.FAILED) not in _ALLOWED_TRANSITIONS.get(current, set()):
                    raise InvalidStepTransition(f"cannot recover step from {current}")
                self._transition(record, StepStatus.FAILED)
            self._transition(record, StepStatus.VERIFYING)
            checkpoint["updated_at"] = _utc_now()
            store.save(checkpoint)
            recovery_started = time.monotonic()
            self._start_step_deadline(context, step, record["attempts"])
            try:
                verified = bool(step.verify_recovery(context, record))
                context.ensure_step_within_deadline()
            except Exception as error:
                record["error"] = {
                    "code": getattr(error, "error_code", "step_recovery_failed"),
                    "type": type(error).__name__,
                }
                record["finished_at"] = _utc_now()
                self._transition(record, StepStatus.FAILED)
                checkpoint["updated_at"] = _utc_now()
                store.save(checkpoint)
                logger.emit(
                    "step.failed",
                    app_id=context.app_id,
                    run_id=context.run_id,
                    program_id=context.program_id,
                    program_version=context.program_version,
                    step_id=step.spec.step_id,
                    status=StepStatus.FAILED,
                    attempt=record["attempts"],
                    duration_ms=int((time.monotonic() - recovery_started) * 1000),
                    error_code=record["error"]["code"],
                    details={"exception_type": type(error).__name__},
                )
                raise
            finally:
                self._clear_step_deadline(context)
            if verified:
                record["finished_at"] = _utc_now()
                record["error"] = None
                self._transition(record, StepStatus.SUCCEEDED)
                checkpoint["updated_at"] = _utc_now()
                store.save(checkpoint)
                logger.emit(
                    "step.recovery_verified",
                    app_id=context.app_id,
                    run_id=context.run_id,
                    program_id=context.program_id,
                    program_version=context.program_version,
                    step_id=step.spec.step_id,
                    status=StepStatus.SUCCEEDED,
                    attempt=record["attempts"],
                )
                return True
            self._transition(record, StepStatus.FAILED)
        elif policy == _value(ResumePolicy.ALWAYS_RUN):
            # Normalize an interrupted state so the next transition is explicit.
            current = _value(record["status"])
            if current != _value(StepStatus.FAILED):
                if _value(StepStatus.FAILED) not in _ALLOWED_TRANSITIONS.get(current, set()):
                    raise InvalidStepTransition(f"cannot resume step from {current}")
                self._transition(record, StepStatus.FAILED)
        else:
            raise RuntimeContractError(f"unsupported resume policy: {step.spec.resume_policy!r}")

        record["error"] = {
            "code": "interrupted_before_resume",
            "type": "InterruptedRun",
        }
        checkpoint["updated_at"] = _utc_now()
        store.save(checkpoint)
        return False

    def _run_step(
        self,
        step: Step,
        context: ExecutionContext,
        checkpoint: dict[str, Any],
        record: dict[str, Any],
        store: CheckpointStore,
        logger: JsonlEventLogger,
    ) -> Any:
        policy = step.spec.retry_policy
        delay = policy.delay_seconds
        last_error: Exception | None = None

        for invocation_attempt in range(1, policy.max_attempts + 1):
            record["attempts"] += 1
            total_attempt = record["attempts"]
            record["started_at"] = _utc_now()
            record["finished_at"] = None
            record["error"] = None
            self._transition(record, StepStatus.RUNNING)
            checkpoint["updated_at"] = _utc_now()
            store.save(checkpoint)
            started = time.monotonic()
            self._start_step_deadline(context, step, total_attempt, started=started)
            logger.emit(
                "step.started",
                app_id=context.app_id,
                run_id=context.run_id,
                program_id=context.program_id,
                program_version=context.program_version,
                step_id=step.spec.step_id,
                status=StepStatus.RUNNING,
                attempt=total_attempt,
            )

            try:
                context.ensure_step_within_deadline()
                result = step.execute(context)
                context.ensure_step_within_deadline()
                self._transition(record, StepStatus.VERIFYING)
                checkpoint["updated_at"] = _utc_now()
                store.save(checkpoint)
                logger.emit(
                    "step.verifying",
                    app_id=context.app_id,
                    run_id=context.run_id,
                    program_id=context.program_id,
                    program_version=context.program_version,
                    step_id=step.spec.step_id,
                    status=StepStatus.VERIFYING,
                    attempt=total_attempt,
                )
                verified = bool(step.verify(context, result))
                context.ensure_step_within_deadline()
                if not verified:
                    verification_error = StepRunError(
                        step.spec.step_id,
                        "step_verification_failed",
                        f"step {step.spec.step_id} did not satisfy its success condition",
                    )
                    raise verification_error

                # SUCCEEDED is persisted only after the verifier returned true.
                record["result"] = sanitize_event_value(result)
                record["evidence_refs"] = self._evidence_refs(result)
                record["finished_at"] = _utc_now()
                self._transition(record, StepStatus.SUCCEEDED)
                checkpoint["updated_at"] = _utc_now()
                store.save(checkpoint)
                logger.emit(
                    "step.succeeded",
                    app_id=context.app_id,
                    run_id=context.run_id,
                    program_id=context.program_id,
                    program_version=context.program_version,
                    step_id=step.spec.step_id,
                    status=StepStatus.SUCCEEDED,
                    attempt=total_attempt,
                    duration_ms=int((time.monotonic() - started) * 1000),
                    evidence_refs=record["evidence_refs"],
                )
                self._clear_step_deadline(context)
                return result
            except Exception as error:
                last_error = error
                can_retry = invocation_attempt < policy.max_attempts and self._is_retryable(error, policy)
                record["error"] = {
                    "code": getattr(error, "error_code", "step_execution_failed"),
                    "type": type(error).__name__,
                }
                record["finished_at"] = _utc_now()
                target = StepStatus.RETRY_WAIT if can_retry else StepStatus.FAILED
                self._transition(record, target)
                checkpoint["updated_at"] = _utc_now()
                store.save(checkpoint)
                logger.emit(
                    "step.retrying" if can_retry else "step.failed",
                    app_id=context.app_id,
                    run_id=context.run_id,
                    program_id=context.program_id,
                    program_version=context.program_version,
                    step_id=step.spec.step_id,
                    status=target,
                    attempt=total_attempt,
                    duration_ms=int((time.monotonic() - started) * 1000),
                    error_code=record["error"]["code"],
                    details={"exception_type": type(error).__name__},
                )
                self._clear_step_deadline(context)
                if not can_retry:
                    if isinstance(error, StepRunError):
                        raise
                    raise StepRunError(
                        step.spec.step_id,
                        getattr(error, "error_code", "step_execution_failed"),
                        f"step {step.spec.step_id} failed after {invocation_attempt} attempt(s)",
                    ) from error
                if delay:
                    self._sleep(delay)
                delay *= policy.backoff_multiplier

        # The loop is non-empty by contract; this protects future policy changes.
        raise StepRunError(
            step.spec.step_id,
            "step_execution_failed",
            f"step {step.spec.step_id} failed",
        ) from last_error

    @staticmethod
    def _start_step_deadline(
        context: ExecutionContext,
        step: Step,
        attempt: int,
        *,
        started: float | None = None,
    ) -> None:
        context.current_step_id = step.spec.step_id
        context.current_attempt = attempt
        context.current_step_timeout_seconds = step.spec.timeout_seconds
        origin = time.monotonic() if started is None else started
        context.step_deadline_monotonic = (
            origin + step.spec.timeout_seconds
            if step.spec.timeout_seconds is not None
            else None
        )

    @staticmethod
    def _clear_step_deadline(context: ExecutionContext) -> None:
        context.current_step_id = None
        context.current_attempt = None
        context.current_step_timeout_seconds = None
        context.step_deadline_monotonic = None

    @staticmethod
    def _transition(record: dict[str, Any], target: StepStatus) -> None:
        current = _value(record["status"])
        requested = _value(target)
        if requested not in _ALLOWED_TRANSITIONS.get(current, set()):
            raise InvalidStepTransition(f"invalid step transition: {current} -> {requested}")
        record["status"] = requested

    @staticmethod
    def _is_retryable(error: Exception, policy: RetryPolicy) -> bool:
        configured = tuple(policy.retryable_errors)
        if not configured:
            return True
        names = {
            type(error).__name__,
            f"{type(error).__module__}.{type(error).__qualname__}",
            str(getattr(error, "error_code", "")),
        }
        return any(item in names for item in configured)

    @staticmethod
    def _evidence_refs(result: Any) -> list[str]:
        if isinstance(result, Mapping):
            raw = result.get("evidence_refs", [])
            if isinstance(raw, (list, tuple)):
                return [str(item) for item in raw]
        return []


# Descriptive aliases used by some application code and reports.
Program = BaseProgram
StepExecutionError = StepRunError
