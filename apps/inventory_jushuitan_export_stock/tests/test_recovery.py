from __future__ import annotations

from pathlib import Path

import pytest

from rpa_core.browser import FakeBrowserActions
from rpa_core.runtime import Runner, StepRunError

from .helpers import (
    ACCOUNT_IDENTITY_ELEMENT_ID,
    FIXTURE_BRAND,
    FIXTURE_IDENTITY,
    make_browser,
    make_context,
    make_program,
    visible_elements,
)


@pytest.mark.parametrize(
    ("failed_step", "missing_element", "include_download", "previous_action"),
    [
        (
            "S003",
            "jushuitan.erp.product_stock.brand_selector",
            True,
            "jushuitan.erp.inventory.product_stock_entry",
        ),
        (
            "S004",
            "jushuitan.erp.product_stock.result_row",
            True,
            "jushuitan.erp.product_stock.reset_button",
        ),
        (
            "S005",
            None,
            False,
            "jushuitan.erp.product_stock.search_button",
        ),
    ],
)
def test_failed_tail_steps_resume_without_repeating_succeeded_steps(
    tmp_path: Path,
    failed_step: str,
    missing_element: str | None,
    include_download: bool,
    previous_action: str,
) -> None:
    run_dir = tmp_path / "runs" / f"resume-{failed_step.lower()}"
    first_browser = make_browser(
        run_dir,
        missing={missing_element} if missing_element else None,
        include_download=include_download,
    )
    first_context = make_context(run_dir, first_browser)
    with pytest.raises(StepRunError) as caught:
        Runner(sleep=lambda _: None).run(make_program(), first_context)
    assert caught.value.step_id == failed_step

    resumed_browser = make_browser(run_dir)
    resumed_context = make_context(run_dir, resumed_browser)
    result = Runner(sleep=lambda _: None).resume(make_program(), resumed_context)

    assert result.status == "succeeded"
    assert failed_step in result.completed_steps
    assert previous_action not in {
        record.element_id
        for record in resumed_browser.actions
        if record.action in {"click", "select", "download"}
    }


class RevealOnClickBrowser(FakeBrowserActions):
    """A page whose destination marker only appears once its entry is clicked.

    The static fake cannot express "navigation changes the page", which is
    exactly the property resume depends on.
    """

    def __init__(self, *args, reveals: dict[str, str], **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._reveals = reveals
        self._revealed: set[str] = set()

    def click(self, element) -> None:
        super().click(element)
        revealed = self._reveals.get(element.id)
        if revealed is not None:
            self._revealed.add(revealed)

    def exists(self, element, *, timeout: float = 0.0) -> bool:
        if element.id in self._revealed:
            return True
        return super().exists(element, timeout=timeout)


def test_resume_replays_navigation_when_the_page_is_no_longer_there(
    tmp_path: Path,
) -> None:
    """The production failure: succeeded navigation was skipped, so the steps
    after it had no page to stand on. S001 still holds and is skipped; S002 no
    longer holds and is replayed."""

    run_dir = tmp_path / "runs" / "resume-off-page"
    first_browser = make_browser(
        run_dir,
        missing={"jushuitan.erp.product_stock.brand_selector"},
    )
    with pytest.raises(StepRunError) as caught:
        Runner(sleep=lambda _: None).run(make_program(), make_context(run_dir, first_browser))
    assert caught.value.step_id == "S003"

    # Resume against a page that is no longer on product stock.
    resumed_browser = RevealOnClickBrowser(
        run_dir=run_dir,
        visible_element_ids=visible_elements(
            missing={"jushuitan.erp.product_stock.page_marker"}
        ),
        downloads=dict(make_browser(run_dir).downloads),
        text_values={
            ACCOUNT_IDENTITY_ELEMENT_ID: FIXTURE_IDENTITY,
            "jushuitan.erp.product_stock.brand_selected_option": FIXTURE_BRAND,
        },
        reveals={
            "jushuitan.erp.inventory.product_stock_entry": (
                "jushuitan.erp.product_stock.page_marker"
            )
        },
    )
    result = Runner(sleep=lambda _: None).resume(
        make_program(), make_context(run_dir, resumed_browser)
    )

    assert result.status == "succeeded"
    clicked = [
        record.element_id
        for record in resumed_browser.actions
        if record.action == "click"
    ]
    # S002 could not prove it still held, so its navigation was replayed...
    assert "jushuitan.erp.inventory.product_stock_entry" in clicked
    assert "S002" in result.completed_steps
    # ...while S001 still held and was left alone.
    assert "jushuitan.erp.navigation.inventory_module" not in clicked
    assert "S001" in result.skipped_steps


def test_prepare_is_satisfied_on_an_already_authenticated_page(tmp_path: Path) -> None:
    """A satisfied session must be reported without navigating anywhere."""

    run_dir = tmp_path / "runs" / "prepare-satisfied"
    browser = make_browser(run_dir)
    context = make_context(run_dir, browser)

    assert make_program().prepare_is_satisfied(context) is True
    assert [record.action for record in browser.actions if record.action == "open"] == []


def test_prepare_is_not_satisfied_when_the_session_marker_is_absent(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "runs" / "prepare-unsatisfied"
    browser = make_browser(
        run_dir,
        missing={"jushuitan.erp.shell.authenticated_marker"},
    )

    assert make_program().prepare_is_satisfied(make_context(run_dir, browser)) is False


def test_prepare_is_not_satisfied_when_another_account_is_logged_in(
    tmp_path: Path,
) -> None:
    """Being logged in is not enough; it has to be the authorized account.

    Skipping prepare here would hand the whole run to the wrong account without
    ever performing the identity check that prepare exists to enforce.
    """

    run_dir = tmp_path / "runs" / "prepare-wrong-account"
    browser = FakeBrowserActions(
        run_dir=run_dir,
        visible_element_ids=visible_elements(),
        text_values={ACCOUNT_IDENTITY_ELEMENT_ID: "somebody-else"},
    )

    assert make_program().prepare_is_satisfied(make_context(run_dir, browser)) is False
