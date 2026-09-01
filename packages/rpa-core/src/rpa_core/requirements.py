"""Load and compare the two canonical requirement representations.

``REQUIREMENT_MEMORY.md`` is the human-editable source.  It contains exactly
one fenced ``toml requirement-canonical`` block.  ``requirement.spec.json`` is
the generated machine representation.  Both are parsed into
:class:`~rpa_core.contracts.RequirementSpec` before they are compared, so TOML
and JSON formatting never affects the result or its SHA-256 hash.
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
import json
from pathlib import Path
import re
import tomllib
from typing import Any

from pydantic import BaseModel, ValidationError

from rpa_core.contracts import AppManifest, RequirementSpec


CANONICAL_REQUIREMENT_FENCE = "toml requirement-canonical"
_ZERO_HASH = "sha256:" + ("0" * 64)
_CANONICAL_BLOCK_PATTERN = re.compile(
    r"(?ms)^[ \t]*(?P<fence>`{3,}|~{3,})[ \t]*toml[ \t]+"
    r"requirement-canonical[ \t]*\r?\n"
    r"(?P<body>.*?)"
    r"(?:\r?\n)?^[ \t]*(?P=fence)[ \t]*$"
)


class RequirementError(ValueError):
    """Base class for deterministic requirement-contract failures."""


class ContractLoadError(RequirementError):
    """A persisted contract could not be decoded or validated."""


class CanonicalRequirementBlockError(ContractLoadError):
    """The Markdown memory does not contain exactly one canonical block."""


class DiffKind(StrEnum):
    ADDED = "added"
    REMOVED = "removed"
    CHANGED = "changed"


@dataclass(frozen=True, slots=True)
class RequirementDiff:
    """One field-level difference between memory and generated JSON."""

    path: str
    kind: DiffKind
    memory_value: Any = None
    spec_value: Any = None
    memory_present: bool = True
    spec_present: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "kind": self.kind.value,
            "memory_value": self.memory_value,
            "spec_value": self.spec_value,
            "memory_present": self.memory_present,
            "spec_present": self.spec_present,
        }


class RequirementConsistencyError(RequirementError):
    """The requirement pair, its hash, blockers, or manifest do not agree."""

    def __init__(
        self,
        issues: list[str],
        *,
        diffs: list[RequirementDiff] | None = None,
    ) -> None:
        self.issues = tuple(issues)
        self.diffs = tuple(diffs or ())
        details = "; ".join(issues)
        super().__init__(f"requirement consistency check failed: {details}")


def load_app_manifest(path: str | Path) -> AppManifest:
    """Load and validate an application's ``app.toml``."""

    source = Path(path)
    try:
        document = tomllib.loads(source.read_text(encoding="utf-8"))
        return AppManifest.model_validate(document)
    except (OSError, UnicodeError, tomllib.TOMLDecodeError, ValidationError) as error:
        raise ContractLoadError(f"invalid app manifest {source}: {error}") from error


def load_requirement_memory(path: str | Path) -> RequirementSpec:
    """Load the sole canonical TOML block from ``REQUIREMENT_MEMORY.md``."""

    source = Path(path)
    try:
        markdown = source.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise ContractLoadError(f"cannot read requirement memory {source}: {error}") from error

    blocks = [match.group("body") for match in _CANONICAL_BLOCK_PATTERN.finditer(markdown)]
    if len(blocks) != 1:
        raise CanonicalRequirementBlockError(
            f"{source} must contain exactly one fenced "
            f"```{CANONICAL_REQUIREMENT_FENCE} block; found {len(blocks)}"
        )

    try:
        document = tomllib.loads(blocks[0])
        return RequirementSpec.model_validate(document)
    except (tomllib.TOMLDecodeError, ValidationError) as error:
        raise ContractLoadError(f"invalid canonical requirement block in {source}: {error}") from error


def load_requirement_spec(path: str | Path) -> RequirementSpec:
    """Load JSON without silently accepting duplicate object keys."""

    source = Path(path)
    try:
        document = json.loads(
            source.read_text(encoding="utf-8"),
            object_pairs_hook=_object_without_duplicate_keys,
        )
        return RequirementSpec.model_validate(document)
    except (OSError, UnicodeError, json.JSONDecodeError, ValidationError, ContractLoadError) as error:
        if isinstance(error, ContractLoadError) and str(error).startswith("duplicate JSON key"):
            detail = str(error)
        else:
            detail = str(error)
        raise ContractLoadError(f"invalid requirement spec {source}: {detail}") from error


def compute_requirement_hash(spec: RequirementSpec | Mapping[str, Any]) -> str:
    """Return a stable SHA-256 over normalized semantic content.

    The embedded ``source.requirement_hash`` is excluded to avoid a circular
    digest.  Mappings may omit that field while a new requirement is being
    assembled; all other contract validation still applies.
    """

    normalized = _normalize_requirement(spec, permit_missing_hash=True)
    source = normalized.get("source")
    if not isinstance(source, dict):  # defensive; model validation normally catches this
        raise RequirementError("requirement source must be an object")
    source.pop("requirement_hash", None)
    encoded = json.dumps(
        normalized,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"sha256:{sha256(encoded).hexdigest()}"


def compare_requirement_models(
    memory: RequirementSpec | Mapping[str, Any],
    spec: RequirementSpec | Mapping[str, Any],
) -> list[RequirementDiff]:
    """Return stable field- and index-level differences in semantic data."""

    memory_value = _normalize_requirement(memory)
    spec_value = _normalize_requirement(spec)
    differences: list[RequirementDiff] = []
    _deep_diff(memory_value, spec_value, "$", differences)
    return differences


def validate_requirement_consistency(
    memory_path: str | Path,
    spec_path: str | Path,
    manifest: AppManifest | str | Path | None = None,
) -> RequirementSpec:
    """Enforce the two-file requirement, hash, blocker, and manifest gate.

    This function is intentionally read-only.  It never regenerates either
    representation when a mismatch is found.
    """

    memory = load_requirement_memory(memory_path)
    spec = load_requirement_spec(spec_path)
    differences = compare_requirement_models(memory, spec)
    issues: list[str] = []

    if differences:
        preview = ", ".join(diff.path for diff in differences[:8])
        suffix = "" if len(differences) <= 8 else f" (+{len(differences) - 8} more)"
        issues.append(f"memory and spec differ at {preview}{suffix}")

    memory_hash = compute_requirement_hash(memory)
    spec_hash = compute_requirement_hash(spec)
    if memory.source.requirement_hash != memory_hash:
        issues.append(
            "memory requirement_hash does not match canonical content "
            f"(declared {memory.source.requirement_hash}, computed {memory_hash})"
        )
    if spec.source.requirement_hash != spec_hash:
        issues.append(
            "spec requirement_hash does not match canonical content "
            f"(declared {spec.source.requirement_hash}, computed {spec_hash})"
        )
    if memory_hash != spec_hash:
        issues.append(f"memory and spec canonical hashes differ ({memory_hash} != {spec_hash})")

    app_manifest = _coerce_manifest(manifest)
    if app_manifest is not None:
        _compare_manifest(app_manifest, spec, issues)

    if spec.has_blockers:
        issues.append(f"unresolved blocking items: {', '.join(spec.blocking_item_ids)}")

    if issues:
        raise RequirementConsistencyError(issues, diffs=differences)
    return spec


def extract_canonical_requirement_toml(markdown: str) -> str:
    """Extract a canonical block from already-loaded Markdown.

    Public mainly for generators and focused diagnostics; normal callers use
    :func:`load_requirement_memory`.
    """

    blocks = [match.group("body") for match in _CANONICAL_BLOCK_PATTERN.finditer(markdown)]
    if len(blocks) != 1:
        raise CanonicalRequirementBlockError(
            "Markdown must contain exactly one fenced "
            f"```{CANONICAL_REQUIREMENT_FENCE} block; found {len(blocks)}"
        )
    return blocks[0]


def _coerce_manifest(manifest: AppManifest | str | Path | None) -> AppManifest | None:
    if manifest is None:
        return None
    if isinstance(manifest, AppManifest):
        return manifest
    return load_app_manifest(manifest)


def _compare_manifest(
    manifest: AppManifest,
    requirement: RequirementSpec,
    issues: list[str],
) -> None:
    comparisons = {
        "schema_version": (manifest.schema_version, requirement.schema_version),
        "app_id": (manifest.app_id, requirement.application.app_id),
        "app_slug": (manifest.app_slug, requirement.application.app_slug),
        "name": (manifest.name, requirement.application.name),
        "version": (manifest.version, requirement.application.version),
        "entrypoint": (manifest.entrypoint, requirement.application.entrypoint),
        "requirement_revision": (manifest.requirement_revision, requirement.source.revision),
        "requirement_hash": (manifest.requirement_hash, requirement.source.requirement_hash),
    }
    for field_name, (manifest_value, requirement_value) in comparisons.items():
        if manifest_value != requirement_value:
            issues.append(
                f"manifest {field_name} differs from requirement "
                f"({manifest_value!r} != {requirement_value!r})"
            )


def _normalize_requirement(
    value: RequirementSpec | Mapping[str, Any],
    *,
    permit_missing_hash: bool = False,
) -> dict[str, Any]:
    if isinstance(value, RequirementSpec):
        model = value
    elif isinstance(value, Mapping):
        document = deepcopy(dict(value))
        if permit_missing_hash:
            source = document.get("source")
            if isinstance(source, Mapping):
                source_copy = dict(source)
                source_copy.setdefault("requirement_hash", _ZERO_HASH)
                document["source"] = source_copy
        model = RequirementSpec.model_validate(document)
    elif isinstance(value, BaseModel):
        model = RequirementSpec.model_validate(value.model_dump(mode="python"))
    else:
        raise TypeError(f"expected RequirementSpec or mapping, got {type(value).__name__}")
    return model.model_dump(mode="json")


def _deep_diff(
    memory: Any,
    spec: Any,
    path: str,
    differences: list[RequirementDiff],
) -> None:
    if isinstance(memory, dict) and isinstance(spec, dict):
        for key in sorted(memory.keys() | spec.keys()):
            child_path = f"{path}.{key}"
            if key not in memory:
                differences.append(
                    RequirementDiff(
                        path=child_path,
                        kind=DiffKind.ADDED,
                        spec_value=spec[key],
                        memory_present=False,
                    )
                )
            elif key not in spec:
                differences.append(
                    RequirementDiff(
                        path=child_path,
                        kind=DiffKind.REMOVED,
                        memory_value=memory[key],
                        spec_present=False,
                    )
                )
            else:
                _deep_diff(memory[key], spec[key], child_path, differences)
        return

    if isinstance(memory, list) and isinstance(spec, list):
        shared_length = min(len(memory), len(spec))
        for index in range(shared_length):
            _deep_diff(memory[index], spec[index], f"{path}[{index}]", differences)
        for index in range(shared_length, len(memory)):
            differences.append(
                RequirementDiff(
                    path=f"{path}[{index}]",
                    kind=DiffKind.REMOVED,
                    memory_value=memory[index],
                    spec_present=False,
                )
            )
        for index in range(shared_length, len(spec)):
            differences.append(
                RequirementDiff(
                    path=f"{path}[{index}]",
                    kind=DiffKind.ADDED,
                    spec_value=spec[index],
                    memory_present=False,
                )
            )
        return

    if memory != spec or type(memory) is not type(spec):
        differences.append(
            RequirementDiff(
                path=path,
                kind=DiffKind.CHANGED,
                memory_value=memory,
                spec_value=spec,
            )
        )


def _object_without_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ContractLoadError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


__all__ = [
    "CANONICAL_REQUIREMENT_FENCE",
    "CanonicalRequirementBlockError",
    "ContractLoadError",
    "DiffKind",
    "RequirementConsistencyError",
    "RequirementDiff",
    "RequirementError",
    "compare_requirement_models",
    "compute_requirement_hash",
    "extract_canonical_requirement_toml",
    "load_app_manifest",
    "load_requirement_memory",
    "load_requirement_spec",
    "validate_requirement_consistency",
]
