import json
from pathlib import Path

import pytest
from inventory_jushuitan_export_stock.program import (
    APPLICATION,
    build_program,
    build_test_context,
)
from rpa_core.runtime import Runner, StepRunError
from rpa_core.verification import (
    Counterexample,
    CounterexampleContractError,
    FakeState,
    assert_steps_are_falsifiable,
)


def context(tmp_path, case=None):
    return build_test_context(build_program().steps[0], case, tmp_path)


def test_complete_flow_downloads_to_configured_directory(tmp_path):
    ctx = context(tmp_path)
    result = Runner().run(build_program(), ctx)
    assert result.completed_steps == ("S000", "S001", "S002", "S003", "S004", "S005")
    assert result.status == "succeeded"
    artifact = Path(result.outputs["S005"]["download_path"])
    assert artifact.parent == ctx.download_dir
    assert artifact.stat().st_size > 0
    report = json.loads((ctx.run_dir / "result.json").read_text())
    assert report["status"] == "succeeded"
    assert not (ctx.run_dir / "checkpoint.json").exists()


def test_normal_and_bad_scenarios_use_the_same_fixture(tmp_path):
    serial = [0]

    def factory(step, case):
        serial[0] += 1
        return build_test_context(step, case, tmp_path / str(serial[0]))

    assert_steps_are_falsifiable(build_program().steps, factory)


@pytest.mark.parametrize("index", range(6))
def test_every_verifier_cannot_be_replaced_with_constant_true(tmp_path, index):
    step = build_program().steps[index]
    step.verify = lambda ctx, result: True
    with pytest.raises(CounterexampleContractError, match="did not fail"):
        assert_steps_are_falsifiable(
            [step], lambda step, case: build_test_context(step, case, tmp_path)
        )


def test_failed_download_can_be_restarted_from_the_beginning(tmp_path):
    failed = context(
        tmp_path / "first",
        Counterexample("download absent", FakeState(downloads_available=False)),
    )
    with pytest.raises(StepRunError) as caught:
        Runner().run(build_program(), failed)
    assert caught.value.step_id == "S005"
    fresh = context(tmp_path / "second")
    result = Runner().run(build_program(), fresh)
    assert result.completed_steps == ("S000", "S001", "S002", "S003", "S004", "S005")
    assert result.status == "succeeded"


def test_empty_or_missing_download_is_rejected_after_the_action(tmp_path):
    ctx = context(tmp_path)
    step = build_program().step("S005")
    result = step.execute(ctx)
    assert step.verify(ctx, result)
    target = Path(result["download_path"])
    target.write_bytes(b"")
    assert not step.verify(ctx, result)
    target.unlink()
    assert not step.verify(ctx, result)


def test_stage_validation_reaches_all_declared_stages(tmp_path):
    from rpa_core.elements import load_element_catalog

    ctx = context(tmp_path)
    result = APPLICATION.verify_element_stages(
        ctx, load_element_catalog(APPLICATION.app_dir / "elements.toml")
    )
    assert result["ok"], result
    assert result["unreached_stages"] == []


from inventory_jushuitan_export_stock.steps import (
    BRAND_SELECTED,
    BRAND_SELECTOR,
    EXPORT_MENU,
    EXPORT_OPTION,
    NAV_INVENTORY,
    PRODUCT_STOCK_ENTRY,
    RESET_BUTTON,
    SEARCH_BUTTON,
)


def test_inventory_actions_keep_the_verified_business_order(tmp_path):
    ctx = context(tmp_path)
    Runner().run(build_program(), ctx)
    actions = [
        (record.action, record.element_id)
        for record in ctx.browser.actions
        if record.action in {"click", "select", "download"}
    ]
    assert actions == [
        ("click", NAV_INVENTORY),
        ("click", PRODUCT_STOCK_ENTRY),
        ("click", RESET_BUTTON),
        ("select", BRAND_SELECTOR),
        ("select", BRAND_SELECTOR),
        ("click", SEARCH_BUTTON),
        ("select", BRAND_SELECTOR),
        ("select", BRAND_SELECTOR),
        ("click", EXPORT_MENU),
        ("download", EXPORT_OPTION),
    ]
    assert [record.action for record in ctx.browser.actions].count("open") == 1


def test_download_verification_rereads_the_selected_brand(tmp_path):
    ctx = context(tmp_path)
    step = build_program().step("S005")
    result = step.execute(ctx)
    ctx.browser._text_lists[BRAND_SELECTED] = ["OTHER_BRAND"]
    assert step.verify(ctx, result) is False


def test_store_config_supports_a_custom_download_directory(tmp_path):
    from inventory_jushuitan_export_stock.models import load_store_config

    sample = (APPLICATION.app_dir / "config" / "stores.example.toml").read_text()
    path = tmp_path / "stores.toml"
    path.write_text(sample.replace("../../runs/downloads", "custom-output"))
    assert load_store_config(path, "STORE_001").download_directory == "custom-output"


def test_agent_resumes_export_with_original_brand_after_local_config_changes(tmp_path):
    from dataclasses import replace

    failed = context(
        tmp_path / "first",
        Counterexample("no download", FakeState(downloads_available=False)),
    )
    with pytest.raises(StepRunError):
        Runner().run(build_program(), failed)
    previous = json.loads((failed.run_dir / "result.json").read_text())
    resumed = context(tmp_path / "resume")
    resumed.run_id = "resumed-run"
    resumed.inputs["brand_value"] = "OTHER_BRAND"
    resumed.metadata["store_config"] = replace(
        resumed.metadata["store_config"], brand_value="OTHER_BRAND"
    )
    resumed.browser.download_dir = Path(previous["download_dir"])
    result = Runner().run(build_program(), resumed, previous=previous, from_step="S005")
    assert result.status == "succeeded"
    assert result.outputs["S005"]["requested_brand"] == "BRAND_001"
    assert result.completed_steps == ("S000", "S001", "S002", "S003", "S004", "S005")
    assert not any(
        action.element_id
        in (NAV_INVENTORY, PRODUCT_STOCK_ENTRY, RESET_BUTTON, SEARCH_BUTTON)
        for action in resumed.browser.actions
    )
    assert Path(result.outputs["S005"]["download_path"]).parent == failed.download_dir
