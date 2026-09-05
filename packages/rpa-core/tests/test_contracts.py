from __future__ import annotations

import json
from importlib.metadata import version as distribution_version
from pathlib import Path

import pytest
from pydantic import ValidationError

from rpa_core import __version__
from rpa_core.contracts import (
    AppManifest,
    AppStatus,
    ConfirmationStatus,
    RequirementSpec,
    ResumePolicy,
    SideEffect,
)
from rpa_core.schema_export import export_schemas, schema_documents


ZERO_HASH = "sha256:" + ("0" * 64)


def requirement_document() -> dict[str, object]:
    return {
        "schema_version": 1,
        "source": {
            "document_id": "redacted-requirement",
            "revision": 7,
            "requirement_hash": ZERO_HASH,
        },
        "application": {
            "app_id": "example.offline_export",
            "app_slug": "example_offline_export",
            "name": "Offline export example",
            "version": "0.1.0",
            "entrypoint": "example_offline_export.cli:main",
        },
        "steps": [
            {
                "id": "load_fixture",
                "name": "Load fixture",
                "action": "read_fixture",
                "outputs": ["records"],
                "success_conditions": ["records_loaded"],
                "side_effect": "read",
            },
            {
                "id": "write_preview",
                "name": "Write preview",
                "action": "write_output",
                "inputs": ["records"],
                "outputs": ["preview_file"],
                "success_conditions": ["preview_exists"],
                "resume": "verify_then_run",
                "side_effect": "write",
            },
        ],
        "outputs": [
            {
                "id": "preview_file",
                "name": "Preview JSON",
                "target": "runs/{run_id}/write-previews/records.json",
                "write_mode": "replace",
                "fields": ["record_id", "amount"],
            }
        ],
    }


def manifest_document() -> dict[str, object]:
    return {
        "schema_version": 1,
        "app_id": "example.offline_export",
        "app_slug": "example_offline_export",
        "name": "Offline export example",
        "version": "0.1.0",
        "entrypoint": "example_offline_export.cli:main",
        "python": "3.12",
        "requirement_revision": 7,
        "requirement_hash": ZERO_HASH,
        "configuration_schema": "config/config.schema.json",
        "status": "draft",
        "latest_review": "",
        "commands": {},
    }


def test_app_manifest_has_fixed_commands_and_statuses() -> None:
    manifest = AppManifest.model_validate(manifest_document())

    assert manifest.status is AppStatus.DRAFT
    assert manifest.commands.check is None
    assert manifest.commands.preview == "rpa-app run"
    assert manifest.commands.live == "rpa-app run --live"
    assert manifest.commands.verify_elements == "rpa-app verify-elements"


def test_core_version_matches_installed_package_metadata() -> None:
    assert __version__ == distribution_version("rpa-core")


def test_v1_manifest_rejects_legacy_cli_commands() -> None:
    document = manifest_document()
    document["commands"] = {
        "check": "rpa-app check",
        "preview": "rpa-app run --mode preview",
        "live": "rpa-app run --mode live",
    }

    with pytest.raises(ValidationError, match="schema_version 1 command"):
        AppManifest.model_validate(document)


def test_v2_manifest_uses_strict_legacy_command_defaults() -> None:
    document = manifest_document()
    document["schema_version"] = 2
    document["catalog_lock"] = "catalog.lock.json"
    document["commands"] = {}

    manifest = AppManifest.model_validate(document)

    assert manifest.schema_version == 2
    assert manifest.catalog_lock == "catalog.lock.json"
    assert manifest.commands.check == "rpa-app check"
    assert manifest.commands.preview == "rpa-app run --mode preview"
    assert manifest.commands.live == "rpa-app run --mode live"
    assert manifest.commands.login == "rpa-app login"
    assert manifest.commands.verify_candidates == "rpa-app verify-candidates"
    assert manifest.commands.verify_elements is None

    compact_commands = manifest_document()
    compact_commands["schema_version"] = 2
    compact_commands["catalog_lock"] = "catalog.lock.json"
    compact_commands["commands"] = {
        "preview": "rpa-app run",
        "live": "rpa-app run --live",
        "verify_elements": "rpa-app verify-elements",
    }
    with pytest.raises(ValidationError, match="schema_version 2 command"):
        AppManifest.model_validate(compact_commands)

    missing_lock = manifest_document()
    missing_lock["schema_version"] = 2
    missing_lock["commands"] = {}
    with pytest.raises(ValidationError, match="requires catalog_lock"):
        AppManifest.model_validate(missing_lock)

    v1_with_legacy_command = manifest_document()
    v1_with_legacy_command["commands"] = {"login": "rpa-app login"}
    with pytest.raises(ValidationError, match="schema_version 1 command"):
        AppManifest.model_validate(v1_with_legacy_command)


def test_manifest_rejects_nonstandard_command_and_mismatched_entrypoint() -> None:
    bad_command = manifest_document()
    bad_command["commands"] = {"live": "rpa-app unsafe-live"}
    with pytest.raises(ValidationError, match="literal_error"):
        AppManifest.model_validate(bad_command)

    bad_entrypoint = manifest_document()
    bad_entrypoint["entrypoint"] = "some_other_package.cli:main"
    with pytest.raises(ValidationError, match="entrypoint package"):
        AppManifest.model_validate(bad_entrypoint)


def test_reviewed_status_requires_review_reference() -> None:
    document = manifest_document()
    document["status"] = "ready_for_push"

    with pytest.raises(ValidationError, match="requires latest_review"):
        AppManifest.model_validate(document)


def test_requirement_defaults_capture_runtime_contract() -> None:
    requirement = RequirementSpec.model_validate(requirement_document())

    assert requirement.steps[0].retry.max_attempts == 1
    assert requirement.steps[1].resume is ResumePolicy.VERIFY_THEN_RUN
    assert requirement.steps[1].side_effect is SideEffect.WRITE
    assert requirement.authorization_requirements.live_requires_separate_authorization
    assert requirement.authorization_requirements.live_scope_fields == [
        "app_id",
        "app_version",
        "program_id",
        "program_version",
        "requirement_hash",
        "catalog_digest",
        "operation",
        "mode",
        "run_id",
        "resume_checkpoint_digest",
        "resume_step_id",
        "account_id",
        "profile_id",
        "allowed_origins",
        "step_ids",
        "browser_actions",
        "element_ids",
        "candidate_asset_refs",
        "external_writes",
        "external_writes.write_id",
        "external_writes.step_id",
        "external_writes.adapter",
        "external_writes.target",
        "external_writes.data_scope",
        "external_writes.expected_record_count",
        "external_writes.payload_digest",
        "source_preview_run_id",
    ]
    assert "checkpoint_recovery" in requirement.test_requirements.required_suites


def test_requirement_rejects_duplicate_ids() -> None:
    document = requirement_document()
    document["steps"] = [document["steps"][0], document["steps"][0]]  # type: ignore[index]

    with pytest.raises(ValidationError, match="duplicate IDs in steps"):
        RequirementSpec.model_validate(document)


def test_requirement_rejects_unknown_and_orphan_blocker_links() -> None:
    unknown = requirement_document()
    unknown["steps"][0]["pending_confirmation_ids"] = ["PC-001"]  # type: ignore[index]
    with pytest.raises(ValidationError, match="unknown pending confirmations"):
        RequirementSpec.model_validate(unknown)

    orphan = requirement_document()
    orphan["pending_confirmations"] = [
        {
            "id": "PC-001",
            "requirement_step": "load_fixture",
            "question": "Which fixture?",
            "risk": "The wrong records could be processed.",
        }
    ]
    with pytest.raises(ValidationError, match="not linked from its step"):
        RequirementSpec.model_validate(orphan)


def test_resolved_confirmation_requires_developer_conclusion() -> None:
    document = requirement_document()
    document["steps"][0]["pending_confirmation_ids"] = ["PC-001"]  # type: ignore[index]
    document["pending_confirmations"] = [
        {
            "id": "PC-001",
            "requirement_step": "load_fixture",
            "question": "Which fixture?",
            "risk": "The wrong records could be processed.",
            "status": ConfirmationStatus.RESOLVED.value,
        }
    ]

    with pytest.raises(ValidationError, match="developer_conclusion"):
        RequirementSpec.model_validate(document)


def test_resolved_element_requires_reference_and_test_evidence() -> None:
    document = requirement_document()
    document["steps"][0]["unresolved_element_ids"] = ["UE-001"]  # type: ignore[index]
    document["unresolved_elements"] = [
        {
            "id": "UE-001",
            "requirement_step": "load_fixture",
            "platform": "example",
            "page": "Fixture page",
            "name": "Download",
            "reason": "No public locator",
            "resolution": "Capture after authorization",
            "status": "resolved",
            "resolved_element_ref": "example.fixture.download",
            "tested": False,
        }
    ]

    with pytest.raises(ValidationError, match="must be tested"):
        RequirementSpec.model_validate(document)


def test_v2_candidate_instruction_is_structured_and_blocks_real_run() -> None:
    document = requirement_document()
    document["schema_version"] = 2
    document["steps"][0]["unresolved_instruction_ids"] = ["UI-001"]  # type: ignore[index]
    document["unresolved_instructions"] = [
        {
            "id": "UI-001",
            "requirement_step": "load_fixture",
            "platform": "example",
            "capability": "load fixture",
            "reason": "No verified shared instruction",
            "candidate_instruction_ref": "example.fixture.load",
            "candidate_implementation": (
                "src/example_offline_export/instructions/example/fixture/load/instruction.py"
            ),
            "fake_test_ref": "tests/test_candidate_fixture_load.py",
            "fake_test_status": "passed",
            "status": "candidate",
        }
    ]

    requirement = RequirementSpec.model_validate(document)

    assert requirement.has_blockers
    assert requirement.blocking_item_ids == ("UI-001",)
    assert requirement.unresolved_instructions[0].blocks_offline_test is False
    assert requirement.unresolved_instructions[0].blocks_real_run


def test_v2_resolved_instruction_requires_step_reference_and_real_evidence() -> None:
    document = requirement_document()
    document["schema_version"] = 2
    document["steps"][0]["instruction_refs"] = ["example.fixture.load"]  # type: ignore[index]
    document["steps"][0]["unresolved_instruction_ids"] = ["UI-001"]  # type: ignore[index]
    document["unresolved_instructions"] = [
        {
            "id": "UI-001",
            "requirement_step": "load_fixture",
            "platform": "example",
            "capability": "load fixture",
            "reason": "Originally absent",
            "status": "resolved",
            "resolved_instruction_ref": "example.fixture.load",
            "real_test_status": "passed",
            "real_test_evidence": "runs/verify-001/evidence.json",
        }
    ]

    requirement = RequirementSpec.model_validate(document)

    assert not requirement.has_blockers

    document["steps"][0]["instruction_refs"] = []  # type: ignore[index]
    with pytest.raises(ValidationError, match="not referenced by its step"):
        RequirementSpec.model_validate(document)


def test_v1_requirement_rejects_instruction_fields() -> None:
    document = requirement_document()
    document["steps"][0]["instruction_refs"] = ["example.fixture.load"]  # type: ignore[index]

    with pytest.raises(ValidationError, match="schema_version 1"):
        RequirementSpec.model_validate(document)


def test_checked_in_schema_export_is_json_and_contains_contracts(tmp_path) -> None:
    paths = export_schemas(tmp_path)

    assert {path.name for path in paths} == {
        "app-manifest.schema.json",
        "authorization-record.schema.json",
        "catalog-lock.schema.json",
        "requirement-spec.schema.json",
    }
    authorization_schema = json.loads(
        (tmp_path / "authorization-record.schema.json").read_text(encoding="utf-8")
    )
    assert authorization_schema["properties"]["schema_version"]["const"] == 1
    assert "AuthorizationScope" in authorization_schema["$defs"]
    assert "ExternalWriteScope" in authorization_schema["$defs"]
    scope_properties = authorization_schema["$defs"]["AuthorizationScope"]["properties"]
    assert "resume_checkpoint_digest" in scope_properties
    assert "resume_step_id" in scope_properties
    requirement_schema = json.loads(
        (tmp_path / "requirement-spec.schema.json").read_text(encoding="utf-8")
    )
    assert requirement_schema["properties"]["steps"]["minItems"] == 1
    assert "PendingConfirmation" in requirement_schema["$defs"]
    assert "UnresolvedInstruction" in requirement_schema["$defs"]

    checked_in = Path(__file__).parents[1] / "src" / "rpa_core" / "schemas"
    for filename, expected in schema_documents().items():
        actual = json.loads((checked_in / filename).read_text(encoding="utf-8"))
        assert actual == expected, f"checked-in schema drift: {filename}"
