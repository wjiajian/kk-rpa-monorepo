"""Public browser, element and sequential execution interfaces."""

from .browser import BrowserActions, ElementSpec, FakeBrowserActions
from .browser_manager import BrowserLaunchSpec, BrowserLifecyclePolicy, BrowserManager
from .drission_browser import DrissionBrowserActions
from .elements import check_element_expectations, load_element_catalog
from .runtime import BaseProgram, ExecutionContext, ProgramSpec, Runner, Step, StepSpec
from .verification import Counterexample, FakeState, assert_steps_are_falsifiable

__version__ = "0.8.0"

__all__ = [
    "BrowserActions",
    "ElementSpec",
    "FakeBrowserActions",
    "BrowserLaunchSpec",
    "BrowserLifecyclePolicy",
    "BrowserManager",
    "DrissionBrowserActions",
    "check_element_expectations",
    "load_element_catalog",
    "BaseProgram",
    "ExecutionContext",
    "ProgramSpec",
    "Runner",
    "Step",
    "StepSpec",
    "Counterexample",
    "FakeState",
    "assert_steps_are_falsifiable",
]
