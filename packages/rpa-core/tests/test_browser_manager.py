from __future__ import annotations

import json
from pathlib import Path
import pytest
import ctypes
from types import SimpleNamespace
from rpa_core import browser_manager

from rpa_core.browser_manager import (
    BrowserLaunchSpec,
    BrowserConfigurationError,
    BrowserHandoffError,
    BrowserLifecycleError,
    BrowserLifecyclePolicy,
    BrowserManager,
    BrowserPortLeaseError,
    BrowserProfileActiveError,
    BrowserStartError,
    PortLeasePool,
)


class FakeOptions:
    def __init__(self) -> None:
        self.local_port: int | None = None
        self.user_data_path: str | None = None
        self.browser_path: str | None = None

    def set_local_port(self, port: int) -> "FakeOptions":
        self.local_port = port
        return self

    def set_user_data_path(self, path: str) -> "FakeOptions":
        self.user_data_path = path
        return self

    def set_browser_path(self, path: str) -> "FakeOptions":
        self.browser_path = path
        return self


class FakeBrowser:
    def __init__(
        self,
        options: FakeOptions,
        *,
        tab: object | None = None,
        process_id: int | None = 4242,
    ) -> None:
        self.options = options
        self.latest_tab = tab if tab is not None else object()
        self.process_id = process_id
        self.quit_calls = 0
        self.quit_kwargs: list[dict[str, object]] = []

    def quit(self, timeout: float = 5, force: bool = False, del_data: bool = False) -> None:
        self.quit_calls += 1
        self.quit_kwargs.append(
            {"timeout": timeout, "force": force, "del_data": del_data}
        )


def make_manager(
    tmp_path: Path,
    browsers: list[FakeBrowser],
    ports=(29600, 29609),
    *,
    port_available=lambda _: True,
    pid_is_alive=None,
    devtools_responds=None,
    process_id: int | None = 4242,
):
    def create_browser(options: FakeOptions) -> FakeBrowser:
        browser = FakeBrowser(options, process_id=process_id)
        browsers.append(browser)
        return browser

    return BrowserManager(
        tmp_path / "runtime",
        port_range=ports,
        options_factory=FakeOptions,
        chromium_factory=create_browser,
        port_available=port_available,
        pid_is_alive=pid_is_alive,
        devtools_responds=devtools_responds,
    )


def make_spec(tmp_path: Path, **changes) -> BrowserLaunchSpec:
    values = {
        "account_id": "ACCOUNT_001",
        "profile_id": "PROFILE_001",
        "profile_dir": tmp_path / "profiles" / "PROFILE_001",
        "lifecycle": BrowserLifecyclePolicy.TERMINATE_ON_FINISH,
    }
    values.update(changes)
    return BrowserLaunchSpec(**values)


@pytest.mark.parametrize(("wait_result", "alive"), [(0, False), (258, True)])
def test_windows_liveness_does_not_send_a_signal(monkeypatch, wait_result, alive):
    closed = []

    def open_process(access, inherit, pid):
        assert access == 0x00100000 and not inherit and pid == 123456
        return 123

    kernel = SimpleNamespace(
        OpenProcess=open_process,
        WaitForSingleObject=lambda handle, timeout: wait_result,
        CloseHandle=lambda handle: closed.append(handle),
    )
    monkeypatch.setattr(ctypes, "WinDLL", lambda *a, **k: kernel, raising=False)
    monkeypatch.setattr(browser_manager.sys, "platform", "win32")
    monkeypatch.setattr(browser_manager.os, "kill", lambda *a: pytest.fail("liveness sent a signal"))
    assert browser_manager._pid_is_alive(123456) is alive
    assert closed == [123]


def test_manager_binds_profile_port_and_run_artifacts(tmp_path: Path) -> None:
    browsers: list[FakeBrowser] = []
    manager = make_manager(tmp_path, browsers)
    run_dir = tmp_path / "runs" / "run-001"

    session = manager.start(make_spec(tmp_path), run_id="run-001", run_dir=run_dir)

    assert session.port == 29600
    assert session.actions.run_dir == run_dir
    assert browsers[0].options.local_port == 29600
    assert browsers[0].options.user_data_path == str(tmp_path / "profiles" / "PROFILE_001")
    lease = json.loads(
        (tmp_path / "runtime" / "port-leases" / "29600.json").read_text(encoding="utf-8")
    )
    assert lease["run_id"] == "run-001"
    assert lease["profile_id"] == "PROFILE_001"

    manager.finish(session)

    assert browsers[0].quit_calls == 1
    assert session.active is False
    assert not (tmp_path / "runtime" / "port-leases" / "29600.json").exists()


def test_keep_open_retains_profile_and_port_until_shutdown(tmp_path: Path) -> None:
    browsers: list[FakeBrowser] = []
    manager = make_manager(tmp_path, browsers)
    spec = make_spec(tmp_path, lifecycle=BrowserLifecyclePolicy.KEEP_OPEN)
    session = manager.start(spec, run_id="run-keep", run_dir=tmp_path / "runs" / "run-keep")

    manager.finish(session)

    assert session.active is True
    assert browsers[0].quit_calls == 0
    competing = make_manager(tmp_path, [])
    with pytest.raises(BrowserProfileActiveError):
        competing.start(spec, run_id="run-other", run_dir=tmp_path / "runs" / "run-other")

    manager.shutdown()
    assert browsers[0].quit_calls == 1
    assert session.active is False


def test_two_profiles_receive_distinct_ports(tmp_path: Path) -> None:
    browsers: list[FakeBrowser] = []
    manager = make_manager(tmp_path, browsers)
    first = manager.start(
        make_spec(tmp_path, lifecycle=BrowserLifecyclePolicy.KEEP_OPEN),
        run_id="run-a",
        run_dir=tmp_path / "runs" / "run-a",
    )
    second = manager.start(
        make_spec(
            tmp_path,
            account_id="ACCOUNT_002",
            profile_id="PROFILE_002",
            profile_dir=tmp_path / "profiles" / "PROFILE_002",
            lifecycle=BrowserLifecyclePolicy.KEEP_OPEN,
        ),
        run_id="run-b",
        run_dir=tmp_path / "runs" / "run-b",
    )

    assert (first.port, second.port) == (29600, 29601)
    manager.shutdown()


def test_port_pool_skips_a_listening_port(tmp_path: Path) -> None:
    busy_port = 29610
    next_port = 29611
    pool = PortLeasePool(
        tmp_path / "leases",
        start_port=busy_port,
        end_port=next_port,
        port_available=lambda port: port != busy_port,
    )
    lease = pool.acquire(run_id="run-port", profile_id="PROFILE_001")

    assert lease.port == next_port
    lease.release()


def test_requested_busy_port_fails_closed(tmp_path: Path) -> None:
    busy_port = 29612
    pool = PortLeasePool(tmp_path / "leases", port_available=lambda _: False)
    with pytest.raises(BrowserPortLeaseError):
        pool.acquire(
            run_id="run-busy",
            profile_id="PROFILE_001",
            requested_port=busy_port,
        )


def test_start_failure_releases_profile_and_port(tmp_path: Path) -> None:
    options: list[FakeOptions] = []

    def options_factory() -> FakeOptions:
        value = FakeOptions()
        options.append(value)
        return value

    manager = BrowserManager(
        tmp_path / "runtime",
        port_range=(29620, 29620),
        options_factory=options_factory,
        chromium_factory=lambda _: (_ for _ in ()).throw(RuntimeError("fixture failure")),
        port_available=lambda _: True,
    )
    spec = make_spec(tmp_path)

    with pytest.raises(BrowserStartError) as caught:
        manager.start(spec, run_id="run-fail", run_dir=tmp_path / "runs" / "run-fail")

    assert caught.value.real_browser_launched is False
    assert not (tmp_path / "runtime" / "port-leases" / "29620.json").exists()
    browsers: list[FakeBrowser] = []
    retry = make_manager(tmp_path, browsers, ports=(29620, 29620))
    session = retry.start(spec, run_id="run-retry", run_dir=tmp_path / "runs" / "run-retry")
    retry.close(session)


def test_symlink_run_directory_fails_before_chromium_factory(
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside-run"
    outside.mkdir()
    runs = tmp_path / "runs"
    runs.mkdir()
    linked_run = runs / "run-linked"
    try:
        linked_run.symlink_to(outside, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"symlinks are unavailable in this test environment: {error}")
    browsers: list[FakeBrowser] = []
    manager = make_manager(tmp_path, browsers)

    with pytest.raises(BrowserConfigurationError, match="symbolic links"):
        manager.start(
            make_spec(tmp_path),
            run_id="run-linked",
            run_dir=linked_run,
        )

    assert browsers == []
    assert list(outside.iterdir()) == []


def test_post_launch_tab_failure_is_audited_and_browser_is_closed(
    tmp_path: Path,
) -> None:
    browsers: list[FakeBrowser] = []

    def create_browser(options: FakeOptions) -> FakeBrowser:
        browser = FakeBrowser(options, tab=False)
        browsers.append(browser)
        return browser

    manager = BrowserManager(
        tmp_path / "runtime",
        port_range=(29621, 29621),
        options_factory=FakeOptions,
        chromium_factory=create_browser,
        port_available=lambda _: True,
    )

    with pytest.raises(BrowserStartError) as caught:
        manager.start(
            make_spec(tmp_path),
            run_id="run-no-tab",
            run_dir=tmp_path / "runs" / "run-no-tab",
        )

    assert caught.value.real_browser_launched is True
    assert browsers[0].quit_calls == 1
    assert not (tmp_path / "runtime" / "port-leases" / "29621.json").exists()


def test_manager_rejects_foreign_or_closed_session(tmp_path: Path) -> None:
    first_browsers: list[FakeBrowser] = []
    first = make_manager(tmp_path / "first", first_browsers, ports=(29630, 29630))
    session = first.start(
        make_spec(tmp_path / "first"),
        run_id="run-owned",
        run_dir=tmp_path / "first" / "runs" / "run-owned",
    )
    second = make_manager(tmp_path / "second", [], ports=(29631, 29631))

    with pytest.raises(BrowserLifecycleError):
        second.close(session)

    first.close(session)
    with pytest.raises(BrowserLifecycleError):
        first.close(session)


def handoff_file(tmp_path: Path, profile_id: str = "PROFILE_001") -> Path:
    return tmp_path / "runtime" / "handoffs" / f"{profile_id}.json"


def keep_open_on_failure_spec(tmp_path: Path, **changes) -> BrowserLaunchSpec:
    values = {"lifecycle": BrowserLifecyclePolicy.KEEP_OPEN_ON_FAILURE}
    values.update(changes)
    return make_spec(tmp_path, **values)


def test_close_force_terminates_the_browser_process(tmp_path: Path) -> None:
    """A bare quit() closes the window but leaves the process holding the port."""

    browsers: list[FakeBrowser] = []
    manager = make_manager(tmp_path, browsers, ports=(29640, 29640))
    session = manager.start(
        make_spec(tmp_path),
        run_id="run-force",
        run_dir=tmp_path / "runs" / "run-force",
    )

    manager.close(session)

    assert browsers[0].quit_kwargs == [
        {"timeout": 10.0, "force": True, "del_data": False}
    ]


def test_failed_finish_detaches_and_records_a_handoff(tmp_path: Path) -> None:
    browsers: list[FakeBrowser] = []
    manager = make_manager(tmp_path, browsers, ports=(29641, 29641))
    spec = keep_open_on_failure_spec(tmp_path)
    session = manager.start(
        spec,
        run_id="run-failed",
        run_dir=tmp_path / "runs" / "run-failed",
    )

    handoff = manager.finish(session, failed=True)

    assert browsers[0].quit_calls == 0
    assert handoff is not None
    assert (handoff.port, handoff.browser_pid, handoff.run_id) == (
        29641,
        4242,
        "run-failed",
    )
    record = json.loads(handoff_file(tmp_path).read_text(encoding="utf-8"))
    assert record["port"] == 29641
    assert record["browser_pid"] == 4242
    assert record["profile_dir"] == str(tmp_path / "profiles" / "PROFILE_001")
    # The port lease and the profile lock are handed back even though the
    # process survives, so a later run can lease them again.
    assert not (tmp_path / "runtime" / "port-leases" / "29641.json").exists()
    assert session.active is False
    # Proof the lock and the lease really came back: a fresh manager can take
    # both again. Probes are stubbed off so this exercises the launch path, not
    # adoption, which its own test covers.
    successor = make_manager(
        tmp_path,
        [],
        ports=(29641, 29641),
        pid_is_alive=lambda _: False,
        devtools_responds=lambda _: False,
    )
    relaunched = successor.start(
        spec,
        run_id="run-relaunch",
        run_dir=tmp_path / "runs" / "run-relaunch",
    )
    assert relaunched.adopted is False


def test_successful_finish_closes_even_under_keep_open_on_failure(
    tmp_path: Path,
) -> None:
    browsers: list[FakeBrowser] = []
    manager = make_manager(tmp_path, browsers, ports=(29642, 29642))
    session = manager.start(
        keep_open_on_failure_spec(tmp_path),
        run_id="run-ok",
        run_dir=tmp_path / "runs" / "run-ok",
    )

    assert manager.finish(session, failed=False) is None

    assert browsers[0].quit_kwargs == [
        {"timeout": 10.0, "force": True, "del_data": False}
    ]
    assert not handoff_file(tmp_path).exists()


def test_start_adopts_the_recorded_browser_on_a_bound_port(tmp_path: Path) -> None:
    """The retained browser still holds the port; that must not block the run."""

    spec = keep_open_on_failure_spec(tmp_path)
    first = make_manager(tmp_path, [], ports=(29643, 29643))
    first.finish(
        first.start(spec, run_id="run-one", run_dir=tmp_path / "runs" / "run-one"),
        failed=True,
    )

    browsers: list[FakeBrowser] = []
    successor = make_manager(
        tmp_path,
        browsers,
        ports=(29643, 29643),
        port_available=lambda _: False,
        pid_is_alive=lambda pid: pid == 4242,
        devtools_responds=lambda port: port == 29643,
    )
    session = successor.start(
        spec,
        run_id="run-two",
        run_dir=tmp_path / "runs" / "run-two",
    )

    assert session.adopted is True
    assert session.port == 29643
    assert browsers[0].options.local_port == 29643
    # Ownership moved to this manager, so the record must not linger.
    assert not handoff_file(tmp_path).exists()


def test_start_refuses_to_adopt_when_the_recorded_process_is_dead(
    tmp_path: Path,
) -> None:
    """Adoption is not a blanket 'ignore the port' — a dead pid still fails closed."""

    spec = keep_open_on_failure_spec(tmp_path)
    first = make_manager(tmp_path, [], ports=(29644, 29644))
    first.finish(
        first.start(spec, run_id="run-one", run_dir=tmp_path / "runs" / "run-one"),
        failed=True,
    )

    browsers: list[FakeBrowser] = []
    successor = make_manager(
        tmp_path,
        browsers,
        ports=(29644, 29644),
        port_available=lambda _: False,
        pid_is_alive=lambda _: False,
        devtools_responds=lambda _: True,
    )

    with pytest.raises(BrowserPortLeaseError):
        successor.start(spec, run_id="run-two", run_dir=tmp_path / "runs" / "run-two")

    assert browsers == []
    assert not handoff_file(tmp_path).exists()


def test_start_refuses_to_adopt_when_devtools_does_not_answer(
    tmp_path: Path,
) -> None:
    """A live pid alone is not identity: the port holder must be our endpoint."""

    spec = keep_open_on_failure_spec(tmp_path)
    first = make_manager(tmp_path, [], ports=(29645, 29645))
    first.finish(
        first.start(spec, run_id="run-one", run_dir=tmp_path / "runs" / "run-one"),
        failed=True,
    )

    browsers: list[FakeBrowser] = []
    successor = make_manager(
        tmp_path,
        browsers,
        ports=(29645, 29645),
        port_available=lambda _: False,
        pid_is_alive=lambda _: True,
        devtools_responds=lambda _: False,
    )

    with pytest.raises(BrowserPortLeaseError):
        successor.start(spec, run_id="run-two", run_dir=tmp_path / "runs" / "run-two")

    assert browsers == []


def test_start_refuses_to_adopt_a_record_from_another_profile_directory(
    tmp_path: Path,
) -> None:
    spec = keep_open_on_failure_spec(tmp_path)
    first = make_manager(tmp_path, [], ports=(29646, 29646))
    first.finish(
        first.start(spec, run_id="run-one", run_dir=tmp_path / "runs" / "run-one"),
        failed=True,
    )
    path = handoff_file(tmp_path)
    record = json.loads(path.read_text(encoding="utf-8"))
    record["profile_dir"] = str(tmp_path / "profiles" / "SOMEONE_ELSE")
    path.write_text(json.dumps(record), encoding="utf-8")

    browsers: list[FakeBrowser] = []
    successor = make_manager(
        tmp_path,
        browsers,
        ports=(29646, 29646),
        port_available=lambda _: False,
        pid_is_alive=lambda _: True,
        devtools_responds=lambda _: True,
    )

    with pytest.raises(BrowserPortLeaseError):
        successor.start(spec, run_id="run-two", run_dir=tmp_path / "runs" / "run-two")

    assert browsers == []


def test_detach_refuses_a_session_without_a_process_id(tmp_path: Path) -> None:
    """An unretainable browser must fail loudly rather than leak a process."""

    manager = make_manager(tmp_path, [], ports=(29647, 29647), process_id=None)
    session = manager.start(
        keep_open_on_failure_spec(tmp_path),
        run_id="run-no-pid",
        run_dir=tmp_path / "runs" / "run-no-pid",
    )

    with pytest.raises(BrowserHandoffError):
        manager.finish(session, failed=True)

    assert not handoff_file(tmp_path).exists()


def test_release_handoff_is_a_no_op_without_a_record(tmp_path: Path) -> None:
    manager = make_manager(tmp_path, [], ports=(29648, 29648))

    assert manager.release_handoff("PROFILE_001") == {
        "released": False,
        "reason": "no_retained_browser",
    }


def test_release_handoff_discards_a_record_whose_browser_is_gone(
    tmp_path: Path,
) -> None:
    spec = keep_open_on_failure_spec(tmp_path)
    manager = make_manager(
        tmp_path,
        [],
        ports=(29649, 29649),
        pid_is_alive=lambda _: False,
    )
    manager.finish(
        manager.start(spec, run_id="run-one", run_dir=tmp_path / "runs" / "run-one"),
        failed=True,
    )

    result = manager.release_handoff("PROFILE_001")

    assert result["released"] is False
    assert result["reason"] == "retained_browser_already_gone"
    assert not handoff_file(tmp_path).exists()
