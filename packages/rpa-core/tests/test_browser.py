from __future__ import annotations

from hashlib import sha256
from pathlib import Path

import pytest
from rpa_core.browser import (
    DownloadError,
    ElementActionError,
    ElementSpec,
    FakeBrowserActions,
    FakeDownload,
    Locator,
    NavigationError,
    SecretValue,
    UnresolvedElementError,
)
from rpa_core.contracts import RunMode
from rpa_core.runtime import ExecutionContext

USERNAME = ElementSpec("example.login.username", "账号框", "login")
EXPORT = ElementSpec("example.inventory.export", "导出", "inventory")


def test_unresolved_element_is_explicit_but_fake_can_use_stable_id(tmp_path) -> None:
    with pytest.raises(UnresolvedElementError):
        USERNAME.require_locator()

    fake = FakeBrowserActions(
        tmp_path,
        visible_element_ids=[USERNAME.id],
    )
    fake.input(USERNAME, SecretValue("runtime-only", label="username"))

    assert fake.actions[-1].detail == "<redacted>"
    assert "runtime-only" not in repr(fake.actions)


def test_selected_option_locator_requires_option_locator() -> None:
    with pytest.raises(ValueError, match="requires option_locator"):
        ElementSpec(
            "example.filter.invalid",
            "无效多选框",
            "inventory",
            locator=Locator("#brand"),
            selected_option_locator=Locator("css:.selected-option"),
        )


def test_fake_download_returns_verified_artifact_without_network(tmp_path) -> None:
    content = b"sku,stock\nSKU_001,12\n"
    fake = FakeBrowserActions(
        tmp_path,
        visible_element_ids=[EXPORT.id],
        downloads={EXPORT.id: FakeDownload("inventory.fixture.csv", content)},
    )

    reference = fake.download(EXPORT)

    assert reference.path.read_bytes() == content
    assert reference.sha256 == f"sha256:{sha256(content).hexdigest()}"
    assert reference.size_bytes == len(content)
    assert reference.status == "completed"


def test_fake_download_rejects_path_escape(tmp_path) -> None:
    with pytest.raises(DownloadError):
        FakeDownload("../escape.csv", b"data")


def test_fake_text_requires_explicit_fixture_and_redacts_action(tmp_path) -> None:
    fake = FakeBrowserActions(
        tmp_path,
        visible_element_ids=[USERNAME.id],
        text_values={USERNAME.id: "runtime-only"},
    )

    assert fake.text(USERNAME) == "runtime-only"
    assert fake.actions[-1].detail == "<redacted>"
    assert "runtime-only" not in repr(fake.actions)

    without_fixture = FakeBrowserActions(
        tmp_path / "missing",
        visible_element_ids=[USERNAME.id],
    )
    with pytest.raises(ElementActionError):
        without_fixture.text(USERNAME)


def test_execution_context_exposes_browser_service(tmp_path) -> None:
    fake = FakeBrowserActions(tmp_path)
    context = ExecutionContext(
        app_id="example.browser.contract",
        run_id="browser-contract",
        account_id="ACCOUNT_001",
        mode=RunMode.PREVIEW,
        run_dir=tmp_path,
        download_dir=tmp_path / "downloads",
        services={"browser": fake},
    )

    assert context.browser is fake


# ---------------------------------------------------------------------------
# count() / texts() on the fake — how counterexamples describe a failing page
# ---------------------------------------------------------------------------


def test_fake_count_defaults_to_visibility(tmp_path: Path) -> None:
    element = ElementSpec("demo.page.rows", "结果行", "demo", locator=Locator("css:tr"))
    visible = FakeBrowserActions(tmp_path, visible_element_ids=(element.id,))
    absent = FakeBrowserActions(tmp_path)

    assert visible.count(element) == 1
    assert absent.count(element) == 0


def test_fake_count_and_texts_are_explicitly_configurable(tmp_path: Path) -> None:
    element = ElementSpec("demo.page.rows", "结果行", "demo", locator=Locator("css:tr"))
    browser = FakeBrowserActions(
        tmp_path,
        visible_element_ids=(element.id,),
        counts={element.id: 0},
        text_lists={element.id: ["甲", "乙"]},
    )

    assert browser.count(element) == 0
    assert browser.texts(element) == ["甲", "乙"]


def test_fake_texts_falls_back_to_the_single_text_fixture(tmp_path: Path) -> None:
    element = ElementSpec("demo.page.chip", "选中项", "demo", locator=Locator("css:.c"))
    browser = FakeBrowserActions(
        tmp_path,
        visible_element_ids=(element.id,),
        text_values={element.id: "目标"},
    )

    assert browser.texts(element) == ["目标"]


def test_fake_multi_reads_validate_their_fixtures(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="non-negative integers"):
        FakeBrowserActions(tmp_path, counts={"demo.page.rows": -1})
    with pytest.raises(ValueError, match="must be strings"):
        FakeBrowserActions(tmp_path, text_lists={"demo.page.rows": [1, 2]})
    with pytest.raises(ValueError, match="invalid fake count element IDs"):
        FakeBrowserActions(tmp_path, counts={"1-bad-id": 1})


def test_fake_click_switches_only_when_a_new_tab_fixture_exists(tmp_path: Path) -> None:
    view = ElementSpec("demo.report.view", "查看", "report")
    browser = FakeBrowserActions(
        tmp_path,
        visible_element_ids=(view.id,),
        new_tab_urls={view.id: "https://example.invalid/downloads"},
    )

    browser.click_and_switch_to_new_tab(view, timeout=3.0)

    assert browser.current_url == "https://example.invalid/downloads"
    assert [item.action for item in browser.actions] == ["click", "switch_new_tab"]

    missing = FakeBrowserActions(
        tmp_path / "missing",
        visible_element_ids=(view.id,),
    )
    with pytest.raises(NavigationError, match="no fake new tab"):
        missing.click_and_switch_to_new_tab(view)
