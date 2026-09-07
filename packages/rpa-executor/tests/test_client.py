import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from rpa_executor.client import Client
from rpa_executor import worker as worker_module


@pytest.fixture
def client(tmp_path):
    path = tmp_path / "executor.toml"
    path.write_text('server_url = "wss://console.test/api/robots/connect"\n'
                    '[deployments.sample]\napp_id = "app"\nversion = "1"\n'
                    'python = "missing-rpa-python-executable"\ncwd = "."\n', encoding="utf-8")
    value = Client(path)
    yield value
    value.journal.db.close()
    value.lock_file.close()


@pytest.mark.parametrize("version", ["1", "missing"])
def test_preparation_failure_ends_without_browser_and_duplicate_replays(client, version):
    command = {"type": "command", "action": "start", "request_id": "start-1",
               "console_run_id": "run", "execution_attempt_id": "attempt",
               "params": {"snapshot": {"app_id": "app", "version": version}}}
    asyncio.run(client.command(command))
    events = client.journal.events("run")
    assert [event["type"] for event in events] == ["result", "ended"]
    assert events[0]["status"] == "failed"
    assert events[0]["result"]["phase"] == "prepare"
    assert client.worker is None
    assert client.journal.state()["phase"] == "ended"
    asyncio.run(client.command(command))
    assert client.journal.events("run") == events


def test_old_run_ack_cannot_discard_current_terminal_replay(client):
    client.state = {"active_run": "new-run", "phase": "ended", "ended_seq": 5}
    client.journal.save_state(client.state)
    client.acknowledge("old-run", 999)
    client.acknowledge("new-run", 4)
    assert client.journal.state()["active_run"] == "new-run"
    client.acknowledge("new-run", 5)
    assert client.journal.state() == {}


def test_broken_worker_pipe_does_not_drop_control_connection(client):
    def closed_pipe(_):
        raise BrokenPipeError
    client.worker = SimpleNamespace(returncode=None, stdin=SimpleNamespace(write=closed_pipe))
    assert asyncio.run(client.input({"type": "connection", "connected": False})) is False
    assert client.journal.events("run") == []


def test_worker_chinese_startup_error_survives_windows_pipe_encoding(client):
    completed = subprocess.run([sys.executable, str(Path(worker_module.__file__)),
                               "--config", str(client.path), "--deployment", "sample"],
                              capture_output=True, env={**os.environ, "PYTHONIOENCODING": "gbk"}, timeout=10)
    assert completed.returncode == 0
    message = json.loads(completed.stdout.decode("ascii"))
    assert message["type"] == "startup_error"
    assert "应用加载失败" in message["data"]["error"]
