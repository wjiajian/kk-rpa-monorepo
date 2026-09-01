"""Standard application CLI. Real browser commands fail closed in Patch B."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
from typing import Sequence

from .validators import APP_DIR, RunBlockedError, application_report, doctor, ensure_real_run_ready


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rpa-app")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor")
    commands.add_parser("check")
    commands.add_parser("test")

    login = commands.add_parser("login")
    login.add_argument("--account", default="STORE_001")

    verify = commands.add_parser("verify-candidates")
    verify.add_argument("--account", default="STORE_001")
    verify.add_argument("--batch-id")

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


def _blocked_browser_command(command: str, account: str) -> int:
    _print(
        {
            "ok": False,
            "command": command,
            "account": account,
            "error_code": "real_browser_authorization_required",
            "message": "需要补丁 C 的精确候选验证授权；本命令未启动浏览器。",
            "real_browser_launched": False,
        }
    )
    return 4


def _blocked_run(command: str, mode: str, account: str) -> int:
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
    _print(
        {
            "ok": False,
            "command": command,
            "error_code": "real_browser_stage_not_implemented",
            "run_directory_created": False,
            "real_browser_launched": False,
        }
    )
    return 4


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
    if args.command in {"login", "verify-candidates"}:
        return _blocked_browser_command(args.command, args.account)
    if args.command in {"run", "resume"}:
        return _blocked_run(args.command, args.mode, args.account)
    raise AssertionError(f"unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
