"""Shared command surface for compact V2 RPA applications."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
import json
from pathlib import Path
import subprocess
import sys
from typing import Any
from uuid import uuid4

from .browser_manager import (
    BrowserLaunchSpec,
    BrowserLifecyclePolicy,
    BrowserManager,
)
from .contracts import RunMode
from .elements import ElementEntry, element_specs, load_element_catalog
from .runtime import BaseProgram, CheckpointStore, ExecutionContext, Runner


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


@dataclass(frozen=True, slots=True)
class ApplicationDefinition:
    """The small Python seam between one application and the shared CLI."""

    app_dir: Path
    build_program: Callable[[], BaseProgram]
    load_runtime_options: RuntimeLoader
    element_blocker_ids: Mapping[str, str]
    additional_blockers: BlockerLoader = lambda: ()
    verify_element_stages: ElementVerifier | None = None

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
                "exception_type": type(error).__name__,
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
    _print(
        {
            "ok": True,
            "app_id": program.spec.app_id,
            "program_id": program.spec.program_id,
            "python_supported": sys.version_info[:2] == (3, 12),
            "local_store_config_exists": (
                application.app_dir / "config" / "stores.local.toml"
            ).is_file(),
            "element_count": len(entries),
            "blockers": list(blockers),
            "real_browser_launched": False,
        }
    )
    return 0


def _test(application: ApplicationDefinition) -> int:
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
        )
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
        result = Runner().resume(program, context) if resume else Runner().run(program, context)
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


def _new_run_id() -> str:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"run-{timestamp}-{uuid4().hex[:8]}"


def _print(payload: object) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


__all__ = [
    "ApplicationBlockedError",
    "ApplicationDefinition",
    "ElementVerifier",
    "RuntimeOptions",
    "collect_blockers",
    "main",
]
