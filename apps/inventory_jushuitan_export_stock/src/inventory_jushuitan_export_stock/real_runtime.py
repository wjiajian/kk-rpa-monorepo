"""Fail-closed real-browser orchestration for the standard application CLI."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
import os
from pathlib import Path
import re
import tomllib
from typing import Any
from uuid import uuid4

from rpa_core.browser_manager import (
    BrowserLaunchSpec,
    BrowserLifecyclePolicy,
    BrowserManager,
)
from rpa_core.contracts import RunMode
from rpa_core.runtime import CheckpointStore, ExecutionContext, RunResult, Runner

from .elements import element_catalog
from .instructions import build_instruction_registry
from .models import (
    LoginCredentials,
    StoreConfig,
    load_local_env,
    load_login_credentials,
    load_store_config,
)
from .program import (
    APP_ID,
    PROGRAM_ID,
    PROGRAM_VERSION,
    bind_program_inputs,
    build_program,
)
from .validators import APP_DIR, load_validated_contracts


PATCH_C_AUTHORIZATION_BATCH_ID = "patch-c-verify-20260901"
ACCOUNT_SESSION_CANDIDATE_AUTHORIZATION_BATCH_ID: str | None = None
_RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class ApplicationRuntimeError(RuntimeError):
    """Sanitized command failure that never includes credentials or business values."""

    def __init__(
        self,
        error_code: str,
        *,
        real_browser_launched: bool,
        run_id: str | None = None,
        step_id: str | None = None,
        instruction_id: str | None = None,
        exception_type: str | None = None,
    ) -> None:
        super().__init__(f"application runtime failed: {error_code}")
        self.error_code = error_code
        self.real_browser_launched = real_browser_launched
        self.run_id = run_id
        self.step_id = step_id
        self.instruction_id = instruction_id
        self.exception_type = exception_type


class CandidateAuthorizationError(ApplicationRuntimeError):
    def __init__(self) -> None:
        super().__init__(
            "real_browser_authorization_required",
            real_browser_launched=False,
        )


class LiveAuthorizationError(ApplicationRuntimeError):
    def __init__(self) -> None:
        super().__init__(
            "live_write_authorization_required",
            real_browser_launched=False,
        )


@dataclass(frozen=True, slots=True)
class _RuntimeInputs:
    requirement_hash: str
    store: StoreConfig
    credentials: LoginCredentials | None


def execute_login(
    *,
    account: str,
    batch_id: str | None,
) -> dict[str, object]:
    """Establish or confirm the authorized persistent Profile login state."""

    _require_patch_c_authorization(batch_id)
    run_id = _new_run_id("login")
    inputs = _load_runtime_inputs(account, require_credentials=True)
    registry = _validated_snapshot_registry()
    run_dir = APP_DIR / "runtime" / "login-runs" / run_id

    def operation(context: ExecutionContext) -> dict[str, object]:
        assert inputs.credentials is not None
        result = registry.execute(
            "jushuitan.auth.login",
            context,
            {
                "login_url": inputs.store.login_url,
                "username": inputs.credentials.username,
                "password": inputs.credentials.password,
            },
        )
        evidence = context.browser.screenshot(
            name=_evidence_name("login-authenticated")
        )
        return {
            "ok": True,
            "command": "login",
            "account": account,
            "run_id": run_id,
            "authenticated": bool(result["authenticated"]),
            "human_verification_required": bool(
                result["human_verification_required"]
            ),
            "evidence": _artifact_summary(evidence.path, run_dir),
            "real_browser_launched": True,
        }

    return _with_browser(
        inputs=inputs,
        run_id=run_id,
        run_dir=run_dir,
        registry=registry,
        operation=operation,
    )


def execute_candidate_verification(
    *,
    account: str,
    batch_id: str | None,
    run_id: str | None = None,
    resume_run_id: str | None = None,
) -> dict[str, object]:
    """Run the bounded Patch C Preview flow, optionally resuming one checkpoint."""

    _require_account_session_candidate_authorization(batch_id)
    if run_id and resume_run_id:
        raise ApplicationRuntimeError(
            "candidate_run_id_conflict",
            real_browser_launched=False,
        )
    selected_run_id = resume_run_id or run_id or _new_run_id("candidate-preview")
    _validate_run_id(selected_run_id)
    inputs = _load_runtime_inputs(account, require_credentials=True)
    registry = _validated_snapshot_registry()
    run_dir = APP_DIR / "runs" / selected_run_id
    resume_target = _resume_target(run_dir) if resume_run_id else None

    def operation(context: ExecutionContext) -> dict[str, object]:
        program = build_program(inputs.requirement_hash)
        result = Runner().resume(program, context) if resume_run_id else Runner().run(program, context)
        evidence_stem = (
            "candidate-resume-succeeded"
            if resume_run_id
            else "candidate-preview-succeeded"
        )
        evidence = context.browser.screenshot(name=_evidence_name(evidence_stem))
        return {
            "ok": True,
            "command": "verify-candidates",
            "account": account,
            "authorization_batch_id": batch_id,
            "resumed": bool(resume_run_id),
            **_run_summary(result, run_dir),
            "evidence": _artifact_summary(evidence.path, run_dir),
            "real_browser_launched": True,
            "external_business_writes_executed": False,
        }

    return _with_browser(
        inputs=inputs,
        run_id=selected_run_id,
        run_dir=run_dir,
        registry=registry,
        operation=operation,
        resume_target=resume_target,
    )


def execute_standard_run(
    *,
    command: str,
    account: str,
    mode: str,
    run_id: str | None,
) -> dict[str, object]:
    """Execute an already-unblocked standard Preview run or resume."""

    normalized_mode = RunMode(mode)
    if normalized_mode is RunMode.LIVE:
        raise LiveAuthorizationError()
    resume = command == "resume"
    selected_run_id = run_id or _new_run_id("preview")
    _validate_run_id(selected_run_id)
    inputs = _load_runtime_inputs(account, require_credentials=True)
    registry = build_instruction_registry()
    run_dir = APP_DIR / "runs" / selected_run_id
    resume_target = _resume_target(run_dir) if resume else None

    def operation(context: ExecutionContext) -> dict[str, object]:
        program = build_program(inputs.requirement_hash)
        result = Runner().resume(program, context) if resume else Runner().run(program, context)
        evidence = context.browser.screenshot(
            name=_evidence_name(
                "resume-succeeded" if resume else "preview-succeeded"
            )
        )
        return {
            "ok": True,
            "command": command,
            "account": account,
            "mode": normalized_mode.value,
            **_run_summary(result, run_dir),
            "evidence": _artifact_summary(evidence.path, run_dir),
            "real_browser_launched": True,
            "external_business_writes_executed": False,
        }

    return _with_browser(
        inputs=inputs,
        run_id=selected_run_id,
        run_dir=run_dir,
        registry=registry,
        operation=operation,
        resume_target=resume_target,
    )


def _with_browser(
    *,
    inputs: _RuntimeInputs,
    run_id: str,
    run_dir: Path,
    registry: Any,
    operation: Any,
    resume_target: str | None = None,
) -> dict[str, object]:
    launched = False
    manager = BrowserManager(
        APP_DIR / "runtime" / "browser-manager",
        port_range=(inputs.store.debug_port, inputs.store.debug_port),
    )
    outcome: dict[str, object] | None = None
    caught: Exception | None = None
    try:
        session = manager.start(
            BrowserLaunchSpec(
                account_id=inputs.store.account_id,
                profile_id=inputs.store.account_id,
                profile_dir=_profile_directory(inputs.store),
                requested_port=inputs.store.debug_port,
                lifecycle=BrowserLifecyclePolicy.TERMINATE_ON_FINISH,
            ),
            run_id=run_id,
            run_dir=run_dir,
            action_timeout=15.0,
            download_timeout=300.0,
        )
        launched = True
        context = ExecutionContext(
            app_id=APP_ID,
            program_id=PROGRAM_ID,
            program_version=PROGRAM_VERSION,
            requirement_hash=inputs.requirement_hash,
            run_id=run_id,
            account_id=inputs.store.account_id,
            mode=RunMode.PREVIEW,
            run_dir=run_dir,
            services={
                "browser": session.actions,
                "elements": element_catalog(),
                "instructions": registry,
            },
            metadata={
                "app_dir": str(APP_DIR),
                "resume_recovery_target": resume_target,
            },
        )
        if inputs.credentials is None:
            raise ApplicationRuntimeError(
                "application_configuration_invalid",
                real_browser_launched=True,
                run_id=run_id,
            )
        bind_program_inputs(context, inputs.store, inputs.credentials)
        outcome = operation(context)
    except Exception as error:
        caught = error
    finally:
        try:
            manager.shutdown()
        except Exception as error:
            if caught is None:
                caught = error
    if caught is not None:
        if isinstance(caught, ApplicationRuntimeError):
            raise caught
        raise ApplicationRuntimeError(
            getattr(caught, "error_code", "application_runtime_failed"),
            real_browser_launched=launched,
            run_id=run_id,
            step_id=getattr(caught, "step_id", None),
            instruction_id=getattr(caught, "instruction_id", None),
            exception_type=type(caught).__name__,
        ) from caught
    assert outcome is not None
    return outcome


def _load_runtime_inputs(account: str, *, require_credentials: bool) -> _RuntimeInputs:
    manifest, _ = load_validated_contracts(APP_DIR)
    store = load_store_config(APP_DIR / "config" / "stores.local.toml", account)
    if store.uses_placeholder_values:
        raise ApplicationRuntimeError(
            "application_configuration_invalid",
            real_browser_launched=False,
        )
    credentials = None
    if require_credentials:
        environment = dict(os.environ)
        load_local_env(APP_DIR / ".env", environment)
        credentials = load_login_credentials(store, environment)
    return _RuntimeInputs(manifest.requirement_hash, store, credentials)


def _validated_snapshot_registry():
    registry = build_instruction_registry()
    elements = element_catalog()
    required_ids = {
        element_id
        for spec in registry.specs()
        for element_id in spec.required_element_ids
    }
    unresolved = sorted(
        element_id
        for element_id in required_ids
        if element_id not in elements or not elements[element_id].is_resolved
    )
    metadata = _element_metadata()
    invalid_metadata = []
    for element_id in sorted(required_ids):
        document = metadata.get(element_id, {})
        status = document.get("status")
        locator_status = document.get("locator_status")
        if status == "verified":
            verification = document.get("verification")
            if (
                locator_status != "verified"
                or not isinstance(verification, dict)
                or verification.get("status") == "failed"
            ):
                invalid_metadata.append(element_id)
        elif status == "candidate":
            offline = document.get("offline_verification")
            if (
                locator_status != "candidate"
                or not isinstance(offline, dict)
                or offline.get("status") != "passed"
            ):
                invalid_metadata.append(element_id)
        else:
            invalid_metadata.append(element_id)
    if unresolved or invalid_metadata:
        raise ApplicationRuntimeError(
            "candidate_snapshot_invalid",
            real_browser_launched=False,
        )
    return registry


def _element_metadata() -> dict[str, dict[str, object]]:
    root = APP_DIR / "src" / "inventory_jushuitan_export_stock" / "elements"
    result: dict[str, dict[str, object]] = {}
    for path in sorted(root.rglob("*.toml")):
        document = tomllib.loads(path.read_text(encoding="utf-8"))
        result[str(document["id"])] = document
    return result


def _profile_directory(store: StoreConfig) -> Path:
    root = APP_DIR / "profiles"
    target = APP_DIR / store.profile_directory
    if root.is_symlink() or target.is_symlink():
        raise ApplicationRuntimeError(
            "application_configuration_invalid",
            real_browser_launched=False,
        )
    try:
        target.absolute().relative_to(root.absolute())
    except ValueError as error:
        raise ApplicationRuntimeError(
            "application_configuration_invalid",
            real_browser_launched=False,
        ) from error
    return target


def _resume_target(run_dir: Path) -> str | None:
    checkpoint = CheckpointStore(run_dir / "checkpoint.json").load()
    if checkpoint is None:
        raise ApplicationRuntimeError(
            "checkpoint_error",
            real_browser_launched=False,
            run_id=run_dir.name,
        )
    steps = checkpoint.get("steps")
    if not isinstance(steps, Mapping):
        raise ApplicationRuntimeError(
            "checkpoint_error",
            real_browser_launched=False,
            run_id=run_dir.name,
        )
    for step_id in ("S001", "S002", "S003", "S004", "S005"):
        record = steps.get(step_id)
        if not isinstance(record, Mapping):
            raise ApplicationRuntimeError(
                "checkpoint_error",
                real_browser_launched=False,
                run_id=run_dir.name,
            )
        if record.get("status") != "succeeded":
            return step_id
    return None


def _require_patch_c_authorization(batch_id: str | None) -> None:
    if batch_id != PATCH_C_AUTHORIZATION_BATCH_ID:
        raise CandidateAuthorizationError()


def _require_account_session_candidate_authorization(batch_id: str | None) -> None:
    if (
        ACCOUNT_SESSION_CANDIDATE_AUTHORIZATION_BATCH_ID is None
        or batch_id != ACCOUNT_SESSION_CANDIDATE_AUTHORIZATION_BATCH_ID
    ):
        raise CandidateAuthorizationError()


def _new_run_id(prefix: str) -> str:
    return f"{prefix}-{datetime.now(UTC).strftime('%Y%m%dT%H%M%S%fZ')}"


def _evidence_name(stem: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,191}", stem):
        raise ApplicationRuntimeError(
            "runtime_contract_invalid",
            real_browser_launched=False,
        )
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    return f"{stem}-{timestamp}-{uuid4().hex}.png"


def _validate_run_id(run_id: str) -> None:
    if not _RUN_ID_PATTERN.fullmatch(run_id):
        raise ApplicationRuntimeError(
            "runtime_contract_invalid",
            real_browser_launched=False,
        )


def _run_summary(result: RunResult, run_dir: Path) -> dict[str, object]:
    export = result.outputs.get("S005")
    artifact = None
    if isinstance(export, Mapping):
        path = Path(str(export.get("download_path", "")))
        artifact = {
            "path": _relative_run_path(path, run_dir),
            "sha256": str(export.get("sha256", "")),
            "size_bytes": int(export.get("size_bytes", 0)),
        }
    return {
        "run_id": result.run_id,
        "status": result.status,
        "completed_steps": list(result.completed_steps),
        "skipped_steps": list(result.skipped_steps),
        "checkpoint": _relative_run_path(result.checkpoint_path, run_dir),
        "download": artifact,
    }


def _artifact_summary(path: Path, run_dir: Path) -> dict[str, object]:
    from hashlib import sha256

    content = path.read_bytes()
    return {
        "path": _relative_run_path(path, run_dir),
        "sha256": f"sha256:{sha256(content).hexdigest()}",
        "size_bytes": len(content),
    }


def _relative_run_path(path: Path, run_dir: Path) -> str:
    try:
        return path.resolve().relative_to(run_dir.resolve()).as_posix()
    except ValueError:
        return "<outside-run-directory>"


__all__ = [
    "ACCOUNT_SESSION_CANDIDATE_AUTHORIZATION_BATCH_ID",
    "ApplicationRuntimeError",
    "CandidateAuthorizationError",
    "LiveAuthorizationError",
    "PATCH_C_AUTHORIZATION_BATCH_ID",
    "execute_candidate_verification",
    "execute_login",
    "execute_standard_run",
]
