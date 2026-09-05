"""Load the application's element catalog from ``elements.toml``."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from rpa_core.browser import ElementSpec
from rpa_core.elements import (
    ElementCatalogError,
    ElementEntry,
    element_specs,
    load_element_catalog,
)


APP_DIR = Path(__file__).resolve().parents[3]
CATALOG_PATH = APP_DIR / "elements.toml"


@lru_cache(maxsize=1)
def element_entries() -> dict[str, ElementEntry]:
    """Return every catalog entry, including its ``expect_count`` assertion."""

    return load_element_catalog(CATALOG_PATH)


@lru_cache(maxsize=1)
def element_catalog() -> dict[str, ElementSpec]:
    """Return the runtime element mapping bound as the ``elements`` service."""

    return element_specs(element_entries())


def get_element(element_id: str) -> ElementSpec:
    try:
        return element_catalog()[element_id]
    except KeyError as error:
        raise ElementCatalogError(f"element not found: {element_id}") from error


__all__ = [
    "APP_DIR",
    "CATALOG_PATH",
    "ElementCatalogError",
    "element_catalog",
    "element_entries",
    "get_element",
]
