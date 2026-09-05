from __future__ import annotations

from pathlib import Path

from rpa_core.browser import FakeBrowserActions, FakeDownload, SecretValue
from rpa_core.contracts import RunMode
from rpa_core.runtime import ExecutionContext
from rpa_core.verification import Counterexample, FakeState

from inventory_jushuitan_export_stock.elements import element_catalog
from inventory_jushuitan_export_stock.models import LoginCredentials, StoreConfig
from inventory_jushuitan_export_stock.program import (
    APP_ID,
    PROGRAM_ID,
    PROGRAM_VERSION,
    REQUIREMENT_HASH,
    bind_program_inputs,
    build_program,
)
from inventory_jushuitan_export_stock.steps import BRAND_SELECTED


EXPORT_ELEMENT_ID = "jushuitan.erp.product_stock.export_stock_option"
ACCOUNT_IDENTITY_ELEMENT_ID = "jushuitan.erp.shell.account_identity_surface"
FIXTURE_IDENTITY = "fixture-user"
FIXTURE_BRAND = "BRAND_001"


def make_store() -> StoreConfig:
    return StoreConfig(
        account_id="STORE_001",
        platform="jushuitan",
        login_url="https://www.erp321.com/login.aspx",
        profile_directory="profiles/STORE_001",
        debug_port=9301,
        brand_value=FIXTURE_BRAND,
        username_env="RPA_STORE_001_USERNAME",
        password_env="RPA_STORE_001_PASSWORD",
        identity_env="RPA_STORE_001_IDENTITY",
    )


def visible_elements(*, missing: set[str] | None = None) -> set[str]:
    return set(element_catalog()) - set(missing or ())


def make_browser(
    run_dir: Path,
    *,
    missing: set[str] | None = None,
    include_download: bool = True,
    state: FakeState | None = None,
) -> FakeBrowserActions:
    """Build the fake page.

    ``state`` is a counterexample's declarative page description; without it the
    fake models the happy path, where the configured brand reads back as the one
    and only selected brand.
    """

    state = state or FakeState()
    hidden = set(missing or ()) | set(state.hidden)
    downloads = {}
    if include_download and state.downloads_available:
        downloads[EXPORT_ELEMENT_ID] = FakeDownload(
            "inventory-export.xlsx",
            b"fake inventory workbook\n",
        )
    return FakeBrowserActions(
        run_dir=run_dir,
        visible_element_ids=visible_elements(missing=hidden),
        downloads=downloads,
        text_values={
            ACCOUNT_IDENTITY_ELEMENT_ID: FIXTURE_IDENTITY,
            BRAND_SELECTED: FIXTURE_BRAND,
        },
        counts=dict(state.counts),
        text_lists={key: tuple(value) for key, value in state.texts.items()},
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
            "elements": element_catalog(),
        },
        metadata={"app_dir": str(run_dir.parent.parent)},
    )
    bind_program_inputs(
        context,
        make_store(),
        LoginCredentials(
            SecretValue(FIXTURE_IDENTITY, label="fixture-user"),
            SecretValue("fixture-secret", label="fixture-secret"),
            SecretValue(FIXTURE_IDENTITY, label="fixture-identity"),
        ),
    )
    return context


def counterexample_context(run_dir: Path, case: Counterexample) -> ExecutionContext:
    """Build the execution context one counterexample describes."""

    context = make_context(run_dir, make_browser(run_dir, state=case.state))
    context.metadata.update(case.metadata)
    return context


def make_program():
    return build_program(REQUIREMENT_HASH)
