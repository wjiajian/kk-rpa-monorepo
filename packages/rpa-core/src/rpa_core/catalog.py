"""Verified source catalogs and immutable application snapshot locks.

The repository-level ``elements/`` and ``instructions/`` directories are
authoring sources.  Generated applications never import from those locations at
runtime: selected items and their dependency closure are copied into the
application and pinned by ``catalog.lock.json``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tomllib
from typing import Any, Iterable, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


_CATALOG_ID_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]*$")
_SEMVER_PATTERN = re.compile(
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:[-+][0-9A-Za-z.-]+)?$"
)
_HASH_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
_PACKAGE_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


class CatalogError(ValueError):
    error_code = "catalog_error"


class CatalogContractError(CatalogError):
    error_code = "catalog_contract_invalid"


class CatalogConflictError(CatalogError):
    error_code = "catalog_conflict"


class CatalogDependencyError(CatalogError):
    error_code = "catalog_dependency_invalid"


class CatalogPathError(CatalogError):
    error_code = "catalog_path_unsafe"


class CatalogIntegrityError(CatalogError):
    error_code = "catalog_integrity_failed"


class CatalogKind(StrEnum):
    ELEMENT = "element"
    INSTRUCTION = "instruction"


class CatalogItemStatus(StrEnum):
    VERIFIED = "verified"
    CANDIDATE = "candidate"


class CatalogSourceType(StrEnum):
    REPOSITORY = "repository"
    APPLICATION_CANDIDATE = "application_candidate"


class _FrozenModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
        validate_default=True,
    )


class CatalogDependency(_FrozenModel):
    kind: CatalogKind
    id: str = Field(pattern=_CATALOG_ID_PATTERN.pattern)

    @property
    def ref(self) -> "CatalogRef":
        return CatalogRef(self.kind, self.id)


class CatalogLockItem(_FrozenModel):
    kind: CatalogKind
    id: str = Field(pattern=_CATALOG_ID_PATTERN.pattern)
    version: str = Field(pattern=_SEMVER_PATTERN.pattern)
    status: CatalogItemStatus
    source_type: CatalogSourceType
    source_path: str = Field(min_length=1)
    target_path: str = Field(min_length=1)
    content_hash: str = Field(pattern=_HASH_PATTERN.pattern)
    dependencies: list[CatalogDependency] = Field(default_factory=list)
    copied_at: str | None = None

    @field_validator("source_path", "target_path")
    @classmethod
    def validate_paths(cls, value: str) -> str:
        _validate_relative_path(value)
        return value

    @model_validator(mode="after")
    def validate_item_relationships(self) -> "CatalogLockItem":
        refs = [dependency.ref for dependency in self.dependencies]
        if len(refs) != len(set(refs)):
            raise ValueError("catalog item dependencies must not contain duplicates")
        target_parts = PurePosixPath(self.target_path).parts
        expected_directory = f"{self.kind.value}s"
        if not target_parts or target_parts[0] != "src" or expected_directory not in target_parts:
            raise ValueError(
                f"{self.kind.value} target_path must be inside src/**/{expected_directory}/"
            )
        if (
            self.source_type is CatalogSourceType.REPOSITORY
            and self.status is not CatalogItemStatus.VERIFIED
        ):
            raise ValueError("repository catalog items must be verified")
        if (
            self.source_type is CatalogSourceType.APPLICATION_CANDIDATE
            and self.status is not CatalogItemStatus.CANDIDATE
        ):
            raise ValueError("application candidate items must have candidate status")
        return self

    @property
    def ref(self) -> "CatalogRef":
        return CatalogRef(self.kind, self.id)


class CatalogLock(_FrozenModel):
    schema_version: Literal[1] = 1
    items: list[CatalogLockItem] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_identity_and_dependencies(self) -> "CatalogLock":
        refs = [item.ref for item in self.items]
        duplicates = sorted(str(ref) for ref in set(refs) if refs.count(ref) > 1)
        if duplicates:
            raise ValueError(f"duplicate catalog lock IDs: {duplicates!r}")
        item_ids = [item.id for item in self.items]
        cross_kind_duplicates = sorted(
            item_id for item_id in set(item_ids) if item_ids.count(item_id) > 1
        )
        if cross_kind_duplicates:
            raise ValueError(
                "catalog IDs must be globally unique across elements and instructions: "
                f"{cross_kind_duplicates!r}"
            )
        available = set(refs)
        for item in self.items:
            unknown = sorted(
                str(dependency.ref)
                for dependency in item.dependencies
                if dependency.ref not in available
            )
            if unknown:
                raise ValueError(
                    f"catalog item {item.ref} has unknown dependencies: {unknown!r}"
                )
        _assert_acyclic(
            {
                item.ref: tuple(
                    dependency.ref for dependency in item.dependencies
                )
                for item in self.items
            }
        )
        return self


@dataclass(frozen=True, slots=True, order=True)
class CatalogRef:
    kind: CatalogKind
    id: str

    def __post_init__(self) -> None:
        if not _CATALOG_ID_PATTERN.fullmatch(self.id):
            raise CatalogContractError(f"invalid catalog item ID: {self.id!r}")

    @classmethod
    def parse(cls, value: str | "CatalogRef") -> "CatalogRef":
        if isinstance(value, CatalogRef):
            return value
        kind_text, separator, item_id = str(value).partition(":")
        if not separator:
            raise CatalogContractError(
                f"catalog reference must use '<kind>:<id>': {value!r}"
            )
        try:
            kind = CatalogKind(kind_text)
        except ValueError as error:
            raise CatalogContractError(f"unsupported catalog kind: {kind_text!r}") from error
        return cls(kind, item_id)

    def __str__(self) -> str:
        return f"{self.kind.value}:{self.id}"


@dataclass(frozen=True, slots=True)
class CatalogSourceItem:
    ref: CatalogRef
    version: str
    name: str
    platform: str
    product: str
    source_path: Path
    repository_relative_path: str
    content_hash: str
    dependencies: tuple[CatalogRef, ...] = ()


class CatalogIndex:
    def __init__(self, items: Iterable[CatalogSourceItem]) -> None:
        self._items: dict[CatalogRef, CatalogSourceItem] = {}
        for item in items:
            if item.ref in self._items:
                raise CatalogConflictError(f"duplicate source catalog ID: {item.ref}")
            self._items[item.ref] = item
        ids = [ref.id for ref in self._items]
        cross_kind_duplicates = sorted(
            item_id for item_id in set(ids) if ids.count(item_id) > 1
        )
        if cross_kind_duplicates:
            raise CatalogConflictError(
                "source catalog IDs must be globally unique across elements and "
                f"instructions: {cross_kind_duplicates!r}"
            )
        graph = {ref: item.dependencies for ref, item in self._items.items()}
        for ref, dependencies in graph.items():
            unknown = sorted(str(value) for value in dependencies if value not in graph)
            if unknown:
                raise CatalogDependencyError(
                    f"catalog item {ref} has unknown dependencies: {unknown!r}"
                )
        _assert_acyclic(graph)

    def __len__(self) -> int:
        return len(self._items)

    def get(self, ref: str | CatalogRef) -> CatalogSourceItem:
        normalized = CatalogRef.parse(ref)
        try:
            return self._items[normalized]
        except KeyError as error:
            raise CatalogDependencyError(f"catalog item not found: {normalized}") from error

    def refs(self) -> tuple[CatalogRef, ...]:
        return tuple(sorted(self._items))

    def dependency_closure(
        self,
        requested: Iterable[str | CatalogRef],
    ) -> tuple[CatalogSourceItem, ...]:
        ordered: list[CatalogSourceItem] = []
        visited: set[CatalogRef] = set()

        def visit(ref: CatalogRef) -> None:
            if ref in visited:
                return
            item = self.get(ref)
            for dependency in item.dependencies:
                visit(dependency)
            visited.add(ref)
            ordered.append(item)

        normalized = sorted({CatalogRef.parse(value) for value in requested})
        for ref in normalized:
            visit(ref)
        return tuple(ordered)


def discover_catalog(repository_root: str | Path) -> CatalogIndex:
    """Load every verified top-level element and instruction definition."""

    root = Path(repository_root).absolute()
    items: list[CatalogSourceItem] = []
    elements_root = root / "elements"
    instructions_root = root / "instructions"

    if elements_root.is_dir():
        for metadata_path in sorted(elements_root.rglob("*.toml")):
            relative = metadata_path.relative_to(elements_root)
            if len(relative.parts) != 4:
                raise CatalogContractError(
                    "element definitions must use "
                    "elements/<platform>/<product>/<page>/<component>.toml: "
                    f"{metadata_path}"
                )
            items.append(
                _load_source_item(
                    root,
                    metadata_path,
                    source_path=metadata_path,
                    expected_kind=CatalogKind.ELEMENT,
                    relative_parts=relative.parts,
                )
            )

    if instructions_root.is_dir():
        for metadata_path in sorted(instructions_root.rglob("instruction.toml")):
            relative = metadata_path.relative_to(instructions_root)
            if len(relative.parts) < 4:
                raise CatalogContractError(
                    "instruction definitions must use "
                    "instructions/<platform>/<product>/<capability>/instruction.toml: "
                    f"{metadata_path}"
                )
            implementation = metadata_path.parent / "instruction.py"
            _assert_safe_path(implementation, root, expected="file")
            items.append(
                _load_source_item(
                    root,
                    metadata_path,
                    source_path=metadata_path.parent,
                    expected_kind=CatalogKind.INSTRUCTION,
                    relative_parts=relative.parts,
                )
            )
    return CatalogIndex(items)


def snapshot_catalog(
    repository_root: str | Path,
    application_root: str | Path,
    python_package: str,
    requested: Iterable[str | CatalogRef],
    *,
    lock_filename: str = "catalog.lock.json",
) -> CatalogLock:
    """Copy a verified dependency closure into a new application snapshot.

    Existing target files and locks are never overwritten.  Upgrading an
    existing snapshot is a separate, reviewable operation.
    """

    if not _PACKAGE_PATTERN.fullmatch(python_package):
        raise CatalogContractError(f"invalid Python package name: {python_package!r}")
    root = Path(repository_root).absolute()
    app_root = Path(application_root).absolute()
    if not app_root.is_dir():
        raise CatalogPathError(f"application root does not exist: {app_root}")
    _validate_relative_path(lock_filename)
    lock_path = _join_relative(app_root, lock_filename)
    _assert_safe_destination_parent(lock_path, app_root)
    if lock_path.exists() or lock_path.is_symlink():
        raise CatalogConflictError(f"catalog lock already exists: {lock_path}")

    index = discover_catalog(root)
    closure = index.dependency_closure(requested)
    copy_plan: list[tuple[CatalogSourceItem, Path, str]] = []
    for item in closure:
        source_prefix = f"{item.ref.kind.value}s/"
        if not item.repository_relative_path.startswith(source_prefix):
            raise CatalogPathError(
                f"source path does not match catalog kind: {item.repository_relative_path}"
            )
        suffix = item.repository_relative_path[len(source_prefix) :]
        target_relative = PurePosixPath(
            "src",
            python_package,
            f"{item.ref.kind.value}s",
            *PurePosixPath(suffix).parts,
        ).as_posix()
        target = _join_relative(app_root, target_relative)
        _assert_safe_destination_parent(target, app_root)
        if target.exists() or target.is_symlink():
            raise CatalogConflictError(f"catalog snapshot target already exists: {target}")
        copy_plan.append((item, target, target_relative))

    lock_items: list[CatalogLockItem] = []
    copied_at = datetime.now(UTC).isoformat(timespec="seconds")
    for item, target, target_relative in copy_plan:
        _copy_catalog_path(item.source_path, target, root)
        copied_hash = hash_catalog_path(target, app_root)
        if copied_hash != item.content_hash:
            raise CatalogIntegrityError(
                f"copied catalog item hash changed: {item.ref} "
                f"({copied_hash} != {item.content_hash})"
            )
        lock_items.append(
            CatalogLockItem(
                kind=item.ref.kind,
                id=item.ref.id,
                version=item.version,
                status=CatalogItemStatus.VERIFIED,
                source_type=CatalogSourceType.REPOSITORY,
                source_path=item.repository_relative_path,
                target_path=target_relative,
                content_hash=item.content_hash,
                copied_at=copied_at,
                dependencies=[
                    CatalogDependency(kind=dependency.kind, id=dependency.id)
                    for dependency in item.dependencies
                ],
            )
        )

    lock = CatalogLock(items=lock_items)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = lock_path.with_name(f".{lock_path.name}.tmp")
    if temporary.exists() or temporary.is_symlink():
        raise CatalogConflictError(f"temporary catalog lock already exists: {temporary}")
    temporary.write_text(
        json.dumps(lock.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, lock_path)
    return verify_catalog_snapshot(app_root, lock)


def load_catalog_lock(path: str | Path) -> CatalogLock:
    source = Path(path)
    try:
        payload = json.loads(
            source.read_text(encoding="utf-8"),
            object_pairs_hook=_object_without_duplicate_keys,
        )
        return CatalogLock.model_validate(payload)
    except CatalogError:
        raise
    except Exception as error:
        raise CatalogContractError(f"invalid catalog lock {source}: {error}") from error


def verify_catalog_snapshot(
    application_root: str | Path,
    lock: CatalogLock | str | Path | None = None,
) -> CatalogLock:
    """Fail closed if an application snapshot is missing, unsafe, or changed."""

    app_root = Path(application_root).absolute()
    if lock is None:
        lock_path = app_root / "catalog.lock.json"
        _assert_safe_path(lock_path, app_root, expected="file")
        normalized_lock = load_catalog_lock(lock_path)
    elif isinstance(lock, CatalogLock):
        normalized_lock = lock
    else:
        lock_path = Path(lock)
        if not lock_path.is_absolute():
            lock_path = app_root / lock_path
        _assert_safe_path(lock_path, app_root, expected="file")
        normalized_lock = load_catalog_lock(lock_path)

    for item in normalized_lock.items:
        target = _join_relative(app_root, item.target_path)
        try:
            actual_hash = hash_catalog_path(target, app_root)
        except CatalogError:
            raise
        except Exception as error:
            raise CatalogIntegrityError(
                f"cannot verify catalog snapshot item {item.ref}: {error}"
            ) from error
        if actual_hash != item.content_hash:
            raise CatalogIntegrityError(
                f"catalog snapshot hash mismatch for {item.ref}: "
                f"{actual_hash} != {item.content_hash}"
            )
    return normalized_lock


def hash_catalog_path(path: str | Path, root: str | Path) -> str:
    """Hash one safe file or directory including relative names and bytes."""

    source = Path(path).absolute()
    boundary = Path(root).absolute()
    expected = "directory" if source.is_dir() else "file"
    _assert_safe_path(source, boundary, expected=expected)
    digest = sha256()
    if source.is_file():
        digest.update(b"file\0")
        digest.update(source.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(_read_safe_file(source, boundary))
    else:
        digest.update(b"directory\0")
        for candidate in sorted(source.rglob("*")):
            _assert_safe_path(
                candidate,
                boundary,
                expected="directory" if candidate.is_dir() else "file",
            )
            relative = candidate.relative_to(source).as_posix().encode("utf-8")
            if candidate.is_dir():
                digest.update(b"dir\0" + relative + b"\0")
            else:
                digest.update(b"file\0" + relative + b"\0")
                digest.update(_read_safe_file(candidate, boundary))
    return f"sha256:{digest.hexdigest()}"


def _load_source_item(
    repository_root: Path,
    metadata_path: Path,
    *,
    source_path: Path,
    expected_kind: CatalogKind,
    relative_parts: tuple[str, ...],
) -> CatalogSourceItem:
    _assert_safe_path(metadata_path, repository_root, expected="file")
    try:
        data = tomllib.loads(_read_safe_file(metadata_path, repository_root).decode("utf-8"))
    except Exception as error:
        raise CatalogContractError(f"invalid catalog metadata {metadata_path}: {error}") from error
    if data.get("schema_version") != 1:
        raise CatalogContractError(f"unsupported catalog schema in {metadata_path}")
    try:
        kind = CatalogKind(str(data.get("kind", "")))
    except ValueError as error:
        raise CatalogContractError(f"invalid catalog kind in {metadata_path}") from error
    if kind is not expected_kind:
        raise CatalogContractError(
            f"catalog kind/path mismatch in {metadata_path}: {kind.value}"
        )
    item_id = str(data.get("id", ""))
    ref = CatalogRef(kind, item_id)
    version = str(data.get("version", ""))
    if not _SEMVER_PATTERN.fullmatch(version):
        raise CatalogContractError(f"invalid catalog version in {metadata_path}: {version!r}")
    if data.get("status") != CatalogItemStatus.VERIFIED.value:
        raise CatalogContractError(
            f"top-level catalog item must be verified: {metadata_path}"
        )
    name = str(data.get("name", "")).strip()
    platform = str(data.get("platform", "")).strip()
    product = str(data.get("product", "")).strip()
    if not name or not platform or not product:
        raise CatalogContractError(
            f"catalog item name, platform, and product are required: {metadata_path}"
        )
    if platform != relative_parts[0] or product != relative_parts[1]:
        raise CatalogContractError(
            f"catalog platform/product do not match path: {metadata_path}"
        )
    raw_dependencies = data.get("dependencies", [])
    if not isinstance(raw_dependencies, list) or any(
        not isinstance(value, str) for value in raw_dependencies
    ):
        raise CatalogContractError(f"catalog dependencies must be strings: {metadata_path}")
    dependencies = tuple(CatalogRef.parse(value) for value in raw_dependencies)
    if len(dependencies) != len(set(dependencies)):
        raise CatalogContractError(f"duplicate catalog dependencies: {metadata_path}")
    if expected_kind is CatalogKind.INSTRUCTION:
        entrypoint = str(data.get("entrypoint", ""))
        if not re.fullmatch(r"instruction\.py:[A-Za-z_][A-Za-z0-9_]*", entrypoint):
            raise CatalogContractError(
                f"instruction entrypoint must use instruction.py:<ClassName>: {metadata_path}"
            )
    repository_relative_path = source_path.relative_to(repository_root).as_posix()
    return CatalogSourceItem(
        ref=ref,
        version=version,
        name=name,
        platform=platform,
        product=product,
        source_path=source_path,
        repository_relative_path=repository_relative_path,
        content_hash=hash_catalog_path(source_path, repository_root),
        dependencies=dependencies,
    )


def _copy_catalog_path(source: Path, target: Path, root: Path) -> None:
    _assert_safe_path(source, root, expected="directory" if source.is_dir() else "file")
    if source.is_file():
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target, follow_symlinks=False)
        return
    target.mkdir(parents=True, exist_ok=False)
    for candidate in sorted(source.rglob("*")):
        relative = candidate.relative_to(source)
        destination = target / relative
        _assert_safe_path(
            candidate,
            root,
            expected="directory" if candidate.is_dir() else "file",
        )
        if candidate.is_dir():
            destination.mkdir(parents=True, exist_ok=False)
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(candidate, destination, follow_symlinks=False)


def _assert_safe_path(path: Path, root: Path, *, expected: str) -> None:
    root = root.absolute()
    path = path.absolute()
    try:
        relative = path.relative_to(root)
    except ValueError as error:
        raise CatalogPathError(f"catalog path escapes its root: {path}") from error
    current = root
    for part in relative.parts:
        current = current / part
        try:
            linked = os.lstat(current)
        except FileNotFoundError as error:
            raise CatalogIntegrityError(f"catalog path is missing: {current}") from error
        if stat.S_ISLNK(linked.st_mode):
            raise CatalogPathError(f"catalog path must not contain symbolic links: {current}")
        if stat.S_ISREG(linked.st_mode) and linked.st_nlink != 1:
            raise CatalogPathError(f"catalog file must not be a hard link: {current}")
    linked = os.lstat(path)
    if expected == "file" and not stat.S_ISREG(linked.st_mode):
        raise CatalogIntegrityError(f"catalog path must be a regular file: {path}")
    if expected == "directory" and not stat.S_ISDIR(linked.st_mode):
        raise CatalogIntegrityError(f"catalog path must be a directory: {path}")


def _read_safe_file(path: Path, root: Path) -> bytes:
    _assert_safe_path(path, root, expected="file")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor: int | None = None
    try:
        descriptor = os.open(path, flags)
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1:
            raise CatalogPathError(f"catalog file changed while opening: {path}")
        linked = os.lstat(path)
        if (opened.st_dev, opened.st_ino) != (linked.st_dev, linked.st_ino):
            raise CatalogPathError(f"catalog file changed while opening: {path}")
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = None
            return stream.read()
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _validate_relative_path(value: str) -> None:
    path = PurePosixPath(value)
    if not value or path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"path must be a normalized relative POSIX path: {value!r}")
    if "\\" in value or path.as_posix() != value:
        raise ValueError(f"path must use normalized POSIX separators: {value!r}")


def _join_relative(root: Path, value: str) -> Path:
    try:
        _validate_relative_path(value)
    except ValueError as error:
        raise CatalogPathError(str(error)) from error
    target = root.joinpath(*PurePosixPath(value).parts).absolute()
    try:
        target.relative_to(root.absolute())
    except ValueError as error:  # pragma: no cover - guarded by normalized parts
        raise CatalogPathError(f"catalog path escapes application root: {value!r}") from error
    return target


def _assert_safe_destination_parent(path: Path, root: Path) -> None:
    """Reject an existing symlink or non-directory in a write destination chain."""

    boundary = root.absolute()
    target = path.absolute()
    try:
        relative = target.relative_to(boundary)
    except ValueError as error:
        raise CatalogPathError(f"catalog destination escapes application: {target}") from error

    try:
        root_stat = os.lstat(boundary)
    except FileNotFoundError as error:
        raise CatalogIntegrityError(
            f"application root is missing: {boundary}"
        ) from error
    if stat.S_ISLNK(root_stat.st_mode):
        raise CatalogPathError(
            f"catalog destination root must not be a symbolic link: {boundary}"
        )
    if not stat.S_ISDIR(root_stat.st_mode):
        raise CatalogPathError(
            f"catalog destination root must be a directory: {boundary}"
        )

    current = boundary
    for part in relative.parts[:-1]:
        current = current / part
        try:
            linked = os.lstat(current)
        except FileNotFoundError:
            return
        if stat.S_ISLNK(linked.st_mode):
            raise CatalogPathError(
                f"catalog destination must not contain symbolic links: {current}"
            )
        if not stat.S_ISDIR(linked.st_mode):
            raise CatalogPathError(
                f"catalog destination parent must be a directory: {current}"
            )


def _assert_acyclic(graph: dict[CatalogRef, Iterable[CatalogRef]]) -> None:
    visiting: set[CatalogRef] = set()
    visited: set[CatalogRef] = set()

    def visit(ref: CatalogRef, chain: tuple[CatalogRef, ...]) -> None:
        if ref in visited:
            return
        if ref in visiting:
            cycle = " -> ".join(str(value) for value in (*chain, ref))
            raise CatalogDependencyError(f"catalog dependency cycle: {cycle}")
        visiting.add(ref)
        for dependency in graph.get(ref, ()):
            visit(dependency, (*chain, ref))
        visiting.remove(ref)
        visited.add(ref)

    for ref in sorted(graph):
        visit(ref, ())


def _object_without_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CatalogContractError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


__all__ = [
    "CatalogConflictError",
    "CatalogContractError",
    "CatalogDependency",
    "CatalogDependencyError",
    "CatalogError",
    "CatalogIndex",
    "CatalogIntegrityError",
    "CatalogItemStatus",
    "CatalogKind",
    "CatalogLock",
    "CatalogLockItem",
    "CatalogPathError",
    "CatalogRef",
    "CatalogSourceItem",
    "CatalogSourceType",
    "discover_catalog",
    "hash_catalog_path",
    "load_catalog_lock",
    "snapshot_catalog",
    "verify_catalog_snapshot",
]
