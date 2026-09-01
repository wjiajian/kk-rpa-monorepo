from __future__ import annotations

from pathlib import Path

from rpa_core.browser import FakeBrowserActions, FakeDownload
from rpa_core.contracts import RunMode
from rpa_core.runtime import ExecutionContext

from inventory_jushuitan_export_stock.elements import element_catalog
from inventory_jushuitan_export_stock.instructions import build_instruction_registry
from inventory_jushuitan_export_stock.models import StoreConfig
from inventory_jushuitan_export_stock.program import (
    APP_ID,
    PROGRAM_ID,
    PROGRAM_VERSION,
    bind_program_inputs,
    build_program,
)


REQUIREMENT_HASH = "sha256:8a86352eedbbbdfbf03bbade09c4766800d34598cadc232d3c513ecf183ac2f2"
EXPORT_ELEMENT_ID = "jushuitan.erp.product_stock.export_stock_option"


def make_store() -> StoreConfig:
    return StoreConfig(
        account_id="STORE_001",
        platform="jushuitan",
        login_url="https://www.erp321.com/login.aspx",
        profile_directory="profiles/STORE_001",
        debug_port=9301,
        brand_value="BRAND_001",
        username_env="RPA_STORE_001_USERNAME",
        password_env="RPA_STORE_001_PASSWORD",
    )


def visible_elements(*, missing: set[str] | None = None) -> set[str]:
    return set(element_catalog()) - set(missing or ())


def make_browser(
    run_dir: Path,
    *,
    missing: set[str] | None = None,
    include_download: bool = True,
) -> FakeBrowserActions:
    downloads = {}
    if include_download:
        downloads[EXPORT_ELEMENT_ID] = FakeDownload(
            "inventory-export.xlsx",
            b"fake inventory workbook\n",
        )
    return FakeBrowserActions(
        run_dir=run_dir,
        visible_element_ids=visible_elements(missing=missing),
        downloads=downloads,
    )


def make_context(run_dir: Path, browser: FakeBrowserActions) -> ExecutionContext:
    context = ExecutionContext(
        app_id=APP_ID,
        program_id=PROGRAM_ID,
        program_version=PROGRAM_VERSION,
        requirement_hash=REQUIREMENT_HASH,
        run_id=run_dir.name,
        account_id="STORE_001",
        mode=RunMode.PREVIEW,
        run_dir=run_dir,
        services={
            "browser": browser,
            "instructions": build_instruction_registry(),
        },
        metadata={"app_dir": str(run_dir.parent.parent)},
    )
    bind_program_inputs(context, make_store())
    return context


def make_program():
    return build_program(REQUIREMENT_HASH)
