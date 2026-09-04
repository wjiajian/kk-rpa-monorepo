"""The falsifiability harness — the framework's only mandatory constraint."""

from __future__ import annotations

from pathlib import Path

import pytest

from rpa_core.browser import ElementSpec, FakeBrowserActions, Locator
from rpa_core.verification import (
    Counterexample,
    CounterexampleContractError,
    FakeState,
    assert_steps_are_falsifiable,
    check_step_counterexamples,
)


TARGET = ElementSpec(
    id="demo.page.rows",
    name="结果行",
    page="demo",
    locator=Locator("css:table tbody tr"),
)
SELECTED = ElementSpec(
    id="demo.page.selected",
    name="已选项",
    page="demo",
    locator=Locator("css:.chip"),
)


def _context(tmp_path: Path, case: Counterexample):
    browser = FakeBrowserActions(
        run_dir=tmp_path,
        visible_element_ids=set({TARGET.id, SELECTED.id}) - set(case.state.hidden),
        text_values={SELECTED.id: "目标"},
        counts=dict(case.state.counts),
        text_lists={key: tuple(value) for key, value in case.state.texts.items()},
    )
    return type("Ctx", (), {"browser": browser, "metadata": dict(case.metadata)})()


class _HonestStep:
    """Reads state back from the page, so a fake state can falsify it."""

    spec = type("Spec", (), {"step_id": "S-honest"})()

    def execute(self, context):
        return {
            "rows": context.browser.count(TARGET),
            "selected": list(context.browser.texts(SELECTED)),
        }

    def verify(self, context, result):
        return result["rows"] > 0 and result["selected"] == ["目标"]

    def counterexamples(self):
        yield Counterexample("没有结果行", FakeState(counts={TARGET.id: 0}))
        yield Counterexample("选中项为空", FakeState(texts={SELECTED.id: ()}))


class _FakeExecutorStep:
    """Echoes its own inputs; a result-level counterexample would not catch it."""

    spec = type("Spec", (), {"step_id": "S-fake-executor"})()

    def execute(self, context):
        context.browser.count(TARGET)
        return {"selected": True}

    def verify(self, context, result):
        return bool(result["selected"])

    def counterexamples(self):
        yield Counterexample("选中项为空", FakeState(texts={SELECTED.id: ()}))


def test_honest_step_passes(tmp_path):
    results = check_step_counterexamples(
        _HonestStep(), lambda case: _context(tmp_path, case)
    )
    assert [item.ok for item in results] == [True, True]


def test_fake_executor_is_caught(tmp_path):
    with pytest.raises(CounterexampleContractError, match="did not fail"):
        assert_steps_are_falsifiable(
            [_FakeExecutorStep()], lambda step, case: _context(tmp_path, case)
        )


def test_execute_raising_counts_as_rejection(tmp_path):
    class RaisingStep(_HonestStep):
        spec = type("Spec", (), {"step_id": "S-raise"})()

        def counterexamples(self):
            yield Counterexample("目标元素消失", FakeState(hidden=(SELECTED.id,)))

        def execute(self, context):
            context.browser.click(SELECTED)
            return {"rows": 1, "selected": ["目标"]}

    results = check_step_counterexamples(
        RaisingStep(), lambda case: _context(tmp_path, case)
    )
    assert results[0].ok
    assert "raised" in results[0].reason


def test_step_without_counterexamples_is_rejected(tmp_path):
    class Bare(_HonestStep):
        spec = type("Spec", (), {"step_id": "S-bare"})()

        def counterexamples(self):
            return ()

    with pytest.raises(CounterexampleContractError, match="no counterexample"):
        check_step_counterexamples(Bare(), lambda case: _context(tmp_path, case))


def test_duplicate_counterexample_labels_are_rejected(tmp_path):
    class Duplicated(_HonestStep):
        spec = type("Spec", (), {"step_id": "S-dup"})()

        def counterexamples(self):
            yield Counterexample("重复", FakeState(counts={TARGET.id: 0}))
            yield Counterexample("重复", FakeState(texts={SELECTED.id: ()}))

    with pytest.raises(CounterexampleContractError, match="repeats counterexample"):
        check_step_counterexamples(Duplicated(), lambda case: _context(tmp_path, case))


def test_counterexample_must_change_something():
    with pytest.raises(ValueError, match="changes nothing"):
        Counterexample("什么都不改")

    # A metadata-only counterexample is legitimate: some failures are input-driven.
    assert Counterexample("输入非法", metadata={"brand": ""}).metadata == {"brand": ""}

    assert not Counterexample(
        "新标签页未出现",
        FakeState(new_tabs_available=False),
    ).state.new_tabs_available


def test_empty_label_is_rejected():
    with pytest.raises(ValueError, match="label must not be empty"):
        Counterexample("   ", FakeState(counts={TARGET.id: 0}))
