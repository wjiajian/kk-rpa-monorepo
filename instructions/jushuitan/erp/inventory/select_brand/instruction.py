"""Verified exact brand selection using a runtime configuration value."""

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


class SelectBrand(Instruction):
    spec = InstructionSpec(
        instruction_id="jushuitan.inventory.select_brand",
        version="0.2.0",
        name="选择商品品牌",
        platform="jushuitan",
        declared_inputs=("brand_value",),
        declared_outputs=("selected_brand", "selection_visible"),
        required_element_ids=(
            "jushuitan.erp.product_stock.reset_button",
            "jushuitan.erp.product_stock.brand_selector",
        ),
        preconditions=("product stock page is open",),
        success_conditions=("requested brand selection is visibly applied",),
        side_effect=SideEffect.READ,
    )

    def execute(self, context: ExecutionContext, inputs: Mapping[str, object]) -> Mapping[str, object]:
        brand_value = inputs["brand_value"]
        if not isinstance(brand_value, str) or not brand_value:
            raise InstructionInputError("brand_value must be a non-empty string")
        context.browser.click(
            _element(context, "jushuitan.erp.product_stock.reset_button")
        )
        context.browser.select(
            _element(context, "jushuitan.erp.product_stock.brand_selector"),
            brand_value,
        )
        return {
            "selected_brand": brand_value,
            "selection_visible": True,
        }

    def verify(self, context: ExecutionContext, result: Mapping[str, object]) -> bool:
        return bool(result["selected_brand"]) and bool(result["selection_visible"])
