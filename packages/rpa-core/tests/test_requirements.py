from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from rpa_core.contracts import AppManifest, RequirementSpec
from rpa_core.requirements import (
    CanonicalRequirementBlockError,
    ContractLoadError,
    DiffKind,
    RequirementConsistencyError,
    compare_requirement_models,
    compute_requirement_hash,
    load_app_manifest,
    load_requirement_memory,
    load_requirement_spec,
    validate_requirement_consistency,
)


def _requirement_document() -> dict[str, object]:
    document: dict[str, object] = {
        "schema_version": 1,
        "source": {
            "document_id": "redacted-doc",
            "revision": 12,
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
                "inputs": ["fixture_path"],
                "outputs": ["records"],
                "success_conditions": ["records_loaded"],
                "side_effect": "read",
            }
        ],
        "outputs": [],
        "pending_confirmations": [],
        "unresolved_elements": [],
    }
    digest = compute_requirement_hash(document)
    document["source"]["requirement_hash"] = digest  # type: ignore[index]
    return document


def _memory_markdown(document: dict[str, object]) -> str:
    source = document["source"]  # type: ignore[assignment]
    application = document["application"]  # type: ignore[assignment]
    step = document["steps"][0]  # type: ignore[index]
    return f'''# Requirement memory

Human-readable explanation may appear before and after the canonical block.

```toml requirement-canonical
schema_version = 1

[source]
document_id = "{source['document_id']}"
revision = {source['revision']}
requirement_hash = "{source['requirement_hash']}"

[application]
app_id = "{application['app_id']}"
app_slug = "{application['app_slug']}"
name = "{application['name']}"
version = "{application['version']}"
entrypoint = "{application['entrypoint']}"

[[steps]]
id = "{step['id']}"
name = "{step['name']}"
action = "{step['action']}"
inputs = ["fixture_path"]
outputs = ["records"]
success_conditions = ["records_loaded"]
side_effect = "read"
```
'''


def _write_pair(
    directory: Path,
    document: dict[str, object] | None = None,
) -> tuple[Path, Path, dict[str, object]]:
    value = deepcopy(document or _requirement_document())
    memory_path = directory / "REQUIREMENT_MEMORY.md"
    spec_path = directory / "requirement.spec.json"
    memory_path.write_text(_memory_markdown(value), encoding="utf-8")
    spec_path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return memory_path, spec_path, value


def _manifest(requirement: dict[str, object]) -> AppManifest:
    source = requirement["source"]  # type: ignore[assignment]
    application = requirement["application"]  # type: ignore[assignment]
    return AppManifest.model_validate(
        {
            "schema_version": 1,
            "app_id": application["app_id"],
            "app_slug": application["app_slug"],
            "name": application["name"],
            "version": application["version"],
            "entrypoint": application["entrypoint"],
            "python": "3.12",
            "requirement_revision": source["revision"],
            "requirement_hash": source["requirement_hash"],
            "status": "draft",
        }
    )


def test_hash_is_canonical_and_does_not_hash_itself() -> None:
    first = _requirement_document()
    second = {
        "steps": first["steps"],
        "application": first["application"],
        "schema_version": first["schema_version"],
        "unresolved_elements": first["unresolved_elements"],
        "pending_confirmations": first["pending_confirmations"],
        "outputs": first["outputs"],
        "source": {
            "requirement_hash": "sha256:" + ("f" * 64),
            "revision": 12,
            "document_id": "redacted-doc",
        },
    }

    assert compute_requirement_hash(first) == compute_requirement_hash(second)
    assert compute_requirement_hash(first).startswith("sha256:")
    assert len(compute_requirement_hash(first)) == 71


def test_memory_and_json_load_as_same_model(tmp_path: Path) -> None:
    memory_path, spec_path, _ = _write_pair(tmp_path)

    memory = load_requirement_memory(memory_path)
    spec = load_requirement_spec(spec_path)

    assert isinstance(memory, RequirementSpec)
    assert compare_requirement_models(memory, spec) == []


def test_memory_requires_exactly_one_canonical_toml_block(tmp_path: Path) -> None:
    memory_path = tmp_path / "REQUIREMENT_MEMORY.md"
    memory_path.write_text("# No canonical data\n", encoding="utf-8")
    with pytest.raises(CanonicalRequirementBlockError, match="found 0"):
        load_requirement_memory(memory_path)

    document = _requirement_document()
    block = _memory_markdown(document)
    memory_path.write_text(block + "\n" + block, encoding="utf-8")
    with pytest.raises(CanonicalRequirementBlockError, match="found 2"):
        load_requirement_memory(memory_path)


def test_unrelated_toml_fence_is_not_treated_as_canonical(tmp_path: Path) -> None:
    document = _requirement_document()
    memory_path = tmp_path / "REQUIREMENT_MEMORY.md"
    memory_path.write_text(
        "```toml\nexample = true\n```\n\n" + _memory_markdown(document),
        encoding="utf-8",
    )

    assert load_requirement_memory(memory_path).application.app_id == "example.offline_export"


def test_compare_returns_field_level_paths() -> None:
    memory = _requirement_document()
    spec = deepcopy(memory)
    spec["steps"][0]["name"] = "Read local fixture"  # type: ignore[index]
    spec["source"]["requirement_hash"] = compute_requirement_hash(spec)  # type: ignore[index]

    differences = compare_requirement_models(memory, spec)
    indexed = {difference.path: difference for difference in differences}

    assert indexed["$.steps[0].name"].kind is DiffKind.CHANGED
    assert indexed["$.steps[0].name"].memory_value == "Load fixture"
    assert indexed["$.steps[0].name"].spec_value == "Read local fixture"
    assert "$.source.requirement_hash" in indexed


def test_consistency_gate_returns_validated_spec(tmp_path: Path) -> None:
    memory_path, spec_path, requirement = _write_pair(tmp_path)

    result = validate_requirement_consistency(
        memory_path,
        spec_path,
        manifest=_manifest(requirement),
    )

    assert result.application.app_id == "example.offline_export"


def test_consistency_gate_reports_stale_json_and_hash(tmp_path: Path) -> None:
    memory_path, spec_path, requirement = _write_pair(tmp_path)
    requirement["steps"][0]["name"] = "Changed only in JSON"  # type: ignore[index]
    spec_path.write_text(json.dumps(requirement), encoding="utf-8")

    with pytest.raises(RequirementConsistencyError) as caught:
        validate_requirement_consistency(memory_path, spec_path)

    assert any("$.steps[0].name" in issue for issue in caught.value.issues)
    assert any("spec requirement_hash" in issue for issue in caught.value.issues)
    assert any(diff.path == "$.steps[0].name" for diff in caught.value.diffs)


def test_consistency_gate_rejects_open_blocking_items(tmp_path: Path) -> None:
    requirement = _requirement_document()
    requirement["steps"][0]["pending_confirmation_ids"] = ["PC-001"]  # type: ignore[index]
    requirement["pending_confirmations"] = [
        {
            "id": "PC-001",
            "requirement_step": "load_fixture",
            "question": "Which source file is authoritative?",
            "risk": "The wrong fixture may be processed.",
        }
    ]
    requirement["source"]["requirement_hash"] = compute_requirement_hash(requirement)  # type: ignore[index]
    memory_path, spec_path, _ = _write_pair(tmp_path, requirement)

    with pytest.raises(RequirementConsistencyError, match="PC-001"):
        validate_requirement_consistency(memory_path, spec_path)


def test_json_loader_rejects_duplicate_keys(tmp_path: Path) -> None:
    path = tmp_path / "requirement.spec.json"
    path.write_text('{"schema_version": 1, "schema_version": 1}', encoding="utf-8")

    with pytest.raises(ContractLoadError, match="duplicate JSON key"):
        load_requirement_spec(path)


def test_app_manifest_loader_validates_toml(tmp_path: Path) -> None:
    requirement = _requirement_document()
    manifest = _manifest(requirement)
    path = tmp_path / "app.toml"
    path.write_text(
        f'''schema_version = 1
app_id = "{manifest.app_id}"
app_slug = "{manifest.app_slug}"
name = "{manifest.name}"
version = "{manifest.version}"
entrypoint = "{manifest.entrypoint}"
python = "3.12"
requirement_revision = {manifest.requirement_revision}
requirement_hash = "{manifest.requirement_hash}"
configuration_schema = "config/config.schema.json"
status = "draft"
latest_review = ""

[commands]
doctor = "rpa-app doctor"
check = "rpa-app check"
test = "rpa-app test"
preview = "rpa-app run --mode preview"
live = "rpa-app run --mode live"
resume = "rpa-app resume"
''',
        encoding="utf-8",
    )

    assert load_app_manifest(path) == manifest
