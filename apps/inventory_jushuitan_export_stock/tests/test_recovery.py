from __future__ import annotations

from pathlib import Path

import pytest

from rpa_core.runtime import Runner, StepRunError

from .helpers import make_browser, make_context, make_program


@pytest.mark.parametrize(
    ("failed_step", "missing_element", "include_download", "previous_action"),
    [
        (
            "S003",
            "jushuitan.erp.product_stock.brand_selected_marker",
            True,
            "jushuitan.erp.inventory.product_stock_entry",
        ),
        (
            "S004",
            "jushuitan.erp.product_stock.filter_applied_marker",
            True,
            "jushuitan.erp.product_stock.brand_selector",
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
