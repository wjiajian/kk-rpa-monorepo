from types import SimpleNamespace
from threading import Event
from time import monotonic
import pytest

from rpa_core.browser import ElementSpec, Locator
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
    w.snapshot = {"account_id": "original", "inputs": {"export_filename": "fixed.xlsx"}}
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
