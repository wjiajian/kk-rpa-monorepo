from __future__ import annotations

from pathlib import Path

from rpa_core.catalog import verify_catalog_snapshot
from rpa_core.discovery import issue_codes, scan_application_architecture, scan_sensitive_content
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
    assert len(spec.open_unresolved_elements) == 16
    assert len(spec.open_unresolved_instructions) == 7


def test_repository_gate_has_only_expected_candidate_blockers() -> None:
    report = application_report()
    codes = issue_codes(report.issues)

    assert "UNRESOLVED_ELEMENT_OPEN" in codes
    assert "UNRESOLVED_INSTRUCTION_OPEN" in codes
    assert not (codes - {"UNRESOLVED_ELEMENT_OPEN", "UNRESOLVED_INSTRUCTION_OPEN"})
    assert scan_application_architecture(APP_DIR) == []
    assert scan_sensitive_content(APP_DIR) == []


def test_normal_run_and_resume_refuse_before_creating_run_directory(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    blocked_runs = APP_DIR / "runs"
    assert not blocked_runs.exists()

    assert main(["run", "--mode", "preview", "--run-id", "blocked-001"]) == 3
    assert not blocked_runs.exists()
    assert main(["resume", "--mode", "preview", "--run-id", "blocked-001"]) == 3
    assert not blocked_runs.exists()
    output = capsys.readouterr().out
    assert "UI-S005-EXPORT" in output
    assert '"run_directory_created": false' in output


def test_doctor_check_login_and_candidate_verification_are_side_effect_free(capsys) -> None:
    assert main(["doctor"]) == 0
    assert main(["check"]) == 2
    assert main(["login", "--account", "STORE_001"]) == 4
    assert main(["verify-candidates", "--account", "STORE_001"]) == 4
    output = capsys.readouterr().out
    assert '"real_browser_launched": false' in output
