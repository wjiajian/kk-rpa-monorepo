"""Candidate inventory-module navigation."""

from collections.abc import Mapping

from rpa_core.contracts import SideEffect
from rpa_core.instructions import Instruction, InstructionSpec
from rpa_core.runtime import ExecutionContext

from inventory_jushuitan_export_stock.elements import get_element


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
        context.browser.click(get_element("jushuitan.erp.navigation.inventory_module"))
        opened = context.browser.exists(
            get_element("jushuitan.erp.inventory.module_marker"), timeout=10.0
        )
        return {"inventory_module_opened": opened}

    def verify(self, context: ExecutionContext, result: Mapping[str, object]) -> bool:
        return bool(result["inventory_module_opened"])
