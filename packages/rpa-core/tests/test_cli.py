import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from rpa_core import cli
from rpa_core.browser import ElementSpec, FakeBrowserActions, FakeDownload, Locator
from rpa_core.browser_manager import BrowserLifecyclePolicy
from rpa_core.cli import ApplicationDefinition, RunRequest, RuntimeOptions
from rpa_core.contracts import RunMode
from rpa_core.downloads import download_result_is_valid
from rpa_core.runtime import BaseProgram, ExecutionContext, ProgramSpec, Step, StepSpec
from rpa_core.verification import Counterexample

TARGET = ElementSpec(
    "demo.page.download", "Download", "Demo", locator=Locator("css:button")
)
CATALOG = """schema_version = 2
[elements."demo.page.download"]
name = "Download"
page = "Demo"
locator = "css:button"
expect_count = 1
check_at = "S1"
"""


def empty_file(ctx, result):
    Path(result["download_path"]).write_bytes(b"")


class ExportStep(Step):
    def __init__(self):
        super().__init__(StepSpec("S1", "Export"))

    def execute(self, ctx):
        ctx.feishu["modes"].append(ctx.mode)
        assert ctx.db is ctx.services["db"]
        ref = ctx.browser.download(TARGET, filename="report.xlsx")
        return {
            "download_path": str(ref.path),
            "status": ref.status,
            "business_date": ctx.inputs.get("business_date"),
        }

    def verify(self, ctx, result):
        return download_result_is_valid(result, ctx.download_dir)

    def counterexamples(self):
        yield Counterexample("empty file", after_execute=empty_file)


@pytest.fixture
def application(tmp_path):
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    (app_dir / "app.toml").write_text(
        'app_id = "demo"\nname = "Demo"\nentrypoint = "demo.cli:main"\n'
    )
    (app_dir / "requirement.md").write_text("Download a report.")
    (app_dir / "elements.toml").write_text(CATALOG)
    destination = tmp_path / "shared"
    modes = []

    def build_context(step, case, root):
        run_dir = root / "runs" / "test"
        browser = FakeBrowserActions(
            run_dir,
            download_dir=root / "downloads",
            visible_element_ids={TARGET.id},
            downloads={TARGET.id: FakeDownload("report.xlsx", b"report")},
        )
        return ExecutionContext(
            "demo",
            "test",
            "STORE_001",
            run_dir,
            root / "downloads",
            services={"browser": browser, "feishu": {"modes": []}, "db": object()},
        )

    return ApplicationDefinition(
        app_dir=app_dir,
        build_program=lambda: BaseProgram(ProgramSpec("demo", "Demo"), [ExportStep()]),
        load_runtime_options=lambda request: RuntimeOptions(
            request.account_id,
            app_dir / "profiles" / request.account_id,
            destination,
            inputs={"business_date": "2026-09-03"},
        ),
        build_test_context=build_context,
        verify_element_stages=lambda ctx, entries: {"ok": True},
        build_services=lambda ctx: {"feishu": {"modes": modes}, "db": object()},
    )


@pytest.fixture
def manager(monkeypatch):
    sessions = []

    class FakeManager:
        def __init__(self, root):
            pass

        def start(self, spec, **kwargs):
            actions = FakeBrowserActions(
                kwargs["run_dir"],
                download_dir=kwargs["download_dir"],
                visible_element_ids={TARGET.id},
                downloads={TARGET.id: FakeDownload("report.xlsx", b"report")},
            )
            session = SimpleNamespace(
                active=True, actions=actions, lifecycle=spec.lifecycle,
                adopted=True, spec=spec,
            )
            sessions.append(session)
            return session

        def finish(self, session, *, failed):
            session.active = False
            session.failed = failed
            session.retained = (
                failed
                and session.lifecycle is BrowserLifecyclePolicy.KEEP_OPEN_ON_FAILURE
            )

        def shutdown(self):
            pass

        def detach(self, session):
            session.active = False
            session.retained = True

    monkeypatch.setattr(cli, "BrowserManager", FakeManager)
    monkeypatch.setattr(
        "builtins.input", lambda *a: pytest.fail("unattended run prompted")
    )
    return sessions


def test_console_public_invocation_runs_original_verify_and_events(application, manager):
    events = []
    result = cli.execute_application(application, request=RunRequest(), event_callback=events.append)
    assert result["ok"] is True
    assert result["record"]["status"] == "succeeded"
    assert [e["event_type"] for e in events][:2] == ["execution.started", "runtime.resolved"]
    assert any(e["event_type"] == "step.succeeded" for e in events)
    assert manager[-1].failed is False


def test_console_stop_before_browser_preserves_stop_record(application, manager):
    result = cli.execute_application(application, request=RunRequest(), stop_requested=lambda: True)
    assert result["record"]["status"] == "stopped"
    assert result["record"]["completed_steps"] == []
    assert manager == []


def test_console_supplied_result_cannot_bypass_original_verify(application, manager):
    # A real execute failure supplies the source; reject an invented download.
    original = application.build_services
    broken = replace(application, build_services=lambda ctx: {**original(ctx), "feishu": {"modes": None}})
    failed = cli.execute_application(broken, request=RunRequest())
    assert failed["record"]["status"] == "failed"
    resumed = cli.execute_application(application, request=RunRequest(), source_run_id=failed["run_id"], from_step="S1",
        step_result={"status": "completed", "download_path": "/missing/report.xlsx"})
    assert resumed["record"]["status"] == "failed"
    assert resumed["record"]["completed_steps"] == []
    assert resumed["record"]["error"]["code"] == "step_verification_failed"


def test_unattended_runs_preserve_existing_downloads_and_keep_separate_evidence(
    application, manager, capsys
):
    destination = application.load_runtime_options(RunRequest()).download_dir
    destination.mkdir()
    (destination / "stale.xlsx").write_bytes(b"stale")
    assert cli.main(application, ["run"]) == 0
    first = json.loads(capsys.readouterr().out)
    assert (destination / "stale.xlsx").read_bytes() == b"stale"
    assert (destination / "report.xlsx").read_bytes() == b"report"
    assert cli.main(application, ["run", "--preview"]) == 0
    second = json.loads(capsys.readouterr().out)
    assert first["run_id"] != second["run_id"]
    assert len(list((application.app_dir / "runs").glob("*/result.json"))) == 2
    assert all(not session.active for session in manager)
    modes = application.build_services(None)["feishu"]["modes"]
    assert modes == [RunMode.LIVE, RunMode.PREVIEW]


def test_invalid_configuration_does_not_open_browser_or_clear_downloads(
    application, manager
):
    destination = application.load_runtime_options(RunRequest()).download_dir
    destination.mkdir()
    (destination / "keep.xlsx").write_bytes(b"keep")

    def invalid(account):
        raise ValueError("configuration invalid")

    definition = replace(application, load_runtime_options=invalid)
    assert cli.main(definition, ["run"]) == 2
    assert manager == [] and (destination / "keep.xlsx").exists()


def test_unresolved_element_fails_before_browser_start(application, manager):
    path = application.app_dir / "elements.toml"
    path.write_text(CATALOG.replace('locator = "css:button"\n', ""))
    assert cli.main(application, ["run"]) == 2
    assert manager == []


def test_service_error_reaches_failed_result_and_retains_browser(application, manager):
    class FailingStep(ExportStep):
        def execute(self, ctx):
            raise RuntimeError("backend error")

    definition = replace(
        application,
        build_program=lambda: BaseProgram(ProgramSpec("demo", "Demo"), [FailingStep()]),
    )
    assert cli.main(definition, ["run"]) == 2
    assert manager[0].failed is True and manager[0].retained is True
    report = json.loads(
        next((application.app_dir / "runs").glob("*/result.json")).read_text()
    )
    assert report["status"] == "failed" and report["failed_step"] == "S1"


def test_offline_test_runs_baselines_and_counterexamples_without_loading_real_options(
    application, manager, monkeypatch
):
    def forbidden(*args):
        pytest.fail("offline test touched real configuration")

    definition = replace(application, load_runtime_options=forbidden)
    monkeypatch.setattr(
        cli.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=0)
    )
    assert cli.main(definition, ["test"]) == 0
    assert manager == []


def test_doctor_does_not_clean_download_directory(application, manager, monkeypatch):
    destination = application.load_runtime_options(RunRequest()).download_dir
    destination.mkdir()
    (destination / "keep").write_bytes(b"keep")
    monkeypatch.setattr(cli, "_browser_status", lambda *args: (True, "test browser"))
    monkeypatch.setattr(cli, "_dependency_status", lambda *args: (True, "locked"))
    assert cli.main(application, ["doctor"]) == 0
    assert manager == [] and (destination / "keep").exists()


def test_resume_restores_original_options_and_keeps_existing_files(
    application, manager, capsys
):
    fail = [True]

    class RepairableStep(ExportStep):
        def execute(self, ctx):
            if fail[0]:
                raise RuntimeError("broken locator")
            return super().execute(ctx)

    definition = replace(
        application,
        build_program=lambda: BaseProgram(
            ProgramSpec("demo", "Demo"), [RepairableStep()]
        ),
    )
    assert cli.main(definition, ["run", "--preview"]) == 2
    failure = json.loads(capsys.readouterr().out)
    original_id = failure["run_id"]
    original_report = definition.app_dir / "runs" / original_id / "result.json"
    original_bytes = original_report.read_bytes()
    options = definition.load_runtime_options(RunRequest())
    marker = options.download_dir / "keep-for-next-step.xlsx"
    marker.write_bytes(b"existing output")
    fail[0] = False
    changed = replace(
        options,
        download_dir=definition.app_dir / "other-output",
        inputs={"business_date": "2099-01-01"},
    )
    definition = replace(definition, load_runtime_options=lambda account: changed)
    assert cli.main(definition, ["resume", original_id, "--from-step", "S1"]) == 0
    output = json.loads(capsys.readouterr().out)
    report = json.loads(
        (definition.app_dir / "runs" / output["run_id"] / "result.json").read_text()
    )
    assert output["run_id"] != original_id and output["resumed_from"] == original_id
    assert report["outputs"]["S1"]["business_date"] == "2026-09-03"
    assert report["mode"] == "preview"
    assert marker.read_bytes() == b"existing output"
    assert (options.download_dir / "report.xlsx").exists()
    assert not changed.download_dir.exists()
    assert original_report.read_bytes() == original_bytes
    assert manager[0].retained and not manager[1].retained


def test_invalid_resume_step_is_reported_before_starting_a_browser(
    application, manager
):
    original_id = "failed-fixture"
    source = application.app_dir / "runs" / original_id
    source.mkdir(parents=True)
    (source / "result.json").write_text(
        json.dumps(
            {
                "app_id": "demo",
                "run_id": original_id,
                "status": "failed",
                "inputs": {},
                "completed_steps": [],
                "outputs": {},
            }
        )
    )
    assert cli.main(application, ["resume", original_id, "--from-step", "absent"]) == 2
    assert manager == []


@pytest.mark.parametrize("phase", ["configuration", "services", "browser", "downloads"])
def test_preparation_failures_return_a_run_id_and_record_the_failure(
    application, manager, monkeypatch, capsys, phase
):
    def fail(*args, **kwargs):
        raise RuntimeError("private startup detail")

    definition = application
    if phase == "configuration":
        definition = replace(application, load_runtime_options=fail)
    elif phase == "services":
        definition = replace(application, build_services=fail)
    elif phase == "browser":
        monkeypatch.setattr(cli.BrowserManager, "start", fail)
    else:
        options = application.load_runtime_options(RunRequest())
        definition = replace(application, load_runtime_options=lambda request: replace(options, download_dir=application.app_dir / "src"))
    assert cli.main(definition, ["run"]) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["run_id"] and payload["record_error"] is None
    run_dir = application.app_dir / "runs" / payload["run_id"]
    report = json.loads((run_dir / "result.json").read_text())
    assert report["run_id"] == payload["run_id"]
    assert report["status"] == "failed" and report["phase"] == "prepare"
    assert report["completed_steps"] == []
    assert "private startup detail" not in (run_dir / "result.json").read_text()
    assert json.loads((run_dir / "events.jsonl").read_text())["event_type"] == "run.failed"
    assert manager == []


def test_cli_passes_inputs_paths_and_credentials_without_saving_credentials(application, manager, tmp_path, capsys):
    credentials = tmp_path / "credentials.json"
    credentials.write_text(json.dumps({"username": "fixture-user", "password": "fixture-secret"}))
    observed = []
    defaults = application.load_runtime_options(RunRequest())

    def load(request):
        observed.append(request)
        return replace(defaults, inputs=request.inputs, metadata={"password": request.credentials["password"]}, download_dir=Path(request.download_dir))

    definition = replace(application, load_runtime_options=load)
    destination = tmp_path / "external-downloads"
    assert cli.main(definition, ["run", "--inputs", '{"business_date":"2026-08-01","period":"week"}', "--credentials", "@" + str(credentials), "--download-dir", str(destination)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert observed[0].inputs["period"] == "week"
    assert observed[0].credentials["username"] == "fixture-user"
    assert "fixture-secret" not in repr(observed[0])
    report = (application.app_dir / "runs" / payload["run_id"] / "result.json").read_text()
    assert "fixture-secret" not in report and "fixture-user" not in report
    assert json.loads(report)["inputs"]["business_date"] == "2026-08-01"
    assert payload["outputs"]["S1"]["download_path"].startswith(str(destination))


def test_cli_verifies_agent_result_with_temporary_locators_and_preserves_the_source(application, manager, tmp_path, capsys):
    executions = []

    class BrokenExport(ExportStep):
        def execute(self, ctx):
            executions.append(self.spec.step_id)
            raise RuntimeError("broken locator")

        def verify(self, ctx, result):
            return ctx.services["elements"][TARGET.id].locator.value == "css:#repaired" and super().verify(ctx, result)

    definition = replace(application, build_program=lambda: BaseProgram(ProgramSpec("demo", "Demo"), [BrokenExport()]))
    catalog = (application.app_dir / "elements.toml").read_bytes()
    assert cli.main(definition, ["run"]) == 2
    source_id = json.loads(capsys.readouterr().out)["run_id"]
    source_path = application.app_dir / "runs" / source_id / "result.json"
    source_bytes = source_path.read_bytes()
    destination = application.load_runtime_options(RunRequest()).download_dir
    downloaded = destination / "agent-export.xlsx"
    downloaded.write_bytes(b"export completed by the agent")
    result_file = tmp_path / "step.json"
    result_file.write_text(json.dumps({"download_path": str(downloaded), "status": "completed"}))
    overrides = json.dumps({TARGET.id: {"locator": "css:#repaired"}})
    assert cli.main(definition, ["resume", source_id, "--from-step", "S1", "--step-result", "@" + str(result_file), "--locator-overrides", overrides]) == 0
    resumed = json.loads(capsys.readouterr().out)
    assert executions == ["S1"]
    report = json.loads((application.app_dir / "runs" / resumed["run_id"] / "result.json").read_text())
    assert report["agent_result_step"] == "S1" and report["completed_steps"] == ["S1"]
    assert source_path.read_bytes() == source_bytes
    assert (application.app_dir / "elements.toml").read_bytes() == catalog
    # The next attempt has the original locators again; a supplied result alone cannot pass.
    assert cli.main(definition, ["resume", source_id, "--from-step", "S1", "--step-result", "@" + str(result_file)]) == 2
    assert json.loads(capsys.readouterr().out)["error"] == "step_verification_failed"


@pytest.mark.parametrize("failure", ["options", "browser"])
def test_resume_can_continue_from_an_attempt_that_failed_during_preparation(application, manager, capsys, monkeypatch, failure):
    fail_step = [True]

    class Second(ExportStep):
        def __init__(self):
            super().__init__()
            self.spec = StepSpec("S2", "Second")

        def execute(self, ctx):
            if fail_step[0]:
                raise RuntimeError("step failed")
            return super().execute(ctx)

    definition = replace(application, build_program=lambda: BaseProgram(ProgramSpec("demo", "Demo"), [ExportStep(), Second()]))
    assert cli.main(definition, ["run"]) == 2
    source_id = json.loads(capsys.readouterr().out)["run_id"]
    original = json.loads((application.app_dir / "runs" / source_id / "result.json").read_text())
    fail_step[0] = False

    def fail(*args, **kwargs):
        raise RuntimeError("preparation failed")

    with monkeypatch.context() as patch:
        broken = definition
        if failure == "options":
            broken = replace(definition, load_runtime_options=fail)
        else:
            patch.setattr(cli.BrowserManager, "start", fail)
        assert cli.main(broken, ["resume", source_id, "--from-step", "S2"]) == 2
    new_id = json.loads(capsys.readouterr().out)["run_id"]
    saved = json.loads((application.app_dir / "runs" / new_id / "result.json").read_text())
    assert saved["completed_steps"] == ["S1"]
    assert saved["outputs"]["S1"] == original["outputs"]["S1"]
    assert saved["inputs"] == original["inputs"]
    assert cli.main(definition, ["resume", new_id, "--from-step", "S2"]) == 0
    assert json.loads(capsys.readouterr().out)["completed_steps"] == ["S1", "S2"]


@pytest.fixture
def recovery_source(application):
    from rpa_core.runtime import StepSpec

    first = ExportStep()
    first.spec = StepSpec("S0", "Previous export")
    definition = replace(application, build_program=lambda: BaseProgram(
        ProgramSpec("demo", "Demo"), [first, ExportStep()]
    ))
    options = definition.load_runtime_options(RunRequest())
    record = {
        "app_id": "demo", "run_id": "run-source", "account_id": "STORE_001",
        "mode": "preview", "status": "failed", "failed_step": "S1",
        "inputs": {"business_date": "2026-08-01"},
        "download_dir": str(options.download_dir),
        "completed_steps": ["S0"], "outputs": {"S0": {"rows": ["saved"]}},
        "locator_overrides": {TARGET.id: {"locator": "css:#old-attempt"}},
    }
    path = definition.app_dir / "runs" / record["run_id"] / "result.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(record))
    return definition, path, record


def test_recovery_preserves_original_context_without_running_steps(
    recovery_source, manager, tmp_path, capsys
):
    definition, path, record = recovery_source
    original_bytes = path.read_bytes()
    defaults = definition.load_runtime_options(RunRequest())
    observed = []
    credentials = {"username": "private-user", "password": "private-password"}

    def load(request):
        observed.append(request)
        return replace(defaults, inputs={"business_date": "2099-01-01"},
                       download_dir=tmp_path / "changed-downloads",
                       metadata={"credentials": request.credentials})

    def services(ctx):
        assert ctx.outputs == record["outputs"]
        assert ctx.inputs == record["inputs"]
        return {"feishu": {"modes": []}, "db": object()}

    definition = replace(definition, load_runtime_options=load, build_services=services)
    defaults.download_dir.mkdir()
    keep = defaults.download_dir / "keep.xlsx"
    keep.write_bytes(b"existing")
    with cli.open_recovery_session(definition, record["run_id"], credentials=credentials) as recovery:
        ctx = recovery.context
        assert recovery.browser_adopted is True
        assert recovery.source_record == record
        assert ctx.account_id == record["account_id"] and ctx.mode is RunMode.PREVIEW
        assert ctx.run_dir == path.parent and ctx.run_id == record["run_id"]
        assert ctx.download_dir == defaults.download_dir
        assert ctx.browser.download_dir == defaults.download_dir
        assert ctx.metadata["credentials"] == credentials
        assert ctx.service("elements")[TARGET.id].locator.value == "css:button"
        assert ctx.browser.actions == [] and ctx.feishu["modes"] == []
        assert ctx.current_step_id is None
        assert "private-password" not in repr(recovery)
        ctx.outputs["S0"]["rows"].append("temporary")
        ctx.inputs["business_date"] = "temporary"
        assert recovery.source_record == record
    assert observed[0].inputs == record["inputs"]
    assert observed[0].download_dir == record["download_dir"]
    assert observed[0].credentials == credentials
    assert manager[-1].retained and not manager[-1].active
    assert keep.read_bytes() == b"existing"
    assert list(defaults.download_dir.iterdir()) == [keep]
    assert not (tmp_path / "changed-downloads").exists()
    assert path.read_bytes() == original_bytes
    events = (path.parent / "recovery-events.jsonl").read_text()
    assert "private-password" not in events and "private-user" not in events
    assert [json.loads(line)["event_type"] for line in events.splitlines()] == [
        "recovery.opened", "recovery.closed",
    ]
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("failure", [RuntimeError, KeyboardInterrupt])
def test_recovery_handler_error_releases_ownership_then_allows_resume(
    recovery_source, manager, capsys, failure
):
    definition, path, record = recovery_source
    original = path.read_bytes()
    with pytest.raises(failure):
        with cli.open_recovery_session(definition, record["run_id"]):
            raise failure("private-handler-password")
    assert manager[-1].retained and not manager[-1].active
    with cli.open_recovery_session(definition, record["run_id"]) as recovery:
        assert recovery.context.outputs == record["outputs"]
    assert cli.main(definition, ["resume", record["run_id"], "--from-step", "S1"]) == 0
    assert json.loads(capsys.readouterr().out)["completed_steps"] == ["S0", "S1"]
    events = (path.parent / "recovery-events.jsonl").read_text()
    assert "private-handler-password" not in events
    failure_event = next(json.loads(line) for line in events.splitlines()
                         if json.loads(line)["event_type"] == "recovery.failed")
    assert failure_event["details"]["diagnostics"]["diagnostic_schema_version"] == 1
    assert path.read_bytes() == original


@pytest.mark.parametrize("changes", [
    {"status": "succeeded"}, {"app_id": "another-app"}, {"run_id": "another-run"},
    {"inputs": None}, {"inputs": []}, {"account_id": None}, {"mode": "unknown"},
    {"download_dir": ""}, {"completed_steps": ["S1"]}, {"outputs": {}},
])
def test_recovery_rejects_unusable_source_before_browser_start(
    recovery_source, manager, changes
):
    from rpa_core.runtime import RuntimeContractError

    definition, path, record = recovery_source
    path.write_text(json.dumps(record | changes))
    original = path.read_bytes()
    with pytest.raises(RuntimeContractError):
        with cli.open_recovery_session(definition, record["run_id"]):
            pytest.fail("invalid recovery entered")
    assert manager == [] and path.read_bytes() == original


@pytest.mark.parametrize("failure", ["inputs", "services", "browser", "locators", "account"])
def test_recovery_preparation_failure_is_diagnosed_without_changing_source(
    recovery_source, manager, monkeypatch, failure
):
    definition, path, record = recovery_source
    original = path.read_bytes()

    def fail(*args, **kwargs):
        raise RuntimeError("private-startup-password")

    options = definition.load_runtime_options(RunRequest())
    if failure == "inputs":
        options = replace(options, inputs={"business_date": "2099-01-01", "missing_saved_input": "default"})
        definition = replace(definition, load_runtime_options=lambda request: options)
    elif failure == "services":
        definition = replace(definition, build_services=fail)
    elif failure == "browser":
        monkeypatch.setattr(cli.BrowserManager, "start", fail)
    elif failure == "account":
        definition = replace(definition, load_runtime_options=lambda request: replace(options, account_id="OTHER"))
    else:
        (definition.app_dir / "elements.toml").write_text(CATALOG.replace('locator = "css:button"\n', ""))
    with pytest.raises((RuntimeError, ValueError)):
        with cli.open_recovery_session(definition, record["run_id"]):
            pytest.fail("invalid recovery entered")
    assert manager == [] and path.read_bytes() == original
    events = (path.parent / "recovery-events.jsonl").read_text()
    assert "private-startup-password" not in events
    assert json.loads(events)["event_type"] == "recovery.failed"
