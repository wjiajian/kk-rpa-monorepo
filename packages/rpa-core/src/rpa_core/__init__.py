"""Public API for the shared RPA runtime."""

from .browser import BrowserActions, ElementSpec, FakeBrowserActions
from .browser_manager import (
    BrowserLaunchSpec,
    BrowserLifecyclePolicy,
    BrowserManager,
    BrowserSession,
    PortLeasePool,
)
from .drission_browser import DrissionBrowserActions

__version__ = "0.1.2"

__all__ = [
    "BrowserActions",
    "BrowserLaunchSpec",
    "BrowserLifecyclePolicy",
    "BrowserManager",
    "BrowserSession",
    "DrissionBrowserActions",
    "ElementSpec",
    "FakeBrowserActions",
    "PortLeasePool",
    "__version__",
]
