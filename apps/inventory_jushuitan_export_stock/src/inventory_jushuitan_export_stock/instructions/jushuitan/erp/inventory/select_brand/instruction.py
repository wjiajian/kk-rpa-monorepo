"""Candidate brand selection using a local configuration value."""

from collections.abc import Mapping

from rpa_core.contracts import SideEffect
from rpa_core.instructions import Instruction, InstructionInputError, InstructionSpec
from rpa_core.runtime import ExecutionContext

from inventory_jushuitan_export_stock.elements import get_element


class SelectBrand(Instruction):
    spec = InstructionSpec(
        instruction_id="jushuitan.inventory.select_brand",
        version="0.1.0",
        name="选择商品品牌",
        platform="jushuitan",
        declared_inputs=("brand_value",),
        declared_outputs=("selected_brand", "selection_visible"),
        required_element_ids=(
            "jushuitan.erp.product_stock.brand_selector",
            "jushuitan.erp.product_stock.brand_selected_marker",
        ),
        preconditions=("product stock page is open",),
        success_conditions=("requested brand selection is visibly applied",),
        side_effect=SideEffect.READ,
    )

    def execute(self, context: ExecutionContext, inputs: Mapping[str, object]) -> Mapping[str, object]:
        brand_value = inputs["brand_value"]
        if not isinstance(brand_value, str) or not brand_value:
            raise InstructionInputError("brand_value must be a non-empty string")
        context.browser.select(
            get_element("jushuitan.erp.product_stock.brand_selector"),
            brand_value,
        )
        visible = context.browser.exists(
            get_element("jushuitan.erp.product_stock.brand_selected_marker"),
            timeout=5.0,
        )
        return {"selected_brand": brand_value, "selection_visible": visible}

    def verify(self, context: ExecutionContext, result: Mapping[str, object]) -> bool:
        return bool(result["selected_brand"]) and bool(result["selection_visible"])
