from __future__ import annotations

import json
from pathlib import Path
import pytest

from rpa_core.browser_manager import (
    BrowserLaunchSpec,
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
    def __init__(self, options: FakeOptions, *, tab: object | None = None) -> None:
        self.options = options
        self.latest_tab = tab if tab is not None else object()
        self.quit_calls = 0

    def quit(self) -> None:
        self.quit_calls += 1


def make_manager(tmp_path: Path, browsers: list[FakeBrowser], ports=(29600, 29609)):
    def create_browser(options: FakeOptions) -> FakeBrowser:
        browser = FakeBrowser(options)
        browsers.append(browser)
        return browser

    return BrowserManager(
        tmp_path / "runtime",
        port_range=ports,
        options_factory=FakeOptions,
        chromium_factory=create_browser,
        port_available=lambda _: True,
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

    with pytest.raises(BrowserStartError):
        manager.start(spec, run_id="run-fail", run_dir=tmp_path / "runs" / "run-fail")

    assert not (tmp_path / "runtime" / "port-leases" / "29620.json").exists()
    browsers: list[FakeBrowser] = []
    retry = make_manager(tmp_path, browsers, ports=(29620, 29620))
    session = retry.start(spec, run_id="run-retry", run_dir=tmp_path / "runs" / "run-retry")
    retry.close(session)


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
