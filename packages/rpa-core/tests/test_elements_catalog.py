"""elements.toml loading and the expect_count assertion."""

from __future__ import annotations

import pytest

from rpa_core.elements import (
    ElementCatalogError,
    ExpectedCount,
    check_element_expectations,
    element_specs,
    load_element_catalog,
    override_element_locators,
)


CATALOG = """
schema_version = 2

[elements."demo.page.export"]
name         = "导出按钮"
page         = "demo"
locator      = "xpath://button[normalize-space(.)='导出']"
expect_count = 1
check_at     = "start"

[elements."demo.page.rows"]
name         = "结果行"
page         = "demo"
locator      = "css:table tbody tr"
frame        = "css:iframe[src*='/demo']"
expect_count = ">0"
check_at     = "start"

[elements."demo.page.body"]
name               = "页面正文"
page               = "demo"
locator            = "xpath://body"
expect_count       = 1
check_at           = "start"
assertion_strength = "weak"
note               = "恒能匹配，只有内容比对有区分力"
"""


def _write(tmp_path, text=CATALOG):
    path = tmp_path / "elements.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_catalog_loads_specs_frames_and_expectations(tmp_path):
    entries = load_element_catalog(_write(tmp_path))

    assert set(entries) == {"demo.page.export", "demo.page.rows", "demo.page.body"}
    rows = entries["demo.page.rows"]
    assert rows.spec.frame_locator is not None
    assert str(rows.expect) == ">0"
    assert entries["demo.page.body"].weak_assertion is True
    assert entries["demo.page.export"].weak_assertion is False
    assert set(element_specs(entries)) == set(entries)


@pytest.mark.parametrize(
    ("expression", "actual", "holds"),
    [
        (1, 1, True),
        (1, 2, False),
        (">0", 21, True),
        (">0", 0, False),
        (">=2", 2, True),
        (">=2", 1, False),
        (0, 0, True),
        (0, 1, False),
    ],
)
def test_expected_count_semantics(expression, actual, holds):
    assert ExpectedCount.parse(expression, "demo").holds(actual) is holds


def test_expect_count_is_required(tmp_path):
    text = """
schema_version = 2

[elements."demo.page.export"]
name    = "导出按钮"
page    = "demo"
locator = "css:#export"
"""
    with pytest.raises(ElementCatalogError, match="expect_count is required"):
        load_element_catalog(_write(tmp_path, text))


def test_unknown_keys_are_rejected(tmp_path):
    """V1 metadata such as status/version must not silently survive."""

    text = CATALOG + '\nstatus = "verified"\n'
    with pytest.raises(ElementCatalogError, match="unknown keys"):
        load_element_catalog(_write(tmp_path, text))


def test_bad_expect_count_is_rejected(tmp_path):
    with pytest.raises(ElementCatalogError, match="expect_count must look like"):
        load_element_catalog(_write(tmp_path, CATALOG.replace('expect_count = ">0"', 'expect_count = "many"')))


def test_negative_expect_count_is_rejected():
    with pytest.raises(ElementCatalogError, match="must not be negative"):
        ExpectedCount.parse(-1, "demo")


def test_bad_assertion_strength_is_rejected(tmp_path):
    text = CATALOG.replace('assertion_strength = "weak"', 'assertion_strength = "maybe"')
    with pytest.raises(ElementCatalogError, match="assertion_strength"):
        load_element_catalog(_write(tmp_path, text))


def test_wrong_schema_version_is_rejected(tmp_path):
    with pytest.raises(ElementCatalogError, match="schema_version"):
        load_element_catalog(_write(tmp_path, CATALOG.replace("schema_version = 2", "schema_version = 1")))


def test_missing_file_is_reported(tmp_path):
    with pytest.raises(ElementCatalogError, match="cannot read element catalog"):
        load_element_catalog(tmp_path / "absent.toml")


def test_locator_may_be_omitted_for_an_uncaptured_element(tmp_path):
    text = CATALOG.replace('locator      = "xpath://button[normalize-space(.)=\'导出\']"\n', "")
    entries = load_element_catalog(_write(tmp_path, text))
    assert entries["demo.page.export"].spec.is_resolved is False


# ---------------------------------------------------------------------------
# check_element_expectations — the repair report that justifies the catalog
# ---------------------------------------------------------------------------


class _CountingBrowser:
    def __init__(self, counts, failing=()):
        self.counts = counts
        self.failing = set(failing)

    def count(self, element, *, timeout: float = 0.0) -> int:
        if element.id in self.failing:
            raise RuntimeError("frame is gone")
        return self.counts.get(element.id, 0)


def _entries(tmp_path):
    return load_element_catalog(_write(tmp_path))


def test_expectations_hold_on_a_healthy_page(tmp_path):
    checks = check_element_expectations(
        _CountingBrowser(
            {"demo.page.export": 1, "demo.page.rows": 21, "demo.page.body": 1}
        ),
        _entries(tmp_path),
        stage="start",
    )

    by_id = {item.element_id: item for item in checks}
    assert by_id["demo.page.export"].symbol == "OK"
    assert by_id["demo.page.rows"].actual == 21 and by_id["demo.page.rows"].ok
    # A passing weak assertion is still surfaced, not silently accepted.
    assert by_id["demo.page.body"].symbol == "WEAK"


def test_a_broken_locator_names_the_single_entry_to_repair(tmp_path):
    checks = check_element_expectations(
        _CountingBrowser({"demo.page.export": 0, "demo.page.rows": 21, "demo.page.body": 1}),
        _entries(tmp_path),
        stage="start",
    )

    failed = [item for item in checks if not item.ok]
    assert [item.element_id for item in failed] == ["demo.page.export"]
    assert "失效" in failed[0].detail
    assert "demo.page.export" in failed[0].render()


def test_a_lookup_error_is_reported_without_aborting_the_sweep(tmp_path):
    checks = check_element_expectations(
        _CountingBrowser(
            {"demo.page.rows": 21, "demo.page.body": 1}, failing={"demo.page.export"}
        ),
        _entries(tmp_path),
        stage="start",
    )

    assert len(checks) == 3
    broken = next(item for item in checks if item.element_id == "demo.page.export")
    assert not broken.ok and "RuntimeError" in broken.detail


def test_an_uncaptured_locator_is_reported_as_a_failure(tmp_path):
    text = CATALOG.replace('locator      = "xpath://button[normalize-space(.)=\'导出\']"\n', "")
    checks = check_element_expectations(
        _CountingBrowser({"demo.page.rows": 21, "demo.page.body": 1}),
        load_element_catalog(_write(tmp_path, text)),
        stage="start",
    )

    export = next(item for item in checks if item.element_id == "demo.page.export")
    assert not export.ok and "尚未捕获" in export.detail


def test_entries_from_other_stages_are_skipped_not_reported(tmp_path):
    """A login input matching zero after login is correct, not broken.

    The first real verify-elements run reported seven entries as failed when
    nothing was broken, purely because every expectation was checked at one
    arbitrary moment. Stages exist to make the report trustworthy.
    """

    text = CATALOG.replace(
        '[elements."demo.page.body"]\nname               = "页面正文"',
        '[elements."demo.page.body"]\nname               = "页面正文"',
    ).replace('check_at           = "start"', 'check_at           = "later"', 1)
    entries = load_element_catalog(_write(tmp_path, text))

    browser = _CountingBrowser({"demo.page.export": 1, "demo.page.rows": 21})
    start = check_element_expectations(browser, entries, stage="start")
    later = check_element_expectations(browser, entries, stage="later")

    assert {item.element_id for item in start} == {"demo.page.export", "demo.page.rows"}
    assert [item.element_id for item in later] == ["demo.page.body"]
    assert all(item.ok for item in start)


def test_check_at_is_required(tmp_path):
    text = """
schema_version = 2

[elements."demo.page.export"]
name         = "导出按钮"
page         = "demo"
locator      = "css:#export"
expect_count = 1
"""
    with pytest.raises(ElementCatalogError, match="check_at is required"):
        load_element_catalog(_write(tmp_path, text))


@pytest.mark.parametrize("changes", [{"expect_count": 0}, {"check_at": "elsewhere"}, {"locator": ""}, {"locator": 3}])
def test_temporary_overrides_cannot_replace_assertions_or_invalid_locators(tmp_path, changes):
    elements = element_specs(_entries(tmp_path))
    with pytest.raises(ElementCatalogError):
        override_element_locators(elements, {"demo.page.export": changes})


def test_temporary_frame_and_locator_overrides_preserve_catalog_metadata(tmp_path):
    entries = _entries(tmp_path)
    original = element_specs(entries)
    patched = override_element_locators(original, {"demo.page.rows": {"frame": None, "locator": "#new-rows"}})
    assert patched["demo.page.rows"].frame_locator is None
    assert original["demo.page.rows"].frame_locator is not None
    assert str(entries["demo.page.rows"].expect) == ">0"
    assert entries["demo.page.rows"].check_at == "start"
    with pytest.raises(ElementCatalogError, match="unknown"):
        override_element_locators(original, {"unknown": {"locator": "#new"}})
