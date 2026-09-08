"""S000-S005 inventory export program."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path

from rpa_core.browser import ElementSpec, FakeBrowserActions, FakeDownload, SecretValue
from rpa_core.cli import ApplicationDefinition, RunRequest, RuntimeOptions
from rpa_core.contracts import RunMode
from rpa_core.downloads import resolve_download_directory
from rpa_core.elements import ElementEntry, check_element_expectations, element_specs
from rpa_core.runtime import BaseProgram, ExecutionContext, ProgramSpec, Step, StepSpec
from rpa_core.verification import Counterexample, FakeState

from .elements import element_entries
from .models import (
    ConfigurationError,
    LoginCredentials,
    StoreConfig,
    load_local_env,
    load_login_credentials,
    load_store_config,
)
from .steps import BRAND_SELECTED, EXPORT_MENU, EXPORT_OPTION, RESULT_ROW, build_steps

APP_DIR = Path(__file__).resolve().parents[2]
APP_ID = "jushuitan.inventory.export_stock"
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
    """Open the stable login URL and confirm an authenticated session."""
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
        result = {
            "authenticated": authenticated,
            "identity_check_skipped": True,
            "login_performed": login_performed,
            "human_verification_required": not authenticated,
        }
        if not authenticated:
            _capture(context, "account-session-unavailable.png")
            raise ApplicationStateError("target account session is unavailable")
        return result
    except Exception:
        _capture(context, "account-session-error.png")
        raise


def _missing_session_result(context, result):
    result["authenticated"] = False


class EnsureSessionStep(Step):
    def execute(self, context):
        return _ensure_target_session(context)

    def verify(self, context, result):
        return (
            result.get("authenticated") is True
            and context.browser.exists(_element(context, SESSION_MARKER))
        )

    def counterexamples(self):
        yield Counterexample(
            "登录结果未确认会话", after_execute=_missing_session_result
        )
        yield Counterexample(
            "登录后仍没有会话",
            FakeState(hidden=(SESSION_MARKER,)),
            expected_error=ApplicationStateError,
        )


def build_program() -> BaseProgram:
    return BaseProgram(
        ProgramSpec(app_id=APP_ID, name="聚水潭库存导出"),
        (
            EnsureSessionStep(StepSpec("S000", "登录并确认目标账号", 75.0)),
            *build_steps(),
        ),
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
    context.inputs.update(
        brand_value=store.brand_value, export_filename=export_filename
    )


def load_runtime_options(request: RunRequest) -> RuntimeOptions:
    if set(request.inputs) - {"brand_value", "export_filename"}:
        raise ConfigurationError("supported inputs: brand_value, export_filename")
    if set(request.credentials) - {"username", "password", "expected_identity"}:
        raise ConfigurationError("supported credentials: username, password, expected_identity")
    brand = request.inputs.get("brand_value")
    if "brand_value" in request.inputs and (not isinstance(brand, str) or not brand.strip()):
        raise ConfigurationError("brand_value must be a non-empty string")
    filename = request.inputs.get("export_filename", "inventory-export.xlsx")
    if not isinstance(filename, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,254}", filename):
        raise ConfigurationError("export_filename must be an ASCII basename")
    store = load_store_config(
        APP_DIR / "config" / "stores.local.toml", request.account_id,
        {"brand_value": brand} if brand is not None else {},
    )
    if store.uses_placeholder_values:
        raise ConfigurationError("local store placeholders must be replaced")
    environment = dict(os.environ)
    load_local_env(APP_DIR / ".env", environment)
    credential_fields = {
        "username": store.username_env, "password": store.password_env,
        "expected_identity": store.identity_env or f"RPA_{request.account_id}_IDENTITY",
    }
    for name, value in request.credentials.items():
        environment[credential_fields[name]] = value
    if "expected_identity" in request.credentials:
        store = replace(store, identity_env=credential_fields["expected_identity"])
    credentials = load_login_credentials(store, environment)
    profile_dir = (APP_DIR / store.profile_directory).resolve(strict=False)
    try:
        profile_dir.relative_to((APP_DIR / "profiles").resolve(strict=False))
    except ValueError as error:
        raise ConfigurationError(
            "profile directory must stay under profiles"
        ) from error
    return RuntimeOptions(
        account_id=store.account_id,
        profile_dir=profile_dir,
        download_dir=resolve_download_directory(APP_DIR, request.download_dir or store.download_directory),
        debug_port=store.debug_port,
        inputs={
            "brand_value": store.brand_value,
            "export_filename": filename,
        },
        metadata={
            "store_config": store,
            "login_credentials": credentials,
        },
    )


def verify_element_stages(
    context: ExecutionContext, entries: Mapping[str, ElementEntry]
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
    session = program.step("S000")
    result = session.execute(context)
    if not session.verify(context, result):
        raise ApplicationStateError("account verification failed")
    sweep("session")
    for step in program.steps:
        if step.spec.step_id in ("S000", "S005"):
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
        "ok": not failures and (not unreached) and (navigation_failure is None),
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


def build_test_context(
    step: Step, case: Counterexample | None, temporary_root: Path
) -> ExecutionContext:
    """Build the deterministic fake page used by the framework test command."""
    state = case.state if case is not None else FakeState()
    entries = element_entries()
    hidden = set(state.hidden)
    visible = set(entries) - hidden - {EXPORT_OPTION}
    run_dir = temporary_root / "runs" / "test-run"
    downloads = (
        {
            EXPORT_OPTION: FakeDownload(
                "inventory-export.xlsx", b"fake inventory workbook\n"
            )
        }
        if state.downloads_available and EXPORT_OPTION not in hidden
        else {}
    )
    counts = {key: value for (key, value) in state.counts.items() if key not in hidden}
    if RESULT_ROW not in hidden:
        counts.setdefault(RESULT_ROW, 1)
    text_lists = {
        key: tuple(value) for (key, value) in state.texts.items() if key not in hidden
    }
    if BRAND_SELECTED not in hidden:
        text_lists.setdefault(BRAND_SELECTED, ("BRAND_001",))
    text_values = (
        {IDENTITY_SURFACE: "fixture-user"} if IDENTITY_SURFACE not in hidden else {}
    )

    class InventoryTestBrowser(FakeBrowserActions):
        def click(self, element):
            super().click(element)
            if element.id == EXPORT_MENU and EXPORT_OPTION not in hidden:
                self._visible = self._visible | {EXPORT_OPTION}

    browser = InventoryTestBrowser(
        run_dir=run_dir,
        visible_element_ids=visible,
        downloads=downloads,
        text_values=text_values,
        counts=counts,
        text_lists=text_lists,
        download_dir=temporary_root / "downloads",
    )
    context = ExecutionContext(
        app_id=APP_ID,
        run_id="test-run",
        account_id="STORE_001",
        mode=RunMode.PREVIEW,
        run_dir=run_dir,
        services={"browser": browser, "elements": element_specs(entries)},
        inputs={"brand_value": "BRAND_001", "export_filename": "inventory-export.xlsx"},
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
            **(dict(case.metadata) if case else {}),
        },
        download_dir=temporary_root / "downloads",
    )
    return context


APPLICATION = ApplicationDefinition(
    app_dir=APP_DIR,
    build_program=build_program,
    load_runtime_options=load_runtime_options,
    verify_element_stages=verify_element_stages,
    build_test_context=build_test_context,
)
