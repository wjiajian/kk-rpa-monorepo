"""Shared development checks and unattended application commands."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from uuid import uuid4

import tomllib

from .browser_manager import BrowserLaunchSpec, BrowserLifecyclePolicy, BrowserManager
from .contracts import RunMode
from .diagnostics import exception_diagnostics
from .downloads import prepare_download_directory
from .elements import ElementEntry, element_specs, load_element_catalog
from .runtime import (
    BaseProgram,
    ExecutionContext,
    Runner,
    RuntimeContractError,
    Step,
    validate_resume,
)
from .verification import Counterexample, assert_steps_are_falsifiable


@dataclass(frozen=True, slots=True)
class RuntimeOptions:
    account_id: str
    profile_dir: Path
    download_dir: Path
    debug_port: int = 0
    browser_path: Path | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    inputs: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ApplicationDefinition:
    app_dir: Path
    build_program: Callable[[], BaseProgram]
    load_runtime_options: Callable[[str], RuntimeOptions]
    build_test_context: Callable[[Step, Counterexample | None, Path], ExecutionContext]
    verify_element_stages: Callable[
        [ExecutionContext, Mapping[str, ElementEntry]], Mapping[str, Any]
    ]
    build_services: Callable[[ExecutionContext], Mapping[str, Any]] = lambda context: {}


def validate_application(application: ApplicationDefinition) -> None:
    manifest = tomllib.loads(
        (application.app_dir / "app.toml").read_text(encoding="utf-8")
    )
    if manifest.get("app_id") != application.build_program().spec.app_id:
        raise ValueError("app.toml and program app IDs differ")
    if not manifest.get("name") or not manifest.get("entrypoint"):
        raise ValueError("app.toml needs name and entrypoint")
    if not (application.app_dir / "requirement.md").is_file():
        raise ValueError("requirement.md is missing")
    load_element_catalog(application.app_dir / "elements.toml")


def collect_blockers(application: ApplicationDefinition) -> tuple[str, ...]:
    return tuple(
        key
        for key, entry in load_element_catalog(
            application.app_dir / "elements.toml"
        ).items()
        if not entry.spec.is_resolved
    )


def main(application: ApplicationDefinition, argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rpa-app")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("doctor", "run", "verify-elements"):
        command = commands.add_parser(name)
        command.add_argument("--account", default="STORE_001")
        if name == "run":
            command.add_argument(
                "--preview",
                action="store_true",
                help="use preview mode in configured business services",
            )
    resume = commands.add_parser("resume")
    resume.add_argument("run_id")
    resume.add_argument(
        "--from-step",
        required=True,
        help="step selected after inspecting and preparing the browser",
    )
    commands.add_parser("test")
    args = parser.parse_args(argv)
    try:
        validate_application(application)
        if args.command == "doctor":
            return _doctor(application, args.account)
        if args.command == "test":
            return _test(application)
        if args.command == "resume":
            previous = _read_failed_run(application, args.run_id, args.from_step)
            return _execute(
                application,
                account=previous["account_id"],
                mode=RunMode(previous["mode"]),
                previous=previous,
                from_step=args.from_step,
            )
        return _execute(
            application,
            account=args.account,
            mode=RunMode.PREVIEW if getattr(args, "preview", False) else RunMode.LIVE,
            verify_elements=args.command == "verify-elements",
        )
    except Exception as error:
        _print(
            {
                "ok": False,
                "error": getattr(error, "error_code", "application_command_failed"),
                "exception_type": type(error).__name__,
                "step_id": getattr(error, "step_id", None),
                "run_id": getattr(error, "run_id", None),
                "diagnostics": exception_diagnostics(error),
            }
        )
        return 2


def _test(application: ApplicationDefinition) -> int:
    with TemporaryDirectory(prefix="rpa-app-test-") as temporary:
        root = Path(temporary).resolve()
        serial = 0

        def context_factory(
            step: Step, case: Counterexample | None
        ) -> ExecutionContext:
            nonlocal serial
            serial += 1
            return application.build_test_context(step, case, root / str(serial))

        assert_steps_are_falsifiable(application.build_program().steps, context_factory)
    return subprocess.run(
        [sys.executable, "-m", "pytest"], cwd=application.app_dir, check=False
    ).returncode


def _doctor(application: ApplicationDefinition, account: str) -> int:
    blockers = collect_blockers(application)
    configuration_error = None
    options = None
    try:
        options = application.load_runtime_options(account)
    except Exception as error:
        configuration_error = type(error).__name__
    browser_ok, browser_detail = _browser_status(
        options.browser_path if options else None
    )
    dependencies_ok, dependency_detail = _dependency_status(application.app_dir)
    ok = (
        sys.version_info[:2] == (3, 12)
        and options is not None
        and browser_ok
        and dependencies_ok
        and not blockers
    )
    _print(
        {
            "ok": ok,
            "account": account,
            "configuration_error": configuration_error,
            "browser_available": browser_ok,
            "browser_detail": browser_detail,
            "dependencies_synchronized": dependencies_ok,
            "dependency_detail": dependency_detail,
            "blockers": blockers,
            "real_browser_launched": False,
        }
    )
    return 0 if ok else 2


def _read_failed_run(
    application: ApplicationDefinition, run_id: str, from_step: str
) -> Mapping[str, Any]:
    if Path(run_id).name != run_id or run_id in {"", ".", ".."}:
        raise RuntimeContractError("run_id must be a run directory name")
    path = application.app_dir / "runs" / run_id / "result.json"
    previous = json.loads(path.read_text(encoding="utf-8"))
    validate_resume(application.build_program(), previous, from_step)
    if previous.get("run_id") != run_id:
        raise RuntimeContractError("run ID differs from its directory")
    return previous


def _execute(
    application: ApplicationDefinition,
    *,
    account: str,
    mode: RunMode,
    verify_elements: bool = False,
    previous: Mapping[str, Any] | None = None,
    from_step: str | None = None,
) -> int:
    blockers = collect_blockers(application)
    if blockers:
        _print(
            {
                "ok": False,
                "error": "unresolved_element_locators",
                "elements": blockers,
                "real_browser_launched": False,
            }
        )
        return 2
    options = application.load_runtime_options(account)
    program = application.build_program()
    entries = load_element_catalog(application.app_dir / "elements.toml")
    run_id = _new_run_id()
    run_dir = application.app_dir / "runs" / run_id
    context = ExecutionContext(
        app_id=program.spec.app_id,
        run_id=run_id,
        account_id=options.account_id,
        run_dir=run_dir,
        download_dir=Path(previous["download_dir"])
        if previous is not None
        else options.download_dir,
        mode=mode,
        services={"elements": element_specs(entries)},
        metadata=dict(options.metadata),
        inputs=dict(previous["inputs"] if previous is not None else options.inputs),
    )
    context.services.update(application.build_services(context))
    manager = BrowserManager(application.app_dir / "runtime" / "browser-manager")
    session = None
    failed = True
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
            download_dir=context.download_dir,
        )
        context.services["browser"] = session.actions
        if previous is None:
            prepare_download_directory(
                context.download_dir, app_dir=application.app_dir, run_dir=run_dir
            )
        if verify_elements:
            payload = dict(application.verify_element_stages(context, entries))
            failed = not bool(payload.get("ok"))
            payload.update(run_id=run_id, real_browser_launched=True)
            _print(payload)
            return 2 if failed else 0
        result = Runner().run(program, context, previous=previous, from_step=from_step)
        failed = False
        _print(
            {
                "ok": True,
                "run_id": result.run_id,
                "status": result.status,
                "completed_steps": result.completed_steps,
                "download_dir": str(context.download_dir),
                "resumed_from": previous["run_id"] if previous is not None else None,
            }
        )
        return 0
    finally:
        try:
            if session is not None and session.active:
                manager.finish(session, failed=failed)
        finally:
            manager.shutdown()


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
