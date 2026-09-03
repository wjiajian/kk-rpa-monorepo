from __future__ import annotations

from pathlib import Path

from rpa_core.runtime import Runner

from .helpers import make_browser, make_context, make_program


def test_fake_browser_runs_prepare_and_s001_through_s005_in_order(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "flow-001"
    browser = make_browser(run_dir)
    context = make_context(run_dir, browser)

    result = Runner(sleep=lambda _: None).run(make_program(), context)

    assert result.status == "succeeded"
    assert result.completed_steps == ("S001", "S002", "S003", "S004", "S005")
    assert result.outputs["S005"]["size_bytes"] > 0
    assert str(result.outputs["S005"]["sha256"]).startswith("sha256:")
    ordered_actions = [
        (record.action, record.element_id)
        for record in browser.actions
        if record.action in {"click", "select", "download"}
    ]
    assert ordered_actions == [
        ("click", "jushuitan.erp.navigation.inventory_module"),
        ("click", "jushuitan.erp.inventory.product_stock_entry"),
        ("click", "jushuitan.erp.product_stock.reset_button"),
        ("select", "jushuitan.erp.product_stock.brand_selector"),
        ("select", "jushuitan.erp.product_stock.brand_selector"),
        ("click", "jushuitan.erp.product_stock.search_button"),
        ("select", "jushuitan.erp.product_stock.brand_selector"),
        ("select", "jushuitan.erp.product_stock.brand_selector"),
        ("click", "jushuitan.erp.product_stock.export_menu"),
        ("download", "jushuitan.erp.product_stock.export_stock_option"),
    ]
    assert [record.action for record in browser.actions].count("open") == 1
    assert browser.current_url == "https://www.erp321.com/login.aspx"
    assert not any(record.element_id == "jushuitan.erp.login.account_input" for record in browser.actions)
