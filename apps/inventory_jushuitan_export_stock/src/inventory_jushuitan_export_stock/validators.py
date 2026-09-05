"""Side-effect-free application contract validation."""

from __future__ import annotations

from pathlib import Path

from rpa_core.discovery import ValidationReport, validate_application_in_repository
from rpa_core.requirements import (
    compute_requirement_hash,
    load_app_manifest,
    load_requirement_memory,
)


APP_DIR = Path(__file__).resolve().parents[2]


def load_validated_contracts(app_dir: Path = APP_DIR):
    manifest = load_app_manifest(app_dir / "app.toml")
    requirement = load_requirement_memory(app_dir / "requirement.md")
    computed = compute_requirement_hash(requirement)
    if manifest.schema_version != 1 or requirement.schema_version != 1:
        raise ValueError("shared CLI applications require compact schema_version 1")
    if requirement.source.requirement_hash != computed:
        raise ValueError("requirement hash does not match canonical content")
    if manifest.requirement_hash != computed:
        raise ValueError("manifest and requirement hashes are not aligned")
    if manifest.requirement_revision != requirement.source.revision:
        raise ValueError("manifest requirement revision does not match requirement")
    if manifest.app_id != requirement.application.app_id:
        raise ValueError("manifest and requirement application IDs differ")
    if manifest.version != requirement.application.version:
        raise ValueError("manifest and requirement application versions differ")
    return manifest, requirement


def application_report(app_dir: Path = APP_DIR) -> ValidationReport:
    return validate_application_in_repository(app_dir)


__all__ = ["APP_DIR", "application_report", "load_validated_contracts"]
