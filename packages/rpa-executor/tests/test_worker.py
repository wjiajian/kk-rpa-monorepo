from types import SimpleNamespace
import base64
from threading import Event
from time import monotonic
import pytest

from rpa_core.browser import ArtifactRef, ElementSpec, Locator
from rpa_executor import worker as worker_module
from rpa_executor.worker import Worker


def worker():
    w = Worker.__new__(Worker)
    w.run_id, w.attempt, w.ended = "run", "attempt", False
    w.stopped, w.connected = Event(), Event()
    w.connected.set()
    w.deadline = monotonic() + 30
    w.needs_observation = False
    w.observed = {"xpath:/html/body/button"}
    w.temporary = {}
    w.snapshot = {"inputs": {"export_filename": "fixed.xlsx"}}
    w.credentials = {"password": "test-only-value"}
    w.config = {"allowed_hosts": ["business.test"]}
    actions = []
    browser = SimpleNamespace(click=lambda target: actions.append(("click", target.id)), input=lambda target, value: actions.append(("input", str(value))))
    element = ElementSpec("button", "按钮", "页面", locator=Locator("css:button"))
    ctx = SimpleNamespace(browser=browser, service=lambda _: {"button": element})
    w.recovery = SimpleNamespace(context=ctx)
    return w, actions


def command(action="act", **params):
    return {"console_run_id": "run", "execution_attempt_id": "attempt", "action": action, "params": params}


def test_stale_run_disconnection_deadline_and_stop_prevent_actions():
    for boundary in ("stale", "disconnect", "deadline", "stop"):
        w, actions = worker()
        c = command(operation="click", target="button")
        if boundary == "stale": c["execution_attempt_id"] = "old"
        if boundary == "disconnect": w.connected.clear()
        if boundary == "deadline": w.deadline = monotonic() - 1
        if boundary == "stop": w.stopped.set()
        with pytest.raises(ValueError): w.execute(c)
        assert actions == []


def test_credential_tool_uses_reference_and_secretvalue():
    w, actions = worker()
    result = w.execute(command("credential", field="password", target="button"))
    assert result == {"entered": True}
    assert actions == [("input", "<redacted>")]
    with pytest.raises(ValueError): w.execute(command("credential", field="other_account", target="button"))


def test_unobserved_locator_and_external_navigation_rejected_before_effect():
    w, actions = worker()
    w.source = lambda: {}
    with pytest.raises(ValueError, match="DOM evidence"):
        w.execute(command("resume", from_step="S2", locator_overrides={"button": {"locator": "invented"}}))
    with pytest.raises(ValueError, match="business hosts"):
        w.execute(command(operation="navigate", value="https://unrelated.test"))
    assert actions == []


def test_no_shell_or_arbitrary_execution_surface():
    w, actions = worker()
    for name in ("bash", "python", "javascript", "write", "install"):
        with pytest.raises(ValueError): w.execute(command(name))
    assert actions == []


def test_start_uses_console_credentials_without_local_account_configuration():
    w, actions = worker()
    w.run_id = None
    w.config = {"app_id": "app", "version": "1"}
    w.program = lambda: dict(w.credentials)
    credentials = {"username": "console-user", "password": "console-password", "expected_identity": "console-identity"}
    result = w.execute(command("start", snapshot={"app_id": "app", "version": "1"}, credentials=credentials))
    assert result == credentials
    assert result is not credentials
    assert actions == []


def test_start_missing_business_credentials_never_runs_program():
    w, actions = worker()
    w.run_id = None
    w.config = {"app_id": "app", "version": "1"}
    w.program = lambda: actions.append("program")
    with pytest.raises(ValueError, match="控制台"):
        w.execute(command("start", snapshot={"app_id": "app", "version": "1"}))
    assert actions == []


def test_program_streams_each_screenshot_before_attempt_finishes_without_account_alias(tmp_path, monkeypatch):
    w, _ = worker()
    w.local_id = None
    w.app = SimpleNamespace()
    events, requests = [], []
    w.emit = events.append
    png = b"\x89PNG\r\n\x1a\nfixture"
    evidence = tmp_path / "step.png"
    evidence.write_bytes(png)

    def execute(app, *, request, event_callback, **kwargs):
        requests.append(request)
        event_callback({"event_type": "execution.started", "run_id": "local"})
        for step in ("S1", "S2"):
            event_callback({"event_type": "execution.evidence", "path": str(evidence), "step_id": step})
        assert [e["type"] for e in events] == ["program_started", "evidence", "evidence"]
        return {"record": {"status": "succeeded"}}

    monkeypatch.setattr(worker_module, "execute_application", execute)
    w.program()
    assert [e["data"]["step_id"] for e in events if e["type"] == "evidence"] == ["S1", "S2"]
    assert all(base64.b64decode(e["data"]["image"]["data"]) == png for e in events if e["type"] == "evidence")
    assert requests[0].account_id == "RUN_RUN"
    assert requests[0].credentials == w.credentials
    assert requests[0].inputs == w.snapshot["inputs"]
    assert "account_id" not in w.snapshot
    first_profile = w.profile_id
    w.run_id = "another-run"
    assert w.profile_id != first_profile


def test_dom_failure_keeps_screenshot_for_dashboard_and_requires_fresh_observation(tmp_path):
    w, _ = worker()
    target = tmp_path / "evidence.png"
    target.write_bytes(b"\x89PNG\r\n\x1a\nfixture")
    w.recovery.context.browser.screenshot_redacted = lambda **kwargs: ArtifactRef.from_path(target)
    def fail(*args, **kwargs):
        raise RuntimeError("DOM unavailable")
    w.recovery.context.browser.observe_dom = fail
    result = w.execute(command("observe"))
    assert base64.b64decode(result["image"]["data"]) == target.read_bytes()
    assert result["observation_error"] == "RuntimeError"
    assert w.needs_observation


def test_recovery_profile_and_original_inputs_must_match(monkeypatch):
    w, _ = worker()
    w.app, w.local_id = SimpleNamespace(), "local"
    w.snapshot["download_dir"] = "/downloads"
    record = {"account_id": w.profile_id, "inputs": w.snapshot["inputs"], "download_dir": "/downloads",
              "phase": "steps", "failed_step": "S2"}
    monkeypatch.setattr(worker_module, "read_recovery_record", lambda *_: record)
    assert w.source() == record
    record["account_id"] = "RUN_OTHER"
    with pytest.raises(ValueError, match="original runtime parameters"):
        w.source()
