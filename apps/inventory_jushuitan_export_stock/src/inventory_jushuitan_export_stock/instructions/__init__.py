"""Application-local instruction catalog snapshot registry."""

from rpa_core.instructions import InstructionRegistry

from .jushuitan.erp.auth.ensure_account_session.instruction import EnsureAccountSession
from .jushuitan.erp.auth.login.instruction import Login
from .jushuitan.erp.inventory.export_stock.instruction import ExportStock
from .jushuitan.erp.inventory.open_module.instruction import OpenInventoryModule
from .jushuitan.erp.inventory.open_product_stock.instruction import OpenProductStock
from .jushuitan.erp.inventory.search.instruction import SearchInventory
from .jushuitan.erp.inventory.select_brand.instruction import SelectBrand


def build_instruction_registry() -> InstructionRegistry:
    return InstructionRegistry(
        [
            Login(),
            EnsureAccountSession(),
            OpenInventoryModule(),
            OpenProductStock(),
            SelectBrand(),
            SearchInventory(),
            ExportStock(),
        ]
    )


__all__ = ["build_instruction_registry"]
