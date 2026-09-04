from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from DrissionPage.common import Keys
from DrissionPage.errors import ContextLostError

from rpa_core.browser import (
    BrowserContextGuardError,
    DownloadError,
    ElementActionError,
    ElementLookupError,
    ElementSpec,
    Locator,
    NavigationError,
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
CUSTOM_INPUT = ElementSpec(
    "example.filter.custom_brand",
    "自定义品牌",
    "库存页",
    locator=Locator("#custom-brand"),
)
CUSTOM_INPUT_WITH_OPTIONS = ElementSpec(
    "example.filter.custom_brand_options",
    "精确选项品牌",
    "库存页",
    locator=Locator("#custom-brand"),
    frame_locator=Locator("#product-stock-frame"),
    option_locator=Locator("css:.brand-option"),
)
CUSTOM_EXCLUSIVE_INPUT = ElementSpec(
    "example.filter.custom_brand_exclusive",
    "精确集合品牌",
    "库存页",
    locator=Locator("#custom-brand"),
    frame_locator=Locator("#product-stock-frame"),
    option_locator=Locator("css:.brand-option"),
    selected_option_locator=Locator("css:.brand-option-selected"),
    popup_locator=Locator("css:.brand-popup"),
    dismiss_locator=Locator("#dismiss-anchor"),
)
FRAMED_INPUT = ElementSpec(
    "example.filter.framed_brand",
    "iframe 品牌",
    "库存页",
    locator=Locator("#framed-brand"),
    frame_locator=Locator("#product-stock-frame"),
)
TEXT_MARKER = ElementSpec(
    "example.inventory.marker",
    "库存标识",
    "库存页",
    locator=Locator("#marker"),
)
DOWNLOAD = ElementSpec(
    "example.inventory.download",
    "下载",
    "库存页",
    locator=Locator("text=导出库存"),
)
FRAMED_DOWNLOAD = ElementSpec(
    "example.inventory.framed_download",
    "frame 下载",
    "库存页",
    locator=Locator("text=导出库存"),
    frame_locator=Locator("#product-stock-frame"),
)


class FakeElementWait:
    def __init__(self, element: "FakeElement") -> None:
        self.element = element

    def clickable(self, **kwargs):
        self.element.wait_calls.append(kwargs)
        if self.element.on_wait is not None:
            self.element.on_wait()
        return self.element.clickable


class FakeElementStates:
    def __init__(self, element: "FakeElement") -> None:
        self.element = element

    @property
    def is_displayed(self) -> bool:
        return self.element.displayed

    @property
    def is_enabled(self) -> bool:
        return self.element.enabled

    @property
    def is_clickable(self) -> bool:
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
        self.element.click_count += 1
        if self.element.on_click is not None:
            self.element.on_click()

    def to_download(
        self,
        save_path: str,
        *,
        rename: str | None,
        by_js: bool,
        timeout: float,
    ) -> FakeMission:
        if self.element.on_download is not None:
            self.element.on_download()
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
    def __init__(
        self,
        *,
        clickable: bool = True,
        displayed: bool = True,
        enabled: bool = True,
        tag: str = "button",
        text: str = "",
        value: str | None = None,
        on_click: Callable[[], None] | None = None,
        on_wait: Callable[[], None] | None = None,
        on_download: Callable[[], None] | None = None,
    ) -> None:
        self.clickable = clickable
        self.displayed = displayed
        self.enabled = enabled
        self.tag = tag
        self.text = text
        self.value = value
        self.on_click = on_click
        self.on_wait = on_wait
        self.on_download = on_download
        self.wait = FakeElementWait(self)
        self.states = FakeElementStates(self)
        self.click = FakeClicker(self)
        self.select = FakeSelect(self)
        self.wait_calls: list[dict[str, object]] = []
        self.clear_calls: list[bool] = []
        self.focused = False
        self.inputs: list[tuple[str, bool, bool]] = []
        self.clicked_with: bool | None = None
        self.click_count = 0
        self.selected: tuple[str, float] | None = None
        self.download_args: dict[str, object] | None = None

    def clear(self, *, by_js: bool) -> None:
        self.clear_calls.append(by_js)

    def focus(self) -> None:
        self.focused = True

    def input(self, value: str, *, clear: bool, by_js: bool) -> None:
        self.inputs.append((value, clear, by_js))

    def attr(self, name: str):
        return self.value if name == "value" else None

    def __bool__(self) -> bool:
        return True


class FakeTabWait:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def doc_loaded(self, **kwargs) -> bool:
        self.calls.append(kwargs)
        return True


class FakeTab:
    def __init__(
        self,
        elements: dict[str, FakeElement] | None = None,
        *,
        frames: dict[str, "FakeTab"] | None = None,
        element_lists: dict[str, list[list[FakeElement]]] | None = None,
    ) -> None:
        self.elements = elements or {}
        self.frames = frames or {}
        self.element_lists = {
            locator: list(responses)
            for locator, responses in (element_lists or {}).items()
        }
        self.wait = FakeTabWait()
        self.opened: list[str] = []
        self.lookups: list[tuple[str, float]] = []
        self.frame_lookups: list[tuple[str, float]] = []
        self.multi_lookups: list[tuple[str, float]] = []
        self.browser = None

    def get(self, url: str) -> bool:
        self.opened.append(url)
        return True

    def ele(self, locator: str, *, timeout: float):
        self.lookups.append((locator, timeout))
        return self.elements.get(locator, False)

    def eles(self, locator: str, *, timeout: float):
        self.multi_lookups.append((locator, timeout))
        responses = self.element_lists.get(locator)
        if not responses:
            return []
        if len(responses) > 1:
            return responses.pop(0)
        return responses[0]

    def get_frame(self, locator: str, *, timeout: float):
        self.frame_lookups.append((locator, timeout))
        return self.frames.get(locator, False)

    def get_screenshot(self, *, path: str, name: str, full_page: bool) -> str:
        target = Path(path) / name
        target.write_bytes(b"fake png bytes")
        return str(target)


class FakeBrowserWait:
    def __init__(self, owner: "FakeBrowser") -> None:
        self.owner = owner
        self.calls: list[dict[str, object]] = []

    def new_tab(self, **kwargs):
        self.calls.append(kwargs)
        return self.owner.new_tab_id


class FakeBrowser:
    def __init__(self, tabs: dict[str, FakeTab], new_tab_id: str | bool) -> None:
        self.tabs = tabs
        self.new_tab_id = new_tab_id
        self.wait = FakeBrowserWait(self)
        for tab in tabs.values():
            tab.browser = self

    def get_tab(self, tab_id: str):
        return self.tabs.get(tab_id, False)

    @property
    def tab_ids(self) -> list[str]:
        return list(self.tabs)


class ReplacingTabBrowser(FakeBrowser):
    """Model a site that replaces the initially signalled target tab."""

    def __init__(
        self,
        source: FakeTab,
        replacement: FakeTab,
        *,
        signalled_tab_id: str | bool = "transient-target",
    ) -> None:
        super().__init__(
            {"source": source, "replacement": replacement},
            signalled_tab_id,
        )
        self.tab_id_reads = 0

    @property
    def tab_ids(self) -> list[str]:
        self.tab_id_reads += 1
        if self.tab_id_reads == 1:
            return ["source"]
        return ["source", "replacement"]


def test_current_url_exposes_adapter_boundary_value(tmp_path: Path) -> None:
    tab = FakeTab()
    tab.url = "https://example.invalid/inventory"
    browser = DrissionBrowserActions(tab, tmp_path)

    assert browser.current_url == "https://example.invalid/inventory"

    del tab.url
    assert browser.current_url is None


def test_context_url_exposes_actual_frame_url_and_fails_closed(
    tmp_path: Path,
) -> None:
    frame = FakeTab({"#framed-brand": FakeElement()})
    frame.url = "https://embedded.example.invalid/inventory"
    tab = FakeTab(frames={"#product-stock-frame": frame})
    tab.url = "https://example.invalid/inventory"
    browser = DrissionBrowserActions(tab, tmp_path)

    assert browser.context_url(USERNAME) == "https://example.invalid/inventory"
    assert (
        browser.context_url(FRAMED_INPUT)
        == "https://embedded.example.invalid/inventory"
    )
    assert tab.frame_lookups == [("#product-stock-frame", 10.0)]

    del frame.url
    assert browser.context_url(FRAMED_INPUT) is None

    tab.frames.clear()
    assert browser.context_url(FRAMED_INPUT) is None


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
    select = FakeElement(tag="select")
    tab = FakeTab({"#login_id": button, "#brand": select})
    browser = DrissionBrowserActions(tab, tmp_path, action_timeout=7.0)

    browser.click(USERNAME)
    browser.select(NATIVE_SELECT, SecretValue("FIXTURE_BRAND", label="brand"))

    assert button.clicked_with is False
    assert button.wait_calls == [
        {"wait_moved": True, "timeout": 7.0, "raise_err": False}
    ]
    assert select.selected == ("FIXTURE_BRAND", 7.0)


def test_adapter_clicks_waits_and_switches_to_new_tab(tmp_path: Path) -> None:
    view = ElementSpec(
        "example.report.view",
        "查看",
        "report",
        locator=Locator("#view"),
    )
    button = FakeElement()
    source = FakeTab({"#view": button})
    source.url = "https://example.invalid/report"
    target = FakeTab()
    target.url = "https://example.invalid/downloads"
    owner = FakeBrowser({"new-tab": target}, "new-tab")
    source.browser = owner
    browser = DrissionBrowserActions(source, tmp_path, action_timeout=7.0)

    browser.click_and_switch_to_new_tab(view, timeout=5.0)

    assert button.click_count == 1
    assert browser.tab is target
    assert owner.wait.calls == [
        {"timeout": 1.0, "curr_tab": source, "raise_err": False}
    ]
    assert target.wait.calls == [{"timeout": 5.0, "raise_err": False}]


def test_adapter_rejects_click_when_no_new_tab_appears(tmp_path: Path) -> None:
    view = ElementSpec(
        "example.report.view",
        "查看",
        "report",
        locator=Locator("#view"),
    )
    source = FakeTab({"#view": FakeElement()})
    source.url = "https://example.invalid/report"
    source.browser = FakeBrowser({}, False)
    browser = DrissionBrowserActions(source, tmp_path)

    with pytest.raises(NavigationError, match="did not open a new tab"):
        browser.click_and_switch_to_new_tab(view)


def test_adapter_recovers_when_site_replaces_signalled_new_tab(
    tmp_path: Path,
) -> None:
    view = ElementSpec(
        "example.report.view",
        "查看",
        "report",
        locator=Locator("#view"),
    )
    source = FakeTab({"#view": FakeElement()})
    target = FakeTab()
    owner = ReplacingTabBrowser(source, target)
    browser = DrissionBrowserActions(source, tmp_path)

    browser.click_and_switch_to_new_tab(view, timeout=1.0)

    assert browser.tab is target
    assert owner.wait.calls == [
        {"timeout": 1.0, "curr_tab": source, "raise_err": False}
    ]
    assert owner.tab_id_reads >= 2


def test_adapter_uses_tab_inventory_when_new_tab_wait_misses_replacement(
    tmp_path: Path,
) -> None:
    view = ElementSpec(
        "example.report.view",
        "查看",
        "report",
        locator=Locator("#view"),
    )
    source = FakeTab({"#view": FakeElement()})
    target = FakeTab()
    owner = ReplacingTabBrowser(source, target, signalled_tab_id=False)
    browser = DrissionBrowserActions(source, tmp_path)

    browser.click_and_switch_to_new_tab(view, timeout=1.0)

    assert browser.tab is target
    assert owner.tab_id_reads >= 2


def test_adapter_selects_custom_input_and_reads_exact_values(tmp_path: Path) -> None:
    custom = FakeElement(tag="input", value="FIXTURE_BRAND")
    marker = FakeElement(tag="span", text="筛选完成")
    browser = DrissionBrowserActions(
        FakeTab({"#custom-brand": custom, "#marker": marker}),
        tmp_path,
    )

    browser.select(CUSTOM_INPUT, SecretValue("FIXTURE_BRAND", label="brand"))

    assert custom.clear_calls == [True]
    assert custom.clicked_with is False
    assert custom.focused is True
    assert custom.inputs == [
        ("FIXTURE_BRAND", False, False),
        (Keys.ENTER, False, False),
    ]
    assert browser.text(CUSTOM_INPUT) == "FIXTURE_BRAND"
    assert browser.text(TEXT_MARKER) == "筛选完成"


def test_adapter_waits_for_one_exact_ready_custom_option_in_same_frame(
    tmp_path: Path,
) -> None:
    custom = FakeElement(tag="input")
    other = FakeElement(tag="div", text="OTHER_BRAND")
    hidden_exact = FakeElement(tag="div", text="FIXTURE_BRAND", displayed=False)
    disabled_exact = FakeElement(tag="div", text="FIXTURE_BRAND", enabled=False)
    ready_exact = FakeElement(tag="div", text=" FIXTURE_BRAND ")
    frame = FakeTab(
        {"#custom-brand": custom},
        element_lists={
            "css:.brand-option": [
                [],
                [other, hidden_exact, disabled_exact, ready_exact],
            ]
        },
    )
    tab = FakeTab(frames={"#product-stock-frame": frame})
    browser = DrissionBrowserActions(tab, tmp_path, action_timeout=0.25)

    browser.select(
        CUSTOM_INPUT_WITH_OPTIONS,
        SecretValue("FIXTURE_BRAND", label="brand"),
    )

    assert custom.inputs == [("FIXTURE_BRAND", False, False)]
    assert custom.clicked_with is False
    assert ready_exact.clicked_with is False
    assert hidden_exact.clicked_with is None
    assert disabled_exact.clicked_with is None
    assert len(tab.frame_lookups) == 3
    assert [locator for locator, _ in frame.multi_lookups] == [
        "css:.brand-option",
        "css:.brand-option",
    ]


def test_adapter_exclusive_custom_select_removes_extra_checked_option(
    tmp_path: Path,
) -> None:
    selected = ["UNSET", "FIXTURE_BRAND"]
    popup = FakeElement(tag="div")

    def toggle(value: str) -> None:
        if value in selected:
            selected.remove(value)
        else:
            selected.append(value)

    options = {
        value: FakeElement(
            tag="div",
            text=value,
            on_click=lambda value=value: toggle(value),
        )
        for value in ("UNSET", "FIXTURE_BRAND", "OTHER_BRAND")
    }

    class ExclusiveFrame(FakeTab):
        def eles(self, locator: str, *, timeout: float):
            self.multi_lookups.append((locator, timeout))
            if locator == "css:.brand-option":
                return list(options.values())
            if locator == "css:.brand-option-selected":
                return [options[value] for value in selected]
            if locator == "css:.brand-popup":
                return [popup]
            return []

    events: list[str] = []

    def dismiss_popup() -> None:
        events.append("dismiss-click")
        popup.displayed = False

    custom = FakeElement(tag="input")
    dismiss = FakeElement(
        on_click=dismiss_popup,
        on_wait=lambda: events.append("dismiss-wait"),
    )
    frame = ExclusiveFrame(
        {"#custom-brand": custom, "#dismiss-anchor": dismiss}
    )
    frame.url = "https://example.invalid/embedded"
    guarded_urls: list[str | None] = []

    def guard(url: str | None) -> None:
        assert url == "https://example.invalid/embedded"
        guarded_urls.append(url)
        events.append("guard")

    tab = FakeTab(frames={"#product-stock-frame": frame})
    browser = DrissionBrowserActions(
        tab,
        tmp_path,
        action_timeout=0.5,
    )

    browser.select(
        CUSTOM_EXCLUSIVE_INPUT,
        "FIXTURE_BRAND",
        context_guard=guard,
    )

    assert selected == ["FIXTURE_BRAND"]
    assert options["UNSET"].click_count == 1
    assert options["FIXTURE_BRAND"].click_count == 0
    assert custom.inputs == [("FIXTURE_BRAND", False, False)]
    assert dismiss.click_count == 1
    assert popup.displayed is False
    assert len(guarded_urls) >= 10
    assert len(tab.frame_lookups) == 7
    dismiss_index = events.index("dismiss-click")
    assert events[dismiss_index - 1 : dismiss_index + 2] == [
        "guard",
        "dismiss-click",
        "guard",
    ]


def test_adapter_exclusive_custom_select_adds_missing_target_after_cleanup(
    tmp_path: Path,
) -> None:
    selected = ["UNSET"]
    popup = FakeElement(tag="div")

    def toggle(value: str) -> None:
        if value in selected:
            selected.remove(value)
        else:
            selected.append(value)

    options = {
        value: FakeElement(
            tag="div",
            text=value,
            on_click=lambda value=value: toggle(value),
        )
        for value in ("UNSET", "FIXTURE_BRAND")
    }

    class ExclusiveFrame(FakeTab):
        def eles(self, locator: str, *, timeout: float):
            self.multi_lookups.append((locator, timeout))
            if locator == "css:.brand-option":
                return list(options.values())
            if locator == "css:.brand-option-selected":
                return [options[value] for value in selected]
            if locator == "css:.brand-popup":
                return [popup]
            return []

    dismiss = FakeElement(on_click=lambda: setattr(popup, "displayed", False))
    frame = ExclusiveFrame(
        {
            "#custom-brand": FakeElement(tag="input"),
            "#dismiss-anchor": dismiss,
        }
    )
    browser = DrissionBrowserActions(
        FakeTab(frames={"#product-stock-frame": frame}),
        tmp_path,
        action_timeout=0.5,
    )

    browser.select(CUSTOM_EXCLUSIVE_INPUT, "FIXTURE_BRAND")

    assert selected == ["FIXTURE_BRAND"]
    assert options["UNSET"].click_count == 1
    assert options["FIXTURE_BRAND"].click_count == 1
    assert dismiss.click_count == 1
    assert popup.displayed is False


def test_adapter_exclusive_custom_select_fails_if_popup_stays_visible(
    tmp_path: Path,
) -> None:
    custom = FakeElement(tag="input")
    selected = FakeElement(tag="div", text="FIXTURE_BRAND")
    popup = FakeElement(tag="div")
    dismiss = FakeElement()
    frame = FakeTab(
        {
            "#custom-brand": custom,
            "#dismiss-anchor": dismiss,
        },
        element_lists={
            "css:.brand-option": [[selected]],
            "css:.brand-option-selected": [[selected]],
            "css:.brand-popup": [[popup]],
        },
    )
    browser = DrissionBrowserActions(
        FakeTab(frames={"#product-stock-frame": frame}),
        tmp_path,
        action_timeout=0.05,
    )

    with pytest.raises(ElementActionError, match="remained visible"):
        browser.select(CUSTOM_EXCLUSIVE_INPUT, "FIXTURE_BRAND")

    assert dismiss.click_count == 1
    assert popup.displayed is True


def test_adapter_rejects_zero_or_multiple_exact_custom_options(tmp_path: Path) -> None:
    custom = FakeElement(tag="input")
    no_match_frame = FakeTab({"#custom-brand": custom})
    no_match = DrissionBrowserActions(
        FakeTab(frames={"#product-stock-frame": no_match_frame}),
        tmp_path / "none",
        action_timeout=0.01,
    )

    with pytest.raises(ElementActionError) as missing:
        no_match.select(CUSTOM_INPUT_WITH_OPTIONS, "FIXTURE_BRAND")
    assert "FIXTURE_BRAND" not in str(missing.value)

    first = FakeElement(tag="div", text="FIXTURE_BRAND")
    second = FakeElement(tag="div", text="FIXTURE_BRAND")
    duplicate_frame = FakeTab(
        {"#custom-brand": FakeElement(tag="input")},
        element_lists={"css:.brand-option": [[first, second]]},
    )
    duplicate = DrissionBrowserActions(
        FakeTab(frames={"#product-stock-frame": duplicate_frame}),
        tmp_path / "duplicate",
        action_timeout=0.1,
    )

    with pytest.raises(ElementActionError, match="multiple exact") as multiple:
        duplicate.select(CUSTOM_INPUT_WITH_OPTIONS, "FIXTURE_BRAND")
    assert "FIXTURE_BRAND" not in str(multiple.value)


def test_adapter_rejects_obstructed_exact_custom_option(tmp_path: Path) -> None:
    obstructed = FakeElement(tag="div", text="FIXTURE_BRAND", clickable=False)
    frame = FakeTab(
        {"#custom-brand": FakeElement(tag="input")},
        element_lists={"css:.brand-option": [[obstructed]]},
    )
    browser = DrissionBrowserActions(
        FakeTab(frames={"#product-stock-frame": frame}),
        tmp_path,
        action_timeout=0.01,
    )

    with pytest.raises(ElementActionError):
        browser.select(CUSTOM_INPUT_WITH_OPTIONS, "FIXTURE_BRAND")
    assert obstructed.clicked_with is None


def test_adapter_relocates_frame_before_each_element_action(tmp_path: Path) -> None:
    framed = FakeElement(tag="input", value="FIXTURE_BRAND")
    frame = FakeTab({"#framed-brand": framed})
    frame.url = "https://example.invalid/embedded"
    tab = FakeTab(frames={"#product-stock-frame": frame})
    browser = DrissionBrowserActions(tab, tmp_path)

    def guard(url: str | None) -> None:
        assert url == "https://example.invalid/embedded"

    assert browser.exists(FRAMED_INPUT, timeout=2.0, context_guard=guard) is True
    assert browser.text(FRAMED_INPUT, context_guard=guard) == "FIXTURE_BRAND"
    browser.input(FRAMED_INPUT, "FIXTURE_BRAND", context_guard=guard)
    browser.select(FRAMED_INPUT, "FIXTURE_BRAND", context_guard=guard)

    assert tab.frame_lookups == [
        ("#product-stock-frame", 2.0),
        ("#product-stock-frame", 10.0),
        ("#product-stock-frame", 10.0),
        ("#product-stock-frame", 10.0),
    ]
    assert frame.lookups == [
        ("#framed-brand", 2.0),
        ("#framed-brand", 10.0),
        ("#framed-brand", 10.0),
        ("#framed-brand", 10.0),
    ]


def test_adapter_guards_the_same_resolved_frame_before_and_after_click(
    tmp_path: Path,
) -> None:
    allowed = "https://example.invalid/embedded"
    unauthorized = "https://unexpected.invalid/embedded"

    def guard(url: str | None) -> None:
        if url != allowed:
            raise RuntimeError("origin rejected")

    blocked = FakeElement()
    blocked_frame = FakeTab({"#framed-brand": blocked})
    blocked_frame.url = unauthorized
    blocked_tab = FakeTab(frames={"#product-stock-frame": blocked_frame})
    blocked_browser = DrissionBrowserActions(blocked_tab, tmp_path / "blocked")

    with pytest.raises(BrowserContextGuardError):
        blocked_browser.click(FRAMED_INPUT, context_guard=guard)
    assert blocked.click_count == 0
    assert len(blocked_tab.frame_lookups) == 1

    waiting_frame = FakeTab()
    waiting_frame.url = allowed
    waiting = FakeElement(
        on_wait=lambda: setattr(waiting_frame, "url", unauthorized)
    )
    waiting_frame.elements["#framed-brand"] = waiting
    waiting_tab = FakeTab(frames={"#product-stock-frame": waiting_frame})
    waiting_browser = DrissionBrowserActions(
        waiting_tab,
        tmp_path / "waiting",
    )

    with pytest.raises(BrowserContextGuardError):
        waiting_browser.click(FRAMED_INPUT, context_guard=guard)
    assert waiting.click_count == 0
    assert len(waiting_tab.frame_lookups) == 1

    navigating_frame = FakeTab()
    navigating_frame.url = allowed
    navigating = FakeElement(
        on_click=lambda: setattr(navigating_frame, "url", unauthorized)
    )
    navigating_frame.elements["#framed-brand"] = navigating
    navigating_tab = FakeTab(
        frames={"#product-stock-frame": navigating_frame}
    )
    navigating_browser = DrissionBrowserActions(
        navigating_tab,
        tmp_path / "navigating",
    )

    with pytest.raises(BrowserContextGuardError):
        navigating_browser.click(FRAMED_INPUT, context_guard=guard)
    assert navigating.click_count == 1
    assert len(navigating_tab.frame_lookups) == 1


def test_adapter_waits_for_transient_blank_frame_before_click(
    tmp_path: Path,
) -> None:
    allowed = "https://example.invalid/embedded"

    class LoadingFrame(FakeTab):
        url_reads = 0

        @property
        def url(self) -> str:
            self.url_reads += 1
            return "about:blank" if self.url_reads == 1 else allowed

    target = FakeElement()
    frame = LoadingFrame({"#framed-brand": target})
    tab = FakeTab(frames={"#product-stock-frame": frame})
    guarded_urls: list[str | None] = []

    def guard(url: str | None) -> None:
        guarded_urls.append(url)
        if url != allowed:
            raise RuntimeError("origin rejected")

    browser = DrissionBrowserActions(tab, tmp_path, action_timeout=0.2)

    browser.click(FRAMED_INPUT, context_guard=guard)

    assert target.click_count == 1
    assert len(tab.frame_lookups) == 2
    assert [locator for locator, _ in frame.lookups] == ["#framed-brand"]
    assert guarded_urls
    assert set(guarded_urls) == {allowed}


def test_adapter_keeps_persistent_blank_frame_fail_closed(
    tmp_path: Path,
) -> None:
    target = FakeElement()
    frame = FakeTab({"#framed-brand": target})
    frame.url = "about:blank"
    tab = FakeTab(frames={"#product-stock-frame": frame})

    def guard(url: str | None) -> None:
        raise RuntimeError(f"origin rejected: {url}")

    browser = DrissionBrowserActions(tab, tmp_path, action_timeout=0.01)

    with pytest.raises(BrowserContextGuardError):
        browser.click(FRAMED_INPUT, context_guard=guard)

    assert target.click_count == 0
    assert frame.lookups == []
    assert len(tab.frame_lookups) >= 1


def test_adapter_rechecks_after_input_and_option_waits_before_effect(
    tmp_path: Path,
) -> None:
    allowed = "https://example.invalid/embedded"
    unauthorized = "https://unexpected.invalid/embedded"

    def guard(url: str | None) -> None:
        if url != allowed:
            raise RuntimeError("origin rejected")

    input_frame = FakeTab()
    input_frame.url = allowed
    field = FakeElement(on_wait=lambda: setattr(input_frame, "url", unauthorized))
    input_frame.elements["#framed-brand"] = field
    input_tab = FakeTab(frames={"#product-stock-frame": input_frame})
    input_browser = DrissionBrowserActions(input_tab, tmp_path / "input")

    with pytest.raises(BrowserContextGuardError):
        input_browser.input(FRAMED_INPUT, "FIXTURE_BRAND", context_guard=guard)
    assert field.clear_calls == []
    assert field.inputs == []
    assert len(input_tab.frame_lookups) == 1

    option_frame = FakeTab()
    option_frame.url = allowed
    option = FakeElement(
        tag="div",
        text="FIXTURE_BRAND",
        on_wait=lambda: setattr(option_frame, "url", unauthorized),
    )
    option_frame.elements["#custom-brand"] = FakeElement(tag="input")
    option_frame.element_lists["css:.brand-option"] = [[option]]
    option_tab = FakeTab(frames={"#product-stock-frame": option_frame})
    option_browser = DrissionBrowserActions(
        option_tab,
        tmp_path / "option",
        action_timeout=0.2,
    )

    with pytest.raises(BrowserContextGuardError):
        option_browser.select(
            CUSTOM_INPUT_WITH_OPTIONS,
            "FIXTURE_BRAND",
            context_guard=guard,
        )
    assert option.click_count == 0
    assert len(option_tab.frame_lookups) == 2


def test_adapter_re_resolves_frame_after_transient_context_loss(tmp_path: Path) -> None:
    class RefreshingFrame(FakeTab):
        lookup_count = 0

        def ele(self, locator: str, *, timeout: float):
            self.lookup_count += 1
            if self.lookup_count == 1:
                raise ContextLostError()
            return super().ele(locator, timeout=timeout)

    frame = RefreshingFrame(
        {"#framed-brand": FakeElement(tag="input", value="FIXTURE_BRAND")}
    )
    tab = FakeTab(frames={"#product-stock-frame": frame})
    browser = DrissionBrowserActions(tab, tmp_path, action_timeout=0.2)

    assert browser.text(FRAMED_INPUT) == "FIXTURE_BRAND"
    assert frame.lookup_count == 2
    assert len(tab.frame_lookups) == 2


def test_adapter_rejects_unknown_select_tags(tmp_path: Path) -> None:
    browser = DrissionBrowserActions(
        FakeTab({"#custom-brand": FakeElement(tag="div")}),
        tmp_path,
    )

    with pytest.raises(ElementActionError, match="unsupported select element tag"):
        browser.select(CUSTOM_INPUT, "FIXTURE_BRAND")


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
    events: list[str] = []

    class ObservedFrame(FakeTab):
        @property
        def url(self) -> str:
            events.append("guard")
            return "https://example.invalid/embedded"

    element = FakeElement(on_download=lambda: events.append("download"))
    frame = ObservedFrame({"text=导出库存": element})
    guarded_urls: list[str | None] = []

    def guard(url: str | None) -> None:
        assert url == "https://example.invalid/embedded"
        guarded_urls.append(url)

    tab = FakeTab(frames={"#product-stock-frame": frame})
    browser = DrissionBrowserActions(
        tab,
        tmp_path,
    )

    result = browser.download(
        FRAMED_DOWNLOAD,
        filename="inventory.fixture.csv",
        context_guard=guard,
    )

    assert result.path == tmp_path / "downloads" / "inventory.fixture.csv"
    assert result.status == "completed"
    assert result.size_bytes > 0
    assert result.sha256.startswith("sha256:")
    assert element.download_args == {
        "save_path": str(tmp_path / "downloads"),
        "rename": "inventory.fixture.csv",
        "by_js": False,
        "timeout": 120.0,
    }
    assert len(guarded_urls) >= 4
    assert len(tab.frame_lookups) == 1
    trigger_index = events.index("download")
    assert events[trigger_index - 1 : trigger_index + 2] == [
        "guard",
        "download",
        "guard",
    ]


def test_adapter_rejects_unsafe_download_name(tmp_path: Path) -> None:
    browser = DrissionBrowserActions(FakeTab(), tmp_path)

    with pytest.raises(DownloadError):
        browser.download(DOWNLOAD, filename="../escape.csv")


def test_adapter_screenshot_stays_inside_run_directory(tmp_path: Path) -> None:
    browser = DrissionBrowserActions(FakeTab(), tmp_path)

    result = browser.screenshot(name="login-page.png", full_page=True)

    assert result.path == tmp_path / "evidence" / "login-page.png"
    assert result.size_bytes == len(b"fake png bytes")


# ---------------------------------------------------------------------------
# count() / texts() — the multi-element reads that make real assertions writable
# ---------------------------------------------------------------------------


ROWS = ElementSpec(
    "example.inventory.rows",
    "结果行",
    "库存页",
    locator=Locator("css:table tbody tr"),
)
FRAMED_ROWS = ElementSpec(
    "example.inventory.framed_rows",
    "iframe 结果行",
    "库存页",
    locator=Locator("css:table tbody tr"),
    frame_locator=Locator("#product-stock-frame"),
)


def test_count_returns_the_number_of_matches(tmp_path: Path) -> None:
    tab = FakeTab(
        element_lists={
            "css:table tbody tr": [[FakeElement(tag="tr") for _ in range(21)]]
        }
    )
    browser = DrissionBrowserActions(tab, tmp_path)

    assert browser.count(ROWS) == 21


def test_count_of_an_absent_target_is_zero_not_an_error(tmp_path: Path) -> None:
    """An empty result set is a page state a step must be able to assert on."""

    browser = DrissionBrowserActions(FakeTab(), tmp_path)

    assert browser.count(ROWS) == 0
    assert browser.texts(ROWS) == []


def test_texts_reads_every_match_and_prefers_input_values(tmp_path: Path) -> None:
    tab = FakeTab(
        element_lists={
            "css:table tbody tr": [
                [
                    FakeElement(tag="td", text="品牌甲"),
                    FakeElement(tag="input", value="品牌乙"),
                    FakeElement(tag="td", text=""),
                ]
            ]
        }
    )
    browser = DrissionBrowserActions(tab, tmp_path)

    assert browser.texts(ROWS) == ["品牌甲", "品牌乙", ""]


def test_multi_element_reads_resolve_the_frame_each_time(tmp_path: Path) -> None:
    frame = FakeTab(
        element_lists={"css:table tbody tr": [[FakeElement(tag="td", text="甲")]]}
    )
    tab = FakeTab(frames={"#product-stock-frame": frame})
    browser = DrissionBrowserActions(tab, tmp_path)

    assert browser.count(FRAMED_ROWS) == 1
    assert browser.texts(FRAMED_ROWS) == ["甲"]
    assert [locator for locator, _ in tab.frame_lookups] == [
        "#product-stock-frame",
        "#product-stock-frame",
    ]


def test_multi_element_reads_reject_a_negative_timeout(tmp_path: Path) -> None:
    browser = DrissionBrowserActions(FakeTab(), tmp_path)

    with pytest.raises(ValueError):
        browser.count(ROWS, timeout=-1.0)
    with pytest.raises(ValueError):
        browser.texts(ROWS, timeout=-1.0)


def test_multi_element_reads_require_a_captured_locator(tmp_path: Path) -> None:
    unresolved = ElementSpec("example.unresolved", "未捕获", "库存页")
    browser = DrissionBrowserActions(FakeTab(), tmp_path)

    with pytest.raises(UnresolvedElementError):
        browser.count(unresolved)


def test_multi_element_reads_wait_for_an_attaching_frame(tmp_path: Path) -> None:
    """A business iframe is routinely still attaching after the outer marker.

    Treating that as a hard failure made verify-elements report a healthy
    selector as broken on its first real run.
    """

    frame = FakeTab(
        element_lists={"css:table tbody tr": [[FakeElement(tag="td", text="甲")]]}
    )
    tab = FakeTab()
    attempts = {"count": 0}
    original = tab.get_frame

    def flaky_get_frame(locator: str, *, timeout: float):
        attempts["count"] += 1
        original(locator, timeout=timeout)
        return frame if attempts["count"] > 2 else False

    tab.get_frame = flaky_get_frame
    browser = DrissionBrowserActions(tab, tmp_path, action_timeout=2.0)

    assert browser.count(FRAMED_ROWS) == 1
    assert attempts["count"] > 2


def test_multi_element_reads_re_resolve_the_scope_after_context_loss(
    tmp_path: Path,
) -> None:
    """The business iframe is re-created after the outer marker appears.

    Querying the already-resolved frame then raises ContextLostError. Retrying
    the same stale scope, or failing outright, reported a healthy selector as
    broken during the first real verify-elements run.
    """

    class LosingFrame(FakeTab):
        def eles(self, locator: str, *, timeout: float):
            raise ContextLostError("frame was replaced")

    good_frame = FakeTab(
        element_lists={"css:table tbody tr": [[FakeElement(tag="td", text="甲")]]}
    )
    tab = FakeTab()
    frames = [LosingFrame(), good_frame]
    resolved: list[object] = []

    def get_frame(locator: str, *, timeout: float):
        frame = frames[min(len(resolved), len(frames) - 1)]
        resolved.append(frame)
        return frame

    tab.get_frame = get_frame
    browser = DrissionBrowserActions(tab, tmp_path, action_timeout=2.0)

    assert browser.count(FRAMED_ROWS) == 1
    # A fresh frame was resolved for the retry rather than reusing the stale one.
    assert len(resolved) >= 2 and resolved[0] is not resolved[1]
