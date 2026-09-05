from types import SimpleNamespace

import pytest
from rpa_core.browser import ElementSpec, FakeBrowserActions, Locator
from rpa_core.verification import (
    Counterexample,
    CounterexampleContractError,
    FakeState,
    assert_steps_are_falsifiable,
)

TARGET = ElementSpec("demo.page.rows", "Rows", "Demo", locator=Locator("css:tr"))
SELECTED = ElementSpec(
    "demo.page.selected", "Selected", "Demo", locator=Locator("css:.chip")
)


def context(tmp_path, case):
    state = case.state if case else FakeState()
    browser = FakeBrowserActions(
        tmp_path,
        visible_element_ids={TARGET.id, SELECTED.id} - set(state.hidden),
        counts=dict(state.counts),
        text_lists={SELECTED.id: ["expected"], **state.texts},
    )
    return SimpleNamespace(browser=browser)


class HonestStep:
    spec = SimpleNamespace(step_id="S1")

    def execute(self, ctx):
        return {
            "selected": ctx.browser.texts(SELECTED),
            "rows": ctx.browser.count(TARGET),
        }

    def verify(self, ctx, result):
        return result["rows"] > 0 and result["selected"] == ["expected"]

    def counterexamples(self):
        yield Counterexample("no rows", FakeState(counts={TARGET.id: 0}))
        yield Counterexample(
            "wrong selection", FakeState(texts={SELECTED.id: ("other",)})
        )


def check(step, tmp_path):
    assert_steps_are_falsifiable([step], lambda _, case: context(tmp_path, case))


def test_healthy_baseline_and_bad_results(tmp_path):
    check(HonestStep(), tmp_path)


@pytest.mark.parametrize("value", [True, False])
def test_constant_verifiers_are_rejected(tmp_path, value):
    step = HonestStep()
    step.verify = lambda ctx, result: value
    with pytest.raises(CounterexampleContractError):
        check(step, tmp_path)


def test_echoing_inputs_without_reading_the_selection_is_rejected(tmp_path):
    step = HonestStep()
    step.execute = lambda ctx: {
        "rows": ctx.browser.count(TARGET),
        "selected": ["expected"],
    }
    with pytest.raises(CounterexampleContractError, match="did not fail"):
        check(step, tmp_path)


def test_accidental_error_does_not_count_as_a_counterexample(tmp_path):
    class Broken(HonestStep):
        def execute(self, ctx):
            if not ctx.browser.count(TARGET):
                raise NameError("bug")
            return super().execute(ctx)

    with pytest.raises(
        CounterexampleContractError, match="unexpected execute error NameError"
    ):
        check(Broken(), tmp_path)


def test_verifier_exception_is_a_test_failure(tmp_path):
    class Broken(HonestStep):
        def verify(self, ctx, result):
            if not result["rows"]:
                raise KeyError("bug")
            return super().verify(ctx, result)

    with pytest.raises(CounterexampleContractError, match="verifier raised KeyError"):
        check(Broken(), tmp_path)


def test_expected_execution_errors_cannot_replace_outcome_tests(tmp_path):
    class OnlyErrors(HonestStep):
        def execute(self, ctx):
            if not ctx.browser.count(TARGET):
                raise ValueError("missing rows")
            return super().execute(ctx)

        def counterexamples(self):
            yield Counterexample(
                "no rows", FakeState(counts={TARGET.id: 0}), expected_error=ValueError
            )

    with pytest.raises(CounterexampleContractError, match="needs an outcome"):
        check(OnlyErrors(), tmp_path)


def test_missing_and_duplicate_cases_are_rejected(tmp_path):
    step = HonestStep()
    step.counterexamples = lambda: ()
    with pytest.raises(CounterexampleContractError, match="no counterexample"):
        check(step, tmp_path)
    case = Counterexample("same", FakeState(counts={TARGET.id: 0}))
    step.counterexamples = lambda: (case, case)
    with pytest.raises(CounterexampleContractError, match="repeats"):
        check(step, tmp_path)


def test_post_execution_change_reaches_the_verifier(tmp_path):
    def remove_rows(ctx, result):
        ctx.browser._counts[TARGET.id] = 0

    step = HonestStep()
    step.verify = lambda ctx, result: ctx.browser.count(TARGET) > 0
    step.counterexamples = lambda: (
        Counterexample("result disappeared", after_execute=remove_rows),
    )
    check(step, tmp_path)
    step.verify = lambda ctx, result: True
    with pytest.raises(CounterexampleContractError, match="did not fail"):
        check(step, tmp_path)
