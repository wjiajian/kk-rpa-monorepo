from __future__ import annotations

import json
from pathlib import Path

from rpa_core.catalog import CatalogLock, hash_catalog_path
from rpa_core.contracts import AppManifest, RequirementSpec
from rpa_core.discovery import (
    ValidationReport,
    _validate_requirement_pair,
    _validate_v2_catalog_references,
    discover_applications,
    ensure_application_identity_available,
    issue_codes,
    scan_application_architecture,
    scan_sensitive_content,
    validate_application_in_repository,
)
from rpa_core.requirements import compute_requirement_hash


def _write_minimal_manifest(path: Path, *, app_id: str, slug: str) -> None:
    path.parent.mkdir(parents=True)
    path.write_text(
        f'''schema_version = 1
app_id = "{app_id}"
app_slug = "{slug}"
name = "Example"
version = "0.1.0"
entrypoint = "{slug}.cli:main"
python = "3.12"
requirement_revision = 1
requirement_hash = "sha256:{'0' * 64}"
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


def test_discovery_reports_duplicate_app_id(tmp_path: Path) -> None:
    repo = tmp_path
    _write_minimal_manifest(
        repo / "apps" / "first" / "app.toml",
        app_id="example.duplicate",
        slug="first",
    )
    _write_minimal_manifest(
        repo / "apps" / "second" / "app.toml",
        app_id="example.duplicate",
        slug="second",
    )

    apps, report = discover_applications(repo)

    assert [app.directory.name for app in apps] == ["first", "second"]
    assert "APP_ID_CONFLICT" in issue_codes(report.issues)


def test_identity_guard_rejects_existing_directory(tmp_path: Path) -> None:
    (tmp_path / "apps" / "existing").mkdir(parents=True)

    try:
        ensure_application_identity_available(tmp_path, "example.new", "existing")
    except FileExistsError as exc:
        assert "already exists" in str(exc)
    else:  # pragma: no cover - defensive failure message
        raise AssertionError("existing directory was not rejected")


def test_application_validation_requires_safe_standard_skeleton(tmp_path: Path) -> None:
    from rpa_core.discovery import validate_application

    report = validate_application(tmp_path, require_lock=True)
    missing = {issue.message for issue in report.issues}

    assert "missing required file: .env.example" in missing
    assert "missing required file: .gitignore" in missing
    assert "missing required file: config/stores.example.toml" in missing
    assert "missing required directory: requirement/assets" in missing
    assert "missing required directory: reviews" in missing


def test_architecture_scan_rejects_direct_driver_and_element_click(
    tmp_path: Path,
) -> None:
    source = tmp_path / "src" / "bad_app" / "program.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        "from DrissionPage import Chromium\n"
        "def bad(page):\n"
        "    page.ele('#submit').click()\n",
        encoding="utf-8",
    )

    issues = scan_application_architecture(tmp_path)

    assert issue_codes(issues) == {
        "APP_FORBIDDEN_IMPORT",
        "APP_DIRECT_ELEMENT_ACTION",
    }


def test_architecture_scan_rejects_runtime_import_from_top_level_catalog(
    tmp_path: Path,
) -> None:
    source = tmp_path / "src" / "bad_app" / "program.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        "from instructions.shared import OpenPage\n"
        "import elements\n",
        encoding="utf-8",
    )

    issues = scan_application_architecture(tmp_path)

    assert issue_codes(issues) == {"APP_RUNTIME_SOURCE_CATALOG_IMPORT"}
    assert len(issues) == 2


def test_architecture_scan_rejects_driver_import_in_copied_instruction(
    tmp_path: Path,
) -> None:
    source = (
        tmp_path
        / "src"
        / "example_app"
        / "instructions"
        / "example"
        / "web"
        / "open_page"
        / "instruction.py"
    )
    source.parent.mkdir(parents=True)
    source.write_text("from DrissionPage import Chromium\n", encoding="utf-8")

    issues = scan_application_architecture(tmp_path)

    assert issue_codes(issues) == {"APP_FORBIDDEN_IMPORT"}


def test_architecture_scan_rejects_hardcoded_port_and_profile(tmp_path: Path) -> None:
    source = tmp_path / "src" / "bad_app" / "browser.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        "def configure(options):\n"
        "    debug_port = 9222\n"
        "    profile_path = 'profiles/STORE_001'\n"
        "    options.set_local_port(9333)\n"
        "    options.set_user_data_path('profiles/STORE_002')\n",
        encoding="utf-8",
    )

    issues = scan_application_architecture(tmp_path)

    assert issue_codes(issues) == {
        "APP_HARDCODED_BROWSER_PORT",
        "APP_HARDCODED_BROWSER_PROFILE",
    }


def test_sensitive_scan_includes_fixtures_and_env_example(tmp_path: Path) -> None:
    fixture = tmp_path / "tests" / "fixtures" / "secret.json"
    fixture.parent.mkdir(parents=True)
    fixture.write_text('{"api_key": "real-looking-secret-value"}\n', encoding="utf-8")
    env_example = tmp_path / ".env.example"
    env_example.write_text("TOKEN=real-looking-token-value\n", encoding="utf-8")

    issues = scan_sensitive_content(tmp_path)

    assert len(issues) == 2
    assert issue_codes(issues) == {"APP_SENSITIVE_CONTENT"}
    assert {Path(issue.path).name for issue in issues} == {"secret.json", ".env.example"}


def test_requirement_blockers_keep_dedicated_issue_codes(tmp_path: Path) -> None:
    document = {
        "schema_version": 1,
        "source": {"document_id": "redacted-doc", "revision": 1},
        "application": {
            "app_id": "example.blocked",
            "app_slug": "example_blocked",
            "name": "Blocked example",
            "version": "0.1.0",
            "entrypoint": "example_blocked.cli:main",
        },
        "steps": [
            {
                "id": "S001",
                "name": "Blocked step",
                "action": "read_fixture",
                "success_conditions": ["fixture_loaded"],
                "pending_confirmation_ids": ["PC-001"],
            }
        ],
        "outputs": [],
        "pending_confirmations": [
            {
                "id": "PC-001",
                "requirement_step": "S001",
                "question": "Which fixture is authoritative?",
                "risk": "The wrong input may be processed.",
            }
        ],
        "unresolved_elements": [],
    }
    digest = compute_requirement_hash(document)
    document["source"]["requirement_hash"] = digest
    requirement_dir = tmp_path / "requirement"
    requirement_dir.mkdir()
    (requirement_dir / "requirement.spec.json").write_text(
        json.dumps(document),
        encoding="utf-8",
    )
    (requirement_dir / "REQUIREMENT_MEMORY.md").write_text(
        f'''# Blocked requirement

```toml requirement-canonical
schema_version = 1
pending_confirmations = [{{ id = "PC-001", requirement_step = "S001", question = "Which fixture is authoritative?", risk = "The wrong input may be processed." }}]
unresolved_elements = []

[source]
document_id = "redacted-doc"
revision = 1
requirement_hash = "{digest}"

[application]
app_id = "example.blocked"
app_slug = "example_blocked"
name = "Blocked example"
version = "0.1.0"
entrypoint = "example_blocked.cli:main"

[[steps]]
id = "S001"
name = "Blocked step"
action = "read_fixture"
success_conditions = ["fixture_loaded"]
pending_confirmation_ids = ["PC-001"]
```
''',
        encoding="utf-8",
    )
    manifest = AppManifest.model_validate(
        {
            "app_id": "example.blocked",
            "app_slug": "example_blocked",
            "name": "Blocked example",
            "version": "0.1.0",
            "entrypoint": "example_blocked.cli:main",
            "python": "3.12",
            "requirement_revision": 1,
            "requirement_hash": digest,
            "status": "ready_for_review",
        }
    )
    report = ValidationReport()

    _validate_requirement_pair(tmp_path, manifest, report)

    codes = issue_codes(report.issues)
    assert "PENDING_CONFIRMATION_OPEN" in codes
    assert "APP_STATUS_BLOCKER_CONFLICT" in codes


def test_scoped_validation_does_not_validate_unrelated_draft_application(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repository = tmp_path
    (repository / "AGENTS.md").write_text("# test\n", encoding="utf-8")
    current = repository / "apps" / "current"
    sibling = repository / "apps" / "sibling"
    _write_minimal_manifest(
        current / "app.toml", app_id="example.current", slug="current"
    )
    _write_minimal_manifest(
        sibling / "app.toml", app_id="example.sibling", slug="sibling"
    )

    validated: list[Path] = []

    def fake_validate(path: Path, *, require_lock: bool = True) -> ValidationReport:
        validated.append(path.resolve())
        report = ValidationReport(applications=["example.current"])
        if path.resolve() == sibling.resolve():
            report.add("UNRELATED_DRAFT_BLOCKER", "must not be evaluated")
        return report

    monkeypatch.setattr("rpa_core.discovery.validate_application", fake_validate)

    report = validate_application_in_repository(current)

    assert report.ok
    assert validated == [current.resolve()]


def test_v2_candidate_instruction_requires_locked_implementation_and_fake_test(
    tmp_path: Path,
) -> None:
    app_dir = tmp_path / "example_app"
    instruction_dir = (
        app_dir
        / "src"
        / "example_app"
        / "instructions"
        / "example"
        / "web"
        / "open_page"
    )
    instruction_dir.mkdir(parents=True)
    implementation = instruction_dir / "instruction.py"
    implementation.write_text("class OpenPage:\n    pass\n", encoding="utf-8")
    fake_test = app_dir / "tests" / "test_candidate_open_page.py"
    fake_test.parent.mkdir(parents=True)
    fake_test.write_text("def test_candidate():\n    assert True\n", encoding="utf-8")

    lock = CatalogLock.model_validate(
        {
            "items": [
                {
                    "kind": "instruction",
                    "id": "example.web.open_page",
                    "version": "0.1.0",
                    "status": "candidate",
                    "source_type": "application_candidate",
                    "source_path": (
                        "src/example_app/instructions/example/web/open_page"
                    ),
                    "target_path": (
                        "src/example_app/instructions/example/web/open_page"
                    ),
                    "content_hash": hash_catalog_path(instruction_dir, app_dir),
                }
            ]
        }
    )
    (app_dir / "catalog.lock.json").write_text(
        json.dumps(lock.model_dump(mode="json")),
        encoding="utf-8",
    )
    manifest = AppManifest.model_validate(
        {
            "schema_version": 2,
            "app_id": "example.app",
            "app_slug": "example_app",
            "name": "Example",
            "version": "0.1.0",
            "entrypoint": "example_app.cli:main",
            "python": "3.12",
            "requirement_revision": 1,
            "requirement_hash": "sha256:" + ("0" * 64),
            "catalog_lock": "catalog.lock.json",
            "commands": {
                "login": "rpa-app login",
                "verify_candidates": "rpa-app verify-candidates",
            },
        }
    )
    requirement = RequirementSpec.model_validate(
        {
            "schema_version": 2,
            "source": {
                "document_id": "redacted",
                "revision": 1,
                "requirement_hash": "sha256:" + ("0" * 64),
            },
            "application": {
                "app_id": "example.app",
                "app_slug": "example_app",
                "name": "Example",
                "version": "0.1.0",
                "entrypoint": "example_app.cli:main",
            },
            "steps": [
                {
                    "id": "S001",
                    "name": "Open page",
                    "action": "open_page",
                    "success_conditions": ["page_open"],
                    "unresolved_instruction_ids": ["UI-001"],
                }
            ],
            "unresolved_instructions": [
                {
                    "id": "UI-001",
                    "requirement_step": "S001",
                    "platform": "example",
                    "capability": "open page",
                    "reason": "not in source catalog",
                    "candidate_instruction_ref": "example.web.open_page",
                    "candidate_implementation": (
                        "src/example_app/instructions/example/web/open_page/instruction.py"
                    ),
                    "fake_test_ref": "tests/test_candidate_open_page.py",
                    "fake_test_status": "passed",
                    "status": "candidate",
                }
            ],
        }
    )
    report = ValidationReport()

    _validate_v2_catalog_references(app_dir, manifest, requirement, report)

    assert report.ok
    fake_test.unlink()
    _validate_v2_catalog_references(app_dir, manifest, requirement, report)
    assert "APP_CANDIDATE_INSTRUCTION_TEST_MISSING" in issue_codes(report.issues)
