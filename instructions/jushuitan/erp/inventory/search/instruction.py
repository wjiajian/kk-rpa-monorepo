"""Verified inventory search capability."""

from collections.abc import Mapping

from rpa_core.browser import ElementSpec
from rpa_core.contracts import SideEffect
from rpa_core.instructions import Instruction, InstructionInputError, InstructionSpec
from rpa_core.runtime import ExecutionContext


def _element(context: ExecutionContext, element_id: str) -> ElementSpec:
    catalog = context.services.get("elements")
    if not isinstance(catalog, Mapping):
        raise RuntimeError("execution context elements service is missing")
    element = catalog.get(element_id)
    if not isinstance(element, ElementSpec):
        raise RuntimeError(f"execution context element is missing: {element_id}")
    return element


class SearchInventory(Instruction):
    spec = InstructionSpec(
        instruction_id="jushuitan.inventory.search",
        version="0.3.0",
        name="搜索商品库存",
        platform="jushuitan",
        declared_inputs=("brand_value",),
        declared_outputs=("filter_applied",),
        required_element_ids=(
            "jushuitan.erp.product_stock.search_button",
            "jushuitan.erp.product_stock.filter_applied_marker",
            "jushuitan.erp.product_stock.brand_selector",
        ),
        preconditions=("the exact configured brand is selected",),
        success_conditions=(
            "filtered inventory result marker is visible",
            "the configured brand remains selected after search",
        ),
        side_effect=SideEffect.READ,
    )

    def execute(self, context: ExecutionContext, inputs: Mapping[str, object]) -> Mapping[str, object]:
        brand_value = inputs["brand_value"]
        if not isinstance(brand_value, str) or not brand_value:
            raise InstructionInputError("brand_value must be a non-empty string")
        brand_selector = _element(
            context,
            "jushuitan.erp.product_stock.brand_selector",
        )
        # The platform may restore its default item when Search completes.
        # Exact multi-select normalization therefore runs both immediately
        # before the query and again after the result marker appears.
        context.browser.select(brand_selector, brand_value)
        context.browser.click(
            _element(context, "jushuitan.erp.product_stock.search_button")
        )
        result_visible = context.browser.exists(
            _element(context, "jushuitan.erp.product_stock.filter_applied_marker"),
            timeout=20.0,
        )
        context.browser.select(brand_selector, brand_value)
        return {"filter_applied": result_visible}

    def verify(self, context: ExecutionContext, result: Mapping[str, object]) -> bool:
        return bool(result["filter_applied"])
