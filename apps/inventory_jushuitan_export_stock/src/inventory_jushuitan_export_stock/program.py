"""Prepare plus S001-S005 inventory export program."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from rpa_core.browser import ElementSpec
from rpa_core.runtime import BaseProgram, ExecutionContext, ProgramSpec

# The identity comparison is imported, never re-implemented: prepare_is_satisfied
# has to agree with the instruction that establishes the session, or resume
# would skip a prepare the instruction would have considered necessary.
from .instructions.jushuitan.erp.auth.ensure_account_session.instruction import (
    _identity_matches,
)
from .models import LoginCredentials, StoreConfig
from .steps import build_steps


APP_ID = "jushuitan.inventory.export_stock"
_SESSION_MARKER = "jushuitan.erp.shell.authenticated_marker"
_IDENTITY_SURFACE = "jushuitan.erp.shell.account_identity_surface"
PROGRAM_ID = "jushuitan-inventory-export-stock"
PROGRAM_VERSION = "0.4.0"


class InventoryExportProgram(BaseProgram):
    def prepare_is_satisfied(self, context: ExecutionContext) -> bool:
        """Report whether the current page already carries the target session.

        Answering true keeps an adopted browser exactly where a failed run left
        it, because ``ensure_account_session`` navigates to the login URL before
        it checks anything.  Only a positive read counts: anything unreadable
        falls through to a normal prepare.
        """

        credentials = context.metadata.get("login_credentials")
        if not isinstance(credentials, LoginCredentials):
            return False
        marker = _element(context, _SESSION_MARKER)
        surface = _element(context, _IDENTITY_SURFACE)
        if marker is None or surface is None:
            return False
        if not context.browser.exists(marker, timeout=0.0):
            return False
        expected_identity = credentials.expected_identity or credentials.username
        return _identity_matches(context.browser.text(surface), expected_identity)

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


def _element(context: ExecutionContext, element_id: str) -> ElementSpec | None:
    catalog = context.services.get("elements")
    if not isinstance(catalog, Mapping):
        return None
    element = catalog.get(element_id)
    return element if isinstance(element, ElementSpec) else None


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
