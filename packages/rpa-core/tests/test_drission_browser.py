from __future__ import annotations

from pathlib import Path

import pytest

from rpa_core.browser import (
    DownloadError,
    ElementLookupError,
    ElementSpec,
    Locator,
    SecretValue,
    UnresolvedElementError,
)
from rpa_core.drission_browser import DrissionBrowserActions


USERNAME = ElementSpec(
    "example.login.username",
    "账号框",
    "登录页",
    locator=Locator("#login_id"),
)
NATIVE_SELECT = ElementSpec(
    "example.filter.brand",
    "品牌",
    "库存页",
    locator=Locator("#brand"),
)
DOWNLOAD = ElementSpec(
    "example.inventory.download",
    "下载",
    "库存页",
    locator=Locator("text=导出库存"),
)


class FakeElementWait:
    def __init__(self, element: "FakeElement") -> None:
        self.element = element

    def clickable(self, **kwargs):
        self.element.wait_calls.append(kwargs)
        return self.element.clickable


class FakeSelect:
    def __init__(self, element: "FakeElement") -> None:
        self.element = element

    def by_text(self, value: str, *, timeout: float):
        self.element.selected = (value, timeout)


class FakeMission:
    def __init__(self, final_path: Path, *, done: bool = True) -> None:
        self.final_path = str(final_path)
        self.state = "completed" if done else "running"
        self.is_done = done
        self.canceled = False

    def cancel(self) -> None:
        self.canceled = True
        self.state = "canceled"
        self.is_done = True


class FakeClicker:
    def __init__(self, element: "FakeElement") -> None:
        self.element = element

    def __call__(self, *, by_js: bool) -> None:
        self.element.clicked_with = by_js

    def to_download(
        self,
        save_path: str,
        *,
        rename: str | None,
        by_js: bool,
        timeout: float,
    ) -> FakeMission:
        target = Path(save_path) / (rename or "download.fixture.csv")
        target.write_bytes(b"sku,stock\nSKU_001,12\n")
        self.element.download_args = {
            "save_path": save_path,
            "rename": rename,
            "by_js": by_js,
            "timeout": timeout,
        }
        return FakeMission(target)


class FakeElement:
    def __init__(self, *, clickable: bool = True) -> None:
        self.clickable = clickable
        self.wait = FakeElementWait(self)
        self.click = FakeClicker(self)
        self.select = FakeSelect(self)
        self.wait_calls: list[dict[str, object]] = []
        self.clear_calls: list[bool] = []
        self.focused = False
        self.inputs: list[tuple[str, bool, bool]] = []
        self.clicked_with: bool | None = None
        self.selected: tuple[str, float] | None = None
        self.download_args: dict[str, object] | None = None

    def clear(self, *, by_js: bool) -> None:
        self.clear_calls.append(by_js)

    def focus(self) -> None:
        self.focused = True

    def input(self, value: str, *, clear: bool, by_js: bool) -> None:
        self.inputs.append((value, clear, by_js))

    def __bool__(self) -> bool:
        return True


class FakeTabWait:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def doc_loaded(self, **kwargs) -> bool:
        self.calls.append(kwargs)
        return True


class FakeTab:
    def __init__(self, elements: dict[str, FakeElement] | None = None) -> None:
        self.elements = elements or {}
        self.wait = FakeTabWait()
        self.opened: list[str] = []
        self.lookups: list[tuple[str, float]] = []

    def get(self, url: str) -> bool:
        self.opened.append(url)
        return True

    def ele(self, locator: str, *, timeout: float):
        self.lookups.append((locator, timeout))
        return self.elements.get(locator, False)

    def get_screenshot(self, *, path: str, name: str, full_page: bool) -> str:
        target = Path(path) / name
        target.write_bytes(b"fake png bytes")
        return str(target)


def test_adapter_opens_page_and_waits_for_document(tmp_path: Path) -> None:
    tab = FakeTab()
    browser = DrissionBrowserActions(tab, tmp_path)

    browser.open("https://example.invalid/login")

    assert tab.opened == ["https://example.invalid/login"]
    assert tab.wait.calls == [{"timeout": 10.0, "raise_err": False}]


def test_adapter_relocates_and_inputs_secret_without_js_typing(tmp_path: Path) -> None:
    field = FakeElement()
    tab = FakeTab({"#login_id": field})
    browser = DrissionBrowserActions(tab, tmp_path)

    browser.input(USERNAME, SecretValue("runtime-only", label="username"))

    assert tab.lookups == [("#login_id", 10.0)]
    assert field.clear_calls == [True]
    assert field.focused is True
    assert field.inputs == [("runtime-only", False, False)]


def test_adapter_click_and_native_select_use_bounded_waits(tmp_path: Path) -> None:
    button = FakeElement()
    select = FakeElement()
    tab = FakeTab({"#login_id": button, "#brand": select})
    browser = DrissionBrowserActions(tab, tmp_path, action_timeout=7.0)

    browser.click(USERNAME)
    browser.select(NATIVE_SELECT, SecretValue("FIXTURE_BRAND", label="brand"))

    assert button.clicked_with is False
    assert button.wait_calls == [
        {"wait_moved": True, "timeout": 7.0, "raise_err": False}
    ]
    assert select.selected == ("FIXTURE_BRAND", 7.0)


def test_adapter_exists_and_unresolved_lookup_fail_closed(tmp_path: Path) -> None:
    tab = FakeTab({"#login_id": FakeElement()})
    browser = DrissionBrowserActions(tab, tmp_path)

    assert browser.exists(USERNAME, timeout=2.0) is True
    assert browser.exists(NATIVE_SELECT, timeout=0.0) is False
    with pytest.raises(UnresolvedElementError):
        browser.exists(ElementSpec("example.unknown", "未知", "页面"))
    with pytest.raises(ElementLookupError):
        browser.click(NATIVE_SELECT)


def test_adapter_download_is_isolated_and_hashed(tmp_path: Path) -> None:
    element = FakeElement()
    browser = DrissionBrowserActions(
        FakeTab({"text=导出库存": element}),
        tmp_path,
    )

    result = browser.download(DOWNLOAD, filename="inventory.fixture.csv")

    assert result.path == tmp_path / "downloads" / "inventory.fixture.csv"
    assert result.status == "completed"
    assert result.size_bytes > 0
    assert result.sha256.startswith("sha256:")
    assert element.download_args == {
        "save_path": str(tmp_path / "downloads"),
        "rename": "inventory.fixture.csv",
        "by_js": False,
        "timeout": 10.0,
    }


def test_adapter_rejects_unsafe_download_name(tmp_path: Path) -> None:
    browser = DrissionBrowserActions(FakeTab(), tmp_path)

    with pytest.raises(DownloadError):
        browser.download(DOWNLOAD, filename="../escape.csv")


def test_adapter_screenshot_stays_inside_run_directory(tmp_path: Path) -> None:
    browser = DrissionBrowserActions(FakeTab(), tmp_path)

    result = browser.screenshot(name="login-page.png", full_page=True)

    assert result.path == tmp_path / "evidence" / "login-page.png"
    assert result.size_bytes == len(b"fake png bytes")
