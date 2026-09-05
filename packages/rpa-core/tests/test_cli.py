import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from rpa_core import cli
from rpa_core.browser import ElementSpec, FakeBrowserActions, FakeDownload, Locator
from rpa_core.browser_manager import BrowserLifecyclePolicy
from rpa_core.cli import ApplicationDefinition, RuntimeOptions
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
        load_runtime_options=lambda account: RuntimeOptions(
            account,
            app_dir / "profiles" / account,
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
                active=True, actions=actions, lifecycle=spec.lifecycle
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

    monkeypatch.setattr(cli, "BrowserManager", FakeManager)
    monkeypatch.setattr(
        "builtins.input", lambda *a: pytest.fail("unattended run prompted")
    )
    return sessions


def test_unattended_runs_clean_shared_output_but_keep_separate_evidence(
    application, manager, capsys
):
    destination = application.load_runtime_options("STORE_001").download_dir
    destination.mkdir()
    (destination / "stale.xlsx").write_bytes(b"stale")
    assert cli.main(application, ["run"]) == 0
    first = json.loads(capsys.readouterr().out)
    assert not (destination / "stale.xlsx").exists()
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
    destination = application.load_runtime_options("STORE_001").download_dir
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
    destination = application.load_runtime_options("STORE_001").download_dir
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
    options = definition.load_runtime_options("STORE_001")
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
