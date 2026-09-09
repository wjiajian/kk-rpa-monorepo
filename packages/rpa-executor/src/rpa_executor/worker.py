"""Fixed application-environment worker. All browser calls run on this thread.

The reader thread can only set stop/connectivity flags, never touch the browser.
The module and Python executable come from local deployment configuration.
"""
import argparse
import base64
import importlib
import importlib.metadata
import json
from pathlib import Path
from queue import Queue, Empty
import re
import sys
from threading import Event, Lock, Thread
from time import monotonic, sleep
import tomllib
from urllib.parse import urlsplit
from uuid import uuid4

from rpa_core.browser import SecretValue
from rpa_core.browser_manager import BrowserManager
from rpa_core.cli import RunRequest, execute_application, open_recovery_session, read_recovery_record


def recovery_context(source, requirement, elements, *, step=None, full=False):
    """Read the requested contract from the application's requirement baseline."""
    step = step or source["failed_step"]
    headings = list(re.finditer(r"(?m)^###\s+(S\d+)\b[^\n]*", requirement))
    selected = next((heading for heading in headings if heading[1] == step), None)
    if full or selected is None:
        return {"source": source, "requirement": requirement, "elements": elements, "scope": "full"}
    end = re.search(r"(?m)^#{1,3}\s", requirement[selected.end():])
    stop = selected.end() + end.start() if end else len(requirement)
    # Preserve all output fields, success conditions and recovery instructions.
    excerpt = requirement[:headings[0].start()] + requirement[selected.start():stop]
    selected_elements = {key: value for key, value in elements.items()
                         if value.get("check_at", "").split("-", 1)[0] == step}
    error = source.get("error") or {}
    root = (error.get("diagnostics") or {}).get("root_cause") or {}
    brief_source = {**source, "error": {key: value for key, value in {
        "code": error.get("code"), "type": root.get("type", error.get("type")),
        "message": root.get("message", error.get("message")), "location": root.get("location"),
    }.items() if value is not None}}
    return {"source": brief_source, "requirement": excerpt,
            "elements": selected_elements or elements, "scope": "step", "step_id": step,
            "available_steps": [heading[0].removeprefix("### ").strip() for heading in headings],
            "more_context": "context(step=步骤ID) 可读其他步骤；context(full=true) 可读完整需求、元素和诊断。"}


class Worker:
    def __init__(self, deployment, emit):
        self.config, self.emit = deployment, emit
        if importlib.metadata.version(deployment["package"]) != deployment["version"]:
            raise ValueError("deployed package version does not match configuration")
        self.app = importlib.import_module(deployment["module"]).APPLICATION
        if self.app.build_program().spec.app_id != deployment["app_id"]:
            raise ValueError("deployed application identity differs")
        self.stopped, self.connected = Event(), Event()
        self.connected.set()
        self.run_id = self.attempt = self.local_id = None
        self.snapshot = None
        self.credentials = {}
        self.recovery = self.cm = None
        self.deadline = None
        self.observed = set()
        self.needs_observation = True
        self.ended = False
        self.cleanup_uncertain = False

    def event(self, kind, data=None):
        self.emit({"type": kind, "console_run_id": self.run_id,
                   "execution_attempt_id": self.attempt, "data": data or {}})

    def check(self, command):
        if self.ended or command["console_run_id"] != self.run_id or command["execution_attempt_id"] != self.attempt:
            raise ValueError("inactive run or stale execution attempt")
        if self.stopped.is_set() or not self.connected.is_set():
            raise ValueError("control is stopped or disconnected")
        if self.deadline is not None and monotonic() >= self.deadline:
            self.stopped.set()
            raise ValueError("recovery budget exhausted")

    def close(self):
        if self.cleanup_uncertain:
            raise ValueError("原框架浏览器收尾失败，进程结束尚未确认")
        if self.recovery:
            if hasattr(self.recovery.context.browser, "release_recovery"):
                self.recovery.context.browser.release_recovery()
            self.recovery.close_browser()
            self.cm.__exit__(None, None, None)
            self.cm = self.recovery = None
        elif self.snapshot and self.local_id:
            manager = BrowserManager(self.app.app_dir / "runtime" / "browser-manager")
            manager.close_retained_browser(f"{self.app.app_dir.name}.{self.profile_id}", expected_run_id=self.local_id)
        self.ended = True
        self.event("ended", {"reason": "cooperative_cleanup"})
        self.credentials.clear()

    def source(self):
        record = read_recovery_record(self.app, self.local_id)
        if (record["account_id"] != self.profile_id or
                record["inputs"] != self.snapshot["inputs"] or
                record["download_dir"] != self.snapshot["download_dir"]):
            raise ValueError("source record differs from original runtime parameters")
        if record.get("phase", "steps") != "steps" or not record.get("failed_step"):
            raise ValueError("preparation failure is not recoverable")
        return record

    @property
    def profile_id(self):
        # The console run owns its browser profile; no user-supplied alias is needed.
        return "RUN_" + self.run_id.replace("-", "").upper()

    def execute(self, command):
        action, params = command["action"], command["params"]
        if action in {"stop", "give_up"}:
            if self.run_id and command["console_run_id"] != self.run_id:
                raise ValueError("stop belongs to another run")
            self.stopped.set()
            return {"stopping": True}
        if action == "start":
            if self.run_id:
                raise ValueError("worker already owns a run")
            self.run_id, self.attempt = command["console_run_id"], command["execution_attempt_id"]
            self.snapshot = params["snapshot"]
            if (self.snapshot["app_id"] != self.config["app_id"] or self.snapshot["version"] != self.config["version"]):
                raise ValueError("requested release differs from deployment")
            credentials = params.get("credentials", {})
            required = {"username", "password"}
            if (not isinstance(credentials, dict) or not required.issubset(credentials) or set(credentials) - (required | {"expected_identity"})
                    or any(not isinstance(value, str) or not value for value in credentials.values())):
                raise ValueError("请在控制台发起运行时填写账号和密码")
            self.credentials = dict(credentials)
            return self.program()
        self.check(command)
        if action == "open_recovery":
            if params["local_run_id"] != self.local_id or self.recovery:
                raise ValueError("recovery source differs")
            self.source()
            self.cm = open_recovery_session(self.app, self.local_id, credentials=self.credentials)
            self.recovery = self.cm.__enter__()
            self.deadline = monotonic() + min(900, params["remaining_seconds"])
            self.observed.clear()
            self.needs_observation = True
            browser = self.recovery.context.browser
            capabilities = browser.recovery_capabilities() if hasattr(browser, "recovery_capabilities") else {"protocol": 1, "features": []}
            self.event("recovery_started", {"capabilities": capabilities,
                "core_version": importlib.metadata.version("rpa-core"),
                "core_module": type(browser).__module__})
            return {"browser_adopted": self.recovery.browser_adopted}
        if not self.recovery:
            raise ValueError("no active recovery context")
        ctx = self.recovery.context
        if action == "context":
            result = recovery_context(self.source(),
                    (self.app.app_dir / "requirement.md").read_text(encoding="utf-8"),
                    tomllib.loads((self.app.app_dir / "elements.toml").read_text(encoding="utf-8"))["elements"],
                    step=params.get("step"), full=params.get("full", False))
            return {**result,
                    "credential_fields": list(self.credentials), "remaining_seconds": max(0, self.deadline - monotonic())}
        if action in {"query", "observe"}:
            started = monotonic()
            browser = ctx.browser
            if not hasattr(browser, "recovery_query"):
                raise ValueError("recovery_protocol_unsupported: update the loaded Windows rpa-core")
            try:
                result = (browser.recovery_query if action == "query" else browser.recovery_observe)(params, ctx.service("elements"))
            except Exception as error:
                self.needs_observation = True
                return {**self.screenshot(), "observation_error": type(error).__name__, "observation_stage": "query" if action == "query" else "read",
                    "observation_hint": "目标或作用域读取失败；用 query 重新获取候选，持续失败则 give_up。",
                    "collection_order": ["failed_dom_state", "screenshot"]}
            result["collection_order"] = ["dom_state"]
            if action == "observe" and params.get("screenshot", not self.observed):
                captured = monotonic()
                result.update(self.screenshot(params.get("target")))
                result["collection_order"].append("screenshot")
                result.setdefault("timings_ms", {})["screenshot"] = (monotonic() - captured) * 1000
            if action == "observe":
                self.observed.add("live_observation")
            self.needs_observation = False
            text = json.dumps(result, ensure_ascii=False)
            if any(word in text for word in ("滑块验证", "短信验证码", "图形验证码", "安全验证")):
                self.stopped.set()
                result["requires_administrator"] = "检测到人工验证，已停止恢复，请管理员处理后重跑"
            result.setdefault("timings_ms", {})["worker_total"] = (monotonic() - started) * 1000
            return result
        if self.needs_observation:
            raise ValueError("observe the current page before any further action")
        if action == "resume":
            self.source()
            overrides = params.get("locator_overrides", {})
            ctx.browser.validate_recovery_overrides(ctx.service("elements"), overrides)
            from rpa_core.runtime import validate_resume
            validate_resume(self.app.build_program(), self.source(), params["from_step"])
            ctx.browser.release_recovery()
            self.cm.__exit__(None, None, None)
            self.cm = self.recovery = None
            self.deadline = None
            self.attempt = command["next_attempt_id"]
            return self.program(params)
        if action == "credential":
            if params["field"] not in self.credentials or not params.get("target"):
                raise ValueError("credential field is not part of this run")
            result = ctx.browser.recovery_act({"operation": "input", "target": params["target"],
                "value": SecretValue(self.credentials[params["field"]], label=params["field"]),
                "read": ["displayed", "enabled"]}, ctx.service("elements"), lambda: self.check(command))
            return {**result, "entered": result.get("phase") == "complete"}
        if action != "act":
            raise ValueError("unsupported runtime tool")
        operation = params["operation"]
        if operation == "navigate":
            url = urlsplit(params["value"])
            if url.scheme not in {"https", "http"} or url.hostname not in self.config["allowed_hosts"]:
                raise ValueError("navigation outside the configured business hosts")
            ctx.browser.open(params["value"])
            ctx.browser.release_recovery()
            self.needs_observation = True
            return {"issued": True, "phase": "complete", "url": ctx.browser.current_url}
        if operation == "download":
            filename = self.snapshot["inputs"].get("export_filename")
            if params.get("filename") is not None and params["filename"] != filename:
                raise ValueError("download filename must preserve the original business input")
            params = {**params, "filename": filename}
        result = ctx.browser.recovery_act(params, ctx.service("elements"), lambda: self.check(command))
        if result.get("error"):
            self.needs_observation = True
        return result

    def screenshot(self, target_ref=None):
        try:
            artifact = self.recovery.context.browser.screenshot_redacted(name="recovery-" + uuid4().hex + ".png", sensitive_values=tuple(self.credentials.values()), target_ref=target_ref, elements=self.recovery.context.service("elements"))
            if artifact.size_bytes > 8 * 1024 * 1024:
                return {"screenshot_missing": "截图超过 8 MiB"}
            return {"image": {"mimeType": "image/png", "data": base64.b64encode(artifact.path.read_bytes()).decode()}}
        except Exception as error:
            return {"screenshot_missing": type(error).__name__}

    def program(self, recovery=None):
        source_id = self.local_id if recovery else None
        def progress(event):
            kind = event["event_type"]
            if kind == "execution.started":
                self.local_id = event["run_id"]
                self.event("program_started", {"local_run_id": self.local_id})
            elif kind == "runtime.resolved":
                self.snapshot = {**self.snapshot, "inputs": event["inputs"], "download_dir": event["download_dir"]}
                self.event("resolved", {"inputs": event["inputs"], "download_dir": event["download_dir"]})
            elif kind == "execution.evidence":
                try:
                    path = Path(event["path"])
                    if path.stat().st_size > 8 * 1024 * 1024:
                        raise ValueError("截图超过 8 MiB")
                    self.event("evidence", {"step_id": event.get("step_id"), "name": path.name,
                        "image": {"mimeType": "image/png", "data": base64.b64encode(path.read_bytes()).decode()}})
                except (OSError, ValueError) as error:
                    self.event("evidence_missing", {"reason": str(error) if isinstance(error, ValueError) else type(error).__name__})
            elif kind == "execution.evidence_missing":
                self.event("evidence_missing", {"reason": event["reason"], "step_id": event.get("step_id")})
            else:
                if event.get("step_id"):
                    event = {**event, "step_name": self.app.build_program().step(event["step_id"]).spec.name}
                self.event("progress", event)
        outcome = execute_application(self.app,
            request=RunRequest(self.profile_id, self.snapshot["inputs"], self.credentials, self.snapshot.get("download_dir")),
            source_run_id=source_id, from_step=recovery["from_step"] if recovery else None,
            step_result=recovery.get("step_result") if recovery else None,
            locator_overrides=recovery.get("locator_overrides") if recovery else None,
            stop_requested=self.stopped.is_set, event_callback=progress)
        record = outcome.get("record", {})
        self.cleanup_uncertain = record.get("phase") == "cleanup" and record.get("status") == "failed"
        status = record.get("status", "succeeded" if outcome.get("ok") else "failed")
        self.event("attempt_finished", {"local_run_id": self.local_id, "status": status,
            "recoverable": status == "failed" and record.get("phase", "steps") == "steps" and bool(record.get("failed_step")),
            "failed_step": record.get("failed_step"), "completed_steps": record.get("completed_steps", []),
            "outputs": record.get("outputs", {}), "error": record.get("error"),
            "verify_source": "original_runner"})
        if status in {"succeeded", "stopped"}:
            self.stopped.set()
        return {"local_run_id": self.local_id, "status": status}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--deployment", required=True)
    args = parser.parse_args()
    configuration = Path(args.config)
    config = (json.loads if configuration.suffix == ".json" else tomllib.loads)(configuration.read_text(encoding="utf-8"))["deployments"][args.deployment]
    output, lock = sys.stdout, Lock()
    worker = None
    # Application diagnostics cannot corrupt the JSON transport.
    sys.stdout = sys.stderr
    def emit(message):
        def redact(value):
            if isinstance(value, str):
                for secret in worker.credentials.values() if worker else ():
                    value = value.replace(secret, "<redacted>")
                return value
            if isinstance(value, dict):
                immutable = {"image", "run_id", "local_run_id", "app_id", "step_id", "account_id", "download_dir", "inputs", "completed_steps"}
                return {key: item if key in immutable else redact(item) for key, item in value.items()}
            if isinstance(value, list):
                return [redact(item) for item in value]
            return value
        with lock:
            safe = {**message, **{key: redact(message[key]) for key in ("data", "result") if key in message}}
            # ASCII JSON also survives Windows pipe encodings such as GBK.
            output.write(json.dumps(safe, ensure_ascii=True) + "\n")
            output.flush()
    try:
        worker = Worker(config, emit)
    except Exception as error:
        emit({"type": "startup_error", "data": {"error": f"应用加载失败：{type(error).__name__}: {error}"}})
        return
    commands = Queue()
    def read():
        for line in sys.stdin:
            command = json.loads(line)
            if command.get("type") == "connection":
                worker.connected.set() if command["connected"] else worker.connected.clear()
            else:
                if command["action"] in {"stop", "give_up"}:
                    worker.stopped.set()
                commands.put(command)
        worker.connected.clear()
    Thread(target=read, daemon=True).start()
    while not worker.ended:
        if worker.deadline and monotonic() >= worker.deadline:
            worker.stopped.set()
        try:
            command = commands.get(timeout=0.2)
        except Empty:
            if worker.stopped.is_set() and worker.run_id:
                try:
                    worker.close()
                except Exception as error:
                    worker.event("uncertain", {"error": type(error).__name__})
                    return
            continue
        try:
            result = worker.execute(command)
            status = "succeeded"
        except Exception as error:
            worker.needs_observation = True
            result, status = {"error": str(error), "type": type(error).__name__, "recovery_active": worker.recovery is not None}, "failed"
        emit({"type": "result", "console_run_id": command["console_run_id"],
              "execution_attempt_id": command["execution_attempt_id"], "request_id": command["request_id"],
              "status": status, "result": result})


if __name__ == "__main__":
    main()
