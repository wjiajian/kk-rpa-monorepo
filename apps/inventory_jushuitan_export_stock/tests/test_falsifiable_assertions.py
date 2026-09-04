"""The framework's only mandatory constraint, enforced for this application.

Every step must supply at least one fake page state that makes it fail. A
``verify()`` no state can drive to ``False`` is not an assertion — which is
exactly how V1's S003 and S004 passed review while never checking anything.
"""

from __future__ import annotations

import pytest

from rpa_core.verification import (
    Counterexample,
    CounterexampleContractError,
    FakeState,
    assert_steps_are_falsifiable,
    check_step_counterexamples,
)

from .helpers import (
    BRAND_SELECTED,
    counterexample_context,
    make_browser,
    make_context,
    make_program,
)


def test_every_step_assertion_is_falsifiable(tmp_path):
    program = make_program()
    assert_steps_are_falsifiable(
        program.steps,
        lambda step, case: counterexample_context(tmp_path, case),
    )


def test_every_step_declares_at_least_one_counterexample():
    program = make_program()
    for step in program.steps:
        assert list(step.counterexamples()), (
            f"{step.spec.step_id} declares no counterexample"
        )


@pytest.mark.parametrize("step_index", range(5))
def test_each_counterexample_is_actually_rejected(tmp_path, step_index):
    step = make_program().steps[step_index]
    results = check_step_counterexamples(
        step,
        lambda case: counterexample_context(tmp_path, case),
    )
    survivors = [item for item in results if not item.ok]
    assert not survivors, (
        f"{step.spec.step_id}: these states did not fail — "
        + ", ".join(item.label for item in survivors)
    )


def test_happy_path_still_verifies(tmp_path):
    """The counterexamples must not be satisfied by a step that always fails."""

    program = make_program()
    context = make_context(tmp_path, make_browser(tmp_path))
    for step in program.steps:
        result = step.execute(context)
        assert step.verify(context, result), (
            f"{step.spec.step_id} failed on the happy path"
        )


def test_vacuous_assertion_is_reported(tmp_path):
    """A step whose verify() ignores the page must be caught by the harness."""

    class AlwaysTrueStep:
        spec = type("Spec", (), {"step_id": "SXXX"})()

        def execute(self, context):
            return {"done": True}

        def verify(self, context, result):
            return bool(result["done"])

        def counterexamples(self):
            yield Counterexample("页面上什么都没有", FakeState(hidden=("anything",)))

    with pytest.raises(CounterexampleContractError, match="did not fail"):
        assert_steps_are_falsifiable(
            [AlwaysTrueStep()],
            lambda step, case: counterexample_context(tmp_path, case),
        )


def test_step_without_counterexamples_is_rejected(tmp_path):
    class NoCounterexampleStep:
        spec = type("Spec", (), {"step_id": "SYYY"})()

        def execute(self, context):
            return {}

        def verify(self, context, result):
            return True

        def counterexamples(self):
            return ()

    with pytest.raises(CounterexampleContractError, match="no counterexample"):
        check_step_counterexamples(
            NoCounterexampleStep(),
            lambda case: counterexample_context(tmp_path, case),
        )


def test_counterexample_that_changes_nothing_is_rejected():
    with pytest.raises(ValueError, match="changes nothing"):
        Counterexample("空反例")


# ---------------------------------------------------------------------------
# Regression guards: the two V1 defects this mechanism exists to catch.
# If either of these ever stops raising, the harness has lost its teeth.
# ---------------------------------------------------------------------------


def test_v1_fake_executor_would_be_rejected(tmp_path):
    """V1 S003 echoed its input instead of reading the selection back."""

    from inventory_jushuitan_export_stock.steps import (
        BRAND_SELECTOR,
        RESET_BUTTON,
        element,
        store,
    )

    class V1SelectBrand:
        spec = type("Spec", (), {"step_id": "S003-v1"})()

        def execute(self, context):
            brand = store(context).brand_value
            context.browser.click(element(context, RESET_BUTTON))
            context.browser.select(element(context, BRAND_SELECTOR), brand)
            return {"selected_brand": brand, "selection_visible": True}

        def verify(self, context, result):
            return bool(result["selected_brand"]) and bool(result["selection_visible"])

        def counterexamples(self):
            yield Counterexample(
                "品牌未被选中（回读为空）",
                FakeState(texts={BRAND_SELECTED: ()}),
            )

    with pytest.raises(CounterexampleContractError, match="did not fail"):
        assert_steps_are_falsifiable(
            [V1SelectBrand()],
            lambda step, case: counterexample_context(tmp_path, case),
        )


def test_v1_fake_verifier_would_be_rejected(tmp_path):
    """V1 S004 asserted a marker that is present before any filter is applied.

    Measured on the live page 2026-09-03: ``css:table tbody`` matched 1 and
    ``css:table tbody tr`` matched 21 both before and after clicking Search.
    """

    from inventory_jushuitan_export_stock.steps import (
        RESULT_ROW,
        SEARCH_BUTTON,
        element,
    )

    class V1Search:
        spec = type("Spec", (), {"step_id": "S004-v1"})()

        def execute(self, context):
            context.browser.click(element(context, SEARCH_BUTTON))
            # Stands in for the always-present "css:table tbody" marker.
            visible = context.browser.exists(element(context, RESULT_ROW), timeout=1.0)
            return {"filter_applied": visible}

        def verify(self, context, result):
            return bool(result["filter_applied"])

        def counterexamples(self):
            yield Counterexample(
                "筛选后没有任何结果行",
                FakeState(counts={RESULT_ROW: 0}),
            )
            yield Counterexample(
                "搜索后平台把品牌选择重置了",
                FakeState(texts={BRAND_SELECTED: ()}),
            )

    with pytest.raises(CounterexampleContractError, match="did not fail"):
        assert_steps_are_falsifiable(
            [V1Search()],
            lambda step, case: counterexample_context(tmp_path, case),
        )
