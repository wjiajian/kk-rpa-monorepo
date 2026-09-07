from rpa_executor.journal import Journal
import pytest


def test_duplicate_click_and_conflicting_params(tmp_path):
    path = tmp_path / "journal.db"
    journal = Journal(path)
    command = {"request_id": "click-1", "console_run_id": "run", "execution_attempt_id": "a", "action": "act", "params": {"operation": "click", "target": "button"}}
    assert journal.accept(command)
    journal.append({"type": "result", **{k: command[k] for k in ("request_id", "console_run_id", "execution_attempt_id")}, "status": "succeeded", "result": {"clicked": True}})
    journal.db.close()
    restored = Journal(path)
    assert not restored.accept(command)
    with pytest.raises(ValueError): restored.accept({**command, "params": {"operation": "download"}})
    assert restored.events("run")[0]["status"] == "succeeded"
    assert restored.requests()["click-1"] == "succeeded"


def test_restart_keeps_pending_requests_and_monotonic_events(tmp_path):
    journal = Journal(tmp_path / "journal.db")
    command = {"request_id": "resume", "console_run_id": "run", "action": "resume"}
    journal.accept(command)
    first = journal.append({"type": "program_started", "console_run_id": "run"})
    second = journal.append({"type": "attempt_finished", "console_run_id": "run"})
    assert (first["seq"], second["seq"]) == (1, 2)
    assert journal.events("run", after=1) == [second]
    assert journal.interrupted() == [command]
