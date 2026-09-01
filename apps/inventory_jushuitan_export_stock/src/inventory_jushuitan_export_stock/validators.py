"""Application preflight gates shared by CLI commands and tests."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import platform
import sys

from rpa_core import __version__ as core_version
from rpa_core.catalog import verify_catalog_snapshot
from rpa_core.discovery import ValidationReport, validate_application_in_repository
from rpa_core.requirements import (
    compare_requirement_models,
    compute_requirement_hash,
    load_app_manifest,
    load_requirement_memory,
    load_requirement_spec,
)


APP_DIR = Path(__file__).resolve().parents[2]


class RunBlockedError(RuntimeError):
    error_code = "application_run_blocked"

    def __init__(self, blocker_ids: tuple[str, ...]) -> None:
        super().__init__("real run is blocked by unresolved requirement items")
        self.blocker_ids = blocker_ids


@dataclass(frozen=True, slots=True)
class DoctorReport:
    app_dir: str
    python: str
    python_supported: bool
    rpa_core: str
    local_store_config_exists: bool
    catalog_snapshot_valid: bool
    candidate_blockers: tuple[str, ...]
    real_browser_launched: bool = False

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def requirement_paths(app_dir: Path = APP_DIR) -> tuple[Path, Path]:
    requirement_dir = app_dir / "requirement"
    return requirement_dir / "REQUIREMENT_MEMORY.md", requirement_dir / "requirement.spec.json"


def load_validated_contracts(app_dir: Path = APP_DIR):
    manifest = load_app_manifest(app_dir / "app.toml")
    memory_path, spec_path = requirement_paths(app_dir)
    memory = load_requirement_memory(memory_path)
    spec = load_requirement_spec(spec_path)
    differences = compare_requirement_models(memory, spec)
    if differences:
        locations = ", ".join(item.path for item in differences[:8])
        raise ValueError(f"Memory and Spec differ at: {locations}")
    computed = compute_requirement_hash(spec)
    declared = {
        memory.source.requirement_hash,
        spec.source.requirement_hash,
        manifest.requirement_hash,
    }
    if declared != {computed}:
        raise ValueError("manifest, Memory and Spec requirement hashes are not aligned")
    if manifest.requirement_revision != spec.source.revision:
        raise ValueError("manifest requirement revision does not match Spec")
    verify_catalog_snapshot(app_dir, manifest.catalog_lock)
    return manifest, spec


def ensure_real_run_ready(app_dir: Path = APP_DIR) -> None:
    _, spec = load_validated_contracts(app_dir)
    if spec.has_blockers:
        raise RunBlockedError(spec.blocking_item_ids)


def application_report(app_dir: Path = APP_DIR) -> ValidationReport:
    return validate_application_in_repository(app_dir)


def doctor(app_dir: Path = APP_DIR) -> DoctorReport:
    snapshot_valid = False
    blockers: tuple[str, ...] = ()
    try:
        _, spec = load_validated_contracts(app_dir)
        snapshot_valid = True
        blockers = spec.blocking_item_ids
    except Exception:
        pass
    return DoctorReport(
        app_dir="<application-root>",
        python=platform.python_version(),
        python_supported=sys.version_info[:2] == (3, 12),
        rpa_core=core_version,
        local_store_config_exists=(app_dir / "config" / "stores.local.toml").is_file(),
        catalog_snapshot_valid=snapshot_valid,
        candidate_blockers=blockers,
    )


__all__ = [
    "APP_DIR",
    "DoctorReport",
    "RunBlockedError",
    "application_report",
    "doctor",
    "ensure_real_run_ready",
    "load_validated_contracts",
    "requirement_paths",
]
