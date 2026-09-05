import json
from pathlib import Path

import pytest
from report_jingmai_export_product_detail.program import (
    APPLICATION,
    build_program,
    build_test_context,
)
from rpa_core.runtime import Runner, StepRunError
from rpa_core.verification import (
    Counterexample,
    CounterexampleContractError,
    FakeState,
    assert_steps_are_falsifiable,
)


def context(tmp_path, case=None):
    return build_test_context(build_program().steps[0], case, tmp_path)


def test_complete_flow_downloads_to_configured_directory(tmp_path):
    ctx = context(tmp_path)
    result = Runner().run(build_program(), ctx)
    assert result.completed_steps == ("S001", "S002", "S003", "S004", "S005", "S006")
    assert result.status == "succeeded"
    artifact = Path(result.outputs["S006"]["download_path"])
    assert artifact.parent == ctx.download_dir
    assert artifact.stat().st_size > 0
    report = json.loads((ctx.run_dir / "result.json").read_text())
    assert report["status"] == "succeeded"
    assert not (ctx.run_dir / "checkpoint.json").exists()


def test_normal_and_bad_scenarios_use_the_same_fixture(tmp_path):
    serial = [0]

    def factory(step, case):
        serial[0] += 1
        return build_test_context(step, case, tmp_path / str(serial[0]))

    assert_steps_are_falsifiable(build_program().steps, factory)


@pytest.mark.parametrize("index", range(6))
def test_every_verifier_cannot_be_replaced_with_constant_true(tmp_path, index):
    step = build_program().steps[index]
    step.verify = lambda ctx, result: True
    with pytest.raises(CounterexampleContractError, match="did not fail"):
        assert_steps_are_falsifiable(
            [step], lambda step, case: build_test_context(step, case, tmp_path)
        )


def test_failed_download_can_be_restarted_from_the_beginning(tmp_path):
    failed = context(
        tmp_path / "first",
        Counterexample("download absent", FakeState(downloads_available=False)),
    )
    with pytest.raises(StepRunError) as caught:
        Runner().run(build_program(), failed)
    assert caught.value.step_id == "S006"
    fresh = context(tmp_path / "second")
    result = Runner().run(build_program(), fresh)
    assert result.completed_steps == ("S001", "S002", "S003", "S004", "S005", "S006")
    assert result.status == "succeeded"


def test_empty_or_missing_download_is_rejected_after_the_action(tmp_path):
    ctx = context(tmp_path)
    step = build_program().step("S006")
    result = step.execute(ctx)
    assert step.verify(ctx, result)
    target = Path(result["download_path"])
    target.write_bytes(b"")
    assert not step.verify(ctx, result)
    target.unlink()
    assert not step.verify(ctx, result)


def test_stage_validation_reaches_all_declared_stages(tmp_path):
    from rpa_core.elements import load_element_catalog

    ctx = context(tmp_path)
    result = APPLICATION.verify_element_stages(
        ctx, load_element_catalog(APPLICATION.app_dir / "elements.toml")
    )
    assert result["ok"], result
    assert result["unreached_stages"] == []


from datetime import datetime

from report_jingmai_export_product_detail.program import (
    AUTHENTICATED_MARKER,
    LOGIN_PASSWORD_INPUT,
    LOGIN_SUBMIT_BUTTON,
    LOGIN_URL,
    LOGIN_USERNAME_INPUT,
    target_date_for_run,
)


def test_login_uses_credentials_and_verifies_the_resulting_session(tmp_path):
    ctx = context(tmp_path)
    delegate = ctx.browser

    class LoginTransition:
        logged_in = False

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

    ctx.services["browser"] = LoginTransition()
    step = build_program().step("S001")
    result = step.execute(ctx)
    assert result["login_performed"] and step.verify(ctx, result)
    assert delegate.current_url == LOGIN_URL
    inputs = [record for record in delegate.actions if record.action == "input"]
    assert [record.element_id for record in inputs] == [
        LOGIN_USERNAME_INPUT,
        LOGIN_PASSWORD_INPUT,
    ]
    assert all(record.detail == "<redacted>" for record in inputs)


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        ("2026-09-01T09:00:00+08:00", "2026-08-31"),
        ("2026-01-01T09:00:00+08:00", "2025-12-31"),
        ("2026-09-04T17:00:00+00:00", "2026-09-04"),
    ],
)
def test_yesterday_is_fixed_when_the_run_options_are_loaded(now, expected):
    assert target_date_for_run(now=datetime.fromisoformat(now)) == expected


def test_agent_resumes_download_with_original_date_after_export_dialog_is_gone(
    tmp_path,
):
    from report_jingmai_export_product_detail.program import (
        DIALOG_REPORT_NAME,
        DOWNLOAD_REPORT_BUTTON,
        EXPORT_READY_DIALOG,
        VIEW_EXPORTS_BUTTON,
    )

    failed = context(
        tmp_path / "first",
        Counterexample("no download", FakeState(downloads_available=False)),
    )
    with pytest.raises(StepRunError):
        Runner().run(build_program(), failed)
    previous = json.loads((failed.run_dir / "result.json").read_text())
    resumed = context(
        tmp_path / "resume",
        Counterexample(
            "old dialog closed",
            FakeState(
                hidden=(DIALOG_REPORT_NAME, EXPORT_READY_DIALOG, VIEW_EXPORTS_BUTTON)
            ),
        ),
    )
    resumed.run_id = "resumed-run"
    resumed.inputs["target_date"] = "2099-01-01"
    resumed.browser.download_dir = Path(previous["download_dir"])
    result = Runner().run(build_program(), resumed, previous=previous, from_step="S006")
    assert result.status == "succeeded"
    assert result.outputs["S006"]["target_date"] == "2026-09-03"
    assert result.completed_steps == ("S001", "S002", "S003", "S004", "S005", "S006")
    assert not any(
        action.element_id == DOWNLOAD_REPORT_BUTTON
        for action in resumed.browser.actions
    )
    assert Path(result.outputs["S006"]["download_path"]).parent == failed.download_dir


def test_main_parameters_override_date_filename_credentials_and_downloads_without_local_files(tmp_path, monkeypatch):
    from report_jingmai_export_product_detail import program
    from rpa_core.cli import RunRequest

    source_dir = program.APP_DIR
    monkeypatch.setattr(program, "APP_DIR", tmp_path / "application")
    request = RunRequest(
        inputs={"target_date": "2026-08-01", "export_filename": "requested.xlsx"},
        credentials={"username": "test-user", "password": "test-secret", "expected_identity": "Test Shop"},
        download_dir=str(tmp_path / "downloads"),
    )
    options = program.load_runtime_options(request)
    assert options.inputs == request.inputs and str(options.download_dir) == request.download_dir
    assert options.metadata["login_username"].reveal() == "test-user"
    assert options.metadata["expected_identity"].reveal() == "Test Shop"
    assert not program.APP_DIR.exists()
    monkeypatch.setattr(program, "APP_DIR", source_dir)
    ctx = context(tmp_path / "fixture")
    ctx.inputs["export_filename"] = options.inputs["export_filename"]
    result = build_program().step("S006").execute(ctx)
    assert Path(result["download_path"]).name == "requested.xlsx"


@pytest.mark.parametrize("inputs", [{"period": "week"}, {"target_date": "2026-02-30"}, {"export_filename": "../escape.xlsx"}])
def test_unsupported_report_parameters_are_rejected_before_execution(tmp_path, monkeypatch, inputs):
    from report_jingmai_export_product_detail import program
    from rpa_core.cli import RunRequest

    monkeypatch.setattr(program, "APP_DIR", tmp_path)
    with pytest.raises(program.LocalConfigurationError):
        program.load_runtime_options(RunRequest(inputs=inputs))
