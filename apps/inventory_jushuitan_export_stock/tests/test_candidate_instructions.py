from __future__ import annotations

from pathlib import Path

from rpa_core.browser import BrowserActionRecord, FakeBrowserActions, SecretValue

from inventory_jushuitan_export_stock.elements import element_catalog, get_element
from inventory_jushuitan_export_stock.instructions import build_instruction_registry

from .helpers import make_context, visible_elements


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


def test_all_candidate_elements_are_unresolved_and_unique() -> None:
    elements = element_catalog()

    assert len(elements) == 16
    assert len(elements) == len(set(elements))
    assert all(not element.is_resolved for element in elements.values())


def test_registry_exposes_every_candidate_instruction() -> None:
    specs = build_instruction_registry().specs()

    assert [spec.instruction_id for spec in specs] == [
        "jushuitan.auth.login",
        "jushuitan.auth.require_session",
        "jushuitan.inventory.export_stock",
        "jushuitan.inventory.open_module",
        "jushuitan.inventory.open_product_stock",
        "jushuitan.inventory.search",
        "jushuitan.inventory.select_brand",
    ]
    assert all(spec.success_conditions for spec in specs)


def test_candidate_login_uses_runtime_secrets_and_stops_on_human_verification(
    tmp_path: Path,
) -> None:
    visible = visible_elements(missing={AUTHENTICATED})
    visible.discard("jushuitan.erp.login.human_verification_marker")
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
    assert get_element(SUBMIT).locator is None
