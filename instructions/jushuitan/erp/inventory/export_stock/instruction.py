"""Verified inventory export and local artifact verification."""

from __future__ import annotations

from collections.abc import Mapping
from hashlib import sha256
from pathlib import Path
import re

from rpa_core.browser import ElementLookupError, ElementSpec
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


class ExportStock(Instruction):
    spec = InstructionSpec(
        instruction_id="jushuitan.inventory.export_stock",
        version="0.3.0",
        name="导出库存文件",
        platform="jushuitan",
        declared_inputs=("filename", "brand_value"),
        declared_outputs=("download_path", "sha256", "size_bytes"),
        required_element_ids=(
            "jushuitan.erp.product_stock.export_menu",
            "jushuitan.erp.product_stock.export_stock_option",
            "jushuitan.erp.product_stock.brand_selector",
        ),
        preconditions=(
            "filtered inventory results are visible",
            "the exact configured brand remains selected",
        ),
        success_conditions=("download exists, is non-empty, and has a reproducible hash",),
        side_effect=SideEffect.READ,
    )

    def execute(self, context: ExecutionContext, inputs: Mapping[str, object]) -> Mapping[str, object]:
        filename = inputs["filename"]
        if not isinstance(filename, str) or not filename:
            raise InstructionInputError("filename must be a non-empty safe basename")
        brand_value = inputs["brand_value"]
        if not isinstance(brand_value, str) or not brand_value:
            raise InstructionInputError("brand_value must be a non-empty string")
        try:
            context.browser.select(
                _element(context, "jushuitan.erp.product_stock.brand_selector"),
                brand_value,
            )
        except Exception:
            self._capture_failure(context)
            raise
        context.browser.click(
            _element(context, "jushuitan.erp.product_stock.export_menu")
        )
        option = _element(
            context,
            "jushuitan.erp.product_stock.export_stock_option",
        )
        if not context.browser.exists(option, timeout=5.0):
            self._capture_failure(context)
            raise ElementLookupError("export stock option is not visible after opening menu")
        try:
            reference = context.browser.download(option, filename=filename)
        except Exception:
            self._capture_failure(context)
            raise
        return {
            "download_path": str(reference.path),
            "sha256": reference.sha256,
            "size_bytes": reference.size_bytes,
        }

    def verify(self, context: ExecutionContext, result: Mapping[str, object]) -> bool:
        path = Path(str(result["download_path"]))
        if path.is_symlink() or not path.is_file():
            return False
        try:
            path.resolve().relative_to((Path(context.run_dir) / "downloads").resolve())
        except ValueError:
            return False
        content = path.read_bytes()
        expected_hash = str(result["sha256"])
        return (
            bool(content)
            and int(result["size_bytes"]) == len(content)
            and bool(re.fullmatch(r"sha256:[0-9a-f]{64}", expected_hash))
            and expected_hash == f"sha256:{sha256(content).hexdigest()}"
        )

    @staticmethod
    def _capture_failure(context: ExecutionContext) -> None:
        attempt = context.current_attempt or 0
        try:
            context.browser.screenshot(
                name=f"s005-download-failed-attempt-{attempt}.png"
            )
        except Exception:
            # Evidence capture must never replace the primary download failure.
            pass
