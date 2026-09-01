"""Candidate inventory export and local artifact verification."""

from __future__ import annotations

from collections.abc import Mapping
from hashlib import sha256
from pathlib import Path
import re

from rpa_core.contracts import SideEffect
from rpa_core.instructions import Instruction, InstructionInputError, InstructionSpec
from rpa_core.runtime import ExecutionContext

from inventory_jushuitan_export_stock.elements import get_element


class ExportStock(Instruction):
    spec = InstructionSpec(
        instruction_id="jushuitan.inventory.export_stock",
        version="0.1.0",
        name="导出库存文件",
        platform="jushuitan",
        declared_inputs=("filename",),
        declared_outputs=("download_path", "sha256", "size_bytes"),
        required_element_ids=(
            "jushuitan.erp.product_stock.export_menu",
            "jushuitan.erp.product_stock.export_stock_option",
        ),
        preconditions=("filtered inventory results are visible",),
        success_conditions=("download exists, is non-empty, and has a reproducible hash",),
        side_effect=SideEffect.READ,
    )

    def execute(self, context: ExecutionContext, inputs: Mapping[str, object]) -> Mapping[str, object]:
        filename = inputs["filename"]
        if not isinstance(filename, str) or not filename:
            raise InstructionInputError("filename must be a non-empty safe basename")
        context.browser.click(get_element("jushuitan.erp.product_stock.export_menu"))
        reference = context.browser.download(
            get_element("jushuitan.erp.product_stock.export_stock_option"),
            filename=filename,
        )
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
