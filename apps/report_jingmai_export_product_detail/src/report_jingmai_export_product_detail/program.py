"""S001-S006 Jingmai product-detail export flow."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import tomllib
from rpa_core.browser import (
    DownloadError,
    ElementLookupError,
    ElementSpec,
    FakeBrowserActions,
    FakeDownload,
    NavigationError,
    SecretValue,
)
from rpa_core.cli import ApplicationDefinition, RunRequest, RuntimeOptions
from rpa_core.contracts import RunMode
from rpa_core.downloads import download_result_is_valid, resolve_download_directory
from rpa_core.elements import (
    ElementEntry,
    check_element_expectations,
    element_specs,
    load_element_catalog,
)
from rpa_core.runtime import BaseProgram, ExecutionContext, ProgramSpec, Step, StepSpec
from rpa_core.verification import Counterexample, FakeState

APP_ID = "jingmai.reports.export_product_detail"
APP_DIR = Path(__file__).resolve().parents[2]
HOME_URL = "https://shop.jd.com/jdm/home"
LOGIN_URL = "https://passport.shop.jd.com/login/index.action"
REPORT_URL = "https://jdsz.jd.com/szweb/view/reports-center/recommend-report-temp.html"
SHANGHAI = ZoneInfo("Asia/Shanghai")
AUTHENTICATED_MARKER = "jingmai.shell.authenticated_marker"
ACCOUNT_IDENTITY = "jingmai.shell.account_identity_surface"
LOGIN_USERNAME_INPUT = "jingmai.login.username_input"
LOGIN_PASSWORD_INPUT = "jingmai.login.password_input"
LOGIN_SUBMIT_BUTTON = "jingmai.login.submit_button"
PRODUCT_DETAIL_ENTRY = "jdsz.reports.product_detail_entry"
PRODUCT_DETAIL_PAGE = "jdsz.product_detail.page_marker"
START_DATE_INPUT = "jdsz.product_detail.start_date_input"
END_DATE_INPUT = "jdsz.product_detail.end_date_input"
DATE_VALUES = "jdsz.product_detail.date_values"
REPORT_ROWS = "jdsz.product_detail.report_rows"
REPORT_ROW_DATES = "jdsz.product_detail.report_row_dates"
CALENDAR_MONTH = "jdsz.product_detail.calendar_month"
CALENDAR_PREVIOUS_MONTH = "jdsz.product_detail.calendar_previous_month"
CALENDAR_NEXT_MONTH = "jdsz.product_detail.calendar_next_month"
DOWNLOAD_REPORT_BUTTON = "jdsz.product_detail.download_report_button"
EXPORT_READY_DIALOG = "jdsz.product_detail.export_ready_dialog"
DIALOG_REPORT_NAME = "jdsz.product_detail.dialog_report_name"
VIEW_EXPORTS_BUTTON = "jdsz.product_detail.view_exports_button"
DOWNLOADS_PAGE = "jdsz.downloads.page_marker"
REFRESH_REPORTS_BUTTON = "jdsz.downloads.refresh_button"
REPORT_SEARCH_INPUT = "jdsz.downloads.search_input"
REPORT_SEARCH_BUTTON = "jdsz.downloads.search_button"
REPORT_NAMES = "jdsz.downloads.report_names"
REPORT_STATUSES = "jdsz.downloads.report_statuses"
MATCHING_DOWNLOAD_BUTTON = "jdsz.downloads.first_matching_download_button"


class ApplicationStateError(RuntimeError):
    error_code = "application_state_invalid"


class ReportNotReadyError(ApplicationStateError):
    error_code = "report_not_ready"


class LocalConfigurationError(RuntimeError):
    error_code = "local_configuration_invalid"


class ManualLoginVerificationRequired(ApplicationStateError):
    error_code = "manual_login_verification_required"


def expected_dialog_name(target_date: str) -> str:
    return f"经营状况-商品明细报表-{target_date}-{target_date}-全部-全部-汇总展示"


def expected_report_filename(target_date: str) -> str:
    return f"经营状况-商品明细日报-{target_date}-全部-全部-汇总-SKU.xlsx"


def local_download_filename(target_date: str) -> str:
    return f"jingmai-product-detail-{target_date}.xlsx"


def target_date_for_run(*, now: datetime | None = None) -> str:
    current = now or datetime.now(SHANGHAI)
    if current.tzinfo is None:
        current = current.replace(tzinfo=SHANGHAI)
    return (current.astimezone(SHANGHAI).date() - timedelta(days=1)).isoformat()


class EnsureSessionStep(Step):
    def __init__(self) -> None:
        super().__init__(
            StepSpec(
                step_id="S001", name="登录并确认京麦会话", timeout_seconds=75.0
            )
        )

    def execute(self, context: ExecutionContext) -> Mapping[str, object]:
        return _ensure_target_session(context)

    def verify(self, context: ExecutionContext, result: Any) -> bool:
        return (
            isinstance(result, Mapping)
            and result.get("target_date") == _target_date(context)
            and context.browser.exists(_element(context, AUTHENTICATED_MARKER))
            and result.get("authenticated") is True
        )

    def counterexamples(self) -> Iterable[Counterexample]:
        yield Counterexample(
            "未登录且登录表单不可用",
            FakeState(
                hidden=(AUTHENTICATED_MARKER, ACCOUNT_IDENTITY, LOGIN_USERNAME_INPUT)
            ),
            expected_error=ApplicationStateError,
        )
        yield Counterexample(
            "提交登录后仍未建立会话",
            FakeState(hidden=(AUTHENTICATED_MARKER, ACCOUNT_IDENTITY)),
            expected_error=ManualLoginVerificationRequired,
        )
        yield Counterexample(
            "登录结果未确认会话", after_execute=lambda context, result: result.update(authenticated=False)
        )


class OpenProductDetailStep(Step):
    def __init__(self) -> None:
        super().__init__(
            StepSpec(
                step_id="S002", name="打开经营状况商品明细报表", timeout_seconds=45.0
            )
        )

    def execute(self, context: ExecutionContext) -> Mapping[str, object]:
        entry = _open_product_detail_entry(context)
        return _activate_product_detail(context, entry)

    def verify(self, context: ExecutionContext, result: Any) -> bool:
        return (
            isinstance(result, Mapping)
            and result.get("target_date") == _target_date(context)
            and (context.browser.count(_element(context, PRODUCT_DETAIL_PAGE)) == 1)
        )

    def counterexamples(self) -> Iterable[Counterexample]:
        yield Counterexample(
            "查看详情入口不存在",
            FakeState(hidden=(PRODUCT_DETAIL_ENTRY,)),
            expected_error=ApplicationStateError,
        )
        yield Counterexample(
            "点击后未进入商品明细页", FakeState(counts={PRODUCT_DETAIL_PAGE: 0})
        )


class SelectReportDateStep(Step):
    def __init__(self) -> None:
        super().__init__(
            StepSpec(step_id="S003", name="选择目标统计日期", timeout_seconds=30.0)
        )

    def execute(self, context: ExecutionContext) -> Mapping[str, object]:
        target = _target_date(context)
        selected_dates = _selected_dates(context)
        if selected_dates != [target, target]:
            _select_target_date(context, target)
        return {
            "target_date": target,
            "selected_dates": _selected_dates(context),
            "row_count": context.browser.count(_element(context, REPORT_ROWS)),
            "row_dates": _texts(context, REPORT_ROW_DATES),
        }

    def verify(self, context: ExecutionContext, result: Any) -> bool:
        target = _target_date(context)
        row_dates = _texts(context, REPORT_ROW_DATES)
        return (
            isinstance(result, Mapping)
            and result.get("target_date") == target
            and (_selected_dates(context) == [target, target])
            and (context.browser.count(_element(context, REPORT_ROWS)) > 0)
            and bool(row_dates)
            and all((value == target for value in row_dates))
        )

    def counterexamples(self) -> Iterable[Counterexample]:
        yield Counterexample(
            "日期控件回读值不是昨日",
            FakeState(texts={DATE_VALUES: ("2099-01-01", "2099-01-01")}),
        )
        yield Counterexample(
            "昨日没有报表结果",
            FakeState(counts={REPORT_ROWS: 0}, texts={REPORT_ROW_DATES: ()}),
        )
        yield Counterexample(
            "结果行仍属于其他日期", FakeState(texts={REPORT_ROW_DATES: ("2099-01-01",)})
        )
        yield Counterexample(
            "组合日期控件不存在",
            FakeState(hidden=(START_DATE_INPUT, DATE_VALUES)),
            expected_error=ElementLookupError,
        )


class RequestExportStep(Step):
    def __init__(self) -> None:
        super().__init__(
            StepSpec(step_id="S004", name="生成商品明细导出任务", timeout_seconds=30.0)
        )

    def execute(self, context: ExecutionContext) -> Mapping[str, object]:
        context.browser.click(_element(context, DOWNLOAD_REPORT_BUTTON))
        target = _target_date(context)
        report_name = _dialog_report_name(_texts(context, DIALOG_REPORT_NAME))
        return {
            "target_date": target,
            "dialog_visible": context.browser.exists(
                _element(context, EXPORT_READY_DIALOG)
            ),
            "report_name": report_name,
        }

    def verify(self, context: ExecutionContext, result: Any) -> bool:
        target = _target_date(context)
        return (
            isinstance(result, Mapping)
            and result.get("target_date") == target
            and context.browser.exists(_element(context, EXPORT_READY_DIALOG))
            and (
                _dialog_report_name(_texts(context, DIALOG_REPORT_NAME))
                == expected_dialog_name(target)
            )
        )

    def counterexamples(self) -> Iterable[Counterexample]:
        yield Counterexample(
            "导出确认弹窗未出现", FakeState(hidden=(EXPORT_READY_DIALOG,))
        )
        yield Counterexample(
            "弹窗对应的是其他日期",
            FakeState(texts={DIALOG_REPORT_NAME: ("经营状况-商品明细报表-其他日期",)}),
        )
        yield Counterexample(
            "下载报表按钮不存在",
            FakeState(hidden=(DOWNLOAD_REPORT_BUTTON,)),
            expected_error=ElementLookupError,
        )


class OpenDownloadsStep(Step):
    def __init__(self) -> None:
        super().__init__(
            StepSpec(step_id="S005", name="打开报表下载页", timeout_seconds=30.0)
        )

    def execute(self, context: ExecutionContext) -> Mapping[str, object]:
        context.browser.click_and_switch_to_new_tab(
            _element(context, VIEW_EXPORTS_BUTTON), timeout=15.0
        )
        page_marker = _ready_element(
            context, DOWNLOADS_PAGE, error="downloads page is unavailable"
        )
        return {
            "target_date": _target_date(context),
            "downloads_opened": context.browser.count(page_marker) == 1,
        }

    def verify(self, context: ExecutionContext, result: Any) -> bool:
        return (
            isinstance(result, Mapping)
            and result.get("target_date") == _target_date(context)
            and (context.browser.count(_element(context, DOWNLOADS_PAGE)) == 1)
        )

    def counterexamples(self) -> Iterable[Counterexample]:
        yield Counterexample(
            "查看按钮没有打开新标签页",
            FakeState(new_tabs_available=False),
            expected_error=NavigationError,
        )
        yield Counterexample(
            "新标签页不是报表下载页", FakeState(counts={DOWNLOADS_PAGE: 0})
        )


def _empty_download(context, result):
    Path(result["download_path"]).write_bytes(b"")


class DownloadMatchingReportStep(Step):
    def __init__(self) -> None:
        super().__init__(
            StepSpec(
                step_id="S006", name="匹配并下载本次商品明细报表", timeout_seconds=300.0
            )
        )

    def execute(self, context: ExecutionContext) -> Mapping[str, object]:
        target = _target_date(context)
        expected = expected_report_filename(target)
        refresh = _ready_element(
            context, REFRESH_REPORTS_BUTTON, error="report download list is unavailable"
        )
        context.browser.click(refresh)
        context.browser.input(_element(context, REPORT_SEARCH_INPUT), expected)
        context.browser.click(_element(context, REPORT_SEARCH_BUTTON))
        (names, statuses) = _report_rows(context)
        if not names or names[0] != expected:
            raise ReportNotReadyError("first filtered row is not the target report")
        if not statuses or statuses[0] != "已生成":
            raise ReportNotReadyError("target report has not reached 已生成")
        reference = context.browser.download(
            _element(context, MATCHING_DOWNLOAD_BUTTON),
            filename=context.inputs.get("export_filename", local_download_filename(target)),
        )
        return {
            "target_date": target,
            "source_filename": expected,
            "download_path": str(reference.path),
            "sha256": reference.sha256,
            "size_bytes": reference.size_bytes,
            "status": reference.status,
        }

    def verify(self, context: ExecutionContext, result: Any) -> bool:
        if not isinstance(result, Mapping):
            return False
        target = _target_date(context)
        expected = expected_report_filename(target)
        (names, statuses) = _report_rows(context)
        ready = bool(
            names and statuses and (names[0] == expected) and (statuses[0] == "已生成")
        )
        return (
            result.get("target_date") == target
            and result.get("source_filename") == expected
            and ready
            and _download_result_is_valid(context, result)
        )

    def counterexamples(self) -> Iterable[Counterexample]:
        yield Counterexample("下载文件为空", after_execute=_empty_download)
        yield Counterexample(
            "筛选首行不是本次文件",
            FakeState(
                texts={
                    REPORT_NAMES: (
                        "过期报表.xlsx",
                        expected_report_filename("2099-01-01"),
                    ),
                    REPORT_STATUSES: ("已生成", "已生成"),
                }
            ),
            metadata={"target_date": "2099-01-01"},
            expected_error=ReportNotReadyError,
        )
        yield Counterexample(
            "本次报表仍在生成",
            FakeState(texts={REPORT_STATUSES: ("生成中",)}),
            expected_error=ReportNotReadyError,
        )
        yield Counterexample(
            "下载动作没有返回文件",
            FakeState(downloads_available=False),
            expected_error=DownloadError,
        )


def build_program() -> BaseProgram:
    return BaseProgram(
        ProgramSpec(app_id=APP_ID, name="京麦商品明细报表导出"),
        [
            EnsureSessionStep(),
            OpenProductDetailStep(),
            SelectReportDateStep(),
            RequestExportStep(),
            OpenDownloadsStep(),
            DownloadMatchingReportStep(),
        ],
    )


def verify_element_stages(
    context: ExecutionContext, entries: Mapping[str, ElementEntry]
) -> Mapping[str, object]:
    """Reach each declared page stage and check every live locator."""
    program = build_program()
    checks = []
    reached: list[str] = []
    skipped: list[str] = []
    navigation_failure: dict[str, object] | None = None
    export_attempted = False

    def sweep(stage: str) -> None:
        checks.extend(check_element_expectations(context.browser, entries, stage=stage))
        reached.append(stage)

    _target_date(context)
    declared_stages = {entry.check_at for entry in entries.values()}
    for step in program.steps:
        context.current_step_id = step.spec.step_id
        before_click_stage = f"{step.spec.step_id}-before-click"
        if step.spec.step_id == "S004":
            export_attempted = True
        try:
            if step.spec.step_id == "S001":
                login_page_checked = False

                def check_login_page() -> None:
                    nonlocal login_page_checked
                    sweep("S001-login-page")
                    login_page_checked = True

                result = _ensure_target_session(context, on_login_page=check_login_page)
                if not login_page_checked:
                    skipped.append("S001-login-page")
            elif step.spec.step_id == "S002":
                entry = _open_product_detail_entry(context)
                sweep(before_click_stage)
                result = _activate_product_detail(context, entry)
            else:
                if before_click_stage in declared_stages:
                    sweep(before_click_stage)
                result = step.execute(context)
            sweep(step.spec.step_id)
            if step.spec.step_id == "S003":
                context.browser.click(_element(context, START_DATE_INPUT))
                sweep("S003-date-picker-open")
                context.browser.click(_element(context, PRODUCT_DETAIL_PAGE))
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
        "export_task_attempted": export_attempted,
    }


def load_runtime_options(request: RunRequest) -> RuntimeOptions:
    account = request.account_id
    if not re.fullmatch("[A-Z][A-Z0-9_]{0,63}", account):
        raise LocalConfigurationError("account must be a stable uppercase alias")
    if set(request.inputs) - {"target_date", "export_filename"}:
        raise LocalConfigurationError("supported inputs: target_date, export_filename")
    if set(request.credentials) - {"username", "password", "expected_identity"}:
        raise LocalConfigurationError("supported credentials: username, password, expected_identity")
    target = request.inputs.get("target_date", target_date_for_run())
    if not isinstance(target, str) or not _is_iso_date(target):
        raise LocalConfigurationError("target_date must be YYYY-MM-DD")
    filename = request.inputs.get("export_filename", local_download_filename(target))
    if not isinstance(filename, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,254}", filename):
        raise LocalConfigurationError("export_filename must be an ASCII basename")
    store = _load_store(account)
    profile_dir = _safe_app_path(str(store.get("profile_directory", f"profiles/{account}")))
    (login_username, login_password) = _load_login_credentials(request.credentials)
    debug_port = store.get("debug_port", 0)
    if isinstance(debug_port, bool) or not isinstance(debug_port, int):
        raise LocalConfigurationError("debug_port must be an integer")
    if not 0 <= debug_port <= 65535:
        raise LocalConfigurationError("debug_port must be between 0 and 65535")
    raw_browser_path = store.get("browser_path")
    browser_path = None
    if raw_browser_path is not None:
        if not isinstance(raw_browser_path, str) or not raw_browser_path.strip():
            raise LocalConfigurationError("browser_path must be a non-empty path")
        browser_path = Path(raw_browser_path).expanduser()
    return RuntimeOptions(
        account_id=account,
        profile_dir=profile_dir,
        download_dir=resolve_download_directory(
            APP_DIR, request.download_dir or store.get("download_directory")
        ),
        debug_port=debug_port,
        browser_path=browser_path,
        inputs={"target_date": target, "export_filename": filename},
        metadata={
            "login_username": SecretValue(login_username, label=f"{account}.username"),
            "login_password": SecretValue(login_password, label=f"{account}.password"),
        },
    )


def _load_store(account: str) -> Mapping[str, Any]:
    path = APP_DIR / "config" / "stores.local.toml"
    if not path.exists():
        return {}
    try:
        document = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as error:
        raise LocalConfigurationError(
            "local store configuration is unavailable"
        ) from error
    stores = document.get("stores")
    if not isinstance(stores, Mapping):
        raise LocalConfigurationError("local configuration must define stores")
    store = stores.get(account, {})
    if not isinstance(store, Mapping):
        raise LocalConfigurationError(f"account alias is not configured: {account}")
    if store.get("platform", "jingmai") != "jingmai":
        raise LocalConfigurationError("store platform must be jingmai")
    return store


def _load_login_credentials(overrides: Mapping[str, str]) -> tuple[str, str]:
    path = APP_DIR / ".env"
    try:
        lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    except (OSError, UnicodeError) as error:
        raise LocalConfigurationError("application .env is unavailable") from error
    values: dict[str, str] = {}
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        (key, raw_value) = line.split("=", 1)
        value = raw_value.strip()
        if len(value) >= 2 and value[0] == value[-1] and (value[0] in {"'", '"'}):
            value = value[1:-1]
        values[key.strip()] = value
    username = overrides.get("username", values.get("username", ""))
    password = overrides.get("password", values.get("password", ""))
    if not username or not password:
        raise LocalConfigurationError(
            "provide non-empty username and password via credentials or .env"
        )
    return (username, password)


def _safe_app_path(raw: str) -> Path:
    candidate = Path(raw)
    if not raw.strip() or candidate.is_absolute() or ".." in candidate.parts:
        raise LocalConfigurationError(
            "profile_directory must stay inside the application"
        )
    resolved_app = APP_DIR.resolve()
    resolved = (APP_DIR / candidate).resolve()
    try:
        resolved.relative_to(resolved_app)
    except ValueError as error:
        raise LocalConfigurationError(
            "profile_directory escapes the application"
        ) from error
    return resolved


def _element(context: ExecutionContext, element_id: str) -> ElementSpec:
    catalog = context.services.get("elements")
    if not isinstance(catalog, Mapping):
        raise ApplicationStateError("element catalog is not bound")
    element = catalog.get(element_id)
    if not isinstance(element, ElementSpec):
        raise ApplicationStateError(f"element is not bound: {element_id}")
    return element


def _ready_element(
    context: ExecutionContext, element_id: str, *, error: str
) -> ElementSpec:
    element = _element(context, element_id)
    for _ in range(2):
        if context.browser.exists(element, timeout=10.0):
            return element
    raise ApplicationStateError(error)


def _ensure_target_session(
    context: ExecutionContext, *, on_login_page: Callable[[], None] | None = None
) -> Mapping[str, object]:
    context.browser.open(HOME_URL, wait="complete")
    authenticated = context.browser.exists(
        _element(context, AUTHENTICATED_MARKER), timeout=5.0
    )
    login_performed = False
    if not authenticated:
        context.browser.open(LOGIN_URL, wait="complete")
        username_input = _ready_element(
            context,
            LOGIN_USERNAME_INPUT,
            error="stable Jingmai login username input is unavailable",
        )
        password_input = _ready_element(
            context,
            LOGIN_PASSWORD_INPUT,
            error="stable Jingmai login password input is unavailable",
        )
        submit_button = _ready_element(
            context,
            LOGIN_SUBMIT_BUTTON,
            error="stable Jingmai login submit button is unavailable",
        )
        if on_login_page is not None:
            on_login_page()
        (username, password) = _login_credentials(context)
        context.browser.input(username_input, username)
        context.browser.input(password_input, password)
        context.browser.click(submit_button)
        login_performed = True
        authenticated = context.browser.exists(
            _element(context, AUTHENTICATED_MARKER), timeout=45.0
        )
        if not authenticated:
            evidence = context.browser.screenshot(
                name=f"login-manual-{context.run_id}.png"
            )
            raise ManualLoginVerificationRequired(
                f"login did not reach the authenticated page; resolve any CAPTCHA, slider, or SMS check before starting a new run (evidence: {evidence.path.name})"
            )
    return {
        "target_date": _target_date(context),
        "login_performed": login_performed,
        "authenticated": authenticated,
        "identity_check_skipped": True,
    }


def _login_credentials(context: ExecutionContext) -> tuple[SecretValue, SecretValue]:
    username = context.metadata.get("login_username")
    password_secret = context.metadata.get("login_password")
    if not isinstance(username, SecretValue) or not isinstance(
        password_secret, SecretValue
    ):
        raise LocalConfigurationError("login credentials are not bound securely")
    return (username, password_secret)


def _open_product_detail_entry(context: ExecutionContext) -> ElementSpec:
    context.browser.open(REPORT_URL, wait="complete")
    return _ready_element(
        context,
        PRODUCT_DETAIL_ENTRY,
        error="product-detail report entry is unavailable",
    )


def _activate_product_detail(
    context: ExecutionContext, entry: ElementSpec
) -> Mapping[str, object]:
    context.browser.click_and_switch_to_new_tab(entry, timeout=20.0)
    page_marker = _ready_element(
        context, PRODUCT_DETAIL_PAGE, error="product-detail page is unavailable"
    )
    return {
        "target_date": _target_date(context),
        "page_marker_count": context.browser.count(page_marker),
    }


def _texts(
    context: ExecutionContext, element_id: str, *, timeout: float = 0.0
) -> list[str]:
    return [
        item.strip()
        for item in context.browser.texts(
            _element(context, element_id), timeout=timeout
        )
        if item.strip()
    ]


def _report_rows(context: ExecutionContext) -> tuple[list[str], list[str]]:
    return (_texts(context, REPORT_NAMES), _texts(context, REPORT_STATUSES))


def _identities(context: ExecutionContext, *, timeout: float = 0.0) -> list[str]:
    return [
        " ".join(value.split()).casefold()
        for value in _texts(context, ACCOUNT_IDENTITY, timeout=timeout)
    ]


def _selected_dates(context: ExecutionContext) -> list[str]:
    values = _texts(context, DATE_VALUES)
    if len(values) != 1:
        return []
    return re.findall("\\b\\d{4}-\\d{2}-\\d{2}\\b", values[0])


def _select_target_date(context: ExecutionContext, target: str) -> None:
    context.browser.click(_element(context, START_DATE_INPUT))
    months = _texts(context, CALENDAR_MONTH)
    if len(months) != 1 or not re.fullmatch("\\d{4}-\\d{2}", months[0]):
        raise ApplicationStateError("calendar month is unavailable")
    displayed = date.fromisoformat(f"{months[0]}-01")
    desired = date.fromisoformat(f"{target[:7]}-01")
    month_delta = (desired.year - displayed.year) * 12 + desired.month - displayed.month
    direction = CALENDAR_NEXT_MONTH if month_delta > 0 else CALENDAR_PREVIOUS_MONTH
    for _ in range(abs(month_delta)):
        context.browser.click(_element(context, direction))
    if _texts(context, CALENDAR_MONTH) != [target[:7]]:
        raise ApplicationStateError("calendar did not reach target month")
    context.browser.select(_element(context, START_DATE_INPUT), target[-2:])


def _dialog_report_name(values: list[str]) -> str:
    if len(values) != 1:
        return ""
    match = re.search("报表【([^】]+)】已生成", values[0])
    return match.group(1).strip() if match else ""


def _target_date(context: ExecutionContext) -> str:
    value = context.inputs.get("target_date")
    if not isinstance(value, str) or not _is_iso_date(value):
        raise ApplicationStateError("inputs.target_date must be an ISO date")
    return value


def _is_iso_date(value: str) -> bool:
    try:
        return date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def _download_result_is_valid(
    context: ExecutionContext, result: Mapping[str, Any]
) -> bool:
    return download_result_is_valid(result, context.download_dir)


def build_test_context(
    step: Step, case: Counterexample | None, temporary_root: Path
) -> ExecutionContext:
    """Build the deterministic happy page with one counterexample applied."""
    state = case.state if case is not None else FakeState()
    target_date = "2026-09-03"
    expected_identity = "ACCOUNT_ALIAS_001"
    entries = load_element_catalog(APP_DIR / "elements.toml")
    visible = set(entries) - set(state.hidden)
    text_lists = {
        ACCOUNT_IDENTITY: (expected_identity,),
        DATE_VALUES: (f"{target_date}  至  {target_date}",),
        CALENDAR_MONTH: (target_date[:7],),
        DIALOG_REPORT_NAME: (
            f"数据将采用离线任务的方式下载，报表【{expected_dialog_name(target_date)}】已生成，您可以前往我的报表查看。",
        ),
        REPORT_NAMES: (expected_report_filename(target_date),),
        REPORT_ROW_DATES: (target_date, target_date),
        REPORT_STATUSES: ("已生成",),
    }
    for hidden in state.hidden:
        text_lists.pop(hidden, None)
    text_lists.update({key: tuple(value) for (key, value) in state.texts.items()})
    counts = {REPORT_ROWS: 2}
    for hidden in state.hidden:
        counts.pop(hidden, None)
    counts.update(state.counts)
    downloads = (
        {
            MATCHING_DOWNLOAD_BUTTON: FakeDownload(
                "source.xlsx", b"PK\x03\x04deterministic fake workbook"
            )
        }
        if state.downloads_available
        else {}
    )
    new_tabs = (
        {
            PRODUCT_DETAIL_ENTRY: "https://jdsz.jd.com/product-detail",
            VIEW_EXPORTS_BUTTON: "https://jdsz.jd.com/download-center",
        }
        if state.new_tabs_available
        else {}
    )
    run_id = "test-run"
    run_dir = temporary_root / "runs" / run_id
    browser = FakeBrowserActions(
        run_dir=run_dir,
        visible_element_ids=visible,
        counts=counts,
        text_lists=text_lists,
        downloads=downloads,
        new_tab_urls=new_tabs,
        download_dir=temporary_root / "downloads",
    )
    metadata = {
        "app_dir": str(temporary_root),
        "target_date": target_date,
        "expected_identity": SecretValue(
            expected_identity, label="STORE_001.expected_identity"
        ),
        "login_username": SecretValue("LOGIN_ALIAS_001", label="STORE_001.username"),
        "login_password": SecretValue("LOGIN_SECRET_001", label="STORE_001.password"),
        "read_only_export_account": True,
        **(dict(case.metadata) if case else {}),
    }
    target = metadata.pop("target_date")
    inputs = {"target_date": target, "export_filename": local_download_filename(target)}
    return ExecutionContext(
        app_id=APP_ID,
        run_id=run_id,
        account_id="STORE_001",
        mode=RunMode.PREVIEW,
        run_dir=run_dir,
        services={"browser": browser, "elements": element_specs(entries)},
        metadata=metadata,
        inputs=inputs,
        download_dir=temporary_root / "downloads",
    )


APPLICATION = ApplicationDefinition(
    app_dir=APP_DIR,
    build_program=build_program,
    load_runtime_options=load_runtime_options,
    verify_element_stages=verify_element_stages,
    build_test_context=build_test_context,
)
