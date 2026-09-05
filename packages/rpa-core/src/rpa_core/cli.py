"""Shared command surface for compact V2 RPA applications."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
import json
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
from typing import Any
from uuid import uuid4

from .browser_manager import (
    BrowserLaunchSpec,
    BrowserLifecyclePolicy,
    BrowserManager,
)
from .contracts import RunMode
from .elements import ElementEntry, element_specs, load_element_catalog
from .runtime import BaseProgram, CheckpointStore, ExecutionContext, Runner, Step
from .verification import Counterexample, assert_steps_are_falsifiable


class ApplicationBlockedError(RuntimeError):
    """A real command reached an application with open requirement items."""

    error_code = "application_run_blocked"

    def __init__(self, blocker_ids: Iterable[str]) -> None:
        self.blocker_ids = tuple(dict.fromkeys(str(item) for item in blocker_ids))
        super().__init__("real execution is blocked by unresolved requirement items")


@dataclass(frozen=True, slots=True)
class RuntimeOptions:
    """Application-supplied local settings needed by the shared runtime."""

    account_id: str
    profile_dir: Path
    debug_port: int = 0
    browser_path: Path | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


RuntimeLoader = Callable[[str, Mapping[str, Any] | None], RuntimeOptions]
BlockerLoader = Callable[[], Iterable[str]]
ElementVerifier = Callable[
    [ExecutionContext, Mapping[str, ElementEntry]],
    Mapping[str, Any],
]
CounterexampleContextFactory = Callable[[Step, Counterexample, Path], ExecutionContext]


class _BrowserLaunchedCommandError(RuntimeError):
    """Preserve the original CLI error after a real browser was started."""

    real_browser_launched = True

    def __init__(self, cause: Exception) -> None:
        self.cause = cause
        self.error_code = getattr(cause, "error_code", "application_command_failed")
        self.exception_type = type(cause).__name__
        self.blocker_ids = tuple(getattr(cause, "blocker_ids", ()))
        super().__init__(str(cause))


@dataclass(frozen=True, slots=True)
class ApplicationDefinition:
    """The small Python seam between one application and the shared CLI."""

    app_dir: Path
    build_program: Callable[[], BaseProgram]
    load_runtime_options: RuntimeLoader
    element_blocker_ids: Mapping[str, str]
    additional_blockers: BlockerLoader = lambda: ()
    verify_element_stages: ElementVerifier | None = None
    build_counterexample_context: CounterexampleContextFactory | None = None

    @property
    def elements_path(self) -> Path:
        return self.app_dir / "elements.toml"


def main(
    application: ApplicationDefinition,
    argv: Sequence[str] | None = None,
) -> int:
    """Run one application's standard CLI without an application-local runtime."""

    args = _parser().parse_args(argv)
    try:
        if args.command == "doctor":
            return _doctor(application)
        if args.command == "test":
            return _test(application)
        if args.command == "verify-elements":
            return _verify_elements(
                application,
                account=args.account,
                confirmed=args.yes,
            )
        if args.command == "run":
            mode = RunMode.LIVE if args.live else RunMode.PREVIEW
            return _execute(
                application,
                account=args.account,
                run_id=_new_run_id(),
                mode=mode,
                resume=False,
                confirmed=args.yes,
            )
        if args.command == "resume":
            return _execute(
                application,
                account=args.account,
                run_id=args.run_id,
                mode=None,
                resume=True,
                confirmed=args.yes,
            )
    except Exception as error:  # noqa: BLE001 - stable CLI boundary
        _print(
            {
                "ok": False,
                "error": getattr(error, "error_code", "application_command_failed"),
                "exception_type": getattr(
                    error,
                    "exception_type",
                    type(error).__name__,
                ),
                "blockers": list(getattr(error, "blocker_ids", ())),
                "real_browser_launched": bool(
                    getattr(error, "real_browser_launched", False)
                ),
            }
        )
        return 2
    raise AssertionError(f"unhandled command: {args.command}")


def collect_blockers(application: ApplicationDefinition) -> tuple[str, ...]:
    """Return exact open IDs without creating runtime files or a browser."""

    entries = load_element_catalog(application.elements_path)
    blockers = [
        application.element_blocker_ids.get(element_id, f"UE-{element_id}")
        for element_id, entry in entries.items()
        if not entry.spec.is_resolved
    ]
    blockers.extend(str(item) for item in application.additional_blockers())
    return tuple(dict.fromkeys(blockers))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rpa-app")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor")
    commands.add_parser("test")

    verify = commands.add_parser("verify-elements")
    verify.add_argument("--account", default="STORE_001")
    verify.add_argument("--yes", action="store_true")

    run = commands.add_parser("run")
    run.add_argument("--account", default="STORE_001")
    run.add_argument("--live", action="store_true")
    run.add_argument("--yes", action="store_true")

    resume = commands.add_parser("resume")
    resume.add_argument("run_id")
    resume.add_argument("--account", default="STORE_001")
    resume.add_argument("--yes", action="store_true")
    return parser


def _doctor(application: ApplicationDefinition) -> int:
    program = application.build_program()
    entries = load_element_catalog(application.elements_path)
    blockers = collect_blockers(application)
    python_supported = sys.version_info[:2] == (3, 12)
    local_store_config_exists = (
        application.app_dir / "config" / "stores.local.toml"
    ).is_file()
    runtime_configuration_valid = False
    runtime_configuration_error: str | None = None
    browser_path: Path | None = None
    try:
        options = application.load_runtime_options("STORE_001", None)
        runtime_configuration_valid = True
        browser_path = options.browser_path
    except Exception as error:  # noqa: BLE001 - doctor reports invalid local setup
        runtime_configuration_error = type(error).__name__
    browser_available, browser_detail = _browser_status(browser_path)
    dependencies_synchronized, dependency_detail = _dependency_status(
        application.app_dir
    )
    ok = (
        python_supported
        and local_store_config_exists
        and runtime_configuration_valid
        and browser_available
        and dependencies_synchronized
        and not blockers
    )
    _print(
        {
            "ok": ok,
            "app_id": program.spec.app_id,
            "program_id": program.spec.program_id,
            "python_supported": python_supported,
            "local_store_config_exists": local_store_config_exists,
            "runtime_configuration_valid": runtime_configuration_valid,
            "runtime_configuration_error": runtime_configuration_error,
            "browser_available": browser_available,
            "browser_detail": browser_detail,
            "dependencies_synchronized": dependencies_synchronized,
            "dependency_detail": dependency_detail,
            "element_count": len(entries),
            "blockers": list(blockers),
            "real_browser_launched": False,
        }
    )
    return 0 if ok else 2


def _test(application: ApplicationDefinition) -> int:
    if application.build_counterexample_context is None:
        raise RuntimeError(
            "application must define build_counterexample_context for rpa-app test"
        )
    program = application.build_program()
    with TemporaryDirectory(prefix="rpa-app-test-") as temporary:
        temporary_root = Path(temporary)
        assert_steps_are_falsifiable(
            program.steps,
            lambda step, case: application.build_counterexample_context(
                step,
                case,
                temporary_root,
            ),
        )
    completed = subprocess.run(
        [sys.executable, "-m", "pytest"],
        cwd=application.app_dir,
        check=False,
    )
    return int(completed.returncode)


def _verify_elements(
    application: ApplicationDefinition,
    *,
    account: str,
    confirmed: bool,
) -> int:
    if not confirmed:
        raise RuntimeError("verify-elements requires --yes")
    entries = load_element_catalog(application.elements_path)
    unresolved = [entry.id for entry in entries.values() if not entry.spec.is_resolved]
    if unresolved:
        _print(
            {
                "ok": False,
                "error": "unresolved_element_locators",
                "elements": unresolved,
                "real_browser_launched": False,
            }
        )
        return 2
    blockers = collect_blockers(application)
    if blockers:
        raise ApplicationBlockedError(blockers)
    if application.verify_element_stages is None:
        _print(
            {
                "ok": False,
                "error": "application_stage_verification_required",
                "detail": "application does not define a stage verifier",
                "real_browser_launched": False,
            }
        )
        return 2

    run_id = _new_run_id().replace("run-", "verify-elements-", 1)
    run_dir = application.app_dir / "runs" / run_id
    options = application.load_runtime_options(account, None)
    program = application.build_program()
    manager = BrowserManager(application.app_dir / "runtime" / "browser-manager")
    session = None
    failed = True
    browser_launched = False
    try:
        try:
            session = manager.start(
                BrowserLaunchSpec(
                    account_id=options.account_id,
                    profile_id=f"{application.app_dir.name}.{options.account_id}",
                    profile_dir=options.profile_dir,
                    requested_port=options.debug_port,
                    browser_path=options.browser_path,
                    lifecycle=BrowserLifecyclePolicy.KEEP_OPEN_ON_FAILURE,
                ),
                run_id=run_id,
                run_dir=run_dir,
                action_timeout=15.0,
                download_timeout=300.0,
            )
            browser_launched = True
            context = ExecutionContext(
                app_id=program.spec.app_id,
                program_id=program.spec.program_id,
                program_version=program.spec.version,
                requirement_hash=program.spec.requirement_hash,
                run_id=run_id,
                account_id=options.account_id,
                mode=RunMode.PREVIEW,
                run_dir=run_dir,
                services={
                    "browser": session.actions,
                    "elements": element_specs(entries),
                },
                metadata={"app_dir": str(application.app_dir), **dict(options.metadata)},
            )
            result = dict(application.verify_element_stages(context, entries))
            result.update(
                {
                    "command": "verify-elements",
                    "account": options.account_id,
                    "run_id": run_id,
                    "real_browser_launched": True,
                }
            )
            failed = not bool(result.get("ok"))
            _print(result)
            return 2 if failed else 0
        finally:
            try:
                if session is not None and session.active:
                    manager.finish(session, failed=failed)
            finally:
                manager.shutdown()
    except Exception as error:
        if browser_launched:
            raise _BrowserLaunchedCommandError(error) from error
        raise


def _execute(
    application: ApplicationDefinition,
    *,
    account: str,
    run_id: str,
    mode: RunMode | None,
    resume: bool,
    confirmed: bool,
) -> int:
    blockers = collect_blockers(application)
    if blockers:
        raise ApplicationBlockedError(blockers)
    if not confirmed:
        raise RuntimeError("real execution requires --yes")

    checkpoint: Mapping[str, Any] | None = None
    run_dir = application.app_dir / "runs" / run_id
    if resume:
        checkpoint = CheckpointStore(run_dir / "checkpoint.json").load()
        if checkpoint is None:
            raise RuntimeError("resume checkpoint does not exist")
        raw_identity = checkpoint.get("identity")
        if not isinstance(raw_identity, Mapping):
            raise RuntimeError("resume checkpoint identity is missing")
        mode = RunMode(str(raw_identity.get("mode", "")))
    assert mode is not None

    options = application.load_runtime_options(account, checkpoint)
    program = application.build_program()
    entries = load_element_catalog(application.elements_path)
    if checkpoint is not None:
        preflight_context = ExecutionContext(
            app_id=program.spec.app_id,
            program_id=program.spec.program_id,
            program_version=program.spec.version,
            requirement_hash=program.spec.requirement_hash,
            run_id=run_id,
            account_id=options.account_id,
            mode=mode,
            run_dir=run_dir,
        )
        CheckpointStore.validate_identity(checkpoint, preflight_context)
        Runner._validate_checkpoint_steps(checkpoint, program)
    manager = BrowserManager(application.app_dir / "runtime" / "browser-manager")
    session = None
    failed = True
    browser_launched = False
    try:
        try:
            session = manager.start(
                BrowserLaunchSpec(
                    account_id=options.account_id,
                    profile_id=f"{application.app_dir.name}.{options.account_id}",
                    profile_dir=options.profile_dir,
                    requested_port=options.debug_port,
                    browser_path=options.browser_path,
                    lifecycle=BrowserLifecyclePolicy.KEEP_OPEN_ON_FAILURE,
                ),
                run_id=run_id,
                run_dir=run_dir,
                action_timeout=15.0,
                download_timeout=300.0,
            )
            browser_launched = True
            context = ExecutionContext(
                app_id=program.spec.app_id,
                program_id=program.spec.program_id,
                program_version=program.spec.version,
                requirement_hash=program.spec.requirement_hash,
                run_id=run_id,
                account_id=options.account_id,
                mode=mode,
                run_dir=run_dir,
                services={
                    "browser": session.actions,
                    "elements": element_specs(entries),
                },
                metadata={"app_dir": str(application.app_dir), **dict(options.metadata)},
            )
            result = (
                Runner().resume(program, context)
                if resume
                else Runner().run(program, context)
            )
            failed = False
            _print(
                {
                    "ok": True,
                    "run_id": result.run_id,
                    "status": result.status,
                    "completed_steps": list(result.completed_steps),
                    "skipped_steps": list(result.skipped_steps),
                }
            )
            return 0
        finally:
            try:
                if session is not None and session.active:
                    manager.finish(session, failed=failed)
            finally:
                manager.shutdown()
    except Exception as error:
        if browser_launched:
            raise _BrowserLaunchedCommandError(error) from error
        raise


def _browser_status(configured_path: Path | None) -> tuple[bool, str]:
    if configured_path is not None:
        available = configured_path.is_file() and not configured_path.is_symlink()
        return available, str(configured_path)

    for name in (
        "google-chrome",
        "google-chrome-stable",
        "chromium",
        "chromium-browser",
        "chrome",
        "msedge",
    ):
        executable = shutil.which(name)
        if executable:
            return True, executable

    candidates = (
        Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
        Path("/Applications/Chromium.app/Contents/MacOS/Chromium"),
        Path("C:/Program Files/Google/Chrome/Application/chrome.exe"),
        Path("C:/Program Files (x86)/Google/Chrome/Application/chrome.exe"),
    )
    for candidate in candidates:
        if candidate.is_file():
            return True, str(candidate)
    return False, "Chrome/Chromium executable not found"


def _dependency_status(app_dir: Path) -> tuple[bool, str]:
    if not (app_dir / "pyproject.toml").is_file():
        return False, "pyproject.toml is missing"
    if not (app_dir / "uv.lock").is_file():
        return False, "uv.lock is missing"
    uv = shutil.which("uv")
    if uv is None:
        return False, "uv executable not found on PATH"
    try:
        completed = subprocess.run(
            [
                uv,
                "sync",
                "--check",
                "--locked",
                "--offline",
                "--no-cache",
            ],
            cwd=app_dir,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return False, type(error).__name__
    if completed.returncode == 0:
        return True, "uv environment matches uv.lock"
    detail = (completed.stderr or completed.stdout).strip().splitlines()
    return False, detail[-1][:200] if detail else "uv dependency check failed"


def _new_run_id() -> str:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"run-{timestamp}-{uuid4().hex[:8]}"


def _print(payload: object) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


__all__ = [
    "ApplicationBlockedError",
    "ApplicationDefinition",
    "CounterexampleContextFactory",
    "ElementVerifier",
    "RuntimeOptions",
    "collect_blockers",
    "main",
]
