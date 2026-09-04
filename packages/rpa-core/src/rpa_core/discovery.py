"""Application discovery and repository-level validation gates."""

from __future__ import annotations

import ast
import re
import subprocess
import tomllib
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable

from .catalog import (
    CatalogItemStatus,
    CatalogKind,
    CatalogSourceType,
    load_catalog_lock,
    verify_catalog_snapshot,
)
from .contracts import (
    AppManifest,
    AppStatus,
    InstructionResolutionStatus,
    RequirementSpec,
)
from .elements import load_element_catalog
from .requirements import (
    RequirementConsistencyError,
    compute_requirement_hash,
    load_app_manifest,
    load_requirement_memory,
    load_requirement_spec,
    validate_requirement_consistency,
)


STANDARD_COMMANDS = {
    "doctor": "rpa-app doctor",
    "check": "rpa-app check",
    "test": "rpa-app test",
    "preview": "rpa-app run --mode preview",
    "live": "rpa-app run --mode live",
    "resume": "rpa-app resume",
}

V2_STANDARD_COMMANDS = {
    "login": "rpa-app login",
    "verify_candidates": "rpa-app verify-candidates",
}

FORBIDDEN_APP_IMPORTS = {
    "drissionpage",
    "lark_oapi",
    "openpyxl",
    "psycopg",
    "psycopg2",
    "pymysql",
    "sqlalchemy",
}

FORBIDDEN_ROOT_CATALOG_IMPORTS = {"elements", "instructions"}

SENSITIVE_PATH_PARTS = {
    ".pytest_cache",
    ".venv",
    "__pycache__",
    ".env",
    "artifacts",
    "browser-profiles",
    "checkpoints",
    "cookies",
    "locks",
    "logs",
    "port-leases",
    "profiles",
    "runtime",
    "runs",
    "stores.local.toml",
}

SECRET_VALUE_PATTERNS = (
    re.compile(
        r"(?i)['\"]?(?:password|passwd|token|cookie|api[_-]?key|secret)['\"]?\s*[:=]\s*"
        r"['\"](?!<|\[|\{|example|placeholder|redacted)([^'\"]{6,})['\"]"
    ),
    re.compile(
        r"(?im)^[ \t]*(?:password|passwd|token|cookie|api[_-]?key|secret)"
        r"[ \t]*=[ \t]*(?!<|\[|\{|example|placeholder|redacted)"
        r"([^\s#]{8,})[ \t]*$"
    ),
    re.compile(r"(?i)bearer\s+[a-z0-9._~+/=-]{12,}"),
    re.compile(r"/Users/[^/\s]+/"),
    re.compile(r"[A-Za-z]:\\Users\\[^\\\s]+\\"),
)


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    code: str
    message: str
    path: str = ""
    line: int | None = None
    blocking: bool = True

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class ValidationReport:
    issues: list[ValidationIssue] = field(default_factory=list)
    applications: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(issue.blocking for issue in self.issues)

    def add(
        self,
        code: str,
        message: str,
        path: Path | str = "",
        *,
        line: int | None = None,
        blocking: bool = True,
    ) -> None:
        self.issues.append(
            ValidationIssue(
                code=code,
                message=message,
                path=str(path),
                line=line,
                blocking=blocking,
            )
        )

    def extend(self, other: "ValidationReport") -> None:
        self.issues.extend(other.issues)
        self.applications.extend(other.applications)

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "applications": sorted(set(self.applications)),
            "issues": [issue.to_dict() for issue in self.issues],
        }


@dataclass(frozen=True, slots=True)
class DiscoveredApplication:
    directory: Path
    manifest_path: Path
    manifest: AppManifest


def find_repository_root(start: Path) -> Path:
    """Find the repository root without relying on the current process directory."""

    start = start.resolve()
    for candidate in (start, *start.parents):
        if (candidate / "AGENTS.md").is_file() and (candidate / "apps").is_dir():
            return candidate
    raise FileNotFoundError(f"repository root not found from {start}")


def discover_applications(repo_root: Path) -> tuple[list[DiscoveredApplication], ValidationReport]:
    """Discover apps by scanning apps/*/app.toml and reject duplicate identities."""

    repo_root = repo_root.resolve()
    report = ValidationReport()
    discovered: list[DiscoveredApplication] = []

    for manifest_path in sorted((repo_root / "apps").glob("*/app.toml")):
        try:
            manifest = load_app_manifest(manifest_path)
        except Exception as exc:  # Pydantic exposes useful validation text here.
            report.add("APP_MANIFEST_INVALID", str(exc), manifest_path)
            continue
        discovered.append(
            DiscoveredApplication(
                directory=manifest_path.parent,
                manifest_path=manifest_path,
                manifest=manifest,
            )
        )
        report.applications.append(manifest.app_id)

    by_id: dict[str, list[DiscoveredApplication]] = {}
    by_slug: dict[str, list[DiscoveredApplication]] = {}
    for app in discovered:
        by_id.setdefault(app.manifest.app_id, []).append(app)
        by_slug.setdefault(app.manifest.app_slug, []).append(app)

    for app_id, apps in by_id.items():
        if len(apps) > 1:
            paths = ", ".join(str(app.manifest_path) for app in apps)
            report.add("APP_ID_CONFLICT", f"app_id {app_id!r} appears in: {paths}")
    for slug, apps in by_slug.items():
        if len(apps) > 1:
            paths = ", ".join(str(app.manifest_path) for app in apps)
            report.add("APP_SLUG_CONFLICT", f"app_slug {slug!r} appears in: {paths}")

    return discovered, report


def ensure_application_identity_available(repo_root: Path, app_id: str, app_slug: str) -> None:
    """Stop before creating or overwriting an existing identity or target directory."""

    target = repo_root / "apps" / app_slug
    if target.exists():
        raise FileExistsError(f"target application directory already exists: {target}")
    apps, report = discover_applications(repo_root)
    if not report.ok:
        raise ValueError(f"repository application registry is invalid: {report.to_dict()}")
    for app in apps:
        if app.manifest.app_id == app_id:
            raise FileExistsError(
                f"app_id {app_id!r} already belongs to {app.manifest_path}"
            )
        if app.manifest.app_slug == app_slug:
            raise FileExistsError(
                f"app_slug {app_slug!r} already belongs to {app.manifest_path}"
            )


def validate_application(app_dir: Path, *, require_lock: bool = True) -> ValidationReport:
    """Validate one independent application without executing its business program."""

    app_dir = app_dir.resolve()
    report = ValidationReport()
    manifest_path = app_dir / "app.toml"
    manifest: AppManifest | None = None
    if manifest_path.is_file():
        try:
            manifest = load_app_manifest(manifest_path)
        except Exception as exc:
            report.add("APP_MANIFEST_INVALID", str(exc), manifest_path)

    common_required = [
        "app.toml",
        "pyproject.toml",
        ".python-version",
        ".gitignore",
        "README.md",
        "config/stores.example.toml",
    ]
    if manifest is not None and manifest.schema_version == 2:
        required = common_required + [
            ".env.example",
            "GENERATION_REPORT.md",
            "config/config.schema.json",
            "requirement/REQUIREMENT_MEMORY.md",
            "requirement/requirement.spec.json",
        ]
        required_directories = ("config", "requirement/assets", "reviews", "src", "tests")
    else:
        required = common_required + ["requirement.md", "elements.toml"]
        required_directories = ("config", "src", "tests")
    if require_lock:
        required.append("uv.lock")
    for relative in required:
        path = app_dir / relative
        if not path.is_file():
            report.add("APP_REQUIRED_FILE_MISSING", f"missing required file: {relative}", path)

    for relative in required_directories:
        path = app_dir / relative
        if not path.is_dir():
            report.add(
                "APP_REQUIRED_DIRECTORY_MISSING",
                f"missing required directory: {relative}",
                path,
            )

    if manifest is None:
        return report
    report.applications.append(manifest.app_id)

    if app_dir.name != manifest.app_slug:
        report.add(
            "APP_SLUG_DIRECTORY_MISMATCH",
            f"directory {app_dir.name!r} does not match app_slug {manifest.app_slug!r}",
            app_dir,
        )

    package_name, separator, function_name = manifest.entrypoint.partition(":")
    if not separator or function_name != "main":
        report.add(
            "APP_ENTRYPOINT_INVALID",
            "entrypoint must use '<python_package>.cli:main'",
            manifest_path,
        )
    else:
        root_package = package_name.split(".", 1)[0]
        if root_package != manifest.app_slug:
            report.add(
                "APP_ENTRYPOINT_PACKAGE_MISMATCH",
                f"entrypoint package {root_package!r} does not match app_slug",
                manifest_path,
            )
        module_path = app_dir / "src" / Path(*package_name.split(".")).with_suffix(".py")
        if not module_path.is_file():
            report.add(
                "APP_ENTRYPOINT_MISSING",
                f"entrypoint module does not exist: {module_path.relative_to(app_dir)}",
                module_path,
            )
        source_package = app_dir / "src" / root_package
        source_files = (
            ("__init__.py", "cli.py", "models.py", "program.py", "steps.py", "validators.py")
            if manifest.schema_version == 2
            else ("__init__.py", "cli.py", "program.py")
        )
        for filename in source_files:
            path = source_package / filename
            if not path.is_file():
                report.add(
                    "APP_REQUIRED_SOURCE_FILE_MISSING",
                    f"missing required source file: src/{root_package}/{filename}",
                    path,
                )
        if manifest.schema_version == 2:
            for catalog_directory in ("elements", "instructions"):
                path = source_package / catalog_directory
                if not path.is_dir():
                    report.add(
                        "APP_CATALOG_DIRECTORY_MISSING",
                        f"missing application snapshot directory: {catalog_directory}",
                        path,
                    )

    if manifest.schema_version == 2:
        command_data = manifest.commands.model_dump(mode="python")
        for name, expected in STANDARD_COMMANDS.items():
            if command_data.get(name) != expected:
                report.add(
                    "APP_STANDARD_COMMAND_INVALID",
                    f"command {name!r} must equal {expected!r}",
                    manifest_path,
                )
        for name, expected in V2_STANDARD_COMMANDS.items():
            if command_data.get(name) != expected:
                report.add(
                    "APP_STANDARD_COMMAND_INVALID",
                    f"command {name!r} must equal {expected!r}",
                    manifest_path,
                )

        lock_path = app_dir / (manifest.catalog_lock or "catalog.lock.json")
        if not lock_path.is_file():
            report.add(
                "APP_CATALOG_LOCK_MISSING",
                f"missing catalog lock: {manifest.catalog_lock}",
                lock_path,
            )
        else:
            try:
                verify_catalog_snapshot(app_dir, lock_path)
            except Exception as exc:
                report.add("APP_CATALOG_SNAPSHOT_INVALID", str(exc), lock_path)

    _validate_pyproject(app_dir, manifest, report)
    if manifest.schema_version == 2:
        _validate_requirement_pair(app_dir, manifest, report)
    else:
        _validate_compact_requirement(app_dir, manifest, report)
    _validate_review_state(app_dir, manifest, report)
    report.issues.extend(scan_application_architecture(app_dir))
    report.issues.extend(scan_sensitive_content(app_dir))
    report.issues.extend(scan_tracked_sensitive_paths(app_dir))
    return report


def validate_repository(repo_root: Path, *, require_lock: bool = True) -> ValidationReport:
    """Validate every discovered application and repository-wide uniqueness."""

    apps, report = discover_applications(repo_root)
    for app in apps:
        report.extend(validate_application(app.directory, require_lock=require_lock))
    return report


def validate_application_in_repository(
    app_dir: Path,
    *,
    require_lock: bool = True,
) -> ValidationReport:
    """Validate one app plus repository-wide manifest identity constraints.

    A draft application's open requirement items must not prevent an unrelated
    application from running.  Repository scope is therefore limited to
    manifest validity and app ID/slug uniqueness, while the full validation
    gate applies only to ``app_dir``.
    """

    app_dir = app_dir.resolve()
    try:
        repo_root = find_repository_root(app_dir)
    except FileNotFoundError:
        return validate_application(app_dir, require_lock=require_lock)

    discovered, registry_report = discover_applications(repo_root)
    report = ValidationReport()
    report.extend(registry_report)
    report.extend(validate_application(app_dir, require_lock=require_lock))

    if (app_dir / "app.toml").is_file() and not any(
        app.directory.resolve() == app_dir for app in discovered
    ):
        report.add(
            "APP_REGISTRATION_INVALID",
            "current application manifest is not validly registered under apps/*/app.toml",
            app_dir / "app.toml",
        )
    return report


def scan_application_architecture(app_dir: Path) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    source_root = app_dir / "src"
    for path in sorted(source_root.rglob("*.py")) if source_root.exists() else []:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as exc:
            issues.append(
                ValidationIssue(
                    "APP_PYTHON_SYNTAX_ERROR",
                    exc.msg,
                    str(path),
                    exc.lineno,
                )
            )
            continue
        for node in ast.walk(tree):
            imported: str | None = None
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported = alias.name.split(".", 1)[0]
                    if imported.lower() in FORBIDDEN_APP_IMPORTS:
                        issues.append(
                            ValidationIssue(
                                "APP_FORBIDDEN_IMPORT",
                                f"business applications may not import {alias.name!r}",
                                str(path),
                                node.lineno,
                            )
                        )
                    if imported.lower() in FORBIDDEN_ROOT_CATALOG_IMPORTS:
                        issues.append(
                            ValidationIssue(
                                "APP_RUNTIME_SOURCE_CATALOG_IMPORT",
                                "applications must import their package-local catalog snapshot",
                                str(path),
                                node.lineno,
                            )
                        )
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported = node.module.split(".", 1)[0]
                if imported.lower() in FORBIDDEN_APP_IMPORTS:
                    issues.append(
                        ValidationIssue(
                            "APP_FORBIDDEN_IMPORT",
                            f"business applications may not import {node.module!r}",
                            str(path),
                            node.lineno,
                        )
                    )
                if (
                    node.level == 0
                    and imported.lower() in FORBIDDEN_ROOT_CATALOG_IMPORTS
                ):
                    issues.append(
                        ValidationIssue(
                            "APP_RUNTIME_SOURCE_CATALOG_IMPORT",
                            "applications must import their package-local catalog snapshot",
                            str(path),
                            node.lineno,
                        )
                    )
            if _is_direct_element_click(node):
                issues.append(
                    ValidationIssue(
                        "APP_DIRECT_ELEMENT_ACTION",
                        "direct ele()/eles() click bypasses BrowserActions",
                        str(path),
                        getattr(node, "lineno", None),
                    )
                )
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if re.match(r"^(?:/Users/|/home/|[A-Za-z]:\\Users\\)", node.value):
                    issues.append(
                        ValidationIssue(
                            "APP_HARDCODED_MACHINE_PATH",
                            "business application contains a machine-specific absolute path",
                            str(path),
                            getattr(node, "lineno", None),
                        )
                    )
            if _has_hardcoded_browser_port(node):
                issues.append(
                    ValidationIssue(
                        "APP_HARDCODED_BROWSER_PORT",
                        "business application must obtain browser ports from the runtime",
                        str(path),
                        getattr(node, "lineno", None),
                    )
                )
            if _has_hardcoded_browser_profile(node):
                issues.append(
                    ValidationIssue(
                        "APP_HARDCODED_BROWSER_PROFILE",
                        "business application must obtain browser profiles from the runtime",
                        str(path),
                        getattr(node, "lineno", None),
                    )
                )
    return issues


def scan_sensitive_content(app_dir: Path) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    excluded_parts = {part.lower() for part in SENSITIVE_PATH_PARTS}
    allowed_suffixes = {".py", ".md", ".toml", ".json", ".yaml", ".yml"}
    for path in sorted(app_dir.rglob("*")):
        if not path.is_file() or (
            path.suffix.lower() not in allowed_suffixes and path.name != ".env.example"
        ):
            continue
        if any(part.lower() in excluded_parts for part in path.parts):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for pattern in SECRET_VALUE_PATTERNS:
            match = pattern.search(text)
            if match:
                line = text.count("\n", 0, match.start()) + 1
                issues.append(
                    ValidationIssue(
                        "APP_SENSITIVE_CONTENT",
                        "possible secret or machine identity detected; value redacted",
                        str(path),
                        line,
                    )
                )
                break
    return issues


def scan_tracked_sensitive_paths(app_dir: Path) -> list[ValidationIssue]:
    """Only tracked paths are errors; local runs and virtual environments may exist."""

    repo_root = _git_root(app_dir)
    if repo_root is None:
        return []
    result = subprocess.run(
        ["git", "ls-files", "--", str(app_dir)],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    issues: list[ValidationIssue] = []
    for raw in result.stdout.splitlines():
        path = Path(raw)
        parts = {part.lower() for part in path.parts}
        name = path.name.lower()
        is_asset = "requirement" in parts and "assets" in parts and name != ".gitkeep"
        if name == ".env" or name == "stores.local.toml" or is_asset:
            issues.append(
                ValidationIssue(
                    "APP_SENSITIVE_PATH_TRACKED",
                    "sensitive local path must not be tracked",
                    str(path),
                )
            )
            continue
        if any(part in SENSITIVE_PATH_PARTS for part in parts):
            issues.append(
                ValidationIssue(
                    "APP_RUNTIME_PATH_TRACKED",
                    "runtime or browser state must not be tracked",
                    str(path),
                )
            )
    return issues


def _validate_pyproject(
    app_dir: Path, manifest: AppManifest, report: ValidationReport
) -> None:
    path = app_dir / "pyproject.toml"
    if not path.is_file():
        return
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        report.add("APP_PYPROJECT_INVALID", str(exc), path)
        return
    project = data.get("project", {})
    expected_script = manifest.entrypoint
    actual_script = project.get("scripts", {}).get("rpa-app")
    if actual_script != expected_script:
        report.add(
            "APP_SCRIPT_ENTRYPOINT_MISMATCH",
            f"project.scripts.rpa-app must equal {expected_script!r}",
            path,
        )
    if "rpa-core" not in {
        str(dependency).split("[", 1)[0].split("<", 1)[0].split(">", 1)[0].split("=", 1)[0]
        for dependency in project.get("dependencies", [])
    }:
        report.add("APP_CORE_DEPENDENCY_MISSING", "project must depend on rpa-core", path)
    core_source = data.get("tool", {}).get("uv", {}).get("sources", {}).get("rpa-core")
    if not isinstance(core_source, dict) or not core_source.get("path"):
        report.add(
            "APP_CORE_PATH_SOURCE_MISSING",
            "tool.uv.sources must map rpa-core to a local path dependency",
            path,
        )


def _validate_compact_requirement(
    app_dir: Path,
    manifest: AppManifest,
    report: ValidationReport,
) -> None:
    """Validate the single-file requirement used by compact applications."""

    requirement_path = app_dir / "requirement.md"
    elements_path = app_dir / "elements.toml"
    if not requirement_path.is_file():
        return
    try:
        requirement = load_requirement_memory(requirement_path)
    except Exception as exc:
        report.add("REQUIREMENT_INVALID", str(exc), requirement_path)
        return

    computed_hash = compute_requirement_hash(requirement)
    if requirement.source.requirement_hash != computed_hash:
        report.add(
            "REQUIREMENT_GATE_FAILED",
            "requirement.md hash does not match its canonical content",
            requirement_path,
        )
    if manifest.requirement_hash != computed_hash:
        report.add(
            "REQUIREMENT_GATE_FAILED",
            "manifest requirement_hash does not match requirement.md",
            app_dir / "app.toml",
        )
    if manifest.requirement_revision != requirement.source.revision:
        report.add(
            "REQUIREMENT_GATE_FAILED",
            "manifest requirement_revision does not match requirement.md",
            app_dir / "app.toml",
        )

    manifest_identity = {
        "app_id": manifest.app_id,
        "app_slug": manifest.app_slug,
        "name": manifest.name,
        "version": manifest.version,
        "entrypoint": manifest.entrypoint,
    }
    requirement_identity = requirement.application.model_dump(mode="python")
    for field_name, expected in manifest_identity.items():
        if requirement_identity.get(field_name) != expected:
            report.add(
                "REQUIREMENT_GATE_FAILED",
                f"requirement application.{field_name} does not match manifest",
                requirement_path,
            )

    if requirement.unresolved_instructions or any(
        step.instruction_refs or step.unresolved_instruction_ids
        for step in requirement.steps
    ):
        report.add(
            "APP_COMPACT_INSTRUCTION_REFERENCE",
            "compact applications implement browser flow directly in Step code",
            requirement_path,
        )

    if elements_path.is_file():
        try:
            element_ids = set(load_element_catalog(elements_path))
        except Exception as exc:
            report.add("APP_ELEMENT_CATALOG_INVALID", str(exc), elements_path)
        else:
            for step in requirement.steps:
                missing = sorted(set(step.element_refs) - element_ids)
                if missing:
                    report.add(
                        "APP_ELEMENT_REFERENCE_MISSING",
                        f"step {step.id!r} references missing elements: {', '.join(missing)}",
                        requirement_path,
                    )

    if requirement.has_blockers and manifest.status in {
        AppStatus.READY_FOR_REVIEW,
        AppStatus.APPROVED,
        AppStatus.READY_FOR_PUSH,
    }:
        report.add(
            "APP_STATUS_BLOCKER_CONFLICT",
            "application status is too advanced while requirement blockers remain",
            app_dir / "app.toml",
        )


def _validate_requirement_pair(
    app_dir: Path, manifest: AppManifest, report: ValidationReport
) -> None:
    memory_path = app_dir / "requirement" / "REQUIREMENT_MEMORY.md"
    spec_path = app_dir / "requirement" / "requirement.spec.json"
    if not memory_path.is_file() or not spec_path.is_file():
        return
    try:
        requirement = load_requirement_spec(spec_path)
    except Exception as exc:
        report.add("REQUIREMENT_INVALID", str(exc), spec_path)
        requirement = None
    if requirement is not None and requirement.schema_version == 2:
        _validate_v2_catalog_references(app_dir, manifest, requirement, report)
    try:
        validate_requirement_consistency(memory_path, spec_path, manifest=manifest)
    except RequirementConsistencyError as exc:
        for difference in exc.diffs:
            report.add(
                "REQUIREMENT_INCONSISTENT",
                (
                    f"{difference.path}: {difference.kind.value}; "
                    f"memory={difference.memory_value!r}, spec={difference.spec_value!r}"
                ),
                memory_path,
            )
        blocker_ids: list[str] = []
        for issue in exc.issues:
            prefix = "unresolved blocking items: "
            if issue.startswith(prefix):
                blocker_ids = [item.strip() for item in issue[len(prefix) :].split(",")]
                pending_ids = [item for item in blocker_ids if item.startswith("PC-")]
                element_ids = [item for item in blocker_ids if item.startswith("UE-")]
                instruction_ids = [item for item in blocker_ids if item.startswith("UI-")]
                if pending_ids:
                    report.add(
                        "PENDING_CONFIRMATION_OPEN",
                        f"open PendingConfirmation IDs: {', '.join(pending_ids)}",
                        memory_path,
                    )
                if element_ids:
                    report.add(
                        "UNRESOLVED_ELEMENT_OPEN",
                        f"open UnresolvedElement IDs: {', '.join(element_ids)}",
                        memory_path,
                    )
                if instruction_ids:
                    report.add(
                        "UNRESOLVED_INSTRUCTION_OPEN",
                        f"open UnresolvedInstruction IDs: {', '.join(instruction_ids)}",
                        memory_path,
                    )
                continue
            report.add("REQUIREMENT_GATE_FAILED", issue, memory_path)
        if blocker_ids and manifest.status in {
            AppStatus.READY_FOR_REVIEW,
            AppStatus.APPROVED,
            AppStatus.READY_FOR_PUSH,
        }:
            report.add(
                "APP_STATUS_BLOCKER_CONFLICT",
                "application status is too advanced while requirement blockers remain",
                app_dir / "app.toml",
            )
        return
    except Exception as exc:
        report.add("REQUIREMENT_INVALID", str(exc), memory_path)
        return


def _validate_v2_catalog_references(
    app_dir: Path,
    manifest: AppManifest,
    requirement: RequirementSpec,
    report: ValidationReport,
) -> None:
    if manifest.schema_version != 2:
        report.add(
            "APP_REQUIREMENT_SCHEMA_MISMATCH",
            "V2 requirement requires a V2 app manifest",
            app_dir / "app.toml",
        )
        return
    lock_path = app_dir / (manifest.catalog_lock or "catalog.lock.json")
    if not lock_path.is_file():
        return
    try:
        lock = load_catalog_lock(lock_path)
    except Exception as exc:
        report.add("APP_CATALOG_LOCK_INVALID", str(exc), lock_path)
        return
    by_identity = {(item.kind, item.id): item for item in lock.items}

    for step in requirement.steps:
        for instruction_id in step.instruction_refs:
            if (CatalogKind.INSTRUCTION, instruction_id) not in by_identity:
                report.add(
                    "APP_INSTRUCTION_SNAPSHOT_MISSING",
                    f"step {step.id!r} references instruction absent from snapshot: "
                    f"{instruction_id}",
                    lock_path,
                )
        for element_id in step.element_refs:
            if (CatalogKind.ELEMENT, element_id) not in by_identity:
                report.add(
                    "APP_ELEMENT_SNAPSHOT_MISSING",
                    f"step {step.id!r} references element absent from snapshot: {element_id}",
                    lock_path,
                )

    for item in requirement.unresolved_instructions:
        if item.status is not InstructionResolutionStatus.CANDIDATE:
            continue
        implementation = _application_relative_path(
            app_dir,
            item.candidate_implementation or "",
            report,
            code="APP_CANDIDATE_INSTRUCTION_MISSING",
        )
        fake_test = _application_relative_path(
            app_dir,
            item.fake_test_ref or "",
            report,
            code="APP_CANDIDATE_INSTRUCTION_TEST_MISSING",
        )
        if implementation is not None and not implementation.is_file():
            report.add(
                "APP_CANDIDATE_INSTRUCTION_MISSING",
                f"candidate implementation does not exist: {item.candidate_implementation}",
                implementation,
            )
        if fake_test is not None and not fake_test.is_file():
            report.add(
                "APP_CANDIDATE_INSTRUCTION_TEST_MISSING",
                f"candidate fake test does not exist: {item.fake_test_ref}",
                fake_test,
            )
        lock_item = by_identity.get(
            (CatalogKind.INSTRUCTION, item.candidate_instruction_ref or "")
        )
        if lock_item is None:
            report.add(
                "APP_CANDIDATE_INSTRUCTION_LOCK_MISSING",
                f"candidate instruction is absent from catalog lock: "
                f"{item.candidate_instruction_ref}",
                lock_path,
            )
            continue
        if (
            lock_item.source_type is not CatalogSourceType.APPLICATION_CANDIDATE
            or lock_item.status is not CatalogItemStatus.CANDIDATE
        ):
            report.add(
                "APP_CANDIDATE_INSTRUCTION_LOCK_INVALID",
                "candidate instruction lock entry must use application_candidate/candidate",
                lock_path,
            )
        if implementation is not None:
            locked_target = _application_relative_path(
                app_dir,
                lock_item.target_path,
                report,
                code="APP_CANDIDATE_INSTRUCTION_LOCK_INVALID",
            )
            if locked_target is not None:
                implementation_resolved = implementation.resolve(strict=False)
                target_resolved = locked_target.resolve(strict=False)
                if not (
                    implementation_resolved == target_resolved
                    or target_resolved in implementation_resolved.parents
                ):
                    report.add(
                        "APP_CANDIDATE_INSTRUCTION_LOCK_INVALID",
                        "candidate implementation is outside its locked target",
                        implementation,
                    )


def _application_relative_path(
    app_dir: Path,
    relative: str,
    report: ValidationReport,
    *,
    code: str,
) -> Path | None:
    if not relative:
        report.add(code, "candidate artifact path is empty", app_dir)
        return None
    path = app_dir / relative
    try:
        path.resolve(strict=False).relative_to(app_dir.resolve())
    except ValueError:
        report.add(code, f"candidate artifact escapes application: {relative}", path)
        return None
    if path.is_symlink():
        report.add(code, f"candidate artifact must not be a symbolic link: {relative}", path)
        return None
    return path


def _validate_review_state(
    app_dir: Path, manifest: AppManifest, report: ValidationReport
) -> None:
    if manifest.status not in {AppStatus.APPROVED, AppStatus.READY_FOR_PUSH}:
        return
    if not manifest.latest_review:
        report.add(
            "APP_REVIEW_REQUIRED",
            "approved/ready_for_push requires latest_review",
            app_dir / "app.toml",
        )
        return
    review_path = app_dir / manifest.latest_review
    if not review_path.is_file():
        report.add(
            "APP_REVIEW_MISSING",
            f"latest review does not exist: {manifest.latest_review}",
            review_path,
        )


def _is_direct_element_click(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
        return False
    if node.func.attr != "click" or not isinstance(node.func.value, ast.Call):
        return False
    inner = node.func.value.func
    return isinstance(inner, ast.Attribute) and inner.attr in {"ele", "eles"}


def _has_hardcoded_browser_port(node: ast.AST) -> bool:
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        if node.func.attr in {"set_local_port", "set_address"} and node.args:
            value = node.args[0]
            return isinstance(value, ast.Constant) and isinstance(value.value, (int, str))
    if isinstance(node, (ast.Assign, ast.AnnAssign)):
        value = node.value
        if not isinstance(value, ast.Constant) or not isinstance(value.value, (int, str)):
            return False
        # Match the identifier segment, not a substring: EXPORT_MENU contains
        # "port" but names an element, not a debugging port.
        return any(
            "port" in _identifier_segments(name) for name in _assignment_names(node)
        )
    return False


def _identifier_segments(name: str) -> set[str]:
    """Split snake_case, camelCase and SCREAMING_CASE into lowercase words."""

    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name)
    return {segment for segment in re.split(r"[^A-Za-z0-9]+", spaced.casefold()) if segment}


def _has_hardcoded_browser_profile(node: ast.AST) -> bool:
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        if node.func.attr == "set_user_data_path" and node.args:
            value = node.args[0]
            return isinstance(value, ast.Constant) and isinstance(value.value, str)
    if isinstance(node, (ast.Assign, ast.AnnAssign)):
        value = node.value
        if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
            return False
        markers = ("profile", "user_data", "userdata")
        return any(
            any(marker in name.casefold() for marker in markers)
            for name in _assignment_names(node)
        )
    return False


def _assignment_names(node: ast.Assign | ast.AnnAssign) -> list[str]:
    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
    names: list[str] = []
    for target in targets:
        if isinstance(target, ast.Name):
            names.append(target.id)
        elif isinstance(target, ast.Attribute):
            names.append(target.attr)
    return names


def _git_root(path: Path) -> Path | None:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=path,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    return Path(result.stdout.strip())


def issue_codes(issues: Iterable[ValidationIssue]) -> set[str]:
    """Convenience helper for tests and CLI presentation."""

    return {issue.code for issue in issues}
