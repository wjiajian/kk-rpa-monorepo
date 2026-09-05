"""Prepare plus S001-S005 inventory export program."""

from __future__ import annotations

from collections.abc import Mapping
from hashlib import sha256
import os
from pathlib import Path
import unicodedata
from typing import Any

from rpa_core.browser import (
    ElementSpec,
    FakeBrowserActions,
    FakeDownload,
    SecretValue,
)
from rpa_core.cli import ApplicationDefinition, RuntimeOptions
from rpa_core.contracts import RunMode
from rpa_core.elements import ElementEntry, check_element_expectations, element_specs
from rpa_core.runtime import BaseProgram, ExecutionContext, ProgramSpec, Step
from rpa_core.verification import Counterexample

from .elements import element_entries
from .models import (
    ConfigurationError,
    LoginCredentials,
    StoreConfig,
    load_local_env,
    load_login_credentials,
    load_store_config,
)
from .steps import BRAND_SELECTED, EXPORT_OPTION, RESULT_ROW, build_steps
from .validators import APP_DIR, load_validated_contracts


APP_ID = "jushuitan.inventory.export_stock"
PROGRAM_ID = "jushuitan-inventory-export-stock"
PROGRAM_VERSION = "0.4.0"
REQUIREMENT_HASH = "sha256:615a2108edca13f072eff8c8e08120f93efdd34885aae0e425d838980b6680bb"

LOGIN_ACCOUNT = "jushuitan.erp.login.account_input"
LOGIN_PASSWORD_INPUT = "jushuitan.erp.login.password_input"
LOGIN_AGREEMENT = "jushuitan.erp.login.agreement_checkbox"
LOGIN_SUBMIT = "jushuitan.erp.login.submit_button"
LOGIN_NOTICE = "jushuitan.erp.login.password_notice_confirm"
SESSION_MARKER = "jushuitan.erp.shell.authenticated_marker"
IDENTITY_SURFACE = "jushuitan.erp.shell.account_identity_surface"


class ApplicationStateError(RuntimeError):
    """The live page cannot prove the configured account state."""

    error_code = "application_state_invalid"


def _element(context: ExecutionContext, element_id: str) -> ElementSpec:
    catalog = context.services.get("elements")
    if not isinstance(catalog, Mapping):
        raise RuntimeError("execution context elements service is missing")
    element = catalog.get(element_id)
    if not isinstance(element, ElementSpec):
        raise RuntimeError(f"execution context element is missing: {element_id}")
    return element


def _normalized_secret(value: object) -> str:
    revealed = value.reveal() if isinstance(value, SecretValue) else value
    if not isinstance(revealed, str) or not revealed.strip():
        raise ValueError("expected account identity must be one non-empty string")
    return " ".join(unicodedata.normalize("NFKC", revealed).casefold().split())


def _identity_matches(page_text: str, expected_identity: object) -> bool:
    normalized_page = " ".join(
        unicodedata.normalize("NFKC", page_text).casefold().split()
    )
    return _normalized_secret(expected_identity) in normalized_page


def _capture(context: ExecutionContext, name: str) -> None:
    try:
        context.browser.screenshot(name=name)
    except Exception:
        pass


def _store(context: ExecutionContext) -> StoreConfig:
    value = context.metadata.get("store_config")
    if not isinstance(value, StoreConfig):
        raise TypeError("execution context metadata must contain StoreConfig")
    return value


def _credentials(context: ExecutionContext) -> LoginCredentials:
    value = context.metadata.get("login_credentials")
    if not isinstance(value, LoginCredentials):
        raise TypeError("execution context metadata must contain LoginCredentials")
    return value


def _ensure_target_session(context: ExecutionContext) -> Mapping[str, object]:
    """Open the stable login URL and prove the resulting account identity."""

    store = _store(context)
    credentials = _credentials(context)
    browser = context.browser
    marker = _element(context, SESSION_MARKER)
    try:
        browser.open(store.login_url, wait="complete")
        context.ensure_step_within_deadline()
        authenticated = browser.exists(marker, timeout=3.0)
        login_performed = not authenticated
        if login_performed:
            browser.input(_element(context, LOGIN_ACCOUNT), credentials.username)
            browser.input(_element(context, LOGIN_PASSWORD_INPUT), credentials.password)
            browser.click(_element(context, LOGIN_AGREEMENT))
            browser.click(_element(context, LOGIN_SUBMIT))
            context.ensure_step_within_deadline()
            notice = _element(context, LOGIN_NOTICE)
            if browser.exists(notice, timeout=8.0):
                browser.click(notice)
            authenticated = browser.exists(marker, timeout=15.0)

        expected_identity = credentials.expected_identity or credentials.username
        identity_verified = authenticated and _identity_matches(
            browser.text(_element(context, IDENTITY_SURFACE)),
            expected_identity,
        )
        result = {
            "authenticated": authenticated,
            "identity_verified": identity_verified,
            "login_performed": login_performed,
            "human_verification_required": not authenticated,
        }
        if not authenticated:
            _capture(context, "account-session-unavailable.png")
            raise ApplicationStateError("target account session is unavailable")
        if not identity_verified:
            _capture(context, "account-identity-mismatch.png")
            raise ApplicationStateError("current account identity does not match")
        return result
    except Exception:
        _capture(context, "account-session-error.png")
        raise


class InventoryExportProgram(BaseProgram):
    def prepare_is_satisfied(self, context: ExecutionContext) -> bool:
        """Keep an adopted browser on its current page only for the target account."""

        try:
            credentials = _credentials(context)
            marker = _element(context, SESSION_MARKER)
            surface = _element(context, IDENTITY_SURFACE)
        except (TypeError, RuntimeError):
            return False
        if not context.browser.exists(marker, timeout=0.0):
            return False
        expected_identity = credentials.expected_identity or credentials.username
        return _identity_matches(context.browser.text(surface), expected_identity)

    def prepare(self, context: ExecutionContext) -> None:
        context.metadata["prepare_result"] = dict(_ensure_target_session(context))

    def verify(self, context: ExecutionContext) -> bool:
        result = context.outputs.get("S005")
        return self.step("S005").verify(context, result)


def build_program(requirement_hash: str = REQUIREMENT_HASH) -> InventoryExportProgram:
    return InventoryExportProgram(
        ProgramSpec(
            app_id=APP_ID,
            program_id=PROGRAM_ID,
            version=PROGRAM_VERSION,
            requirement_hash=requirement_hash,
            name="聚水潭库存导出",
        ),
        build_steps(),
    )


def bind_program_inputs(
    context: ExecutionContext,
    store: StoreConfig,
    credentials: LoginCredentials,
    *,
    export_filename: str = "inventory-export.xlsx",
) -> None:
    context.metadata["store_config"] = store
    context.metadata["login_credentials"] = credentials
    context.metadata["export_filename"] = export_filename


def load_runtime_options(
    account: str,
    checkpoint: Mapping[str, Any] | None,
) -> RuntimeOptions:
    del checkpoint
    manifest, _ = load_validated_contracts(APP_DIR)
    if manifest.requirement_hash != REQUIREMENT_HASH:
        raise ConfigurationError("program requirement hash does not match app manifest")
    store = load_store_config(APP_DIR / "config" / "stores.local.toml", account)
    if store.uses_placeholder_values:
        raise ConfigurationError("local store placeholders must be replaced")
    environment = dict(os.environ)
    load_local_env(APP_DIR / ".env", environment)
    credentials = load_login_credentials(store, environment)
    profile_dir = (APP_DIR / store.profile_directory).resolve(strict=False)
    try:
        profile_dir.relative_to((APP_DIR / "profiles").resolve(strict=False))
    except ValueError as error:
        raise ConfigurationError("profile directory must stay under profiles") from error
    return RuntimeOptions(
        account_id=store.account_id,
        profile_dir=profile_dir,
        debug_port=store.debug_port,
        metadata={
            "store_config": store,
            "login_credentials": credentials,
            "export_filename": "inventory-export.xlsx",
        },
    )


def additional_blockers() -> tuple[str, ...]:
    blockers: list[str] = []
    try:
        _, spec = load_validated_contracts(APP_DIR)
        blockers.extend(spec.blocking_item_ids)
    except Exception:
        return ("PC-APPLICATION-CONTRACT",)
    try:
        store = load_store_config(
            APP_DIR / "config" / "stores.local.toml",
            "STORE_001",
        )
        if store.uses_placeholder_values:
            blockers.append("PC-LOCAL-STORE-CONFIG")
        environment = dict(os.environ)
        load_local_env(APP_DIR / ".env", environment)
        load_login_credentials(store, environment)
    except ConfigurationError:
        blockers.append("PC-LOCAL-RUNTIME-CONFIG")
    return tuple(dict.fromkeys(blockers))


def verify_element_stages(
    context: ExecutionContext,
    entries: Mapping[str, ElementEntry],
) -> Mapping[str, object]:
    """Navigate the read-only stages and evaluate every declared expectation."""

    program = build_program()
    checks = []
    reached: list[str] = []
    skipped: list[str] = []
    navigation_failure: dict[str, object] | None = None

    def sweep(stage: str) -> None:
        checks.extend(check_element_expectations(context.browser, entries, stage=stage))
        reached.append(stage)

    store = _store(context)
    context.browser.open(store.login_url, wait="complete")
    if context.browser.exists(_element(context, SESSION_MARKER), timeout=3.0):
        skipped.append("login_page")
    else:
        sweep("login_page")
    program.prepare(context)
    sweep("session")

    for step in program.steps:
        if step.spec.step_id == "S005":
            continue
        context.current_step_id = step.spec.step_id
        try:
            result = step.execute(context)
            sweep(step.spec.step_id)
            if not step.verify(context, result):
                navigation_failure = {
                    "step_id": step.spec.step_id,
                    "phase": "verify",
                    "error_code": "step_verification_failed",
                }
                break
        except Exception as error:
            navigation_failure = {
                "step_id": step.spec.step_id,
                "phase": "execute",
                "exception_type": type(error).__name__,
                "error_code": getattr(error, "error_code", None),
                "message": str(error)[:200],
            }
            break

    declared_stages = {entry.check_at for entry in entries.values()}
    unreached = sorted(declared_stages - set(reached) - set(skipped))
    failures = [item for item in checks if not item.ok]
    evidence = context.browser.screenshot(name="verify-elements.png")
    return {
        "ok": not failures and not unreached and navigation_failure is None,
        "reached_stages": reached,
        "skipped_stages": skipped,
        "unreached_stages": unreached,
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
        "failed_element_ids": [item.element_id for item in failures],
        "weak_element_ids": [
            item.element_id for item in checks if item.ok and item.weak
        ],
        "evidence_path": str(evidence.path),
    }


def build_counterexample_context(
    step: Step,
    case: Counterexample,
    temporary_root: Path,
) -> ExecutionContext:
    """Build the deterministic fake page used by the framework test command."""

    state = case.state
    entries = element_entries()
    hidden = set(state.hidden)
    visible = set(entries) - hidden
    step_id = str(getattr(step.spec, "step_id", "step"))
    case_id = sha256(case.label.encode("utf-8")).hexdigest()[:12]
    run_dir = temporary_root / f"{step_id}-{case_id}"
    downloads = (
        {EXPORT_OPTION: FakeDownload("inventory-export.xlsx", b"fake inventory workbook\n")}
        if state.downloads_available and EXPORT_OPTION not in hidden
        else {}
    )
    counts = {
        key: value for key, value in state.counts.items() if key not in hidden
    }
    if RESULT_ROW not in hidden:
        counts.setdefault(RESULT_ROW, 1)
    text_lists = {
        key: tuple(value) for key, value in state.texts.items() if key not in hidden
    }
    if BRAND_SELECTED not in hidden:
        text_lists.setdefault(BRAND_SELECTED, ("BRAND_001",))
    text_values = (
        {IDENTITY_SURFACE: "fixture-user"}
        if IDENTITY_SURFACE not in hidden
        else {}
    )
    browser = FakeBrowserActions(
        run_dir=run_dir,
        visible_element_ids=visible,
        downloads=downloads,
        text_values=text_values,
        counts=counts,
        text_lists=text_lists,
    )
    context = ExecutionContext(
        app_id=APP_ID,
        program_id=PROGRAM_ID,
        program_version=PROGRAM_VERSION,
        requirement_hash=REQUIREMENT_HASH,
        run_id="counterexample",
        account_id="STORE_001",
        mode=RunMode.PREVIEW,
        run_dir=run_dir,
        services={"browser": browser, "elements": element_specs(entries)},
        metadata={
            "app_dir": str(temporary_root),
            "store_config": StoreConfig(
                account_id="STORE_001",
                platform="jushuitan",
                login_url="https://www.erp321.com/login.aspx",
                profile_directory="profiles/STORE_001",
                debug_port=9301,
                brand_value="BRAND_001",
                username_env="RPA_STORE_001_USERNAME",
                password_env="RPA_STORE_001_PASSWORD",
                identity_env="RPA_STORE_001_IDENTITY",
            ),
            "login_credentials": LoginCredentials(
                SecretValue("fixture-user", label="fixture-user"),
                SecretValue("fixture-secret", label="fixture-secret"),
                SecretValue("fixture-user", label="fixture-identity"),
            ),
            "export_filename": "inventory-export.xlsx",
            **dict(case.metadata),
        },
    )
    return context


APPLICATION = ApplicationDefinition(
    app_dir=APP_DIR,
    build_program=build_program,
    load_runtime_options=load_runtime_options,
    element_blocker_ids={},
    additional_blockers=additional_blockers,
    verify_element_stages=verify_element_stages,
    build_counterexample_context=build_counterexample_context,
)


__all__ = [
    "APPLICATION",
    "APP_ID",
    "ApplicationStateError",
    "InventoryExportProgram",
    "PROGRAM_ID",
    "PROGRAM_VERSION",
    "REQUIREMENT_HASH",
    "additional_blockers",
    "bind_program_inputs",
    "build_counterexample_context",
    "build_program",
    "load_runtime_options",
    "verify_element_stages",
]
