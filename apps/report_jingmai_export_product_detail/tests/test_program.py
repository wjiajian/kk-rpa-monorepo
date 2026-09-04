from __future__ import annotations

from datetime import datetime
from pathlib import Path

from rpa_core.browser import FakeBrowserActions, FakeDownload, SecretValue
from rpa_core.cli import ApplicationDefinition, collect_blockers, main
from rpa_core.contracts import ResumePolicy, RunMode, SideEffect
from rpa_core.discovery import validate_application_in_repository
from rpa_core.elements import element_specs, load_element_catalog
from rpa_core.requirements import (
    compute_requirement_hash,
    load_app_manifest,
    load_requirement_memory,
)
from rpa_core.runtime import ExecutionContext, Runner
from rpa_core.verification import Counterexample, FakeState, assert_steps_are_falsifiable

from report_jingmai_export_product_detail.program import (
    ACCOUNT_IDENTITY,
    APP_DIR,
    APP_ID,
    AUTHENTICATED_MARKER,
    CALENDAR_MONTH,
    DATE_VALUES,
    DIALOG_REPORT_NAME,
    DOWNLOADS_PAGE,
    ELEMENT_BLOCKER_IDS,
    LOGIN_URL,
    LOGIN_PASSWORD_INPUT,
    LOGIN_SUBMIT_BUTTON,
    LOGIN_USERNAME_INPUT,
    MATCHING_DOWNLOAD_BUTTON,
    PRODUCT_DETAIL_ENTRY,
    PROGRAM_ID,
    PROGRAM_VERSION,
    REPORT_NAMES,
    REPORT_ROW_DATES,
    REPORT_ROWS,
    REPORT_STATUSES,
    REQUIREMENT_HASH,
    VIEW_EXPORTS_BUTTON,
    build_program,
    expected_dialog_name,
    expected_report_filename,
    target_date_from_checkpoint,
    verify_element_stages,
)


TARGET_DATE = "2026-09-03"
EXPECTED_IDENTITY = "ACCOUNT_ALIAS_001"


def _entries():
    return load_element_catalog(APP_DIR / "elements.toml")


def _context(
    tmp_path: Path,
    case: Counterexample | None = None,
    *,
    run_id: str = "run-test",
) -> ExecutionContext:
    state = case.state if case is not None else FakeState()
    entries = _entries()
    visible = set(entries) - set(state.hidden)
    text_lists = {
        ACCOUNT_IDENTITY: (EXPECTED_IDENTITY,),
        DATE_VALUES: (f"{TARGET_DATE}  至  {TARGET_DATE}",),
        CALENDAR_MONTH: (TARGET_DATE[:7],),
        DIALOG_REPORT_NAME: (
            "数据将采用离线任务的方式下载，"
            f"报表【{expected_dialog_name(TARGET_DATE)}】已生成，"
            "您可以前往我的报表查看。",
        ),
        REPORT_NAMES: (expected_report_filename(TARGET_DATE),),
        REPORT_ROW_DATES: (TARGET_DATE, TARGET_DATE),
        REPORT_STATUSES: ("已生成",),
    }
    for hidden in state.hidden:
        text_lists.pop(hidden, None)
    text_lists.update({key: tuple(value) for key, value in state.texts.items()})
    counts = {REPORT_ROWS: 2}
    for hidden in state.hidden:
        counts.pop(hidden, None)
    counts.update(state.counts)
    downloads = (
        {
            MATCHING_DOWNLOAD_BUTTON: FakeDownload(
                "source.xlsx",
                b"PK\x03\x04deterministic fake workbook",
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
    app_dir = tmp_path
    run_dir = app_dir / "runs" / run_id
    browser = FakeBrowserActions(
        run_dir=run_dir,
        visible_element_ids=visible,
        counts=counts,
        text_lists=text_lists,
        downloads=downloads,
        new_tab_urls=new_tabs,
    )
    metadata = {
        "app_dir": str(app_dir),
        "target_date": TARGET_DATE,
        "expected_identity": SecretValue(
            EXPECTED_IDENTITY,
            label="STORE_001.expected_identity",
        ),
        "login_username": SecretValue(
            "LOGIN_ALIAS_001",
            label="STORE_001.username",
        ),
        "login_password": SecretValue(
            "LOGIN_SECRET_001",
            label="STORE_001.password",
        ),
        "read_only_export_account": True,
    }
    if case is not None:
        metadata.update(case.metadata)
    return ExecutionContext(
        app_id=APP_ID,
        program_id=PROGRAM_ID,
        program_version=PROGRAM_VERSION,
        requirement_hash=REQUIREMENT_HASH,
        run_id=run_id,
        account_id="STORE_001",
        mode=RunMode.PREVIEW,
        run_dir=run_dir,
        services={"browser": browser, "elements": element_specs(entries)},
        metadata=metadata,
    )


def test_complete_fake_flow_reads_back_state_and_downloads(tmp_path: Path) -> None:
    context = _context(tmp_path, run_id="run-complete")
    result = Runner(sleep=lambda _: None).run(build_program(), context)

    assert result.status == "succeeded"
    assert result.completed_steps == ("S001", "S002", "S003", "S004", "S005", "S006")
    artifact = Path(result.outputs["S006"]["download_path"])
    assert artifact.is_file()
    assert artifact.parent == context.run_dir / "downloads"
    assert result.outputs["S006"]["target_date"] == TARGET_DATE

    actions = [record.action for record in context.browser.actions]
    assert actions.count("switch_new_tab") == 2
    assert actions.index("switch_new_tab") < actions.index("download")
    assert actions.count("select") == 0


def test_requirement_hash_matches_manifest_and_program() -> None:
    requirement = load_requirement_memory(APP_DIR / "requirement.md")
    manifest = load_app_manifest(APP_DIR / "app.toml")

    assert compute_requirement_hash(requirement) == REQUIREMENT_HASH
    assert requirement.source.requirement_hash == REQUIREMENT_HASH
    assert manifest.requirement_hash == REQUIREMENT_HASH


def test_repository_gate_accepts_compact_application() -> None:
    report = validate_application_in_repository(APP_DIR)

    assert report.ok
    assert report.issues == []


def test_stage_verifier_checks_every_catalog_entry(tmp_path: Path) -> None:
    context = _context(tmp_path, run_id="verify-elements")

    result = verify_element_stages(context, _entries())

    assert result["ok"] is True
    assert result["unreached_stages"] == []
    assert result["skipped_stages"] == ["S001-login-page"]
    assert result["navigation_failure"] is None
    assert len(result["checks"]) == 23
    assert len(_entries()) == 26
    assert result["failed_element_ids"] == []
    assert result["export_task_attempted"] is True
    assert Path(result["evidence_path"]).is_file()


def test_s001_logs_in_with_redacted_credentials_when_session_is_missing(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path, run_id="login-transition")
    delegate = context.browser

    class LoginTransitionBrowser:
        def __init__(self) -> None:
            self.logged_in = False

        def __getattr__(self, name):
            return getattr(delegate, name)

        def exists(self, element, **kwargs):
            if element.id == AUTHENTICATED_MARKER and not self.logged_in:
                return False
            return delegate.exists(element, **kwargs)

        def click(self, element, **kwargs):
            delegate.click(element, **kwargs)
            if element.id == LOGIN_SUBMIT_BUTTON:
                self.logged_in = True

    context.services["browser"] = LoginTransitionBrowser()
    step = build_program().step("S001")

    result = step.execute(context)

    assert result["login_performed"] is True
    assert step.verify(context, result)
    assert delegate.current_url == LOGIN_URL
    inputs = [item for item in delegate.actions if item.action == "input"]
    assert [item.element_id for item in inputs] == [
        LOGIN_USERNAME_INPUT,
        LOGIN_PASSWORD_INPUT,
    ]
    assert all(item.detail == "<redacted>" for item in inputs)


def test_every_step_rejects_each_declared_counterexample(tmp_path: Path) -> None:
    program = build_program()

    assert_steps_are_falsifiable(
        program.steps,
        lambda _step, case: _context(tmp_path, case),
    )


def test_export_request_is_single_attempt_manual_write() -> None:
    spec = build_program().step("S004").spec

    assert spec.side_effect is SideEffect.WRITE
    assert spec.resume_policy is ResumePolicy.MANUAL
    assert spec.retry_policy.max_attempts == 1


def test_resume_keeps_original_target_date() -> None:
    checkpoint = {
        "created_at": "2026-09-04T01:00:00+00:00",
        "steps": {
            "S001": {
                "result": {"target_date": "2026-09-02"},
            }
        },
    }
    assert target_date_from_checkpoint(checkpoint) == "2026-09-02"

    fallback = {
        "created_at": "2026-09-04T01:00:00+00:00",
        "steps": {},
    }
    assert target_date_from_checkpoint(fallback) == "2026-09-03"
    assert target_date_from_checkpoint(
        None,
        now=datetime.fromisoformat("2026-09-04T09:00:00+08:00"),
    ) == "2026-09-03"


def test_run_fails_on_declared_blocker_before_runtime_and_run_directory(
    tmp_path: Path,
    capsys,
) -> None:
    (tmp_path / "elements.toml").write_text(
        (APP_DIR / "elements.toml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    def forbidden_runtime(*_args, **_kwargs):
        raise AssertionError("blocked run must not load runtime configuration")

    definition = ApplicationDefinition(
        app_dir=tmp_path,
        build_program=build_program,
        load_runtime_options=forbidden_runtime,
        element_blocker_ids=ELEMENT_BLOCKER_IDS,
        additional_blockers=lambda: ("PC-READONLY-ACCOUNT",),
    )

    assert main(definition, ["run", "--yes"]) == 2
    assert not (tmp_path / "runs").exists()
    output = capsys.readouterr().out
    assert "PC-READONLY-ACCOUNT" in output
    assert '"real_browser_launched": false' in output


def test_resolved_elements_add_no_catalog_blockers() -> None:
    blockers = collect_blockers(
        ApplicationDefinition(
            app_dir=APP_DIR,
            build_program=build_program,
            load_runtime_options=lambda *_: (_ for _ in ()).throw(AssertionError()),
            element_blocker_ids=ELEMENT_BLOCKER_IDS,
            additional_blockers=lambda: (),
        )
    )

    assert not set(ELEMENT_BLOCKER_IDS.values()).intersection(blockers)
    assert blockers == ()
