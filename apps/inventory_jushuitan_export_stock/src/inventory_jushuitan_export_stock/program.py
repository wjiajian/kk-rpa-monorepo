"""Prepare plus S001-S005 inventory export program."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from rpa_core.runtime import BaseProgram, ExecutionContext, ProgramSpec

from .models import LoginCredentials, StoreConfig
from .steps import build_steps


APP_ID = "jushuitan.inventory.export_stock"
PROGRAM_ID = "jushuitan-inventory-export-stock"
PROGRAM_VERSION = "0.4.0"


class InventoryExportProgram(BaseProgram):
    def prepare(self, context: ExecutionContext) -> None:
        store = context.metadata.get("store_config")
        credentials = context.metadata.get("login_credentials")
        if not isinstance(store, StoreConfig) or not isinstance(
            credentials,
            LoginCredentials,
        ):
            raise TypeError("Prepare requires store configuration and login credentials")
        expected_identity = credentials.expected_identity or credentials.username
        result = context.instructions.execute(
            "jushuitan.auth.ensure_account_session",
            context,
            {
                "login_url": store.login_url,
                "username": credentials.username,
                "password": credentials.password,
                "expected_identity": expected_identity,
            },
        )
        context.metadata["prepare_result"] = dict(result)

    def verify(self, context: ExecutionContext) -> bool:
        result = context.outputs.get("S005")
        if not isinstance(result, Mapping):
            return False
        path = Path(str(result.get("download_path", "")))
        return path.is_file() and int(result.get("size_bytes", 0)) > 0


def build_program(requirement_hash: str) -> InventoryExportProgram:
    return InventoryExportProgram(
        ProgramSpec(
            app_id=APP_ID,
            program_id=PROGRAM_ID,
            version=PROGRAM_VERSION,
            requirement_hash=requirement_hash,
            name="聚水潭库存导出",
        ),
        build_steps(),
    )


def bind_program_inputs(
    context: ExecutionContext,
    store: StoreConfig,
    credentials: LoginCredentials,
    *,
    export_filename: str = "inventory-export.xlsx",
) -> None:
    context.metadata["store_config"] = store
    context.metadata["login_credentials"] = credentials
    context.metadata["export_filename"] = export_filename


__all__ = [
    "APP_ID",
    "InventoryExportProgram",
    "PROGRAM_ID",
    "PROGRAM_VERSION",
    "bind_program_inputs",
    "build_program",
]
