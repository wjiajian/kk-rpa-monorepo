"""Verified inventory-module navigation."""

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


class OpenInventoryModule(Instruction):
    spec = InstructionSpec(
        instruction_id="jushuitan.inventory.open_module",
        version="0.1.0",
        name="打开库存模块",
        platform="jushuitan",
        declared_outputs=("inventory_module_opened",),
        required_element_ids=(
            "jushuitan.erp.navigation.inventory_module",
            "jushuitan.erp.inventory.module_marker",
        ),
        preconditions=("authenticated session is available",),
        success_conditions=("inventory module marker is visible",),
        side_effect=SideEffect.READ,
    )

    def execute(self, context: ExecutionContext, inputs: Mapping[str, object]) -> Mapping[str, object]:
        context.browser.click(
            _element(context, "jushuitan.erp.navigation.inventory_module")
        )
        opened = context.browser.exists(
            _element(context, "jushuitan.erp.inventory.module_marker"),
            timeout=10.0,
        )
        return {"inventory_module_opened": opened}

    def verify(self, context: ExecutionContext, result: Mapping[str, object]) -> bool:
        return bool(result["inventory_module_opened"])
