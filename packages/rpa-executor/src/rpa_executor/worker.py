"""Fixed application-environment worker. All browser calls run on this thread.

The reader thread can only set stop/connectivity flags, never touch the browser.
The module and Python executable come from local deployment configuration.
"""
import argparse
import base64
from dataclasses import asdict
import importlib
import importlib.metadata
import json
import os
from pathlib import Path
from queue import Queue, Empty
import sys
from threading import Event, Lock, Thread
from time import monotonic, sleep
import tomllib
from urllib.parse import urlsplit
from uuid import uuid4

from rpa_core.browser import ElementSpec, Locator, SecretValue
from rpa_core.browser_manager import BrowserManager
from rpa_core.cli import RunRequest, execute_application, open_recovery_session, read_recovery_record
from rpa_core.elements import override_element_locators


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
        self.temporary = {}
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
            self.recovery.close_browser()
            self.cm.__exit__(None, None, None)
            self.cm = self.recovery = None
        elif self.snapshot and self.local_id:
            manager = BrowserManager(self.app.app_dir / "runtime" / "browser-manager")
            manager.close_retained_browser(f"{self.app.app_dir.name}.{self.snapshot['account_id']}", expected_run_id=self.local_id)
        self.ended = True
        self.event("ended", {"reason": "cooperative_cleanup"})

    def source(self):
        record = read_recovery_record(self.app, self.local_id)
        if (record["account_id"] != self.snapshot["account_id"] or
                record["inputs"] != self.snapshot["inputs"] or
                record["download_dir"] != self.snapshot["download_dir"]):
            raise ValueError("source record differs from original runtime parameters")
        if record.get("phase", "steps") != "steps" or not record.get("failed_step"):
            raise ValueError("preparation failure is not recoverable")
        return record

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
            account = self.config["accounts"][self.snapshot["account_id"]]
            self.credentials = {field: os.environ[env] for field, env in account["credentials_env"].items()}
            return self.program()
        self.check(command)
        if action == "open_recovery":
            if params["local_run_id"] != self.local_id or self.recovery:
                raise ValueError("recovery source differs")
            self.source()
            self.cm = open_recovery_session(self.app, self.local_id, credentials=self.credentials)
            self.recovery = self.cm.__enter__()
            self.deadline = monotonic() + min(900, params["remaining_seconds"])
            self.temporary.clear()
            self.observed.clear()
            self.needs_observation = True
            self.event("recovery_started")
            return {"browser_adopted": self.recovery.browser_adopted}
        if not self.recovery:
            raise ValueError("no active recovery context")
        ctx = self.recovery.context
        if action == "context":
            return {"source": self.source(),
                    "requirement": (self.app.app_dir / "requirement.md").read_text(encoding="utf-8"),
                    "elements": (self.app.app_dir / "elements.toml").read_text(encoding="utf-8"),
                    "credential_fields": list(self.credentials), "remaining_seconds": max(0, self.deadline - monotonic())}
        if action == "observe":
            element = self.element(params["target"]) if params.get("target") else None
            if params.get("frame_target"):
                frame = self.element(params["frame_target"]).require_locator()
                element = ElementSpec("frame_body", "当前框架", "recovery", locator=Locator("tag:body"), frame_locator=frame)
            dom = ctx.browser.observe_dom(element, limit=params.get("limit", 200))
            for node in dom["nodes"]:
                target_id = "observed_" + uuid4().hex[:12]
                self.temporary[target_id] = ElementSpec(target_id, node["tag"], "recovery",
                    locator=Locator(node["locator"]), frame_locator=Locator(node["frame_locator"]) if node.get("frame_locator") else None)
                node["target"] = target_id
                self.observed.add(node["locator"])
                if node.get("frame_locator"):
                    self.observed.add(node["frame_locator"])
            self.needs_observation = False
            # Detect-only: the fixed tool cannot bypass an interactive challenge.
            challenge = any(word in dom["text"] for word in ("滑块验证", "短信验证码", "图形验证码", "安全验证"))
            screenshot = self.screenshot()
            if challenge:
                self.stopped.set()
                return {**dom, **screenshot, "requires_administrator": "检测到人工验证，已停止恢复，请管理员处理后重跑"}
            return {**dom, **screenshot}
        if self.needs_observation:
            raise ValueError("observe the current page before any further action")
        if action == "resume":
            self.source()
            overrides = params.get("locator_overrides", {})
            for fields in overrides.values():
                for value in fields.values():
                    if value is not None and value not in self.observed:
                        raise ValueError("locator override lacks actual DOM evidence")
            override_element_locators(ctx.service("elements"), overrides)
            from rpa_core.runtime import validate_resume
            validate_resume(self.app.build_program(), self.source(), params["from_step"])
            self.cm.__exit__(None, None, None)
            self.cm = self.recovery = None
            self.deadline = None
            self.attempt = command["next_attempt_id"]
            return self.program(params)
        target = self.element(params["target"]) if params.get("target") else None
        if action == "credential":
            if params["field"] not in self.credentials or not target:
                raise ValueError("credential field is not part of this run")
            ctx.browser.input(target, SecretValue(self.credentials[params["field"]], label=params["field"]))
            return {"entered": True}
        if action != "act":
            raise ValueError("unsupported runtime tool")
        operation = params["operation"]
        if operation == "navigate":
            url = urlsplit(params["value"])
            if url.scheme not in {"https", "http"} or url.hostname not in self.config["allowed_hosts"]:
                raise ValueError("navigation outside the configured business hosts")
            ctx.browser.open(params["value"])
        elif operation in {"click", "new_tab"}:
            (ctx.browser.click if operation == "click" else ctx.browser.click_and_switch_to_new_tab)(target)
        elif operation in {"input", "select"}:
            getattr(ctx.browser, operation)(target, params["value"])
        elif operation == "read":
            return {"text": ctx.browser.text(target), "count": ctx.browser.count(target)}
        elif operation == "wait":
            return {"exists": ctx.browser.exists(target, timeout=min(15, max(0.1, float(params.get("seconds", 1)))))}
        elif operation == "download":
            filename = self.snapshot["inputs"].get("export_filename")
            if params.get("filename") is not None and params["filename"] != filename:
                raise ValueError("download filename must preserve the original business input")
            return {"download": ctx.browser.download(target, filename=filename).to_dict()}
        else:
            raise ValueError("unsupported browser action")
        return {"performed": operation}

    def element(self, target):
        return self.temporary[target] if target in self.temporary else self.recovery.context.service("elements")[target]

    def screenshot(self):
        try:
            artifact = self.recovery.context.browser.screenshot_redacted(name="recovery-" + uuid4().hex + ".png", sensitive_values=tuple(self.credentials.values()))
            if artifact.size_bytes > 8 * 1024 * 1024:
                return {"screenshot_missing": "截图超过 8 MiB"}
            return {"image": {"mimeType": "image/png", "data": base64.b64encode(artifact.path.read_bytes()).decode()}}
        except Exception as error:
            return {"screenshot_missing": type(error).__name__}

    def program(self, recovery=None):
        source_id = self.local_id if recovery else None
        evidence = {}
        def progress(event):
            kind = event["event_type"]
            if kind == "execution.started":
                self.local_id = event["run_id"]
                self.event("program_started", {"local_run_id": self.local_id})
            elif kind == "runtime.resolved":
                self.snapshot = {**self.snapshot, "inputs": event["inputs"], "download_dir": event["download_dir"]}
                self.event("resolved", {"inputs": event["inputs"], "download_dir": event["download_dir"]})
            elif kind == "execution.evidence":
                path = Path(event["path"])
                if path.stat().st_size <= 8 * 1024 * 1024:
                    evidence["image"] = {"mimeType": "image/png", "data": base64.b64encode(path.read_bytes()).decode()}
            else:
                if event.get("step_id"):
                    event = {**event, "step_name": self.app.build_program().step(event["step_id"]).spec.name}
                self.event("progress", event)
        outcome = execute_application(self.app,
            request=RunRequest(self.snapshot["account_id"], self.snapshot["inputs"], self.credentials, self.snapshot.get("download_dir")),
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
        return {"local_run_id": self.local_id, "status": status, **evidence}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--deployment", required=True)
    args = parser.parse_args()
    config = tomllib.loads(Path(args.config).read_text(encoding="utf-8"))["deployments"][args.deployment]
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
