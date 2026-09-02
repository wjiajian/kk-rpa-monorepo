"""Complete Prepare plus S001-S005 inventory export program."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from rpa_core.runtime import BaseProgram, ExecutionContext, ProgramSpec

from .models import StoreConfig
from .steps import build_steps


APP_ID = "jushuitan.inventory.export_stock"
PROGRAM_ID = "jushuitan-inventory-export-stock"
PROGRAM_VERSION = "0.1.0"


class InventoryExportProgram(BaseProgram):
    def prepare(self, context: ExecutionContext) -> None:
        result = context.instructions.execute(
            "jushuitan.auth.require_session",
            context,
            {},
        )
        context.metadata["prepare_result"] = dict(result)
        target = context.metadata.get("resume_recovery_target")
        if target is not None:
            self._restore_resume_browser_state(context, str(target))

    @staticmethod
    def _restore_resume_browser_state(
        context: ExecutionContext,
        target_step_id: str,
    ) -> None:
        store = context.metadata.get("store_config")
        if not isinstance(store, StoreConfig):
            raise TypeError("resume recovery requires StoreConfig")
        prerequisites = {
            "S001": (),
            "S002": (
                ("jushuitan.inventory.open_module", {}),
            ),
            "S003": (
                ("jushuitan.inventory.open_module", {}),
                ("jushuitan.inventory.open_product_stock", {}),
            ),
            "S004": (
                ("jushuitan.inventory.open_module", {}),
                ("jushuitan.inventory.open_product_stock", {}),
                (
                    "jushuitan.inventory.select_brand",
                    {"brand_value": store.brand_value},
                ),
            ),
            "S005": (
                ("jushuitan.inventory.open_module", {}),
                ("jushuitan.inventory.open_product_stock", {}),
                (
                    "jushuitan.inventory.select_brand",
                    {"brand_value": store.brand_value},
                ),
                (
                    "jushuitan.inventory.search",
                    {"brand_value": store.brand_value},
                ),
            ),
        }
        try:
            recovery_plan = prerequisites[target_step_id]
        except KeyError as error:
            raise ValueError(f"unsupported resume target: {target_step_id}") from error
        last_error: Exception | None = None
        for plan_attempt in range(1, 3):
            recovered = []
            try:
                for instruction_id, inputs in recovery_plan:
                    context.instructions.execute(
                        instruction_id,
                        context,
                        inputs,
                    )
                    recovered.append(instruction_id)
            except Exception as error:
                last_error = error
                if plan_attempt < 2:
                    continue
                try:
                    context.browser.screenshot(
                        name=f"resume-prepare-{target_step_id.lower()}-failed.png"
                    )
                except Exception:
                    pass
                raise
            context.metadata["resume_prepare_instructions"] = tuple(recovered)
            return
        assert last_error is not None
        raise last_error

    def verify(self, context: ExecutionContext) -> bool:
        result = context.outputs.get("S005")
        if not isinstance(result, Mapping):
            return False
        path = Path(str(result.get("download_path", "")))
        return path.is_file() and int(result.get("size_bytes", 0)) > 0


def build_program(
    requirement_hash: str,
) -> InventoryExportProgram:
    program = InventoryExportProgram(
        ProgramSpec(
            app_id=APP_ID,
            program_id=PROGRAM_ID,
            version=PROGRAM_VERSION,
            requirement_hash=requirement_hash,
            name="聚水潭库存导出",
        ),
        build_steps(),
    )
    return program


def bind_program_inputs(
    context: ExecutionContext,
    store: StoreConfig,
    *,
    export_filename: str = "inventory-export.xlsx",
) -> None:
    context.metadata["store_config"] = store
    context.metadata["export_filename"] = export_filename


__all__ = [
    "APP_ID",
    "InventoryExportProgram",
    "PROGRAM_ID",
    "PROGRAM_VERSION",
    "bind_program_inputs",
    "build_program",
]
