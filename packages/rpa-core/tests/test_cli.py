from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import rpa_core.cli as cli_module
from rpa_core.browser import FakeBrowserActions
from rpa_core.cli import (
    ApplicationDefinition,
    RuntimeOptions,
    collect_blockers,
    main,
)
from rpa_core.runtime import BaseProgram


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
