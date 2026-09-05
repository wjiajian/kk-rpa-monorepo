"""Business steps for the inventory export program.

Every step owns three things: the browser work (``execute``), a falsifiable
success assertion (``verify``), and the fake page states that must make it fail
(``counterexamples``). The offline suite runs ``execute`` under each
counterexample and requires it to raise or ``verify`` to return false — an
assertion nothing can falsify is not an assertion.

The V1 versions of S003 and S004 are the reason this contract exists:

    # S003 — fake executor: echoed its input, never read the page back
    return {"selected_brand": brand_value, "selection_visible": True}

    # S004 — fake verifier: "css:table tbody" is present before any filter runs
    # (2026-09-03 measurement: 21 rows before search, 21 rows after)
    return {"filter_applied": browser.exists(filter_applied_marker)}

Both now read state back from the page instead.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from rpa_core.browser import (
    DownloadError,
    ElementActionError,
    ElementLookupError,
    ElementSpec,
)
from rpa_core.downloads import download_result_is_valid
from rpa_core.runtime import ExecutionContext, Step, StepSpec
from rpa_core.verification import Counterexample, FakeState

NAV_INVENTORY = "jushuitan.erp.navigation.inventory_module"
INVENTORY_MARKER = "jushuitan.erp.inventory.module_marker"
PRODUCT_STOCK_ENTRY = "jushuitan.erp.inventory.product_stock_entry"
PRODUCT_STOCK_MARKER = "jushuitan.erp.product_stock.page_marker"
RESET_BUTTON = "jushuitan.erp.product_stock.reset_button"
BRAND_SELECTOR = "jushuitan.erp.product_stock.brand_selector"
BRAND_SELECTED = "jushuitan.erp.product_stock.brand_selected_option"
SEARCH_BUTTON = "jushuitan.erp.product_stock.search_button"
RESULT_ROW = "jushuitan.erp.product_stock.result_row"
EXPORT_MENU = "jushuitan.erp.product_stock.export_menu"
EXPORT_OPTION = "jushuitan.erp.product_stock.export_stock_option"


def element(context: ExecutionContext, element_id: str) -> ElementSpec:
    catalog = context.services.get("elements")
    if not isinstance(catalog, Mapping):
        raise RuntimeError("execution context elements service is missing")
    spec = catalog.get(element_id)
    if not isinstance(spec, ElementSpec):
        raise RuntimeError(f"execution context element is missing: {element_id}")
    return spec


def _brand(context: ExecutionContext) -> str:
    value = context.inputs.get("brand_value")
    if not isinstance(value, str) or not value:
        raise ValueError("run inputs must contain brand_value")
    return value


def _normalize(value: str) -> str:
    """Fold width, case and whitespace so page text compares to configuration."""
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _brand_set(values: Iterable[str]) -> set[str]:
    return {_normalize(value) for value in values if _normalize(value)}


def _capture(context: ExecutionContext, name: str) -> None:
    try:
        context.browser.screenshot(name=name)
    except Exception:
        pass


class _NavigationStep(Step):
    """Click one entry point and confirm the destination marker is active."""

    entry_id: str
    marker_id: str
    output_key: str
    marker_timeout: float

    def execute(self, context: ExecutionContext) -> Mapping[str, object]:
        context.browser.click(element(context, self.entry_id))
        visible = context.browser.exists(
            element(context, self.marker_id), timeout=self.marker_timeout
        )
        return {self.output_key: visible}

    def verify(self, context: ExecutionContext, result: Any) -> bool:
        return (
            isinstance(result, Mapping)
            and bool(result.get(self.output_key))
            and context.browser.exists(element(context, self.marker_id), timeout=0.0)
        )

    def counterexamples(self) -> Iterable[Counterexample]:
        yield Counterexample(
            "点击后目标页标识未出现", FakeState(hidden=(self.marker_id,))
        )
        yield Counterexample(
            "入口元素不存在",
            FakeState(hidden=(self.entry_id,)),
            expected_error=ElementLookupError,
        )


class OpenInventoryModule(_NavigationStep):
    entry_id = NAV_INVENTORY
    marker_id = INVENTORY_MARKER
    output_key = "inventory_module_active"
    marker_timeout = 10.0


class OpenProductStock(_NavigationStep):
    entry_id = PRODUCT_STOCK_ENTRY
    marker_id = PRODUCT_STOCK_MARKER
    output_key = "product_stock_active"
    marker_timeout = 15.0


class SelectBrand(Step):
    def execute(self, context: ExecutionContext) -> Mapping[str, object]:
        brand = _brand(context)
        context.browser.click(element(context, RESET_BUTTON))
        context.browser.select(element(context, BRAND_SELECTOR), brand)
        selected = context.browser.texts(element(context, BRAND_SELECTED))
        return {"requested_brand": brand, "selected_brands": list(selected)}

    def verify(self, context: ExecutionContext, result: Any) -> bool:
        if not isinstance(result, Mapping):
            return False
        requested = _normalize(str(result.get("requested_brand", "")))
        configured = _normalize(_brand(context))
        selected = result.get("selected_brands")
        if not requested or requested != configured or (not isinstance(selected, list)):
            return False
        live_selected = context.browser.texts(element(context, BRAND_SELECTED))
        return _brand_set(selected) == {requested} and _brand_set(live_selected) == {
            requested
        }

    def counterexamples(self) -> Iterable[Counterexample]:
        yield Counterexample(
            "品牌未被选中（回读为空）", FakeState(texts={BRAND_SELECTED: ()})
        )
        yield Counterexample(
            "选中了另一个品牌", FakeState(texts={BRAND_SELECTED: ("其他品牌",)})
        )
        yield Counterexample(
            "选中了多个品牌",
            FakeState(texts={BRAND_SELECTED: ("其他品牌", "第二个品牌")}),
        )
        yield Counterexample(
            "重置按钮不存在",
            FakeState(hidden=(RESET_BUTTON,)),
            expected_error=ElementLookupError,
        )


class SearchInventory(Step):
    """Search and assert both declared success conditions.

    V1 declared "filtered result marker is visible" and "configured brand
    remains selected after search", then checked neither: the marker was
    ``css:table tbody`` (present before any filter) and the brand was re-selected
    rather than read back.
    """

    def execute(self, context: ExecutionContext) -> Mapping[str, object]:
        brand = _brand(context)
        selector = element(context, BRAND_SELECTOR)
        selected_target = element(context, BRAND_SELECTED)
        context.browser.select(selector, brand)
        context.browser.click(element(context, SEARCH_BUTTON))
        row_count = context.browser.count(element(context, RESULT_ROW), timeout=20.0)
        after_search = list(context.browser.texts(selected_target))
        context.browser.select(selector, brand)
        normalized = list(context.browser.texts(selected_target))
        return {
            "requested_brand": brand,
            "row_count": row_count,
            "brands_after_search": after_search,
            "brands_normalized": normalized,
        }

    def verify(self, context: ExecutionContext, result: Any) -> bool:
        if not isinstance(result, Mapping):
            return False
        requested = _normalize(str(result.get("requested_brand", "")))
        if not requested:
            return False
        try:
            row_count = int(result["row_count"])
        except (KeyError, TypeError, ValueError):
            return False
        after = result.get("brands_after_search")
        normalized = result.get("brands_normalized")
        if not isinstance(after, list) or not isinstance(normalized, list):
            return False
        live_rows = context.browser.count(element(context, RESULT_ROW), timeout=0.0)
        live_selected = context.browser.texts(element(context, BRAND_SELECTED))
        return (
            row_count > 0
            and _brand_set(after) == {requested}
            and (_brand_set(normalized) == {requested})
            and (live_rows > 0)
            and (_brand_set(live_selected) == {requested})
        )

    def counterexamples(self) -> Iterable[Counterexample]:
        yield Counterexample("筛选后没有任何结果行", FakeState(counts={RESULT_ROW: 0}))
        yield Counterexample(
            "搜索后平台把品牌选择重置了", FakeState(texts={BRAND_SELECTED: ()})
        )
        yield Counterexample(
            "搜索后选中集合变成了多个品牌",
            FakeState(texts={BRAND_SELECTED: ("其他品牌", "第二个品牌")}),
        )
        yield Counterexample(
            "搜索按钮不存在",
            FakeState(hidden=(SEARCH_BUTTON,)),
            expected_error=ElementLookupError,
        )


def _empty_download(context, result):
    Path(result["download_path"]).write_bytes(b"")


class ExportStock(Step):
    def execute(self, context: ExecutionContext) -> Mapping[str, object]:
        brand = _brand(context)
        filename = str(context.inputs["export_filename"])
        try:
            context.browser.select(element(context, BRAND_SELECTOR), brand)
            selected = list(context.browser.texts(element(context, BRAND_SELECTED)))
        except Exception:
            _capture(context, "s005-brand-normalise-failed.png")
            raise
        if _brand_set(selected) != {_normalize(brand)}:
            _capture(context, "s005-brand-verification-failed.png")
            raise ElementActionError(
                "configured brand is not the only selected brand before export"
            )
        context.browser.click(element(context, EXPORT_MENU))
        option = element(context, EXPORT_OPTION)
        if not context.browser.exists(option, timeout=5.0):
            _capture(context, "s005-export-option-missing.png")
            raise ElementLookupError(
                "export stock option is not visible after opening the menu"
            )
        try:
            reference = context.browser.download(option, filename=filename)
        except Exception:
            _capture(context, "s005-download-failed.png")
            raise
        return {
            "requested_brand": brand,
            "selected_brands": selected,
            "download_path": str(reference.path),
            "size_bytes": reference.size_bytes,
            "status": reference.status,
        }

    def verify(self, context: ExecutionContext, result: Any) -> bool:
        if not isinstance(result, Mapping):
            return False
        requested = _normalize(str(result.get("requested_brand", "")))
        configured = _normalize(_brand(context))
        selected = result.get("selected_brands")
        if not requested or requested != configured or (not isinstance(selected, list)):
            return False
        live_selected = context.browser.texts(element(context, BRAND_SELECTED))
        if _brand_set(selected) != {requested} or _brand_set(live_selected) != {
            requested
        }:
            return False
        return download_result_is_valid(result, context.download_dir)

    def counterexamples(self) -> Iterable[Counterexample]:
        yield Counterexample("下载文件为空", after_execute=_empty_download)
        yield Counterexample(
            "导出菜单展开后没有导出库存选项",
            FakeState(hidden=(EXPORT_OPTION,)),
            expected_error=ElementLookupError,
        )
        yield Counterexample(
            "点击导出后没有产生下载",
            FakeState(downloads_available=False),
            expected_error=DownloadError,
        )
        yield Counterexample(
            "导出菜单不存在",
            FakeState(hidden=(EXPORT_MENU,)),
            expected_error=ElementLookupError,
        )
        yield Counterexample(
            "导出前选中了另一个品牌",
            FakeState(texts={BRAND_SELECTED: ("其他品牌",)}),
            expected_error=ElementActionError,
        )


def build_steps() -> tuple[Step, ...]:
    return (
        OpenInventoryModule(
            StepSpec(step_id="S001", name="打开库存模块", timeout_seconds=30.0)
        ),
        OpenProductStock(
            StepSpec(step_id="S002", name="进入商品库存", timeout_seconds=30.0)
        ),
        SelectBrand(
            StepSpec(step_id="S003", name="选择本地配置品牌", timeout_seconds=30.0)
        ),
        SearchInventory(
            StepSpec(step_id="S004", name="搜索并验证筛选", timeout_seconds=60.0)
        ),
        ExportStock(
            StepSpec(step_id="S005", name="导出并验证库存文件", timeout_seconds=360.0)
        ),
    )


__all__ = [
    "BRAND_SELECTED",
    "BRAND_SELECTOR",
    "EXPORT_MENU",
    "EXPORT_OPTION",
    "ExportStock",
    "OpenInventoryModule",
    "OpenProductStock",
    "RESULT_ROW",
    "SearchInventory",
    "SelectBrand",
    "build_steps",
    "element",
]
