"""Standard application CLI with fail-closed real-browser authorization gates."""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from datetime import UTC, datetime
import getpass
import json
import os
import subprocess
import sys
from typing import Sequence
from uuid import uuid4

from rpa_core import exception_diagnostics

from .real_runtime import (
    ApplicationRuntimeError,
    LiveUnsupportedError,
    create_authorization_request,
    execute_candidate_verification,
    execute_element_verification,
    execute_login,
    execute_standard_run,
    grant_authorization_request,
    release_retained_browser,
    revoke_authorization_request,
)
from .validators import APP_DIR, RunBlockedError, application_report, doctor, ensure_real_run_ready


_INTERACTIVE_PREVIEW_TTL_SECONDS = 300
_TRUSTED_ERROR_MODULES = ("rpa_core", "inventory_jushuitan_export_stock")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rpa-app")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor")
    commands.add_parser("check")
    commands.add_parser("test")

    preview = commands.add_parser(
        "preview",
        help="request, confirm, grant, and run one Preview interactively",
    )
    preview.add_argument("--account", default="STORE_001")

    authorization = commands.add_parser("authorization")
    authorization_commands = authorization.add_subparsers(
        dest="authorization_command",
        required=True,
    )
    authorization_request = authorization_commands.add_parser("request")
    authorization_request.add_argument(
        "--operation",
        choices=("login", "verify-candidates", "verify-elements", "run", "resume"),
        required=True,
    )
    authorization_request.add_argument(
        "--mode",
        choices=("preview", "live"),
        default="preview",
    )
    authorization_request.add_argument("--account", default="STORE_001")
    authorization_request.add_argument("--run-id", required=True)
    authorization_request.add_argument("--authorization-id")
    authorization_request.add_argument("--requested-by", default="developer")

    authorization_grant = authorization_commands.add_parser("grant")
    authorization_grant.add_argument("--authorization-id", required=True)
    authorization_grant.add_argument("--scope-digest", required=True)
    authorization_grant.add_argument("--authorized-by", required=True)
    authorization_grant.add_argument("--approval-reference", required=True)
    authorization_grant.add_argument("--ttl-seconds", type=int, required=True)

    login = commands.add_parser("login")
    login.add_argument("--account", default="STORE_001")
    login.add_argument("--run-id", required=True)
    login.add_argument("--authorization-id", required=True)

    verify_elements = commands.add_parser("verify-elements")
    verify_elements.add_argument("--account", required=True)
    verify_elements.add_argument("--run-id", required=True)
    verify_elements.add_argument("--authorization-id", required=True)

    verify = commands.add_parser("verify-candidates")
    verify.add_argument("--account", default="STORE_001")
    verify.add_argument("--run-id", required=True)
    verify.add_argument("--authorization-id", required=True)

    run = commands.add_parser("run")
    run.add_argument("--mode", choices=("preview", "live"), required=True)
    run.add_argument("--account", default="STORE_001")
    run.add_argument("--run-id", required=True)
    run.add_argument("--authorization-id", required=True)

    browser = commands.add_parser(
        "browser",
        help="manage the browser a failed run left open",
    )
    browser_commands = browser.add_subparsers(
        dest="browser_command",
        required=True,
    )
    browser_release = browser_commands.add_parser(
        "release",
        help="close the browser retained by the last failed run",
    )
    browser_release.add_argument("--account", default="STORE_001")

    resume = commands.add_parser("resume")
    resume.add_argument("--run-id", required=True)
    resume.add_argument("--mode", choices=("preview", "live"), required=True)
    resume.add_argument("--account", default="STORE_001")
    resume.add_argument("--authorization-id", required=True)
    return parser


def _print(payload: object) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def _error_diagnostics(error: BaseException) -> dict[str, object]:
    return exception_diagnostics(
        error,
        source_root=APP_DIR.parents[1],
        trusted_module_prefixes=_TRUSTED_ERROR_MODULES,
    )


def _is_interactive_terminal() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def _local_developer_id() -> str:
    try:
        developer_id = getpass.getuser().strip()
    except (KeyError, OSError) as error:
        raise ApplicationRuntimeError(
            "local_developer_identity_unavailable",
            real_browser_launched=False,
            exception_type=type(error).__name__,
        ) from error
    if not developer_id:
        raise ApplicationRuntimeError(
            "local_developer_identity_unavailable",
            real_browser_launched=False,
        )
    return developer_id


def _new_preview_ids() -> tuple[str, str]:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_id = f"preview-{timestamp}-{uuid4().hex[:8]}"
    return run_id, f"auth-{run_id}"


def _requested_authorization(
    payload: object,
    *,
    expected_authorization_id: str,
    expected_run_id: str,
    expected_account: str,
) -> tuple[Mapping[str, object], Mapping[str, object], str]:
    if not isinstance(payload, Mapping):
        raise ApplicationRuntimeError(
            "authorization_record_invalid",
            real_browser_launched=False,
        )
    authorization = payload.get("authorization")
    if not isinstance(authorization, Mapping):
        raise ApplicationRuntimeError(
            "authorization_record_invalid",
            real_browser_launched=False,
        )
    scope = authorization.get("scope")
    scope_digest = authorization.get("scope_digest")
    expected_scope = {
        "operation": "run",
        "mode": "preview",
        "run_id": expected_run_id,
        "account_id": expected_account,
    }
    if (
        not isinstance(scope, Mapping)
        or not isinstance(scope_digest, str)
        or authorization.get("authorization_id") != expected_authorization_id
        or any(scope.get(key) != value for key, value in expected_scope.items())
    ):
        raise ApplicationRuntimeError(
            "authorization_record_invalid",
            real_browser_launched=False,
        )
    return authorization, scope, scope_digest


def _compact_scope_value(value: object) -> str:
    if isinstance(value, list):
        return "[" + ", ".join(str(item) for item in value) + "]"
    return str(value)


def _print_preview_confirmation(
    authorization: Mapping[str, object],
    scope: Mapping[str, object],
) -> None:
    del authorization
    account_id = scope.get("account_id")
    external_writes = _compact_scope_value(scope.get("external_writes"))
    print(f"\n即将执行 Preview：{account_id}")
    print(f"会真实登录、查询和下载；external_writes: {external_writes}")


def _location_text(location: object) -> str | None:
    if not isinstance(location, Mapping):
        return None
    file = location.get("file")
    line = location.get("line")
    function = location.get("function")
    if not isinstance(file, str) or not isinstance(line, int):
        return None
    suffix = f" ({function})" if isinstance(function, str) and function else ""
    return f"{file}:{line}{suffix}"


def _trigger_location(payload: Mapping[str, object]) -> str | None:
    root_cause = payload.get("root_cause")
    root_index = root_cause.get("index") if isinstance(root_cause, Mapping) else None
    traceback_frames = payload.get("traceback")
    if not isinstance(traceback_frames, list):
        return None
    app_source_prefix = f"apps/{APP_DIR.name}/src/"
    candidates = [
        frame
        for frame in traceback_frames
        if isinstance(frame, Mapping)
        and frame.get("exception_index") == root_index
        and isinstance(frame.get("file"), str)
        and str(frame["file"]).startswith(app_source_prefix)
    ]
    return _location_text(candidates[-1]) if candidates else None


def _write_error_diagnostics(payload: Mapping[str, object]) -> str | None:
    run_id = payload.get("run_id")
    if not isinstance(run_id, str) or not run_id:
        return None
    try:
        rendered = json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ) + "\n"
        app_root = APP_DIR.resolve(strict=True)
        runs_root = (APP_DIR / "runs").resolve(strict=True)
        runs_root.relative_to(app_root)
        run_dir = (APP_DIR / "runs" / run_id).resolve(strict=True)
        run_dir.relative_to(runs_root)
        if not run_dir.is_dir():
            return None
        name = (
            "error-diagnostics-"
            f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%S%fZ')}-"
            f"{uuid4().hex[:8]}.json"
        )
        target = run_dir / name
        flags = (
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0)
        )
        descriptor = os.open(target, flags, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(rendered)
    except (OSError, TypeError, ValueError):
        return None
    return (APP_DIR / "runs" / run_id / name).relative_to(APP_DIR).as_posix()


def _print_compact_failure(payload: Mapping[str, object]) -> None:
    mode = payload.get("mode")
    command = payload.get("command", "command")
    title = "Preview failed" if mode == "preview" else f"{command} failed"
    step_id = payload.get("step_id")
    instruction_id = payload.get("instruction_id")
    scope = " / ".join(
        str(value) for value in (step_id, instruction_id) if value is not None
    )
    print(f"\n{title}{f' — {scope}' if scope else ''}")

    root_cause = payload.get("root_cause")
    if isinstance(root_cause, Mapping):
        error_type = root_cause.get("type")
        error_code = root_cause.get("error_code") or payload.get("error_code")
        message = root_cause.get("message")
        rendered_error = (
            f"{error_type} ({error_code})" if error_type else str(error_code)
        )
        print(f"  root_cause: {rendered_error}")
        if isinstance(message, str):
            print(f"  message: {message}")
        trigger = _trigger_location(payload)
        raised = _location_text(root_cause.get("location"))
        if trigger is not None and trigger != raised:
            print(f"  triggered_at: {trigger}")
        if raised is not None:
            print(f"  raised_at: {raised}")
    else:
        print(f"  error_code: {payload.get('error_code')}")

    blocker_ids = payload.get("blocker_ids")
    if isinstance(blocker_ids, list) and blocker_ids:
        print(f"  blocker_ids: {_compact_scope_value(blocker_ids)}")

    _print_retained_browser(payload)

    details_file = _write_error_diagnostics(payload)
    if details_file is not None:
        print(f"  details: {details_file}")
    run_id = payload.get("run_id")
    if run_id is not None:
        print(f"  run_id: {run_id}")


def _print_retained_browser(payload: Mapping[str, object]) -> None:
    """Say the browser is still open, and how to pick the run back up."""

    retained = payload.get("retained_browser")
    if not isinstance(retained, Mapping):
        return
    print(
        "  retained_browser: "
        f"port={retained.get('port')} pid={retained.get('browser_pid')}"
        " —— 窗口停在失败现场，下一次 run/resume 会接管它"
    )
    run_id = payload.get("run_id")
    mode = payload.get("mode")
    if isinstance(run_id, str) and isinstance(mode, str):
        print(
            f"  resume: rpa-app resume --run-id {run_id} --mode {mode}"
            " --authorization-id <id>"
        )
    print("  release: rpa-app browser release")


def _emit_failure(payload: Mapping[str, object], *, compact: bool) -> None:
    if compact:
        _print_compact_failure(payload)
    else:
        _print(payload)


def _confirm_preview() -> bool:
    try:
        answer = input("确认执行本次 Preview？[y/N] ")
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    return answer.strip().casefold() in {"y", "yes"}


def _run_interactive_preview(account: str) -> int:
    if not _is_interactive_terminal():
        return _print_runtime_error(
            "preview",
            account,
            ApplicationRuntimeError(
                "interactive_confirmation_required",
                real_browser_launched=False,
            ),
            mode="preview",
        )
    try:
        ensure_real_run_ready()
    except RunBlockedError as error:
        _emit_failure(
            {
                "ok": False,
                "command": "preview",
                "mode": "preview",
                "account": account,
                "error_code": error.error_code,
                "blocker_ids": list(error.blocker_ids),
                "run_directory_created": False,
                "real_browser_launched": False,
                **_error_diagnostics(error),
            },
            compact=True,
        )
        return 3

    try:
        developer_id = _local_developer_id()
        run_id, authorization_id = _new_preview_ids()
        requested = create_authorization_request(
            operation="run",
            account=account,
            mode="preview",
            run_id=run_id,
            requested_by=developer_id,
            authorization_id=authorization_id,
        )
        authorization, scope, scope_digest = _requested_authorization(
            requested,
            expected_authorization_id=authorization_id,
            expected_run_id=run_id,
            expected_account=account,
        )
        _print_preview_confirmation(authorization, scope)
        if not _confirm_preview():
            revoked = revoke_authorization_request(
                authorization_id=authorization_id,
                revoked_by=developer_id,
                reason="interactive_preview_declined",
            )
            revoked_authorization = revoked.get("authorization")
            status = (
                revoked_authorization.get("status")
                if isinstance(revoked_authorization, Mapping)
                else "revoked"
            )
            _print(
                {
                    "ok": True,
                    "command": "preview",
                    "status": "cancelled",
                    "authorization_id": authorization_id,
                    "authorization_status": status,
                    "run_directory_created": False,
                    "real_browser_launched": False,
                }
            )
            return 0
        grant_authorization_request(
            authorization_id=authorization_id,
            scope_digest=scope_digest,
            authorized_by=developer_id,
            approval_reference=f"interactive-preview:{run_id}",
            ttl_seconds=_INTERACTIVE_PREVIEW_TTL_SECONDS,
        )
        return _run_standard_command(
            "run",
            "preview",
            account,
            run_id,
            authorization_id,
            compact_errors=True,
        )
    except ApplicationRuntimeError as error:
        return _print_runtime_error(
            "preview",
            account,
            error,
            mode="preview",
            compact=True,
        )


def _run_standard_command(
    command: str,
    mode: str,
    account: str,
    run_id: str,
    authorization_id: str,
    *,
    compact_errors: bool = False,
) -> int:
    if mode == "live":
        return _print_runtime_error(
            command,
            account,
            LiveUnsupportedError(),
            mode=mode,
        )
    try:
        ensure_real_run_ready()
    except RunBlockedError as error:
        _emit_failure(
            {
                "ok": False,
                "command": command,
                "mode": mode,
                "account": account,
                "error_code": error.error_code,
                "blocker_ids": list(error.blocker_ids),
                "run_directory_created": False,
                "real_browser_launched": False,
                **_error_diagnostics(error),
            },
            compact=compact_errors,
        )
        return 3
    try:
        _print(
            execute_standard_run(
                command=command,
                account=account,
                mode=mode,
                run_id=run_id,
                authorization_id=authorization_id,
            )
        )
        return 0
    except ApplicationRuntimeError as error:
        return _print_runtime_error(
            command,
            account,
            error,
            mode=mode,
            compact=compact_errors,
        )


def _print_runtime_error(
    command: str,
    account: str,
    error: ApplicationRuntimeError,
    *,
    mode: str | None = None,
    compact: bool = False,
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
    if error.retained_browser is not None:
        payload["retained_browser"] = dict(error.retained_browser)
    payload.update(_error_diagnostics(error))
    _emit_failure(payload, compact=compact)
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
    if args.command == "preview":
        return _run_interactive_preview(args.account)
    if args.command == "authorization":
        raw_operation = getattr(args, "operation", None)
        operation = raw_operation.replace("-", "_") if raw_operation else raw_operation
        command = f"authorization {args.authorization_command}"
        try:
            if args.authorization_command == "request":
                _print(
                    create_authorization_request(
                        operation=operation,
                        account=args.account,
                        mode=args.mode,
                        run_id=args.run_id,
                        requested_by=args.requested_by,
                        authorization_id=args.authorization_id,
                    )
                )
            else:
                _print(
                    grant_authorization_request(
                        authorization_id=args.authorization_id,
                        scope_digest=args.scope_digest,
                        authorized_by=args.authorized_by,
                        approval_reference=args.approval_reference,
                        ttl_seconds=args.ttl_seconds,
                    )
                )
            return 0
        except ApplicationRuntimeError as error:
            return _print_runtime_error(
                command,
                getattr(args, "account", "<not-applicable>"),
                error,
                mode=getattr(args, "mode", None),
            )
    if args.command == "login":
        try:
            _print(
                execute_login(
                    account=args.account,
                    run_id=args.run_id,
                    authorization_id=args.authorization_id,
                )
            )
            return 0
        except ApplicationRuntimeError as error:
            return _print_runtime_error(args.command, args.account, error)
    if args.command == "verify-elements":
        try:
            payload = execute_element_verification(
                account=args.account,
                run_id=args.run_id,
                authorization_id=args.authorization_id,
            )
        except ApplicationRuntimeError as error:
            return _print_runtime_error(args.command, args.account, error, mode="preview")
        for item in payload["checks"]:
            actual = "-" if item["actual"] is None else item["actual"]
            line = f"{item['status']:<4} {item['element_id']:<50} expect={item['expect']:<4} actual={actual}"
            print(f"{line}  {item['detail']}" if item["detail"] else line)
        _print(payload)
        return 0 if payload["ok"] else 1
    if args.command == "verify-candidates":
        try:
            _print(
                execute_candidate_verification(
                    account=args.account,
                    run_id=args.run_id,
                    authorization_id=args.authorization_id,
                )
            )
            return 0
        except ApplicationRuntimeError as error:
            return _print_runtime_error(args.command, args.account, error, mode="preview")
    if args.command == "browser":
        try:
            _print(release_retained_browser(account=args.account))
            return 0
        except ApplicationRuntimeError as error:
            return _print_runtime_error(
                f"browser {args.browser_command}",
                args.account,
                error,
            )
    if args.command in {"run", "resume"}:
        return _run_standard_command(
            args.command,
            args.mode,
            args.account,
            args.run_id,
            args.authorization_id,
        )
    raise AssertionError(f"unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
