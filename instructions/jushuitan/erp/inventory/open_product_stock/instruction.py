"""Verified product-stock navigation."""

from collections.abc import Mapping

from rpa_core.browser import ElementSpec
from rpa_core.contracts import SideEffect
from rpa_core.instructions import Instruction, InstructionSpec
from rpa_core.runtime import ExecutionContext


def _element(context: ExecutionContext, element_id: str) -> ElementSpec:
    catalog = context.services.get("elements")
    if not isinstance(catalog, Mapping):
        raise RuntimeError("execution context elements service is missing")
    element = catalog.get(element_id)
    if not isinstance(element, ElementSpec):
        raise RuntimeError(f"execution context element is missing: {element_id}")
    return element


class OpenProductStock(Instruction):
    spec = InstructionSpec(
        instruction_id="jushuitan.inventory.open_product_stock",
        version="0.1.0",
        name="进入商品库存",
        platform="jushuitan",
        declared_outputs=("product_stock_opened",),
        required_element_ids=(
            "jushuitan.erp.inventory.product_stock_entry",
            "jushuitan.erp.product_stock.page_marker",
        ),
        preconditions=("inventory module is open",),
        success_conditions=("product stock page marker is visible",),
        side_effect=SideEffect.READ,
    )

    def execute(self, context: ExecutionContext, inputs: Mapping[str, object]) -> Mapping[str, object]:
        context.browser.click(
            _element(context, "jushuitan.erp.inventory.product_stock_entry")
        )
        opened = context.browser.exists(
            _element(context, "jushuitan.erp.product_stock.page_marker"),
            timeout=15.0,
        )
        return {"product_stock_opened": opened}

    def verify(self, context: ExecutionContext, result: Mapping[str, object]) -> bool:
        return bool(result["product_stock_opened"])
