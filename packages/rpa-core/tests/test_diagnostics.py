from __future__ import annotations

import json
from pathlib import Path

from rpa_core.browser import ElementLookupError
from rpa_core.diagnostics import exception_diagnostics
from rpa_core.runtime import StepRunError

CORE_DIR = Path(__file__).resolve().parents[1]


def _raise_trusted_root_cause() -> None:
    raise ElementLookupError("element was not found")


def _raise_trusted_chain() -> None:
    try:
        _raise_trusted_root_cause()
    except ElementLookupError as error:
        raise StepRunError(
            "S003",
            error.error_code,
            "step S003 failed",
        ) from error


def test_exception_diagnostics_reports_root_cause_file_line_and_chain() -> None:
    try:
        _raise_trusted_chain()
    except StepRunError as error:
        report = exception_diagnostics(error, source_root=CORE_DIR)

    assert report["diagnostic_schema_version"] == 1
    root_cause = report["root_cause"]
    assert isinstance(root_cause, dict)
    assert root_cause["type"] == "ElementLookupError"
    assert root_cause["error_code"] == "browser_element_not_found"
    assert root_cause["message"] == "element was not found"
    assert root_cause["location"] == {
        "file": "tests/test_diagnostics.py",
        "line": _raise_trusted_root_cause.__code__.co_firstlineno + 1,
        "function": "_raise_trusted_root_cause",
        "code": ('raise ElementLookupError("element was not found")'),
    }
    assert [entry["type"] for entry in report["exception_chain"]] == [
        "ElementLookupError",
        "StepRunError",
    ]
    assert report["traceback"]
    assert report["exception_chain_truncated"] is False
    assert report["traceback_truncated"] is False


def test_exception_diagnostics_redacts_untrusted_exception_messages() -> None:
    try:
        raise RuntimeError("password=fixture-secret-must-not-appear")
    except RuntimeError as error:
        report = exception_diagnostics(error, source_root=CORE_DIR)

    encoded = json.dumps(report)
    root_cause = report["root_cause"]
    assert isinstance(root_cause, dict)
    assert root_cause["type"] == "RuntimeError"
    assert root_cause["error_code"] is None
    assert root_cause["message"] == "<redacted: no trusted stable error contract>"
    assert "fixture-secret-must-not-appear" not in encoded
    assert str(CORE_DIR) not in encoded


def _raise_unwrapped_transport_error() -> None:
    try:
        try:
            _raise_trusted_root_cause()
        except ElementLookupError as error:
            raise RuntimeError("transport wrapper") from error
    except RuntimeError as error:
        raise error.__cause__


def test_exception_diagnostics_ignores_unwrapped_transport_cycle() -> None:
    try:
        try:
            _raise_unwrapped_transport_error()
        except ElementLookupError as error:
            raise StepRunError(
                "S003",
                error.error_code,
                "step S003 failed",
            ) from error
    except StepRunError as error:
        report = exception_diagnostics(error, source_root=CORE_DIR)

    assert report["root_cause"]["type"] == "ElementLookupError"
    assert [entry["type"] for entry in report["exception_chain"]] == [
        "ElementLookupError",
        "StepRunError",
    ]
    assert report["exception_chain_truncated"] is False
