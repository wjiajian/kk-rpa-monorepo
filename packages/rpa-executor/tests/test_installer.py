import asyncio
import io
import json
import os
from pathlib import Path
import shutil
import sys
import tarfile
from uuid import uuid4

import pytest

from rpa_executor import installer as module
from rpa_executor.installer import Installer, CleanupUncertain


@pytest.fixture
def installation(tmp_path, monkeypatch):
    archive = tmp_path / 'source.tar'
    schema = {'type': 'object', 'properties': {}, 'additionalProperties': False}
    with tarfile.open(archive, 'w') as output:
        for path, value in {
            'apps/sample/app.toml': 'app_id="sample"\n[console]\ninput_schema="input.schema.json"\n',
            'apps/sample/input.schema.json': json.dumps(schema),
        }.items():
            data = value.encode()
            member = tarfile.TarInfo(path)
            member.size = len(data)
            output.addfile(member, io.BytesIO(data))
    installer = Installer(tmp_path / 'releases', 'wss://console.invalid', 'PRIVATE_ROBOT_TOKEN')
    monkeypatch.setattr(installer, 'download', lambda path, destination: shutil.copyfile(archive, destination))
    calls = []
    async def process(args, cwd):
        calls.append((args, cwd))
    monkeypatch.setattr(installer, 'run_process', process)
    command = {'job_id': str(uuid4()), 'release_id': str(uuid4()), 'action': 'install',
               'commit': 'a' * 40, 'artifact_url': '/api/robot-deployment-jobs/job/artifact',
               'deployment': {'path': 'apps/sample', 'app_id': 'sample', 'version': '1',
                              'module': 'sample.program', 'package': 'sample',
                              'allowed_hosts': ['example.invalid'], 'input_schema': schema}}
    reports = []
    async def report(status, stage, error=None):
        reports.append((status, stage, error))
    return installer, command, report, reports, calls


def test_installed_only_after_checks_and_durable_registry(installation):
    installer, command, report, reports, calls = installation
    asyncio.run(installer.execute(command, report))
    assert reports[-1][:2] == ('installed', 'complete')
    assert [args[-1] for args, _ in calls] == ['3.12', '--deployment', 'test']
    saved = json.loads(installer.registry_path.read_text())
    assert saved == installer.registry
    assert saved[command['release_id']]['commit'] == command['commit']
    assert 'PRIVATE_ROBOT_TOKEN' not in installer.registry_path.read_text()
    asyncio.run(installer.execute(command, report))
    assert len(calls) == 3  # Replayed install does not overwrite the environment.


def test_registry_write_failure_never_makes_version_available(installation, monkeypatch):
    installer, command, report, reports, _ = installation
    def failure(*args):
        raise OSError('disk full')
    monkeypatch.setattr(module, 'atomic_json', failure)
    asyncio.run(installer.execute(command, report))
    assert reports[-1][:2] == ('failed', 'test')
    assert installer.registry == {}
    assert not (installer.root / command['release_id']).exists()


def test_failed_check_preserves_old_version(installation, monkeypatch):
    installer, command, report, reports, _ = installation
    old = str(uuid4())
    installer.registry[old] = {'version': 'old'}
    (installer.root / old).mkdir()
    async def failure(*args):
        raise ValueError('命令退出码 1')
    monkeypatch.setattr(installer, 'run_process', failure)
    asyncio.run(installer.execute(command, report))
    assert reports[-1][:2] == ('failed', 'dependencies')
    assert list(installer.registry) == [old]
    assert (installer.root / old).exists()
    assert not (installer.root / command['release_id']).exists()


@pytest.mark.parametrize('exception', [CleanupUncertain, asyncio.CancelledError])
def test_interrupted_install_keeps_directory_and_uncertain_state(installation, monkeypatch, exception):
    installer, command, report, reports, _ = installation
    async def failure(*args):
        raise exception()
    monkeypatch.setattr(installer, 'run_process', failure)
    asyncio.run(installer.execute(command, report))
    assert reports[-1][0] == 'uncertain'
    assert command['release_id'] not in installer.registry
    assert (installer.root / command['release_id']).exists()


def test_invalid_release_id_is_reported_without_touching_paths(installation):
    installer, command, report, reports, _ = installation
    command['release_id'] = '../escape'
    asyncio.run(installer.execute(command, report))
    assert reports[-1] == ('failed', 'prepare', 'prepare：发布版本 ID 无效')
    assert list(installer.root.iterdir()) == []


@pytest.mark.skipif(os.name == 'nt', reason='POSIX process group integration; Windows requires target acceptance')
def test_timeout_stops_child_writer(tmp_path, monkeypatch):
    installer = Installer(tmp_path / 'releases', 'wss://console.invalid', 'token')
    marker = tmp_path / 'child-alive'
    ready = tmp_path / 'child-ready'
    child = "import time,pathlib; pathlib.Path('child-ready').touch(); time.sleep(1); pathlib.Path('child-alive').touch()"
    parent = f'import subprocess,sys,time; subprocess.Popen([sys.executable,"-c",{child!r}]); time.sleep(10)'
    monkeypatch.setattr(module, 'PROCESS_TIMEOUT', 0.5)
    async def scenario():
        with pytest.raises(ValueError, match='超时'):
            await installer.run_process([sys.executable, '-c', parent], tmp_path)
        await asyncio.sleep(1)
    asyncio.run(scenario())
    assert ready.exists()
    assert not marker.exists()
