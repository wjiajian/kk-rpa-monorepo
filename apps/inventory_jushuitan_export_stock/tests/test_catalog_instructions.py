from __future__ import annotations

from pathlib import Path

import pytest

from rpa_core.browser import BrowserActionRecord, FakeBrowserActions, SecretValue
from rpa_core.catalog import discover_catalog, load_catalog_lock
from rpa_core.instructions import InstructionExecutionError, InstructionVerificationError

from inventory_jushuitan_export_stock.elements import element_catalog, get_element
from inventory_jushuitan_export_stock.instructions import build_instruction_registry

from .helpers import (
    ACCOUNT_IDENTITY_ELEMENT_ID,
    FIXTURE_IDENTITY,
    make_browser,
    make_context,
    visible_elements,
)


AUTHENTICATED = "jushuitan.erp.shell.authenticated_marker"
SUBMIT = "jushuitan.erp.login.submit_button"


class LoginTransitionBrowser(FakeBrowserActions):
    submitted: bool = False

    def exists(self, element, *, timeout: float = 0.0) -> bool:
        if element.id == AUTHENTICATED:
            found = self.submitted
            self.actions.append(
                BrowserActionRecord("exists", element.id, "present" if found else "missing")
            )
            return found
        return super().exists(element, timeout=timeout)

    def click(self, element) -> None:
        super().click(element)
        if element.id == SUBMIT:
            self.submitted = True


def test_local_verified_elements_are_unique_and_resolved() -> None:
    elements = element_catalog()

    assert len(elements) == 17
    assert len(elements) == len(set(elements))
    assert all(element.is_resolved for element in elements.values())


def test_public_catalog_exposes_the_verified_application_dependency_closure() -> None:
    repository_root = Path(__file__).resolve().parents[3]
    index = discover_catalog(repository_root)
    lock = load_catalog_lock(
        repository_root
        / "apps"
        / "inventory_jushuitan_export_stock"
        / "catalog.lock.json"
    )

    assert {item.ref for item in lock.items} <= set(index.refs())


def test_registry_exposes_every_snapshot_instruction() -> None:
    specs = build_instruction_registry().specs()

    assert [spec.instruction_id for spec in specs] == [
        "jushuitan.auth.ensure_account_session",
        "jushuitan.auth.login",
        "jushuitan.inventory.export_stock",
        "jushuitan.inventory.open_module",
        "jushuitan.inventory.open_product_stock",
        "jushuitan.inventory.search",
        "jushuitan.inventory.select_brand",
    ]
    assert all(spec.success_conditions for spec in specs)


def test_ensure_account_session_navigates_and_reuses_matching_session(
    tmp_path: Path,
) -> None:
    browser = make_browser(tmp_path / "matching-session")
    context = make_context(tmp_path / "matching-session", browser)

    result = context.instructions.execute(
        "jushuitan.auth.ensure_account_session",
        context,
        {
            "login_url": "https://www.erp321.com/login.aspx",
            "username": SecretValue(FIXTURE_IDENTITY, label="test-user"),
            "password": SecretValue("example-password", label="test-password"),
            "expected_identity": SecretValue(
                FIXTURE_IDENTITY,
                label="test-identity",
            ),
        },
    )

    assert dict(result) == {
        "authenticated": True,
        "identity_verified": True,
        "login_performed": False,
        "human_verification_required": False,
    }
    assert browser.current_url == "https://www.erp321.com/login.aspx"
    assert not any(record.action == "input" for record in browser.actions)


def test_ensure_account_session_logs_in_before_identity_check(tmp_path: Path) -> None:
    visible = visible_elements(missing={AUTHENTICATED})
    browser = LoginTransitionBrowser(
        run_dir=tmp_path / "login-and-check",
        visible_element_ids=visible,
        text_values={ACCOUNT_IDENTITY_ELEMENT_ID: f"tenant [{FIXTURE_IDENTITY}]"},
    )
    context = make_context(tmp_path / "login-and-check", browser)

    result = context.instructions.execute(
        "jushuitan.auth.ensure_account_session",
        context,
        {
            "login_url": "https://www.erp321.com/login.aspx",
            "username": SecretValue(FIXTURE_IDENTITY, label="test-user"),
            "password": SecretValue("example-password", label="test-password"),
            "expected_identity": SecretValue(
                FIXTURE_IDENTITY,
                label="test-identity",
            ),
        },
    )

    assert result["authenticated"] is True
    assert result["identity_verified"] is True
    assert result["login_performed"] is True
    assert [record.action for record in browser.actions].count("input") == 2


def test_ensure_account_session_fails_closed_on_wrong_account(tmp_path: Path) -> None:
    browser = FakeBrowserActions(
        run_dir=tmp_path / "wrong-account",
        visible_element_ids=visible_elements(),
        text_values={ACCOUNT_IDENTITY_ELEMENT_ID: "different-account"},
    )
    context = make_context(tmp_path / "wrong-account", browser)

    with pytest.raises(InstructionVerificationError):
        context.instructions.execute(
            "jushuitan.auth.ensure_account_session",
            context,
            {
                "login_url": "https://www.erp321.com/login.aspx",
                "username": SecretValue(FIXTURE_IDENTITY, label="test-user"),
                "password": SecretValue("example-password", label="test-password"),
                "expected_identity": SecretValue(
                    FIXTURE_IDENTITY,
                    label="test-identity",
                ),
            },
        )

    assert any(record.action == "screenshot" for record in browser.actions)
    assert not any(
        record.element_id == "jushuitan.erp.navigation.inventory_module"
        for record in browser.actions
    )


def test_verified_login_uses_runtime_secrets_and_stops_on_human_verification(
    tmp_path: Path,
) -> None:
    visible = visible_elements(missing={AUTHENTICATED})
    browser = LoginTransitionBrowser(run_dir=tmp_path / "login", visible_element_ids=visible)
    context = make_context(tmp_path / "login", browser)

    result = context.instructions.execute(
        "jushuitan.auth.login",
        context,
        {
            "login_url": "https://www.erp321.com/login.aspx",
            "username": SecretValue("example-user", label="test-user"),
            "password": SecretValue("example-password", label="test-password"),
        },
    )

    assert result == {
        "authenticated": True,
        "human_verification_required": False,
    }
    assert [record.action for record in browser.actions if record.action == "input"] == [
        "input",
        "input",
    ]
    assert all(record.detail == "<redacted>" for record in browser.actions if record.action == "input")
    assert get_element(SUBMIT).locator is not None


def test_verified_select_brand_delegates_exact_selection_to_browser_contract(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "select-brand"
    browser = make_browser(run_dir)
    context = make_context(run_dir, browser)

    result = context.instructions.execute(
        "jushuitan.inventory.select_brand",
        context,
        {"brand_value": "BRAND_001"},
    )

    assert dict(result) == {
        "selected_brand": "BRAND_001",
        "selection_visible": True,
    }
    assert browser.actions[-1] == BrowserActionRecord(
        "select",
        "jushuitan.erp.product_stock.brand_selector",
        "<redacted>",
    )


def test_verified_export_refuses_when_exact_brand_cannot_be_enforced(
    tmp_path: Path,
) -> None:
    browser = make_browser(
        tmp_path / "unfiltered-export",
        missing={"jushuitan.erp.product_stock.brand_selector"},
    )
    context = make_context(tmp_path / "unfiltered-export", browser)

    with pytest.raises(InstructionExecutionError):
        context.instructions.execute(
            "jushuitan.inventory.export_stock",
            context,
            {
                "filename": "inventory-export.xlsx",
                "brand_value": "BRAND_001",
            },
        )

    assert not any(
        record.element_id
        in {
            "jushuitan.erp.product_stock.export_menu",
            "jushuitan.erp.product_stock.export_stock_option",
        }
        and record.action in {"click", "download"}
        for record in browser.actions
    )
