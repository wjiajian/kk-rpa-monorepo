"""Candidate inventory search capability."""

from collections.abc import Mapping

from rpa_core.contracts import SideEffect
from rpa_core.instructions import Instruction, InstructionSpec
from rpa_core.runtime import ExecutionContext

from inventory_jushuitan_export_stock.elements import get_element


class SearchInventory(Instruction):
    spec = InstructionSpec(
        instruction_id="jushuitan.inventory.search",
        version="0.1.0",
        name="搜索商品库存",
        platform="jushuitan",
        declared_outputs=("filter_applied",),
        required_element_ids=(
            "jushuitan.erp.product_stock.search_button",
            "jushuitan.erp.product_stock.filter_applied_marker",
        ),
        preconditions=("brand selection is applied",),
        success_conditions=("filtered inventory result marker is visible",),
        side_effect=SideEffect.READ,
    )

    def execute(self, context: ExecutionContext, inputs: Mapping[str, object]) -> Mapping[str, object]:
        context.browser.click(get_element("jushuitan.erp.product_stock.search_button"))
        applied = context.browser.exists(
            get_element("jushuitan.erp.product_stock.filter_applied_marker"),
            timeout=20.0,
        )
        return {"filter_applied": applied}

    def verify(self, context: ExecutionContext, result: Mapping[str, object]) -> bool:
        return bool(result["filter_applied"])
