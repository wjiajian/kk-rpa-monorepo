from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from rpa_core.catalog import (
    CatalogConflictError,
    CatalogContractError,
    CatalogDependencyError,
    CatalogIntegrityError,
    CatalogLock,
    CatalogPathError,
    discover_catalog,
    snapshot_catalog,
    verify_catalog_snapshot,
)


def _write_element(
    repository: Path,
    *,
    item_id: str = "example.web.login.account",
    dependencies: tuple[str, ...] = (),
) -> Path:
    path = repository / "elements" / "example" / "web" / "login" / "account.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    dependency_text = ", ".join(json.dumps(value) for value in dependencies)
    path.write_text(
        f'''schema_version = 1
kind = "element"
id = "{item_id}"
version = "1.0.0"
name = "Login account"
platform = "example"
product = "web"
status = "verified"
dependencies = [{dependency_text}]

[locator]
strategy = "css"
value = "#login_id"

[verification]
match_count = 1
visible = true
''',
        encoding="utf-8",
    )
    return path


def _write_instruction(
    repository: Path,
    *,
    item_id: str = "example.web.open_login",
    dependencies: tuple[str, ...] = ("element:example.web.login.account",),
) -> Path:
    directory = repository / "instructions" / "example" / "web" / "open_login"
    directory.mkdir(parents=True, exist_ok=True)
    dependency_text = ", ".join(json.dumps(value) for value in dependencies)
    (directory / "instruction.toml").write_text(
        f'''schema_version = 1
kind = "instruction"
id = "{item_id}"
version = "1.0.0"
name = "Open login"
platform = "example"
product = "web"
status = "verified"
entrypoint = "instruction.py:OpenLogin"
dependencies = [{dependency_text}]
''',
        encoding="utf-8",
    )
    (directory / "instruction.py").write_text(
        "class OpenLogin:\n    pass\n",
        encoding="utf-8",
    )
    return directory


def test_discovery_resolves_instruction_dependency_closure(tmp_path: Path) -> None:
    _write_element(tmp_path)
    _write_instruction(tmp_path)

    index = discover_catalog(tmp_path)
    closure = index.dependency_closure(["instruction:example.web.open_login"])

    assert [str(item.ref) for item in closure] == [
        "element:example.web.login.account",
        "instruction:example.web.open_login",
    ]


def test_snapshot_is_frozen_from_source_and_detects_local_tampering(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repository"
    application = repository / "apps" / "example_app"
    application.mkdir(parents=True)
    source_element = _write_element(repository)
    _write_instruction(repository)

    lock = snapshot_catalog(
        repository,
        application,
        "example_app",
        ["instruction:example.web.open_login"],
    )

    assert len(lock.items) == 2
    assert all(item.copied_at for item in lock.items)
    assert verify_catalog_snapshot(application) == lock
    source_element.write_text(source_element.read_text(encoding="utf-8") + "\n# changed\n")
    assert verify_catalog_snapshot(application) == lock

    copied_element = (
        application
        / "src"
        / "example_app"
        / "elements"
        / "example"
        / "web"
        / "login"
        / "account.toml"
    )
    copied_element.write_text("tampered\n", encoding="utf-8")
    with pytest.raises(CatalogIntegrityError, match="hash mismatch"):
        verify_catalog_snapshot(application)


def test_instruction_snapshot_ignores_only_generated_python_bytecode(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repository"
    application = repository / "apps" / "example_app"
    application.mkdir(parents=True)
    _write_element(repository)
    source_instruction = _write_instruction(repository)
    source_cache = source_instruction / "__pycache__"
    source_cache.mkdir()
    (source_cache / "instruction.cpython-312.pyc").write_bytes(b"generated")

    lock = snapshot_catalog(
        repository,
        application,
        "example_app",
        ["instruction:example.web.open_login"],
    )
    copied_instruction = (
        application
        / "src"
        / "example_app"
        / "instructions"
        / "example"
        / "web"
        / "open_login"
    )
    assert not (copied_instruction / "__pycache__").exists()

    runtime_cache = copied_instruction / "__pycache__"
    runtime_cache.mkdir()
    (runtime_cache / "instruction.cpython-312.pyc").write_bytes(b"generated")
    assert verify_catalog_snapshot(application) == lock

    (copied_instruction / "unexpected.py").write_text("unexpected\n", encoding="utf-8")
    with pytest.raises(CatalogIntegrityError, match="hash mismatch"):
        verify_catalog_snapshot(application)


def test_snapshot_never_overwrites_existing_lock_or_target(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    application = repository / "apps" / "example_app"
    application.mkdir(parents=True)
    _write_element(repository)

    snapshot_catalog(
        repository,
        application,
        "example_app",
        ["element:example.web.login.account"],
    )

    with pytest.raises(CatalogConflictError, match="lock already exists"):
        snapshot_catalog(
            repository,
            application,
            "example_app",
            ["element:example.web.login.account"],
        )


def test_snapshot_rejects_symlinked_destination_parent_before_copy(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repository"
    application = repository / "apps" / "example_app"
    application.mkdir(parents=True)
    _write_element(repository)
    external = tmp_path / "external"
    external.mkdir()
    package_root = application / "src" / "example_app"
    package_root.mkdir(parents=True)
    (package_root / "elements").symlink_to(external, target_is_directory=True)

    with pytest.raises(CatalogPathError, match="destination.*symbolic links"):
        snapshot_catalog(
            repository,
            application,
            "example_app",
            ["element:example.web.login.account"],
        )

    assert list(external.iterdir()) == []
    assert not (application / "catalog.lock.json").exists()


def test_catalog_rejects_unknown_dependency_cycle_and_duplicate_id(
    tmp_path: Path,
) -> None:
    _write_element(tmp_path, dependencies=("element:example.web.missing",))
    with pytest.raises(CatalogDependencyError, match="unknown dependencies"):
        discover_catalog(tmp_path)

    cycle_repo = tmp_path / "cycle"
    _write_element(
        cycle_repo,
        item_id="example.web.login.account",
        dependencies=("instruction:example.web.open_login",),
    )
    _write_instruction(cycle_repo)
    with pytest.raises(CatalogDependencyError, match="cycle"):
        discover_catalog(cycle_repo)

    duplicate_repo = tmp_path / "duplicate"
    first = _write_element(duplicate_repo)
    second = (
        duplicate_repo
        / "elements"
        / "example"
        / "web"
        / "other"
        / "duplicate.toml"
    )
    second.parent.mkdir(parents=True)
    second.write_text(first.read_text(encoding="utf-8"), encoding="utf-8")
    with pytest.raises(CatalogConflictError, match="duplicate source catalog ID"):
        discover_catalog(duplicate_repo)


def test_catalog_ids_are_globally_unique_across_kinds(tmp_path: Path) -> None:
    _write_element(tmp_path, item_id="example.web.shared")
    _write_instruction(
        tmp_path,
        item_id="example.web.shared",
        dependencies=(),
    )

    with pytest.raises(CatalogConflictError, match="globally unique"):
        discover_catalog(tmp_path)


def test_catalog_rejects_path_escape_symlink_and_hardlink(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="normalized relative"):
        CatalogLock.model_validate(
            {
                "items": [
                    {
                        "kind": "element",
                        "id": "example.web.login.account",
                        "version": "1.0.0",
                        "status": "verified",
                        "source_type": "repository",
                        "source_path": "elements/example.toml",
                        "target_path": "../outside.toml",
                        "content_hash": "sha256:" + ("0" * 64),
                    }
                ]
            }
        )

    symlink_repo = tmp_path / "symlink"
    target = tmp_path / "outside.toml"
    target.write_text("outside\n", encoding="utf-8")
    symlink = (
        symlink_repo / "elements" / "example" / "web" / "login" / "account.toml"
    )
    symlink.parent.mkdir(parents=True)
    symlink.symlink_to(target)
    with pytest.raises(CatalogPathError, match="symbolic links"):
        discover_catalog(symlink_repo)

    hardlink_repo = tmp_path / "hardlink"
    hardlink = (
        hardlink_repo / "elements" / "example" / "web" / "login" / "account.toml"
    )
    hardlink.parent.mkdir(parents=True)
    original = tmp_path / "original.toml"
    original.write_text(_write_element(tmp_path / "template").read_text(encoding="utf-8"))
    os.link(original, hardlink)
    with pytest.raises(CatalogPathError, match="hard link"):
        discover_catalog(hardlink_repo)


def test_snapshot_verification_rejects_symlinked_lock(tmp_path: Path) -> None:
    application = tmp_path / "application"
    application.mkdir()
    external_lock = tmp_path / "external-lock.json"
    external_lock.write_text('{"schema_version": 1, "items": []}\n', encoding="utf-8")
    (application / "catalog.lock.json").symlink_to(external_lock)

    with pytest.raises(CatalogPathError, match="symbolic links"):
        verify_catalog_snapshot(application)


def test_instruction_requires_implementation_and_valid_entrypoint(tmp_path: Path) -> None:
    directory = _write_instruction(tmp_path, dependencies=())
    (directory / "instruction.py").unlink()
    with pytest.raises(CatalogIntegrityError, match="missing"):
        discover_catalog(tmp_path)

    directory = _write_instruction(tmp_path, dependencies=())
    metadata = directory / "instruction.toml"
    metadata.write_text(
        metadata.read_text(encoding="utf-8").replace(
            "instruction.py:OpenLogin", "other.py:OpenLogin"
        ),
        encoding="utf-8",
    )
    with pytest.raises(CatalogContractError, match="entrypoint"):
        discover_catalog(tmp_path)
