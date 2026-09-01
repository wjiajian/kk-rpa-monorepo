from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from rpa_core.contracts import (
    AppManifest,
    AppStatus,
    ConfirmationStatus,
    RequirementSpec,
    ResumePolicy,
    SideEffect,
)
from rpa_core.schema_export import export_schemas


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
    assert manifest.commands.preview == "rpa-app run --mode preview"
    assert manifest.commands.live == "rpa-app run --mode live"


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


def test_checked_in_schema_export_is_json_and_contains_contracts(tmp_path) -> None:
    paths = export_schemas(tmp_path)

    assert {path.name for path in paths} == {
        "app-manifest.schema.json",
        "requirement-spec.schema.json",
    }
    requirement_schema = json.loads(
        (tmp_path / "requirement-spec.schema.json").read_text(encoding="utf-8")
    )
    assert requirement_schema["properties"]["steps"]["minItems"] == 1
    assert "PendingConfirmation" in requirement_schema["$defs"]
