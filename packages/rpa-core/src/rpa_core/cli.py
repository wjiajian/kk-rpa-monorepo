"""Shared development checks and unattended application commands."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from uuid import uuid4

import tomllib

from .browser_manager import (
    BrowserLaunchSpec, BrowserLifecyclePolicy, BrowserManager, BrowserSession,
)
from .contracts import RunMode
from .diagnostics import exception_diagnostics
from .downloads import prepare_download_directory
from .elements import ElementEntry, element_specs, load_element_catalog, override_element_locators
from .events import JsonlEventLogger, sanitize_event_value
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
class RunRequest:
    """Invocation parameters; credentials are never part of the saved inputs."""

    account_id: str = "STORE_001"
    inputs: Mapping[str, Any] = field(default_factory=dict)
    credentials: Mapping[str, str] = field(default_factory=dict, repr=False)
    download_dir: str | None = None

    def __post_init__(self) -> None:
        if self.download_dir is not None and (
            not isinstance(self.download_dir, str) or not self.download_dir.strip()
        ):
            raise RuntimeContractError("download_dir must be a non-empty path")
        if not isinstance(self.inputs, Mapping) or not isinstance(self.credentials, Mapping):
            raise RuntimeContractError("inputs and credentials must be mappings")
        if any(not isinstance(value, str) or not value.strip() for value in self.credentials.values()):
            raise RuntimeContractError("credential values must be non-empty strings")


@dataclass(frozen=True, slots=True)
class RuntimeOptions:
    account_id: str
    profile_dir: Path
    download_dir: Path
    debug_port: int = 0
    browser_path: Path | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict, repr=False)
    inputs: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ApplicationDefinition:
    app_dir: Path
    build_program: Callable[[], BaseProgram]
    load_runtime_options: Callable[[RunRequest], RuntimeOptions]
    build_test_context: Callable[[Step, Counterexample | None, Path], ExecutionContext]
    verify_element_stages: Callable[
        [ExecutionContext, Mapping[str, ElementEntry]], Mapping[str, Any]
    ]
    build_services: Callable[[ExecutionContext], Mapping[str, Any]] = lambda context: {}


@dataclass(frozen=True, slots=True)
class RecoverySession:
    """An inspection context, not a completed or resumed run."""

    context: ExecutionContext = field(repr=False)
    source_record: Mapping[str, Any] = field(repr=False)
    browser_adopted: bool


@contextmanager
def open_recovery_session(
    application: ApplicationDefinition,
    run_id: str,
    *,
    credentials: Mapping[str, str] | None = None,
) -> Iterator[RecoverySession]:
    """Connect a failed run for agent inspection without executing any Step.

    Inputs, outputs, account, mode and downloads come from the source record.
    Credentials and services use the application's usual configuration loader.
    Evidence stays in the source run directory; result.json is never written.
    Exit releases Profile ownership and retains the browser for a later resume.
    An adopted browser still needs its account and current page checked.
    """
    previous = _read_failed_run(application, run_id)
    run_dir = application.app_dir / "runs" / run_id
    logger = JsonlEventLogger(run_dir / "recovery-events.jsonl")
    manager = None
    session = None

    def emit(event: str, **details: Any) -> None:
        logger.emit(event, app_id=previous["app_id"], run_id=run_id, details=details)

    try:
        try:
            validate_application(application)
            specs = element_specs(load_element_catalog(application.app_dir / "elements.toml"))
            _check_resolved_elements(specs)
            request = _recovery_request(previous, credentials or {})
            options = application.load_runtime_options(request)
            context = _build_execution_context(
                application.build_program(), request, options,
                run_id=run_id, run_dir=run_dir, mode=RunMode(previous["mode"]),
                specs=specs, previous=previous,
                completed_steps=previous["completed_steps"],
            )
            prepare_download_directory(
                context.download_dir, app_dir=application.app_dir, run_dir=run_dir
            )
            context.services.update(application.build_services(context))
            manager = BrowserManager(application.app_dir / "runtime" / "browser-manager")
            session = _start_browser(manager, application, options, context)
            context.services["browser"] = session.actions
            emit("recovery.opened", browser_adopted=session.adopted)
            yield RecoverySession(context, deepcopy(previous), session.adopted)
        finally:
            if manager is not None:
                try:
                    if session is not None and session.active:
                        manager.detach(session)
                finally:
                    manager.shutdown()
    except BaseException as error:
        emit("recovery.failed", diagnostics=exception_diagnostics(error))
        raise
    else:
        emit("recovery.closed")


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
        command.add_argument("--inputs", help="business inputs as a JSON object or @file")
        command.add_argument("--credentials", help="credentials as a JSON object or @file")
        command.add_argument("--download-dir", help="override the download directory")
        if name == "run":
            command.add_argument(
                "--preview",
                action="store_true",
                help="use preview mode in configured business services",
            )
    resume = commands.add_parser("resume")
    resume.add_argument("run_id")
    resume.add_argument("--credentials", help="credentials as a JSON object or @file")
    resume.add_argument("--step-result", help="agent-completed failed-step output as JSON or @file")
    resume.add_argument("--locator-overrides", help="temporary locator fields as JSON or @file")
    resume.add_argument(
        "--from-step",
        required=True,
        help="step selected after inspecting and preparing the browser",
    )
    commands.add_parser("test")
    args = parser.parse_args(argv)
    try:
        if args.command == "test":
            validate_application(application)
            return _test(application)
        credentials = _json_object(args.credentials)
        if args.command == "resume":
            previous = _read_failed_run(application, args.run_id)
            validate_resume(application.build_program(), previous, args.from_step)
            return _execute(
                application,
                request=_recovery_request(previous, credentials),
                mode=RunMode(previous["mode"]),
                previous=previous,
                from_step=args.from_step,
                step_result=_json_object(args.step_result) if args.step_result is not None else None,
                locator_overrides=_json_object(args.locator_overrides),
            )
        request = RunRequest(args.account, _json_object(args.inputs), credentials, args.download_dir)
        if args.command == "doctor":
            validate_application(application)
            return _doctor(application, request)
        return _execute(
            application,
            request=request,
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


def _json_object(raw: str | None) -> dict[str, Any]:
    if raw is None:
        return {}
    try:
        text = Path(raw[1:]).read_text(encoding="utf-8-sig") if raw.startswith("@") else raw
        value = json.loads(text)
    except (OSError, UnicodeError, ValueError) as error:
        raise RuntimeContractError("argument must be a JSON object or @JSON-file") from error
    if not isinstance(value, dict):
        raise RuntimeContractError("argument must be a JSON object")
    return value


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


def _doctor(application: ApplicationDefinition, request: RunRequest) -> int:
    blockers = collect_blockers(application)
    configuration_error = None
    options = None
    try:
        options = application.load_runtime_options(request)
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
            "account": request.account_id,
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
    application: ApplicationDefinition, run_id: str
) -> Mapping[str, Any]:
    if Path(run_id).name != run_id or run_id in {"", ".", ".."}:
        raise RuntimeContractError("run_id must be a run directory name")
    path = application.app_dir / "runs" / run_id / "result.json"
    previous = json.loads(path.read_text(encoding="utf-8"))
    program = application.build_program()
    if (
        not isinstance(previous, Mapping)
        or previous.get("app_id") != program.spec.app_id
        or previous.get("status") != "failed"
    ):
        raise RuntimeContractError("recovery needs a failed run of this application")
    if previous.get("run_id") != run_id:
        raise RuntimeContractError("run ID differs from its directory")
    if not isinstance(previous.get("inputs"), Mapping):
        raise RuntimeContractError("this run has no saved inputs; supply parameters and start a new run")
    if any(
        not isinstance(previous.get(key), str) or not previous[key].strip()
        for key in ("account_id", "download_dir", "mode")
    ) or previous["mode"] not in {mode.value for mode in RunMode}:
        raise RuntimeContractError("this run lacks account, mode or downloads; supply parameters and start a new run")
    completed = previous.get("completed_steps")
    outputs = previous.get("outputs")
    ids = [step.spec.step_id for step in program.steps]
    if (
        not isinstance(completed, list)
        or completed != ids[:len(completed)]
        or not isinstance(outputs, Mapping)
        or any(not isinstance(outputs.get(key), Mapping) for key in completed)
    ):
        raise RuntimeContractError("this run is missing completed step results; start a new run")
    return previous


def _recovery_request(
    previous: Mapping[str, Any], credentials: Mapping[str, str]
) -> RunRequest:
    return RunRequest(
        previous["account_id"], inputs=deepcopy(previous["inputs"]),
        credentials=credentials, download_dir=previous["download_dir"],
    )


def _check_resolved_elements(specs: Mapping[str, Any]) -> None:
    blockers = [key for key, spec in specs.items() if not spec.is_resolved]
    if blockers:
        raise RuntimeContractError("unresolved element locators: " + ", ".join(blockers))


def _build_execution_context(
    program: BaseProgram,
    request: RunRequest,
    options: RuntimeOptions,
    *,
    run_id: str,
    run_dir: Path,
    mode: RunMode,
    specs: Mapping[str, Any],
    previous: Mapping[str, Any] | None = None,
    completed_steps: Sequence[str] = (),
) -> ExecutionContext:
    if options.account_id != request.account_id:
        raise RuntimeContractError("runtime options changed the requested account")
    if previous is not None and set(options.inputs) - set(previous["inputs"]):
        raise RuntimeContractError("saved inputs are incomplete; supply parameters and start a new run")
    return ExecutionContext(
        app_id=program.spec.app_id,
        run_id=run_id,
        account_id=options.account_id,
        run_dir=run_dir,
        download_dir=Path(previous["download_dir"]) if previous is not None else options.download_dir,
        mode=mode,
        services={"elements": specs},
        metadata=dict(options.metadata),
        inputs=deepcopy(dict(previous["inputs"] if previous is not None else options.inputs)),
        outputs={key: deepcopy(previous["outputs"][key]) for key in completed_steps},
    )


def _start_browser(
    manager: BrowserManager,
    application: ApplicationDefinition,
    options: RuntimeOptions,
    context: ExecutionContext,
) -> BrowserSession:
    return manager.start(
        BrowserLaunchSpec(
            account_id=options.account_id,
            profile_id=f"{application.app_dir.name}.{options.account_id}",
            profile_dir=options.profile_dir,
            requested_port=options.debug_port,
            browser_path=options.browser_path,
            lifecycle=BrowserLifecyclePolicy.KEEP_OPEN_ON_FAILURE,
        ),
        run_id=context.run_id, run_dir=context.run_dir,
        action_timeout=15.0, download_timeout=300.0,
        download_dir=context.download_dir,
    )


def _execute(
    application: ApplicationDefinition,
    *,
    request: RunRequest,
    mode: RunMode,
    verify_elements: bool = False,
    previous: Mapping[str, Any] | None = None,
    from_step: str | None = None,
    step_result: Mapping[str, Any] | None = None,
    locator_overrides: Mapping[str, Any] | None = None,
) -> int:
    run_id = _new_run_id()
    run_dir = application.app_dir / "runs" / run_id
    report_path = run_dir / "result.json"
    context = None
    program = None
    manager = None
    session = None
    failed = True
    phase = "prepare"
    prefix = ()
    try:
        try:
            run_dir.mkdir(parents=True, exist_ok=False)
            program = application.build_program()
            if previous is not None:
                prefix = validate_resume(program, previous, from_step)
            validate_application(application)
            entries = load_element_catalog(application.app_dir / "elements.toml")
            specs = element_specs(entries)
            effective = override_element_locators(specs, locator_overrides or {})
            _check_resolved_elements(effective)
            if step_result is not None and (
                previous is None or previous.get("failed_step") != from_step
            ):
                raise RuntimeContractError("a supplied result must belong to the failed step")
            options = application.load_runtime_options(request)
            context = _build_execution_context(
                program, request, options, run_id=run_id, run_dir=run_dir,
                mode=mode, specs=specs, previous=previous, completed_steps=prefix,
            )
            prepare_download_directory(
                context.download_dir, app_dir=application.app_dir, run_dir=run_dir
            )
            context.services.update(application.build_services(context))
            manager = BrowserManager(application.app_dir / "runtime" / "browser-manager")
            session = _start_browser(manager, application, options, context)
            context.services["browser"] = session.actions
            phase = "verify-elements" if verify_elements else "steps"
            if verify_elements:
                payload = dict(application.verify_element_stages(context, entries))
                failed = not bool(payload.get("ok"))
                payload.update(run_id=run_id, real_browser_launched=True)
            else:
                result = Runner().run(
                    program, context, previous=previous, from_step=from_step,
                    step_result=step_result, locator_overrides=locator_overrides,
                )
                failed = False
                payload = {
                    "ok": True,
                    "run_id": result.run_id,
                    "status": result.status,
                    "completed_steps": result.completed_steps,
                    "outputs": sanitize_event_value(result.outputs),
                    "download_dir": str(context.download_dir),
                    "resumed_from": previous["run_id"] if previous else None,
                }
        finally:
            try:
                if not failed:
                    phase = "cleanup"
                if session is not None and session.active:
                    manager.finish(session, failed=failed)
            finally:
                if manager is not None:
                    manager.shutdown()
    except Exception as error:
        code = getattr(error, "error_code", "application_command_failed")
        diagnostics = exception_diagnostics(error)
        record_error = None
        try:
            report = json.loads(report_path.read_text()) if report_path.exists() else {
                "app_id": program.spec.app_id if program else None,
                "run_id": run_id,
                "account_id": request.account_id,
                "mode": mode.value,
                "inputs": dict(context.inputs) if context else dict(previous["inputs"]) if previous else None,
                "download_dir": str(context.download_dir) if context else request.download_dir,
                "completed_steps": list(prefix),
                "outputs": {key: dict(previous["outputs"][key]) for key in prefix},
            }
            report.update(
                status="failed", failed_step=getattr(error, "step_id", None),
                phase=phase,
                error={"code": code, "type": type(error).__name__, "diagnostics": diagnostics},
            )
            if previous is not None:
                report.update(resumed_from=previous["run_id"], from_step=from_step)
            temporary = report_path.with_suffix(".tmp")
            temporary.write_text(
                json.dumps(sanitize_event_value(report), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            temporary.replace(report_path)
            if phase != "steps":
                JsonlEventLogger(run_dir / "events.jsonl").emit(
                    "run.failed", app_id=report["app_id"], run_id=run_id,
                    status="failed", error_code=code, details={"phase": phase},
                )
        except (OSError, ValueError, TypeError) as recording_error:
            record_error = type(recording_error).__name__
        _print({
            "ok": False, "run_id": run_id, "error": code,
            "exception_type": type(error).__name__,
            "step_id": getattr(error, "step_id", None), "diagnostics": diagnostics,
            "record_error": record_error,
        })
        return 2
    _print(payload)
    return 2 if failed else 0


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
