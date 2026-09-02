from __future__ import annotations

from pathlib import Path

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
from inventory_jushuitan_export_stock.validators import APP_DIR, application_report


def test_v2_contracts_hash_and_catalog_snapshot_are_aligned() -> None:
    manifest = load_app_manifest(APP_DIR / "app.toml")
    memory = load_requirement_memory(APP_DIR / "requirement" / "REQUIREMENT_MEMORY.md")
    spec = load_requirement_spec(APP_DIR / "requirement" / "requirement.spec.json")
    lock = verify_catalog_snapshot(APP_DIR)

    assert manifest.schema_version == 2
    assert manifest.requirement_revision == 107
    assert compare_requirement_models(memory, spec) == []
    assert compute_requirement_hash(spec) == manifest.requirement_hash
    assert len(lock.items) == 23
    assert spec.open_unresolved_elements == ()
    assert spec.open_unresolved_instructions == ()
    assert {item.source_type.value for item in lock.items} == {"repository"}
    assert {item.status.value for item in lock.items} == {"verified"}


def test_repository_gate_passes_after_verified_assets_are_promoted() -> None:
    report = application_report()

    assert report.ok
    assert report.issues == []
    assert scan_application_architecture(APP_DIR) == []
    assert scan_sensitive_content(APP_DIR) == []


def test_normal_run_and_resume_dispatch_after_verified_assets_are_promoted(
    monkeypatch,
    capsys,
) -> None:
    from inventory_jushuitan_export_stock import cli

    calls: list[dict[str, object]] = []

    def fake_run(**kwargs):
        calls.append(kwargs)
        return {"ok": True, "command": kwargs["command"], "run_id": kwargs["run_id"]}

    monkeypatch.setattr(cli, "execute_standard_run", fake_run)

    assert main(["run", "--mode", "preview", "--run-id", "preview-001"]) == 0
    assert main(["resume", "--mode", "preview", "--run-id", "preview-001"]) == 0
    assert calls == [
        {
            "command": "run",
            "account": "STORE_001",
            "mode": "preview",
            "run_id": "preview-001",
        },
        {
            "command": "resume",
            "account": "STORE_001",
            "mode": "preview",
            "run_id": "preview-001",
        },
    ]
    output = capsys.readouterr().out
    assert output.count('"ok": true') == 2


def test_doctor_check_login_and_candidate_verification_are_side_effect_free(capsys) -> None:
    assert main(["doctor"]) == 0
    assert main(["check"]) == 0
    assert main(["login", "--account", "STORE_001"]) == 4
    assert main(["verify-candidates", "--account", "STORE_001"]) == 4
    output = capsys.readouterr().out
    assert '"real_browser_launched": false' in output


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

    batch_id = "patch-c-verify-20260901"
    assert main(["login", "--batch-id", batch_id]) == 0
    assert main(
        [
            "verify-candidates",
            "--batch-id",
            batch_id,
            "--run-id",
            "candidate-test-001",
        ]
    ) == 0
    assert calls == [
        ("login", {"account": "STORE_001", "batch_id": batch_id}),
        (
            "verify-candidates",
            {
                "account": "STORE_001",
                "batch_id": batch_id,
                "run_id": "candidate-test-001",
                "resume_run_id": None,
            },
        ),
    ]
    output = capsys.readouterr().out
    assert "password" not in output.casefold()


def test_live_command_requires_separate_authorization_before_browser_launch(
    monkeypatch,
    capsys,
) -> None:
    from inventory_jushuitan_export_stock import cli

    monkeypatch.setattr(cli, "ensure_real_run_ready", lambda: None)

    assert main(["run", "--mode", "live", "--run-id", "live-blocked-001"]) == 4
    output = capsys.readouterr().out
    assert '"error_code": "live_write_authorization_required"' in output
    assert '"real_browser_launched": false' in output
