"""Standard application CLI with fail-closed real-browser authorization gates."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
from typing import Sequence

from .real_runtime import (
    ApplicationRuntimeError,
    execute_candidate_verification,
    execute_login,
    execute_standard_run,
)
from .validators import APP_DIR, RunBlockedError, application_report, doctor, ensure_real_run_ready


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rpa-app")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor")
    commands.add_parser("check")
    commands.add_parser("test")

    login = commands.add_parser("login")
    login.add_argument("--account", default="STORE_001")
    login.add_argument("--batch-id")

    verify = commands.add_parser("verify-candidates")
    verify.add_argument("--account", default="STORE_001")
    verify.add_argument("--batch-id")
    candidate_run = verify.add_mutually_exclusive_group()
    candidate_run.add_argument("--run-id")
    candidate_run.add_argument("--resume-run-id")

    run = commands.add_parser("run")
    run.add_argument("--mode", choices=("preview", "live"), required=True)
    run.add_argument("--account", default="STORE_001")
    run.add_argument("--run-id")

    resume = commands.add_parser("resume")
    resume.add_argument("--run-id", required=True)
    resume.add_argument("--mode", choices=("preview", "live"), required=True)
    resume.add_argument("--account", default="STORE_001")
    return parser


def _print(payload: object) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def _run_standard_command(
    command: str,
    mode: str,
    account: str,
    run_id: str | None,
) -> int:
    try:
        ensure_real_run_ready()
    except RunBlockedError as error:
        _print(
            {
                "ok": False,
                "command": command,
                "mode": mode,
                "account": account,
                "error_code": error.error_code,
                "blocker_ids": list(error.blocker_ids),
                "run_directory_created": False,
                "real_browser_launched": False,
            }
        )
        return 3
    try:
        _print(
            execute_standard_run(
                command=command,
                account=account,
                mode=mode,
                run_id=run_id,
            )
        )
        return 0
    except ApplicationRuntimeError as error:
        return _print_runtime_error(command, account, error, mode=mode)


def _print_runtime_error(
    command: str,
    account: str,
    error: ApplicationRuntimeError,
    *,
    mode: str | None = None,
) -> int:
    payload: dict[str, object] = {
        "ok": False,
        "command": command,
        "account": account,
        "error_code": error.error_code,
        "real_browser_launched": error.real_browser_launched,
        "browser_cleanup_attempted": error.real_browser_launched,
    }
    if mode is not None:
        payload["mode"] = mode
    if error.run_id is not None:
        payload["run_id"] = error.run_id
    if error.step_id is not None:
        payload["step_id"] = error.step_id
    if error.instruction_id is not None:
        payload["instruction_id"] = error.instruction_id
    if error.exception_type is not None:
        payload["exception_type"] = error.exception_type
    _print(payload)
    return 4 if not error.real_browser_launched else 5


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "doctor":
        report = doctor()
        _print({"ok": report.python_supported, "doctor": report.to_dict()})
        return 0 if report.python_supported else 1
    if args.command == "check":
        report = application_report()
        _print(report.to_dict())
        return 0 if report.ok else 2
    if args.command == "test":
        completed = subprocess.run(
            [sys.executable, "-m", "pytest"],
            cwd=APP_DIR,
            check=False,
        )
        return completed.returncode
    if args.command == "login":
        try:
            _print(execute_login(account=args.account, batch_id=args.batch_id))
            return 0
        except ApplicationRuntimeError as error:
            return _print_runtime_error(args.command, args.account, error)
    if args.command == "verify-candidates":
        try:
            _print(
                execute_candidate_verification(
                    account=args.account,
                    batch_id=args.batch_id,
                    run_id=args.run_id,
                    resume_run_id=args.resume_run_id,
                )
            )
            return 0
        except ApplicationRuntimeError as error:
            return _print_runtime_error(args.command, args.account, error, mode="preview")
    if args.command in {"run", "resume"}:
        return _run_standard_command(
            args.command,
            args.mode,
            args.account,
            args.run_id,
        )
    raise AssertionError(f"unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
