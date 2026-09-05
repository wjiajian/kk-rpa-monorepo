from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import rpa_core.cli as cli_module
from rpa_core.browser import FakeBrowserActions
from rpa_core.cli import (
    ApplicationDefinition,
    RuntimeOptions,
    collect_blockers,
    main,
)
from rpa_core.contracts import RunMode
from rpa_core.runtime import BaseProgram, CheckpointStore, ExecutionContext, StepRunError
from rpa_core.verification import Counterexample, FakeState


REQUIREMENT_HASH = "sha256:" + ("1" * 64)


def _write_unresolved_elements(app_dir: Path) -> None:
    (app_dir / "elements.toml").write_text(
        """\
schema_version = 2

[elements."example.report.button"]
name = "报表按钮"
page = "report"
expect_count = 1
check_at = "S001"
note = "等待真实页面验证"
""",
        encoding="utf-8",
    )


def _write_resolved_elements(app_dir: Path) -> None:
    (app_dir / "elements.toml").write_text(
        """\
schema_version = 2

[elements."example.report.button"]
name = "报表按钮"
page = "report"
locator = "css:#report"
expect_count = 1
check_at = "S001"
""",
        encoding="utf-8",
    )


def _program() -> SimpleNamespace:
    return SimpleNamespace(
        spec=SimpleNamespace(
            app_id="example.compact",
            program_id="example-program",
            version="0.1.0",
            requirement_hash=REQUIREMENT_HASH,
        ),
        steps=(),
    )


def _runtime_options(app_dir: Path, account: str = "STORE_001") -> RuntimeOptions:
    return RuntimeOptions(
        account_id=account,
        profile_dir=app_dir / "profiles" / account,
    )


def _definition(app_dir: Path) -> ApplicationDefinition:
    def build_program() -> BaseProgram:
        raise AssertionError("blocked commands must not build the program")

    def load_runtime(account: str, checkpoint: object):
        raise AssertionError("blocked commands must not load runtime settings")

    return ApplicationDefinition(
        app_dir=app_dir,
        build_program=build_program,
        load_runtime_options=load_runtime,  # type: ignore[arg-type]
        element_blocker_ids={"example.report.button": "UE-REPORT-BUTTON"},
        additional_blockers=lambda: ("UI-REPORT-NAVIGATION",),
    )


def test_collect_blockers_uses_requirement_ids(tmp_path: Path) -> None:
    _write_unresolved_elements(tmp_path)

    assert collect_blockers(_definition(tmp_path)) == (
        "UE-REPORT-BUTTON",
        "UI-REPORT-NAVIGATION",
    )


def test_run_refuses_blockers_before_runtime_or_run_directory(
    tmp_path: Path,
    capsys,
) -> None:
    _write_unresolved_elements(tmp_path)

    result = main(_definition(tmp_path), ["run", "--yes"])

    assert result == 2
    assert not (tmp_path / "runs").exists()
    output = capsys.readouterr().out
    assert "UE-REPORT-BUTTON" in output
    assert '"real_browser_launched": false' in output


def test_verify_elements_lists_unresolved_without_launching(
    tmp_path: Path,
    capsys,
) -> None:
    _write_unresolved_elements(tmp_path)

    result = main(
        _definition(tmp_path),
        ["verify-elements", "--account", "STORE_001", "--yes"],
    )

    assert result == 2
    assert not (tmp_path / "runs").exists()
    assert "example.report.button" in capsys.readouterr().out


def test_verify_elements_runs_the_application_stage_verifier(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    (tmp_path / "elements.toml").write_text(
        """\
schema_version = 2

[elements."example.report.button"]
name = "报表按钮"
page = "report"
locator = "css:#report"
expect_count = 1
check_at = "S001"
""",
        encoding="utf-8",
    )
    lifecycle: list[str] = []

    class FakeManager:
        def __init__(self, _runtime_root: Path) -> None:
            lifecycle.append("created")

        def start(self, _spec, *, run_id, run_dir, **_kwargs):
            lifecycle.append("started")
            return SimpleNamespace(
                actions=FakeBrowserActions(run_dir),
                active=True,
                run_id=run_id,
            )

        def finish(self, session, *, failed: bool) -> None:
            assert failed is False
            session.active = False
            lifecycle.append("finished")

        def shutdown(self) -> None:
            lifecycle.append("shutdown")

    monkeypatch.setattr(cli_module, "BrowserManager", FakeManager)

    spec = SimpleNamespace(
        app_id="example.compact",
        program_id="example-program",
        version="0.1.0",
        requirement_hash=REQUIREMENT_HASH,
    )

    def verify_stages(context, entries):
        assert context.account_id == "STORE_002"
        assert set(entries) == {"example.report.button"}
        return {"ok": True, "checks": [{"element_id": "example.report.button"}]}

    definition = ApplicationDefinition(
        app_dir=tmp_path,
        build_program=lambda: SimpleNamespace(spec=spec),  # type: ignore[arg-type]
        load_runtime_options=lambda account, _checkpoint: RuntimeOptions(
            account_id=account,
            profile_dir=tmp_path / "profiles" / account,
        ),
        element_blocker_ids={},
        verify_element_stages=verify_stages,
    )

    result = main(
        definition,
        ["verify-elements", "--account", "STORE_002", "--yes"],
    )

    assert result == 0
    assert lifecycle == ["created", "started", "finished", "shutdown"]
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["account"] == "STORE_002"
    assert payload["real_browser_launched"] is True


def test_test_enforces_counterexamples_before_running_pytest(
    tmp_path: Path,
    monkeypatch,
) -> None:
    calls: list[str] = []

    class HonestStep:
        spec = SimpleNamespace(step_id="S001")

        def execute(self, context):
            calls.append("execute")
            return context

        def verify(self, _context, result):
            return not result.metadata["reject"]

        def counterexamples(self):
            yield Counterexample("页面拒绝", FakeState(counts={"example.rows": 0}))

    temporary_roots: list[Path] = []

    def build_context(_step, _case, temporary_root):
        calls.append("context")
        temporary_roots.append(temporary_root)
        assert temporary_root.is_dir()
        return ExecutionContext(
            app_id="example.compact",
            program_id="example-program",
            program_version="0.1.0",
            requirement_hash=REQUIREMENT_HASH,
            run_id="run-counterexample",
            account_id="STORE_001",
            mode=RunMode.PREVIEW,
            run_dir=temporary_root / "run-counterexample",
            metadata={"reject": True},
        )

    def run_pytest(*_args, **_kwargs):
        calls.append("pytest")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(cli_module.subprocess, "run", run_pytest)
    definition = ApplicationDefinition(
        app_dir=tmp_path,
        build_program=lambda: SimpleNamespace(steps=(HonestStep(),)),  # type: ignore[arg-type]
        load_runtime_options=lambda *_: _runtime_options(tmp_path),
        element_blocker_ids={},
        build_counterexample_context=build_context,
    )

    assert main(definition, ["test"]) == 0
    assert calls == ["context", "execute", "pytest"]
    assert len(temporary_roots) == 1
    assert not temporary_roots[0].exists()


def test_test_fails_closed_without_counterexample_context(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setattr(
        cli_module.subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("pytest must not run")
        ),
    )
    definition = ApplicationDefinition(
        app_dir=tmp_path,
        build_program=lambda: _program(),  # type: ignore[arg-type]
        load_runtime_options=lambda *_: _runtime_options(tmp_path),
        element_blocker_ids={},
    )

    assert main(definition, ["test"]) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["exception_type"] == "RuntimeError"
    assert payload["real_browser_launched"] is False


def test_test_stops_before_pytest_when_counterexample_survives(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    class VacuousStep:
        spec = SimpleNamespace(step_id="S001")

        def execute(self, _context):
            return {"success": True}

        def verify(self, _context, result):
            return result["success"]

        def counterexamples(self):
            yield Counterexample("页面无结果", FakeState(counts={"example.rows": 0}))

    monkeypatch.setattr(
        cli_module.subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("pytest must not run")
        ),
    )
    definition = ApplicationDefinition(
        app_dir=tmp_path,
        build_program=lambda: SimpleNamespace(steps=(VacuousStep(),)),  # type: ignore[arg-type]
        load_runtime_options=lambda *_: _runtime_options(tmp_path),
        element_blocker_ids={},
        build_counterexample_context=lambda _step, _case, root: ExecutionContext(
            app_id="example.compact",
            program_id="example-program",
            program_version="0.1.0",
            requirement_hash=REQUIREMENT_HASH,
            run_id="run-counterexample",
            account_id="STORE_001",
            mode=RunMode.PREVIEW,
            run_dir=root / "run-counterexample",
        ),
    )

    assert main(definition, ["test"]) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["error"] == "step_assertion_not_falsifiable"
    assert payload["real_browser_launched"] is False


def test_run_failure_after_launch_reports_real_browser(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    _write_resolved_elements(tmp_path)
    lifecycle: list[str] = []

    class FakeManager:
        def __init__(self, _runtime_root: Path) -> None:
            lifecycle.append("created")

        def start(self, _spec, *, run_id, run_dir, **_kwargs):
            lifecycle.append("started")
            return SimpleNamespace(
                actions=FakeBrowserActions(run_dir),
                active=True,
                run_id=run_id,
            )

        def finish(self, session, *, failed: bool) -> None:
            assert failed is True
            session.active = False
            lifecycle.append("finished")

        def shutdown(self) -> None:
            lifecycle.append("shutdown")

    class FailingRunner:
        def run(self, _program, _context):
            raise StepRunError("S001", "step_failed", "failure after launch")

    monkeypatch.setattr(cli_module, "BrowserManager", FakeManager)
    monkeypatch.setattr(cli_module, "Runner", FailingRunner)
    definition = ApplicationDefinition(
        app_dir=tmp_path,
        build_program=lambda: _program(),  # type: ignore[arg-type]
        load_runtime_options=lambda account, _checkpoint: _runtime_options(
            tmp_path, account
        ),
        element_blocker_ids={},
    )

    assert main(definition, ["run", "--yes"]) == 2
    assert lifecycle == ["created", "started", "finished", "shutdown"]
    payload = json.loads(capsys.readouterr().out)
    assert payload["error"] == "step_failed"
    assert payload["exception_type"] == "StepRunError"
    assert payload["real_browser_launched"] is True


def test_resume_identity_is_checked_before_browser_start(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    _write_resolved_elements(tmp_path)
    run_id = "run-resume"
    store = CheckpointStore(tmp_path / "runs" / run_id / "checkpoint.json")
    store.save(
        {
            "schema_version": 1,
            "identity": {
                "app_id": "example.compact",
                "program_id": "example-program",
                "program_version": "0.0.9",
                "requirement_hash": REQUIREMENT_HASH,
                "run_id": run_id,
                "account_id": "STORE_001",
                "mode": RunMode.PREVIEW.value,
            },
            "steps": {},
        }
    )

    class ForbiddenManager:
        def __init__(self, _runtime_root: Path) -> None:
            raise AssertionError("browser manager must not be created")

    monkeypatch.setattr(cli_module, "BrowserManager", ForbiddenManager)
    definition = ApplicationDefinition(
        app_dir=tmp_path,
        build_program=lambda: _program(),  # type: ignore[arg-type]
        load_runtime_options=lambda account, _checkpoint: _runtime_options(
            tmp_path, account
        ),
        element_blocker_ids={},
    )

    assert main(definition, ["resume", run_id, "--yes"]) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["error"] == "checkpoint_identity_mismatch"
    assert payload["real_browser_launched"] is False


def test_resume_step_set_is_checked_before_browser_start(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    _write_resolved_elements(tmp_path)
    run_id = "run-resume"
    store = CheckpointStore(tmp_path / "runs" / run_id / "checkpoint.json")
    store.save(
        {
            "schema_version": 1,
            "identity": {
                "app_id": "example.compact",
                "program_id": "example-program",
                "program_version": "0.1.0",
                "requirement_hash": REQUIREMENT_HASH,
                "run_id": run_id,
                "account_id": "STORE_001",
                "mode": RunMode.PREVIEW.value,
            },
            "steps": {"unexpected": {}},
        }
    )

    class ForbiddenManager:
        def __init__(self, _runtime_root: Path) -> None:
            raise AssertionError("browser manager must not be created")

    monkeypatch.setattr(cli_module, "BrowserManager", ForbiddenManager)
    definition = ApplicationDefinition(
        app_dir=tmp_path,
        build_program=lambda: _program(),  # type: ignore[arg-type]
        load_runtime_options=lambda account, _checkpoint: _runtime_options(
            tmp_path, account
        ),
        element_blocker_ids={},
    )

    assert main(definition, ["resume", run_id, "--yes"]) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["error"] == "checkpoint_error"
    assert payload["real_browser_launched"] is False


def test_doctor_fails_when_local_configuration_is_missing(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    _write_resolved_elements(tmp_path)
    (tmp_path / "pyproject.toml").write_text("[project]\nname='example'\n")
    (tmp_path / "uv.lock").write_text("version = 1\n")
    monkeypatch.setattr(cli_module, "_browser_status", lambda _path: (True, "chrome"))
    monkeypatch.setattr(
        cli_module,
        "_dependency_status",
        lambda _app_dir: (True, "synchronized"),
    )
    definition = ApplicationDefinition(
        app_dir=tmp_path,
        build_program=lambda: _program(),  # type: ignore[arg-type]
        load_runtime_options=lambda account, _checkpoint: _runtime_options(
            tmp_path, account
        ),
        element_blocker_ids={},
    )

    assert main(definition, ["doctor"]) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["local_store_config_exists"] is False
    assert payload["runtime_configuration_valid"] is True
    assert payload["browser_available"] is True
    assert payload["dependencies_synchronized"] is True
    assert payload["real_browser_launched"] is False


def test_browser_status_rejects_configured_symlink(tmp_path: Path) -> None:
    executable = tmp_path / "chrome"
    executable.write_bytes(b"fake browser")
    linked = tmp_path / "chrome-link"
    try:
        linked.symlink_to(executable)
    except OSError as error:
        pytest.skip(f"symlinks are unavailable in this test environment: {error}")

    available, detail = cli_module._browser_status(linked)

    assert available is False
    assert detail == str(linked)


def test_dependency_status_uses_read_only_uv_check(
    tmp_path: Path,
    monkeypatch,
) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='example'\n")
    (tmp_path / "uv.lock").write_text("version = 1\n")
    recorded: dict[str, object] = {}

    monkeypatch.setattr(cli_module.shutil, "which", lambda name: f"/bin/{name}")

    def fake_run(command, **kwargs):
        recorded["command"] = command
        recorded.update(kwargs)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(cli_module.subprocess, "run", fake_run)

    assert cli_module._dependency_status(tmp_path) == (
        True,
        "uv environment matches uv.lock",
    )
    assert recorded["command"] == [
        "/bin/uv",
        "sync",
        "--check",
        "--locked",
        "--offline",
        "--no-cache",
    ]
    assert recorded["cwd"] == tmp_path
    assert recorded["timeout"] == 30
