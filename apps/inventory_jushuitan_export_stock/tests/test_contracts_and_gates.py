from __future__ import annotations

import json

import pytest
from rpa_core.catalog import verify_catalog_snapshot
from rpa_core.discovery import scan_application_architecture, scan_sensitive_content
from rpa_core.requirements import (
    compare_requirement_models,
    compute_requirement_hash,
    load_app_manifest,
    load_requirement_memory,
    load_requirement_spec,
)

from inventory_jushuitan_export_stock.cli import main
from inventory_jushuitan_export_stock.validators import (
    APP_DIR,
    application_report,
    ensure_real_run_ready,
)


def test_v2_contracts_hash_and_catalog_snapshot_are_aligned() -> None:
    manifest = load_app_manifest(APP_DIR / "app.toml")
    memory = load_requirement_memory(APP_DIR / "requirement" / "REQUIREMENT_MEMORY.md")
    spec = load_requirement_spec(APP_DIR / "requirement" / "requirement.spec.json")
    lock = verify_catalog_snapshot(APP_DIR)

    assert manifest.schema_version == 2
    assert manifest.requirement_revision == 107
    assert manifest.version == "0.3.0"
    assert manifest.status.value == "ready_for_push"
    assert manifest.latest_review == "reviews/20260903T143849+0800.toml"
    assert compare_requirement_models(memory, spec) == []
    assert compute_requirement_hash(spec) == manifest.requirement_hash
    assert len(lock.items) == 24
    assert spec.open_unresolved_elements == ()
    assert spec.open_unresolved_instructions == ()
    assert {item.source_type.value for item in lock.items} == {"repository"}
    assert {item.status.value for item in lock.items} == {"verified"}


def test_repository_gate_passes_after_real_validation_and_promotion() -> None:
    report = application_report()

    assert report.ok
    assert report.issues == []
    assert scan_application_architecture(APP_DIR) == []
    assert scan_sensitive_content(APP_DIR) == []


def test_normal_run_and_resume_dispatch_after_candidate_gate_is_cleared(
    monkeypatch,
    capsys,
) -> None:
    from inventory_jushuitan_export_stock import cli

    calls: list[dict[str, object]] = []

    def fake_run(**kwargs):
        calls.append(kwargs)
        return {"ok": True, "command": kwargs["command"], "run_id": kwargs["run_id"]}

    monkeypatch.setattr(cli, "execute_standard_run", fake_run)
    monkeypatch.setattr(cli, "ensure_real_run_ready", lambda: None)

    assert main(
        [
            "run",
            "--mode",
            "preview",
            "--run-id",
            "preview-001",
            "--authorization-id",
            "auth-preview-001",
        ]
    ) == 0
    assert main(
        [
            "resume",
            "--mode",
            "preview",
            "--run-id",
            "preview-001",
            "--authorization-id",
            "auth-resume-001",
        ]
    ) == 0
    assert calls == [
        {
            "command": "run",
            "account": "STORE_001",
            "mode": "preview",
            "run_id": "preview-001",
            "authorization_id": "auth-preview-001",
        },
        {
            "command": "resume",
            "account": "STORE_001",
            "mode": "preview",
            "run_id": "preview-001",
            "authorization_id": "auth-resume-001",
        },
    ]
    output = capsys.readouterr().out
    assert output.count('"ok": true') == 2


def test_normal_run_gate_is_cleared_after_identity_verification() -> None:
    ensure_real_run_ready()


def test_doctor_and_check_are_side_effect_free(capsys) -> None:
    assert main(["doctor"]) == 0
    assert main(["check"]) == 0
    output = capsys.readouterr().out
    assert '"ok": true' in output


@pytest.mark.parametrize(
    "argv",
    [
        ["login", "--run-id", "login-001"],
        ["login", "--authorization-id", "auth-login-001"],
        ["verify-candidates", "--run-id", "candidate-001"],
        ["verify-candidates", "--authorization-id", "auth-candidate-001"],
        ["run", "--mode", "preview", "--run-id", "preview-001"],
        [
            "run",
            "--mode",
            "preview",
            "--authorization-id",
            "auth-preview-001",
        ],
        ["resume", "--mode", "preview", "--run-id", "preview-001"],
        [
            "resume",
            "--mode",
            "preview",
            "--authorization-id",
            "auth-resume-001",
        ],
    ],
)
def test_real_browser_commands_require_run_and_authorization_ids(argv) -> None:
    with pytest.raises(SystemExit) as caught:
        main(argv)
    assert caught.value.code == 2


def test_authorized_login_and_candidate_commands_dispatch_without_printing_secrets(
    monkeypatch,
    capsys,
) -> None:
    from inventory_jushuitan_export_stock import cli

    calls: list[tuple[str, dict[str, object]]] = []

    def fake_login(**kwargs):
        calls.append(("login", kwargs))
        return {"ok": True, "command": "login", "authenticated": True}

    def fake_verify(**kwargs):
        calls.append(("verify-candidates", kwargs))
        return {"ok": True, "command": "verify-candidates", "status": "succeeded"}

    monkeypatch.setattr(cli, "execute_login", fake_login)
    monkeypatch.setattr(cli, "execute_candidate_verification", fake_verify)

    assert main(
        [
            "login",
            "--run-id",
            "login-test-001",
            "--authorization-id",
            "auth-login-test-001",
        ]
    ) == 0
    assert main(
        [
            "verify-candidates",
            "--run-id",
            "candidate-test-001",
            "--authorization-id",
            "auth-candidate-test-001",
        ]
    ) == 0
    assert calls == [
        (
            "login",
            {
                "account": "STORE_001",
                "run_id": "login-test-001",
                "authorization_id": "auth-login-test-001",
            },
        ),
        (
            "verify-candidates",
            {
                "account": "STORE_001",
                "run_id": "candidate-test-001",
                "authorization_id": "auth-candidate-test-001",
            },
        ),
    ]
    output = capsys.readouterr().out
    assert "password" not in output.casefold()


def test_candidate_resume_flag_is_rejected() -> None:
    with pytest.raises(SystemExit) as caught:
        main(
            [
                "verify-candidates",
                "--run-id",
                "candidate-test-001",
                "--authorization-id",
                "auth-candidate-test-001",
                "--resume",
            ]
        )
    assert caught.value.code == 2


def test_authorization_request_and_grant_dispatch_exact_review_fields(
    monkeypatch,
    capsys,
) -> None:
    from inventory_jushuitan_export_stock import cli

    calls: list[tuple[str, dict[str, object]]] = []

    def fake_request(**kwargs):
        calls.append(("request", kwargs))
        return {"ok": True, "command": "authorization request"}

    def fake_grant(**kwargs):
        calls.append(("grant", kwargs))
        return {"ok": True, "command": "authorization grant"}

    monkeypatch.setattr(cli, "create_authorization_request", fake_request)
    monkeypatch.setattr(cli, "grant_authorization_request", fake_grant)

    assert main(
        [
            "authorization",
            "request",
            "--operation",
            "verify-candidates",
            "--mode",
            "preview",
            "--account",
            "STORE_001",
            "--run-id",
            "candidate-request-001",
            "--authorization-id",
            "auth-candidate-request-001",
            "--requested-by",
            "fixture-developer",
        ]
    ) == 0
    assert main(
        [
            "authorization",
            "grant",
            "--authorization-id",
            "auth-candidate-request-001",
            "--scope-digest",
            "sha256:" + "a" * 64,
            "--authorized-by",
            "fixture-reviewer",
            "--approval-reference",
            "fixture-approval",
            "--ttl-seconds",
            "300",
        ]
    ) == 0

    assert calls == [
        (
            "request",
            {
                "operation": "verify_candidates",
                "account": "STORE_001",
                "mode": "preview",
                "run_id": "candidate-request-001",
                "requested_by": "fixture-developer",
                "authorization_id": "auth-candidate-request-001",
            },
        ),
        (
            "grant",
            {
                "authorization_id": "auth-candidate-request-001",
                "scope_digest": "sha256:" + "a" * 64,
                "authorized_by": "fixture-reviewer",
                "approval_reference": "fixture-approval",
                "ttl_seconds": 300,
            },
        ),
    ]
    assert capsys.readouterr().out.count('"ok": true') == 2


def _interactive_preview_request() -> dict[str, object]:
    return {
        "ok": True,
        "command": "authorization request",
        "authorization": {
            "authorization_id": "auth-preview-20260903T010203Z-a1b2c3d4",
            "scope_digest": "sha256:" + "a" * 64,
            "status": "requested",
            "scope": {
                "app_id": "jushuitan.inventory.export_stock",
                "app_version": "0.3.0",
                "operation": "run",
                "mode": "preview",
                "run_id": "preview-20260903T010203Z-a1b2c3d4",
                "account_id": "STORE_001",
                "profile_id": "profile-" + "b" * 64,
                "allowed_origins": ["https://www.erp321.com"],
                "step_ids": ["Prepare", "S001", "S002", "S003", "S004", "S005"],
                "browser_actions": ["open", "exists", "click", "download"],
                "candidate_asset_refs": [],
                "external_writes": [],
            },
        },
        "real_browser_launched": False,
        "run_directory_created": False,
    }


def test_interactive_preview_composes_request_confirm_grant_and_run(
    monkeypatch,
    capsys,
) -> None:
    from inventory_jushuitan_export_stock import cli

    calls: list[tuple[str, dict[str, object]]] = []
    gate_calls = 0

    def fake_gate() -> None:
        nonlocal gate_calls
        gate_calls += 1

    def fake_request(**kwargs):
        calls.append(("request", kwargs))
        return _interactive_preview_request()

    def fake_grant(**kwargs):
        calls.append(("grant", kwargs))
        return {"ok": True, "command": "authorization grant"}

    def fake_run(**kwargs):
        calls.append(("run", kwargs))
        return {"ok": True, "command": "run", "run_id": kwargs["run_id"]}

    monkeypatch.setattr(cli, "_is_interactive_terminal", lambda: True)
    monkeypatch.setattr(cli, "_local_developer_id", lambda: "fixture-developer")
    monkeypatch.setattr(
        cli,
        "_new_preview_ids",
        lambda: (
            "preview-20260903T010203Z-a1b2c3d4",
            "auth-preview-20260903T010203Z-a1b2c3d4",
        ),
    )
    monkeypatch.setattr(cli, "_confirm_preview", lambda: True)
    monkeypatch.setattr(cli, "ensure_real_run_ready", fake_gate)
    monkeypatch.setattr(cli, "create_authorization_request", fake_request)
    monkeypatch.setattr(cli, "grant_authorization_request", fake_grant)
    monkeypatch.setattr(cli, "execute_standard_run", fake_run)
    monkeypatch.setattr(
        cli,
        "revoke_authorization_request",
        lambda **kwargs: pytest.fail(f"unexpected revoke: {kwargs}"),
    )

    assert main(["preview", "--account", "STORE_001"]) == 0
    assert gate_calls == 2
    assert calls == [
        (
            "request",
            {
                "operation": "run",
                "account": "STORE_001",
                "mode": "preview",
                "run_id": "preview-20260903T010203Z-a1b2c3d4",
                "requested_by": "fixture-developer",
                "authorization_id": "auth-preview-20260903T010203Z-a1b2c3d4",
            },
        ),
        (
            "grant",
            {
                "authorization_id": "auth-preview-20260903T010203Z-a1b2c3d4",
                "scope_digest": "sha256:" + "a" * 64,
                "authorized_by": "fixture-developer",
                "approval_reference": (
                    "interactive-preview:preview-20260903T010203Z-a1b2c3d4"
                ),
                "ttl_seconds": 300,
            },
        ),
        (
            "run",
            {
                "command": "run",
                "account": "STORE_001",
                "mode": "preview",
                "run_id": "preview-20260903T010203Z-a1b2c3d4",
                "authorization_id": "auth-preview-20260903T010203Z-a1b2c3d4",
            },
        ),
    ]
    output = capsys.readouterr().out
    assert "即将执行 Preview：STORE_001" in output
    assert "会真实登录、查询和下载；external_writes: []" in output
    assert "app_id:" not in output
    assert "allowed_origins:" not in output
    assert "step_ids:" not in output
    assert "profile_id:" not in output
    assert "scope_digest:" not in output
    assert "ttl_seconds:" not in output
    assert '"ok": true' in output


def test_interactive_preview_decline_revokes_without_grant_or_run(
    monkeypatch,
    capsys,
) -> None:
    from inventory_jushuitan_export_stock import cli

    revoked: list[dict[str, object]] = []

    monkeypatch.setattr(cli, "_is_interactive_terminal", lambda: True)
    monkeypatch.setattr(cli, "_local_developer_id", lambda: "fixture-developer")
    monkeypatch.setattr(
        cli,
        "_new_preview_ids",
        lambda: (
            "preview-20260903T010203Z-a1b2c3d4",
            "auth-preview-20260903T010203Z-a1b2c3d4",
        ),
    )
    monkeypatch.setattr(cli, "_confirm_preview", lambda: False)
    monkeypatch.setattr(cli, "ensure_real_run_ready", lambda: None)
    monkeypatch.setattr(
        cli,
        "create_authorization_request",
        lambda **kwargs: _interactive_preview_request(),
    )
    monkeypatch.setattr(
        cli,
        "revoke_authorization_request",
        lambda **kwargs: (
            revoked.append(kwargs)
            or {"authorization": {"status": "revoked"}}
        ),
    )
    monkeypatch.setattr(
        cli,
        "grant_authorization_request",
        lambda **kwargs: pytest.fail(f"unexpected grant: {kwargs}"),
    )
    monkeypatch.setattr(
        cli,
        "execute_standard_run",
        lambda **kwargs: pytest.fail(f"unexpected run: {kwargs}"),
    )

    assert main(["preview"]) == 0
    assert revoked == [
        {
            "authorization_id": "auth-preview-20260903T010203Z-a1b2c3d4",
            "revoked_by": "fixture-developer",
            "reason": "interactive_preview_declined",
        }
    ]
    output = capsys.readouterr().out
    assert '"status": "cancelled"' in output
    assert '"authorization_status": "revoked"' in output
    assert '"real_browser_launched": false' in output


def test_preview_shortcut_requires_interactive_terminal_before_request(
    monkeypatch,
    capsys,
) -> None:
    from inventory_jushuitan_export_stock import cli

    monkeypatch.setattr(cli, "_is_interactive_terminal", lambda: False)
    monkeypatch.setattr(
        cli,
        "create_authorization_request",
        lambda **kwargs: pytest.fail(f"unexpected request: {kwargs}"),
    )

    assert main(["preview"]) == 4
    output = capsys.readouterr().out
    assert '"error_code": "interactive_confirmation_required"' in output
    assert '"real_browser_launched": false' in output


def test_preview_shortcut_does_not_accept_noninteractive_yes_flag() -> None:
    with pytest.raises(SystemExit) as caught:
        main(["preview", "--yes"])
    assert caught.value.code == 2


def test_preview_shortcut_checks_gates_before_creating_request(
    monkeypatch,
    capsys,
) -> None:
    from inventory_jushuitan_export_stock import cli

    monkeypatch.setattr(cli, "_is_interactive_terminal", lambda: True)
    monkeypatch.setattr(
        cli,
        "ensure_real_run_ready",
        lambda: (_ for _ in ()).throw(cli.RunBlockedError(("PC-001",))),
    )
    monkeypatch.setattr(
        cli,
        "create_authorization_request",
        lambda **kwargs: pytest.fail(f"unexpected request: {kwargs}"),
    )

    assert main(["preview"]) == 3
    output = capsys.readouterr().out
    assert "Preview failed" in output
    assert "RunBlockedError (application_run_blocked)" in output
    assert "blocker_ids: [PC-001]" in output
    assert '"traceback"' not in output


def test_live_command_is_unsupported_before_gate_or_browser_launch(
    monkeypatch,
    capsys,
) -> None:
    from inventory_jushuitan_export_stock import cli

    gate_called = False

    def unexpected_gate() -> None:
        nonlocal gate_called
        gate_called = True

    monkeypatch.setattr(cli, "ensure_real_run_ready", unexpected_gate)

    assert main(
        [
            "run",
            "--mode",
            "live",
            "--run-id",
            "live-blocked-001",
            "--authorization-id",
            "auth-live-blocked-001",
        ]
    ) == 4
    output = capsys.readouterr().out
    assert '"error_code": "application_live_unsupported"' in output
    assert '"real_browser_launched": false' in output
    assert gate_called is False


def test_runtime_failure_prints_root_cause_and_source_line(
    monkeypatch,
    capsys,
) -> None:
    from rpa_core.authorization import BrowserOriginNotAuthorizedError
    from rpa_core.instructions import InstructionExecutionError
    from rpa_core.runtime import StepRunError

    from inventory_jushuitan_export_stock import cli

    def raise_origin_error() -> None:
        raise BrowserOriginNotAuthorizedError("browser origin is not authorized")

    def raise_instruction_error() -> None:
        try:
            raise_origin_error()
        except BrowserOriginNotAuthorizedError as error:
            raise InstructionExecutionError(
                "jushuitan.inventory.select_brand",
                "instruction failed: BrowserOriginNotAuthorizedError",
            ) from error

    def fake_run(**kwargs):
        try:
            raise_instruction_error()
        except InstructionExecutionError as error:
            try:
                raise StepRunError(
                    "S003",
                    error.error_code,
                    "step S003 failed after 2 attempt(s)",
                ) from error
            except StepRunError as step_error:
                raise cli.ApplicationRuntimeError(
                    step_error.error_code,
                    real_browser_launched=True,
                    run_id=str(kwargs["run_id"]),
                    step_id=step_error.step_id,
                    instruction_id="jushuitan.inventory.select_brand",
                    exception_type=type(step_error).__name__,
                ) from step_error

    monkeypatch.setattr(cli, "ensure_real_run_ready", lambda: None)
    monkeypatch.setattr(cli, "execute_standard_run", fake_run)

    assert main(
        [
            "run",
            "--mode",
            "preview",
            "--run-id",
            "detailed-error-001",
            "--authorization-id",
            "auth-detailed-error-001",
        ]
    ) == 5
    payload = json.loads(capsys.readouterr().out)
    assert payload["error_code"] == "instruction_execution_failed"
    assert payload["step_id"] == "S003"
    assert payload["instruction_id"] == "jushuitan.inventory.select_brand"
    assert payload["root_cause"]["type"] == "BrowserOriginNotAuthorizedError"
    assert payload["root_cause"]["error_code"] == "browser_origin_not_authorized"
    location = payload["root_cause"]["location"]
    assert location["file"].endswith("tests/test_contracts_and_gates.py")
    assert isinstance(location["line"], int)
    assert location["function"] == "raise_origin_error"
    assert "raise BrowserOriginNotAuthorizedError" in location["code"]
    assert [entry["type"] for entry in payload["exception_chain"]] == [
        "BrowserOriginNotAuthorizedError",
        "InstructionExecutionError",
        "StepRunError",
        "ApplicationRuntimeError",
    ]
    assert payload["traceback"]
    assert "/Users/" not in json.dumps(payload)


def test_interactive_failure_prints_summary_and_saves_full_diagnostics(
    monkeypatch,
    capsys,
    tmp_path,
) -> None:
    from inventory_jushuitan_export_stock import cli

    run_id = "compact-error-001"
    app_dir = tmp_path / "inventory_jushuitan_export_stock"
    (app_dir / "runs" / run_id).mkdir(parents=True)
    diagnostics = {
        "diagnostic_schema_version": 1,
        "root_cause": {
            "index": 0,
            "type": "BrowserOriginNotAuthorizedError",
            "module": "rpa_core.authorization",
            "error_code": "browser_origin_not_authorized",
            "message": "browser URL does not have an HTTP(S) origin",
            "location": {
                "file": "packages/rpa-core/src/rpa_core/authorization.py",
                "line": 114,
                "function": "_origin_from_url",
                "code": "raise BrowserOriginNotAuthorizedError(...)",
            },
        },
        "exception_chain": [
            {
                "index": 0,
                "type": "BrowserOriginNotAuthorizedError",
                "module": "rpa_core.authorization",
                "error_code": "browser_origin_not_authorized",
                "message": "browser URL does not have an HTTP(S) origin",
                "location": None,
            }
        ],
        "traceback": [
            {
                "exception_index": 0,
                "exception_type": "BrowserOriginNotAuthorizedError",
                "file": (
                    "apps/inventory_jushuitan_export_stock/src/"
                    "inventory_jushuitan_export_stock/instructions/jushuitan/erp/"
                    "inventory/select_brand/instruction.py"
                ),
                "line": 42,
                "function": "execute",
                "code": "context.browser.click(...)",
            }
        ],
        "exception_chain_truncated": False,
        "traceback_truncated": False,
    }
    monkeypatch.setattr(cli, "APP_DIR", app_dir)
    monkeypatch.setattr(cli, "_error_diagnostics", lambda error: diagnostics)
    error = cli.ApplicationRuntimeError(
        "instruction_execution_failed",
        real_browser_launched=True,
        run_id=run_id,
        step_id="S003",
        instruction_id="jushuitan.inventory.select_brand",
        exception_type="StepRunError",
    )

    assert cli._print_runtime_error(
        "run",
        "STORE_001",
        error,
        mode="preview",
        compact=True,
    ) == 5

    output = capsys.readouterr().out
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    assert len(lines) == 7
    assert lines[0] == (
        "Preview failed — S003 / jushuitan.inventory.select_brand"
    )
    assert lines[1] == (
        "root_cause: BrowserOriginNotAuthorizedError "
        "(browser_origin_not_authorized)"
    )
    assert lines[2] == "message: browser URL does not have an HTTP(S) origin"
    assert lines[3].endswith("select_brand/instruction.py:42 (execute)")
    assert lines[4].endswith("authorization.py:114 (_origin_from_url)")
    assert lines[6] == f"run_id: {run_id}"
    assert '"exception_chain"' not in output
    assert '"traceback"' not in output

    details_path = app_dir / lines[5].removeprefix("details: ")
    saved = json.loads(details_path.read_text(encoding="utf-8"))
    assert saved["root_cause"] == diagnostics["root_cause"]
    assert saved["exception_chain"] == diagnostics["exception_chain"]
    assert saved["traceback"] == diagnostics["traceback"]
