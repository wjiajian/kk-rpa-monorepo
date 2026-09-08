import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from rpa_executor.client import Client, load_config
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


def test_deployment_paths_resolve_from_config_independent_of_shell_directory(client, tmp_path, monkeypatch):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    config = load_config(client.path)
    assert config["deployments"]["sample"]["cwd"] == str(client.path.parent)
    assert config["deployments"]["sample"]["python"] == str(client.path.parent / "missing-rpa-python-executable")
    assert "ca_file" not in config


def test_absolute_paths_and_explicit_ca_are_preserved(tmp_path):
    path = tmp_path / "config.toml"
    executable = str(tmp_path / "python.exe").replace("\\", "/")
    path.write_text(f'ca_file = "certs/ca.pem"\n[deployments.app]\npython = "{executable}"\ncwd = "."\n', encoding="utf-8")
    config = load_config(path)
    assert Path(config["deployments"]["app"]["python"]) == tmp_path / "python.exe"
    assert Path(config["ca_file"]) == tmp_path / "certs" / "ca.pem"


def test_local_install_resolution_requires_confirmation_and_preserves_evidence(client):
    from uuid import uuid4
    job_id, release_id = str(uuid4()), str(uuid4())
    job = {'job_id': job_id, 'release_id': release_id, 'action': 'install'}
    client.journal.accept_deployment(job)
    client.journal.deployment_report(job_id, 'uncertain', 'restart')
    directory = client.installer.root / release_id
    directory.mkdir()
    (directory / 'partial.txt').write_text('diagnostic fixture')
    with pytest.raises(ValueError, match='全部进程'):
        client.resolve_deployment(job_id)
    client.state = {'active_run': 'unfinished-run'}
    with pytest.raises(ValueError, match='未结束'):
        client.resolve_deployment(job_id, True)
    client.state = {}
    report = client.resolve_deployment(job_id, True)
    assert report['status'] == 'failed' and report['seq'] == 2
    assert not directory.exists()
    assert (client.installer.root / 'interrupted' / job_id / 'partial.txt').read_text() == 'diagnostic fixture'
    with pytest.raises(ValueError, match='uncertain'):
        client.resolve_deployment(job_id, True)
    assert client.journal.deployment_records()[0][1] == report


def test_local_uninstall_resolution_removes_only_target_registration(client):
    from uuid import uuid4
    from rpa_executor.installer import atomic_json
    job_id, release_id, old_id = str(uuid4()), str(uuid4()), str(uuid4())
    client.installer.registry = {release_id: {'version': 'new'}, old_id: {'version': 'old'}}
    atomic_json(client.installer.registry_path, client.installer.registry)
    job = {'job_id': job_id, 'release_id': release_id, 'action': 'uninstall'}
    client.journal.accept_deployment(job)
    client.journal.deployment_report(job_id, 'uncertain', 'uninstall')
    # Removal already happened before the crash; finish only registry and journal.
    report = client.resolve_deployment(job_id, True)
    assert report['status'] == 'uninstalled'
    assert client.installer.registry == {old_id: {'version': 'old'}}
    assert json.loads(client.installer.registry_path.read_text()) == client.installer.registry
