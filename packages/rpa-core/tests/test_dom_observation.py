from types import SimpleNamespace

import pytest
from DrissionPage._elements.chromium_element import ChromiumElement
from DrissionPage._pages.chromium_frame import ChromiumFrame

from rpa_core.drission_browser import DrissionBrowserActions


def node(xpath, *, tag="button", text="下载", displayed=True):
    # Exercise the pinned SDK's real xpath property without opening a browser.
    element = object.__new__(ChromiumElement)
    element._tag = tag
    element._states = SimpleNamespace(is_displayed=displayed)
    element._run_js = lambda *args, **kwargs: xpath
    element.attr = lambda key: "report" if key == "id" else None
    element.property = lambda name: text
    return element


def observe(tmp_path, nodes, **kwargs):
    body = SimpleNamespace(property=lambda name: "报表页面")
    tab = SimpleNamespace(url="https://business.test/reports", eles=lambda *a, **k: nodes,
                          ele=lambda *a, **k: body)
    return DrissionBrowserActions(tab, tmp_path).observe_dom(**kwargs)


@pytest.mark.parametrize("missing_xpath", [None, ""])
def test_missing_xpath_does_not_abort_other_observed_targets(tmp_path, missing_xpath):
    result = observe(tmp_path, [node(missing_xpath), node("/html/body/button[1]")])
    assert result["skipped_nodes"] == 1
    assert [n["locator"] for n in result["nodes"]] == ["xpath:/html/body/button[1]"]
    assert result["nodes"][0]["text"] == "下载"
    assert result["text"] == "报表页面"


def test_frame_can_be_observed_without_element_text_api(tmp_path):
    frame = object.__new__(ChromiumFrame)
    frame._frame_ele = node("/html/body/iframe[1]", tag="iframe")
    frame._states = SimpleNamespace(is_displayed=True)
    result = observe(tmp_path, [frame])
    assert result["nodes"][0]["tag"] == "iframe"
    assert result["nodes"][0]["locator"] == "xpath:/html/body/iframe[1]"
    assert result["nodes"][0]["text"] == ""


def test_observation_keeps_limits_and_does_not_read_field_values(tmp_path):
    result = observe(tmp_path, [node("/hidden", displayed=False),
        node("/input", tag="input", text="secret"), node("/textarea", tag="textarea", text="secret"),
        node("/button")], limit=2)
    assert len(result["nodes"]) == 2
    assert all(n["text"] == "" for n in result["nodes"])
    assert result["truncated"]
    assert "secret" not in str(result)


def test_dom_read_errors_are_not_reported_as_success(tmp_path):
    broken = node("/button")
    def fail(name):
        raise RuntimeError("fixture DOM failure")
    broken.property = fail
    with pytest.raises(RuntimeError, match="fixture DOM failure"):
        observe(tmp_path, [broken])
