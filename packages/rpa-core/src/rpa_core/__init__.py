"""Public API for the shared RPA runtime."""

from .browser import BrowserActions, ElementSpec, FakeBrowserActions
from .browser_manager import (
    BrowserLaunchSpec,
    BrowserLifecyclePolicy,
    BrowserManager,
    BrowserSession,
    PortLeasePool,
)
from .catalog import (
    CatalogIndex,
    CatalogLock,
    CatalogRef,
    discover_catalog,
    snapshot_catalog,
    verify_catalog_snapshot,
)
from .drission_browser import DrissionBrowserActions
from .instructions import Instruction, InstructionRegistry, InstructionSpec

__version__ = "0.2.0"

__all__ = [
    "BrowserActions",
    "BrowserLaunchSpec",
    "BrowserLifecyclePolicy",
    "BrowserManager",
    "BrowserSession",
    "CatalogIndex",
    "CatalogLock",
    "CatalogRef",
    "DrissionBrowserActions",
    "ElementSpec",
    "FakeBrowserActions",
    "Instruction",
    "InstructionRegistry",
    "InstructionSpec",
    "PortLeasePool",
    "__version__",
    "discover_catalog",
    "snapshot_catalog",
    "verify_catalog_snapshot",
]
