"""Fail-closed real-browser orchestration for the standard application CLI."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
import os
from pathlib import Path
import re
import stat
import tomllib
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

from rpa_core.authorization import (
    AuthorizationError,
    AuthorizationOperation,
    AuthorizationScope,
    AuthorizationSession,
    AuthorizationStatus,
    AuthorizationStore,
    AuthorizedBrowserActions,
    BrowserAction,
    catalog_lock_digest,
)
from rpa_core.browser_manager import (
    BrowserLaunchSpec,
    BrowserLifecyclePolicy,
    BrowserManager,
)
from rpa_core.catalog import CatalogItemStatus, verify_catalog_snapshot
from rpa_core.contracts import RunMode
from rpa_core.runtime import (
    CheckpointError,
    CheckpointStore,
    ExecutionContext,
    RunResult,
    Runner,
    checkpoint_digest,
)

from rpa_core.elements import check_element_expectations

from .elements import element_catalog, element_entries
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


_RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_AUTHORIZATION_ROOT = Path("runtime") / "authorizations"
_LOGIN_STEP_ID = "LOGIN"
_PROGRAM_STEP_IDS = ("Prepare", "S001", "S002", "S003", "S004", "S005")
_LOGIN_BROWSER_ACTIONS = (
    BrowserAction.OPEN,
    BrowserAction.EXISTS,
    BrowserAction.CLICK,
    BrowserAction.INPUT,
    BrowserAction.SCREENSHOT,
)
_PROGRAM_BROWSER_ACTIONS = tuple(BrowserAction)


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


class AuthorizationRequiredError(ApplicationRuntimeError):
    def __init__(self) -> None:
        super().__init__(
            "authorization_required",
            real_browser_launched=False,
        )


class CandidateScopeEmptyError(ApplicationRuntimeError):
    def __init__(self) -> None:
        super().__init__(
            "candidate_scope_empty",
            real_browser_launched=False,
        )


class LiveUnsupportedError(ApplicationRuntimeError):
    def __init__(self) -> None:
        super().__init__(
            "application_live_unsupported",
            real_browser_launched=False,
        )


@dataclass(frozen=True, slots=True)
class _RuntimeInputs:
    requirement_hash: str
    store: StoreConfig
    credentials: LoginCredentials | None


@dataclass(frozen=True, slots=True)
class _ResumeAuthorizationState:
    checkpoint_digest: str
    step_id: str


def create_authorization_request(
    *,
    operation: str,
    account: str,
    mode: str,
    run_id: str,
    requested_by: str,
    authorization_id: str | None = None,
) -> dict[str, object]:
    """Persist the exact scope that a developer can inspect before granting."""

    try:
        normalized_operation = AuthorizationOperation(operation)
        normalized_mode = RunMode(mode)
    except ValueError as error:
        raise ApplicationRuntimeError(
            "authorization_scope_invalid",
            real_browser_launched=False,
            exception_type=type(error).__name__,
        ) from error
    _require_supported_mode(normalized_mode)
    _validate_run_id(run_id)
    if not requested_by.strip():
        raise ApplicationRuntimeError(
            "authorization_request_invalid",
            real_browser_launched=False,
        )
    inputs = _load_runtime_inputs(account, require_credentials=False)
    scope = _build_authorization_scope(
        inputs=inputs,
        operation=normalized_operation,
        mode=normalized_mode,
        run_id=run_id,
    )
    try:
        record = _authorization_store().create_request(
            scope,
            requested_by=requested_by,
            authorization_id=authorization_id,
        )
    except (AuthorizationError, ValueError) as error:
        raise _authorization_runtime_error(error) from error
    return {
        "ok": True,
        "command": "authorization request",
        "authorization": _model_payload(record),
        "real_browser_launched": False,
        "run_directory_created": False,
    }


def grant_authorization_request(
    *,
    authorization_id: str,
    scope_digest: str,
    authorized_by: str,
    approval_reference: str,
    ttl_seconds: int,
    now: datetime | None = None,
) -> dict[str, object]:
    """Grant one previously requested scope without launching a browser."""

    if not 1 <= ttl_seconds <= 3600:
        raise ApplicationRuntimeError(
            "authorization_ttl_invalid",
            real_browser_launched=False,
        )
    if not authorized_by.strip() or not approval_reference.strip():
        raise ApplicationRuntimeError(
            "authorization_grant_invalid",
            real_browser_launched=False,
        )
    granted_at = now or datetime.now(UTC)
    if granted_at.tzinfo is None:
        raise ApplicationRuntimeError(
            "authorization_time_invalid",
            real_browser_launched=False,
        )
    try:
        record = _authorization_store().grant(
            authorization_id,
            scope_digest=scope_digest,
            authorized_by=authorized_by,
            approval_reference=approval_reference,
            expires_at=granted_at + timedelta(seconds=ttl_seconds),
            now=granted_at,
        )
    except (AuthorizationError, ValueError) as error:
        raise _authorization_runtime_error(error) from error
    return {
        "ok": True,
        "command": "authorization grant",
        "authorization": _model_payload(record),
        "real_browser_launched": False,
        "run_directory_created": False,
    }


def revoke_authorization_request(
    *,
    authorization_id: str,
    revoked_by: str,
    reason: str,
) -> dict[str, object]:
    """Revoke an unclaimed request without launching a browser."""

    try:
        record = _authorization_store().revoke(
            authorization_id,
            revoked_by=revoked_by,
            reason=reason,
        )
    except (AuthorizationError, ValueError) as error:
        raise _authorization_runtime_error(error) from error
    return {
        "ok": True,
        "command": "authorization revoke",
        "authorization": _model_payload(record),
        "real_browser_launched": False,
        "run_directory_created": False,
    }


def execute_login(
    *,
    account: str,
    run_id: str,
    authorization_id: str,
) -> dict[str, object]:
    """Establish or confirm the authorized persistent Profile login state."""

    _validate_run_id(run_id)
    inputs = _load_runtime_inputs(account, require_credentials=False)
    authorization = _claim_authorization(
        authorization_id,
        _build_authorization_scope(
            inputs=inputs,
            operation=AuthorizationOperation.LOGIN,
            mode=RunMode.PREVIEW,
            run_id=run_id,
        ),
    )
    run_dir = APP_DIR / "runtime" / "login-runs" / run_id

    def operation(
        context: ExecutionContext,
        runtime_inputs: _RuntimeInputs,
    ) -> dict[str, object]:
        assert runtime_inputs.credentials is not None
        context.browser.open(runtime_inputs.store.login_url, wait="complete")
        result = context.instructions.execute(
            "jushuitan.auth.login",
            context,
            {
                "login_url": runtime_inputs.store.login_url,
                "username": runtime_inputs.credentials.username,
                "password": runtime_inputs.credentials.password,
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
            "authorization_id": authorization.authorization_id,
            "authorization_scope_digest": authorization.scope_digest,
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
        registry_factory=_validated_snapshot_registry,
        operation=operation,
        authorization=authorization,
        mode=RunMode.PREVIEW,
        fallback_step_id=_LOGIN_STEP_ID,
    )


def execute_candidate_verification(
    *,
    account: str,
    run_id: str,
    authorization_id: str,
) -> dict[str, object]:
    """Run one fresh candidate-bound Preview flow."""

    _validate_run_id(run_id)
    inputs = _load_runtime_inputs(account, require_credentials=False)
    run_dir = APP_DIR / "runs" / run_id
    authorization = _claim_authorization(
        authorization_id,
        _build_authorization_scope(
            inputs=inputs,
            operation=AuthorizationOperation.VERIFY_CANDIDATES,
            mode=RunMode.PREVIEW,
            run_id=run_id,
        ),
    )

    def operation(
        context: ExecutionContext,
        runtime_inputs: _RuntimeInputs,
    ) -> dict[str, object]:
        program = build_program(runtime_inputs.requirement_hash)
        result = Runner().run(program, context)
        evidence = context.browser.screenshot(
            name=_evidence_name("candidate-preview-succeeded")
        )
        return {
            "ok": True,
            "command": "verify-candidates",
            "account": account,
            "authorization_id": authorization.authorization_id,
            "authorization_scope_digest": authorization.scope_digest,
            "resumed": False,
            **_run_summary(result, run_dir),
            "evidence": _artifact_summary(evidence.path, run_dir),
            "real_browser_launched": True,
            "external_business_writes_executed": False,
        }

    return _with_browser(
        inputs=inputs,
        run_id=run_id,
        run_dir=run_dir,
        registry_factory=_validated_snapshot_registry,
        operation=operation,
        authorization=authorization,
        mode=RunMode.PREVIEW,
        fallback_step_id="Prepare",
    )


def execute_element_verification(
    *,
    account: str,
    run_id: str,
    authorization_id: str,
) -> dict[str, object]:
    """Assert every ``elements.toml`` expect_count against the live pages.

    This is the element catalog's payoff: when the site changes, one run names
    the entries to repair instead of leaving a step to fail with an opaque
    lookup error.
    """

    _validate_run_id(run_id)
    inputs = _load_runtime_inputs(account, require_credentials=True)
    run_dir = APP_DIR / "runs" / run_id
    authorization = _claim_authorization(
        authorization_id,
        _build_authorization_scope(
            inputs=inputs,
            operation=AuthorizationOperation.VERIFY_ELEMENTS,
            mode=RunMode.PREVIEW,
            run_id=run_id,
        ),
    )

    def operation(
        context: ExecutionContext,
        runtime_inputs: _RuntimeInputs,
    ) -> dict[str, object]:
        program = build_program(runtime_inputs.requirement_hash)
        entries = element_entries()
        checks: list[Any] = []
        reached: list[str] = []
        skipped_stages: list[str] = []
        navigation_failure: dict[str, object] | None = None

        def sweep(stage: str) -> None:
            checks.extend(check_element_expectations(context.browser, entries, stage=stage))

        # The login form only exists when a session actually has to be created.
        # Reporting its inputs as broken during a reused session would be a lie.
        context.browser.open(runtime_inputs.store.login_url, wait="complete")
        if context.browser.exists(
            element_catalog()["jushuitan.erp.shell.authenticated_marker"],
            timeout=3.0,
        ):
            skipped_stages.append("login_page")
        else:
            reached.append("login_page")
            sweep("login_page")

        program.prepare(context)
        reached.append("session")
        sweep("session")

        for step in program.steps:
            if step.spec.step_id not in {"S001", "S002", "S003", "S004"}:
                continue
            context.current_step_id = step.spec.step_id
            try:
                result = step.execute(context)
            except Exception as error:
                # Silently breaking would report the remaining stages as
                # "unreached" without saying why they could not be reached.
                navigation_failure = {
                    "step_id": step.spec.step_id,
                    "phase": "execute",
                    "exception_type": type(error).__name__,
                    "error_code": getattr(error, "error_code", None),
                    # Adapter messages carry element IDs only, never values.
                    "message": str(error)[:200],
                }
                break
            reached.append(step.spec.step_id)
            sweep(step.spec.step_id)
            if not step.verify(context, result):
                navigation_failure = {
                    "step_id": step.spec.step_id,
                    "phase": "verify",
                    "exception_type": None,
                    "error_code": "step_verification_failed",
                }
                break

        checked_stages = {item.check_at for item in entries.values()}
        unreached = sorted(
            checked_stages - set(reached) - set(skipped_stages)
        )
        evidence = context.browser.screenshot(name=_evidence_name("verify-elements"))
        failures = [item for item in checks if not item.ok]
        return {
            "ok": not failures and not unreached,
            "command": "verify-elements",
            "account": account,
            "authorization_id": authorization.authorization_id,
            "reached_stages": tuple(reached),
            "skipped_stages": tuple(skipped_stages),
            "unreached_stages": tuple(unreached),
            "navigation_failure": navigation_failure,
            "checks": [
                {
                    "element_id": item.element_id,
                    "expect": item.expected,
                    "actual": item.actual,
                    "status": item.symbol,
                    "detail": item.detail,
                }
                for item in checks
            ],
            "failed_element_ids": tuple(item.element_id for item in failures),
            "weak_element_ids": tuple(
                item.element_id for item in checks if item.ok and item.weak
            ),
            "evidence": _artifact_summary(evidence.path, run_dir),
            "real_browser_launched": True,
            "external_business_writes_executed": False,
        }

    return _with_browser(
        inputs=inputs,
        run_id=run_id,
        run_dir=run_dir,
        registry_factory=_validated_snapshot_registry,
        operation=operation,
        authorization=authorization,
        mode=RunMode.PREVIEW,
        fallback_step_id="Prepare",
    )


def execute_standard_run(
    *,
    command: str,
    account: str,
    mode: str,
    run_id: str,
    authorization_id: str,
) -> dict[str, object]:
    """Execute an already-unblocked standard Preview run or resume."""

    normalized_mode = RunMode(mode)
    _require_supported_mode(normalized_mode)
    if command not in {"run", "resume"}:
        raise ApplicationRuntimeError(
            "application_command_invalid",
            real_browser_launched=False,
        )
    resume = command == "resume"
    operation_kind = (
        AuthorizationOperation.RESUME if resume else AuthorizationOperation.RUN
    )
    _validate_run_id(run_id)
    inputs = _load_runtime_inputs(account, require_credentials=False)
    run_dir = APP_DIR / "runs" / run_id
    resume_state = (
        _resume_authorization_state(
            run_dir,
            inputs=inputs,
            mode=normalized_mode,
        )
        if resume
        else None
    )
    resume_target = resume_state.step_id if resume_state is not None else None
    authorization = _claim_authorization(
        authorization_id,
        _build_authorization_scope(
            inputs=inputs,
            operation=operation_kind,
            mode=normalized_mode,
            run_id=run_id,
            resume_state=resume_state,
        ),
    )

    def operation(
        context: ExecutionContext,
        runtime_inputs: _RuntimeInputs,
    ) -> dict[str, object]:
        program = build_program(runtime_inputs.requirement_hash)
        result = (
            Runner().resume(program, context)
            if resume
            else Runner().run(program, context)
        )
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
            "authorization_id": authorization.authorization_id,
            "authorization_scope_digest": authorization.scope_digest,
            **_run_summary(result, run_dir),
            "evidence": _artifact_summary(evidence.path, run_dir),
            "real_browser_launched": True,
            "external_business_writes_executed": False,
        }

    return _with_browser(
        inputs=inputs,
        run_id=run_id,
        run_dir=run_dir,
        registry_factory=build_instruction_registry,
        operation=operation,
        resume_target=resume_target,
        authorization=authorization,
        mode=normalized_mode,
        fallback_step_id="Prepare",
    )


def _with_browser(
    *,
    inputs: _RuntimeInputs,
    run_id: str,
    run_dir: Path,
    registry_factory: Any,
    operation: Any,
    authorization: AuthorizationSession,
    mode: RunMode,
    fallback_step_id: str,
    resume_target: str | None = None,
) -> dict[str, object]:
    launched = False
    manager: BrowserManager | None = None
    outcome: dict[str, object] | None = None
    caught: Exception | None = None
    try:
        inputs = _load_credentials(inputs)
        registry = registry_factory()
        profile_dir = _profile_directory(inputs.store)
        profile_id = _profile_id(profile_dir)
        if profile_id != authorization.scope.profile_id:
            raise ApplicationRuntimeError(
                "authorization_scope_mismatch",
                real_browser_launched=False,
                run_id=run_id,
            )
        if authorization.scope.operation is AuthorizationOperation.RESUME:
            current_resume_state = _resume_authorization_state(
                run_dir,
                inputs=inputs,
                mode=mode,
            )
            if (
                current_resume_state.checkpoint_digest
                != authorization.scope.resume_checkpoint_digest
                or current_resume_state.step_id
                != authorization.scope.resume_step_id
            ):
                raise ApplicationRuntimeError(
                    "authorization_scope_mismatch",
                    real_browser_launched=False,
                    run_id=run_id,
                )
        authorization.assert_active()
        manager = BrowserManager(
            APP_DIR / "runtime" / "browser-manager",
            port_range=(inputs.store.debug_port, inputs.store.debug_port),
        )
        try:
            session = manager.start(
                BrowserLaunchSpec(
                    account_id=inputs.store.account_id,
                    profile_id=profile_id,
                    profile_dir=profile_dir,
                    requested_port=inputs.store.debug_port,
                    lifecycle=BrowserLifecyclePolicy.TERMINATE_ON_FINISH,
                ),
                run_id=run_id,
                run_dir=run_dir,
                action_timeout=15.0,
                download_timeout=300.0,
            )
        except Exception as error:
            launched = bool(getattr(error, "real_browser_launched", False))
            raise
        launched = True
        context = ExecutionContext(
            app_id=APP_ID,
            program_id=PROGRAM_ID,
            program_version=PROGRAM_VERSION,
            requirement_hash=inputs.requirement_hash,
            run_id=run_id,
            account_id=inputs.store.account_id,
            mode=mode,
            run_dir=run_dir,
            services={
                "authorization": authorization,
                "browser": session.actions,
                "elements": element_catalog(),
                "instructions": registry,
            },
            metadata={
                "app_dir": str(APP_DIR),
                "resume_recovery_target": resume_target,
            },
        )
        context.services["browser"] = AuthorizedBrowserActions(
            session.actions,
            authorization,
            step_id_getter=lambda: context.current_step_id or fallback_step_id,
        )
        if inputs.credentials is None:
            raise ApplicationRuntimeError(
                "application_configuration_invalid",
                real_browser_launched=True,
                run_id=run_id,
        )
        bind_program_inputs(context, inputs.store, inputs.credentials)
        outcome = operation(context, inputs)
    except Exception as error:
        caught = error
    finally:
        if manager is not None:
            try:
                manager.shutdown()
            except Exception as error:
                if caught is None:
                    caught = error
    authorization_error: Exception | None = None
    try:
        authorization.finish(
            status=(
                AuthorizationStatus.SUCCEEDED
                if caught is None
                else AuthorizationStatus.FAILED
            ),
            error_code=(
                None
                if caught is None
                else getattr(caught, "error_code", "application_runtime_failed")
            ),
            evidence_refs=_authorization_evidence_refs(outcome),
        )
    except Exception as error:
        authorization_error = error
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
    if authorization_error is not None:
        raise ApplicationRuntimeError(
            getattr(
                authorization_error,
                "error_code",
                "authorization_record_invalid",
            ),
            real_browser_launched=launched,
            run_id=run_id,
            exception_type=type(authorization_error).__name__,
        ) from authorization_error
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


def _load_credentials(inputs: _RuntimeInputs) -> _RuntimeInputs:
    environment = dict(os.environ)
    load_local_env(APP_DIR / ".env", environment)
    return _RuntimeInputs(
        inputs.requirement_hash,
        inputs.store,
        load_login_credentials(inputs.store, environment),
    )


def _authorization_store() -> AuthorizationStore:
    return AuthorizationStore(
        APP_DIR / _AUTHORIZATION_ROOT,
        boundary=APP_DIR,
    )


def _build_authorization_scope(
    *,
    inputs: _RuntimeInputs,
    operation: AuthorizationOperation,
    mode: RunMode,
    run_id: str,
    resume_state: _ResumeAuthorizationState | None = None,
) -> AuthorizationScope:
    lock = verify_catalog_snapshot(APP_DIR)
    candidate_refs = tuple(
        sorted(
            f"{item.kind.value}:{item.id}"
            for item in lock.items
            if item.status is CatalogItemStatus.CANDIDATE
        )
    )
    if operation is AuthorizationOperation.VERIFY_CANDIDATES and not candidate_refs:
        raise CandidateScopeEmptyError()
    if operation is AuthorizationOperation.RESUME:
        resume_state = resume_state or _resume_authorization_state(
            APP_DIR / "runs" / run_id,
            inputs=inputs,
            mode=mode,
        )
    elif resume_state is not None:
        raise ApplicationRuntimeError(
            "authorization_scope_invalid",
            real_browser_launched=False,
            run_id=run_id,
        )

    if operation is AuthorizationOperation.LOGIN:
        registry = build_instruction_registry()
        element_ids = tuple(
            sorted(
                registry.get("jushuitan.auth.login").spec.required_element_ids
            )
        )
        step_ids = (_LOGIN_STEP_ID,)
        browser_actions = _LOGIN_BROWSER_ACTIONS
        scoped_candidates: tuple[str, ...] = ()
    else:
        element_ids = tuple(sorted(element_catalog()))
        step_ids = _PROGRAM_STEP_IDS
        browser_actions = _PROGRAM_BROWSER_ACTIONS
        scoped_candidates = (
            candidate_refs
            if operation is AuthorizationOperation.VERIFY_CANDIDATES
            else ()
        )

    return AuthorizationScope(
        app_id=APP_ID,
        app_version=PROGRAM_VERSION,
        program_id=PROGRAM_ID,
        program_version=PROGRAM_VERSION,
        requirement_hash=inputs.requirement_hash,
        catalog_digest=catalog_lock_digest(lock),
        operation=operation,
        mode=mode,
        run_id=run_id,
        resume_checkpoint_digest=(
            resume_state.checkpoint_digest if resume_state is not None else None
        ),
        resume_step_id=(resume_state.step_id if resume_state is not None else None),
        account_id=inputs.store.account_id,
        profile_id=_profile_id(_profile_directory(inputs.store)),
        allowed_origins=(_origin(inputs.store.login_url),),
        step_ids=step_ids,
        browser_actions=browser_actions,
        element_ids=element_ids,
        candidate_asset_refs=scoped_candidates,
        external_writes=(),
        source_preview_run_id=None,
    )


def _claim_authorization(
    authorization_id: str | None,
    scope: AuthorizationScope,
) -> AuthorizationSession:
    if not isinstance(authorization_id, str) or not authorization_id.strip():
        raise AuthorizationRequiredError()
    try:
        return _authorization_store().claim(authorization_id, scope)
    except AuthorizationError as error:
        raise ApplicationRuntimeError(
            error.error_code,
            real_browser_launched=False,
            run_id=scope.run_id,
            exception_type=type(error).__name__,
        ) from error


def _authorization_runtime_error(error: Exception) -> ApplicationRuntimeError:
    return ApplicationRuntimeError(
        getattr(error, "error_code", "authorization_record_invalid"),
        real_browser_launched=False,
        exception_type=type(error).__name__,
    )


def _require_supported_mode(mode: RunMode) -> None:
    if mode is RunMode.LIVE:
        raise LiveUnsupportedError()


def _origin(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme.casefold() != "https" or parsed.hostname is None:
        raise ApplicationRuntimeError(
            "application_configuration_invalid",
            real_browser_launched=False,
        )
    hostname = parsed.hostname.casefold()
    rendered_host = f"[{hostname}]" if ":" in hostname else hostname
    try:
        port = parsed.port
    except ValueError as error:
        raise ApplicationRuntimeError(
            "application_configuration_invalid",
            real_browser_launched=False,
        ) from error
    suffix = "" if port in {None, 443} else f":{port}"
    return f"https://{rendered_host}{suffix}"


def _model_payload(model: Any) -> dict[str, object]:
    payload = model.model_dump(mode="json")
    if not isinstance(payload, dict):
        raise TypeError("authorization record must serialize to one object")
    return payload


def _authorization_evidence_refs(
    outcome: Mapping[str, object] | None,
) -> tuple[str, ...]:
    if outcome is None:
        return ()
    refs: list[str] = []
    for key in ("checkpoint", "evidence", "download"):
        value = outcome.get(key)
        if isinstance(value, Mapping):
            path = value.get("path")
        else:
            path = value
        if isinstance(path, str) and path and path != "<outside-run-directory>":
            refs.append(path)
    return tuple(refs)


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
    try:
        target.absolute().relative_to(root.absolute())
    except ValueError as error:
        raise ApplicationRuntimeError(
            "application_configuration_invalid",
            real_browser_launched=False,
        ) from error
    current = APP_DIR
    for part in Path(store.profile_directory).parts:
        current = current / part
        try:
            metadata = os.lstat(current)
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(metadata.st_mode):
            raise ApplicationRuntimeError(
                "application_configuration_invalid",
                real_browser_launched=False,
            )
        if current != target and not stat.S_ISDIR(metadata.st_mode):
            raise ApplicationRuntimeError(
                "application_configuration_invalid",
                real_browser_launched=False,
            )
    try:
        target.resolve(strict=False).relative_to(root.resolve(strict=False))
    except ValueError as error:
        raise ApplicationRuntimeError(
            "application_configuration_invalid",
            real_browser_launched=False,
        ) from error
    return target


def _profile_id(profile_dir: Path) -> str:
    fingerprint = sha256(
        profile_dir.resolve(strict=False).as_posix().encode("utf-8")
    ).hexdigest()
    return f"profile-{fingerprint}"


def _resume_authorization_state(
    run_dir: Path,
    *,
    inputs: _RuntimeInputs,
    mode: RunMode,
) -> _ResumeAuthorizationState:
    try:
        checkpoint = CheckpointStore(run_dir / "checkpoint.json").load()
    except CheckpointError as error:
        raise ApplicationRuntimeError(
            "checkpoint_error",
            real_browser_launched=False,
            run_id=run_dir.name,
            exception_type=type(error).__name__,
        ) from error
    if checkpoint is None:
        raise ApplicationRuntimeError(
            "checkpoint_error",
            real_browser_launched=False,
            run_id=run_dir.name,
        )
    identity = checkpoint.get("identity")
    expected_identity = {
        "app_id": APP_ID,
        "program_id": PROGRAM_ID,
        "program_version": PROGRAM_VERSION,
        "requirement_hash": inputs.requirement_hash,
        "run_id": run_dir.name,
        "account_id": inputs.store.account_id,
        "mode": mode.value,
    }
    if not isinstance(identity, Mapping) or any(
        str(identity.get(key)) != str(value)
        for key, value in expected_identity.items()
    ):
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
    resume_step_id: str | None = None
    allowed_step_statuses = {
        "pending",
        "running",
        "verifying",
        "retry_wait",
        "failed",
        "succeeded",
    }
    for step_id in ("S001", "S002", "S003", "S004", "S005"):
        record = steps.get(step_id)
        if not isinstance(record, Mapping):
            raise ApplicationRuntimeError(
                "checkpoint_error",
                real_browser_launched=False,
                run_id=run_dir.name,
            )
        status_value = record.get("status")
        if status_value not in allowed_step_statuses:
            raise ApplicationRuntimeError(
                "checkpoint_error",
                real_browser_launched=False,
                run_id=run_dir.name,
            )
        if status_value != "succeeded" and resume_step_id is None:
            resume_step_id = step_id
    if resume_step_id is None:
        raise ApplicationRuntimeError(
            "checkpoint_error",
            real_browser_launched=False,
            run_id=run_dir.name,
        )
    try:
        digest = checkpoint_digest(checkpoint)
    except CheckpointError as error:
        raise ApplicationRuntimeError(
            "checkpoint_error",
            real_browser_launched=False,
            run_id=run_dir.name,
            exception_type=type(error).__name__,
        ) from error
    return _ResumeAuthorizationState(
        checkpoint_digest=digest,
        step_id=resume_step_id,
    )


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
    "ApplicationRuntimeError",
    "AuthorizationRequiredError",
    "CandidateScopeEmptyError",
    "LiveUnsupportedError",
    "create_authorization_request",
    "execute_candidate_verification",
    "execute_login",
    "execute_standard_run",
    "grant_authorization_request",
    "revoke_authorization_request",
]
