from __future__ import annotations

from hashlib import sha256

import pytest

from rpa_core.browser import (
    DownloadError,
    ElementActionError,
    ElementSpec,
    FakeBrowserActions,
    FakeDownload,
    Locator,
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
        program_id="example.browser.contract.program",
        program_version="0.1.0",
        requirement_hash="sha256:" + ("0" * 64),
        run_id="browser-contract",
        account_id="ACCOUNT_001",
        mode=RunMode.PREVIEW,
        run_dir=tmp_path,
        services={"browser": fake},
    )

    assert context.browser is fake
