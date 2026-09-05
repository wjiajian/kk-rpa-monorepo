"""Execution mode selected at invocation, without interactive approval state."""

from enum import StrEnum


class RunMode(StrEnum):
    LIVE = "live"
    PREVIEW = "preview"
