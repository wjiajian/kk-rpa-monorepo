"""Redacted, source-level diagnostics for terminal error reports."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
import traceback


_MAX_EXCEPTION_CHAIN = 16
_MAX_TRACEBACK_FRAMES = 80
_MAX_MESSAGE_LENGTH = 500
_REDACTED_EXTERNAL_MESSAGE = "<redacted: no trusted stable error contract>"


def exception_diagnostics(
    error: BaseException,
    *,
    source_root: str | Path | None = None,
    trusted_module_prefixes: Sequence[str] = ("rpa_core",),
) -> dict[str, object]:
    """Return useful file/line/error details without serializing locals.

    Exception messages are included only when the exception exposes a stable
    ``error_code`` and comes from a trusted project module. Third-party and
    built-in messages are redacted because they may contain runtime values.
    """

    root = Path(source_root).resolve() if source_root is not None else None
    chain, chain_truncated = _exception_chain(error)
    exceptions: list[dict[str, object]] = []
    frames: list[dict[str, object]] = []
    traceback_truncated = False

    for exception_index, current in enumerate(chain):
        module = type(current).__module__
        error_code = getattr(current, "error_code", None)
        trusted_details = (
            isinstance(error_code, str)
            and bool(error_code)
            and _module_is_trusted(module, trusted_module_prefixes)
        )
        extracted = traceback.extract_tb(current.__traceback__)
        current_frames: list[dict[str, object]] = []
        for frame in extracted:
            if len(frames) >= _MAX_TRACEBACK_FRAMES:
                traceback_truncated = True
                break
            rendered = {
                "exception_index": exception_index,
                "exception_type": type(current).__name__,
                "file": _display_source_path(frame.filename, root),
                "line": frame.lineno,
                "function": frame.name,
                "code": (
                    frame.line.strip()
                    if trusted_details and frame.line
                    else "<redacted: untrusted exception source>"
                ),
            }
            current_frames.append(rendered)
            frames.append(rendered)

        message = (
            _bounded_single_line(str(current))
            if trusted_details
            else _REDACTED_EXTERNAL_MESSAGE
        )
        location = dict(current_frames[-1]) if current_frames else None
        if location is not None:
            location.pop("exception_index", None)
            location.pop("exception_type", None)
        exceptions.append(
            {
                "index": exception_index,
                "type": type(current).__name__,
                "module": module,
                "error_code": error_code if isinstance(error_code, str) else None,
                "message": message,
                "location": location,
            }
        )

    root_cause = dict(exceptions[0])
    root_location = root_cause.get("location")
    if isinstance(root_location, dict):
        root_cause["location"] = dict(root_location)
    return {
        "diagnostic_schema_version": 1,
        "root_cause": root_cause,
        "exception_chain": exceptions,
        "traceback": frames,
        "exception_chain_truncated": chain_truncated,
        "traceback_truncated": traceback_truncated,
    }


def _exception_chain(
    error: BaseException,
) -> tuple[tuple[BaseException, ...], bool]:
    outer_to_inner: list[BaseException] = []
    seen: set[int] = set()
    current: BaseException | None = error
    truncated = False
    while current is not None:
        identity = id(current)
        if identity in seen:
            truncated = True
            break
        seen.add(identity)
        outer_to_inner.append(current)
        if len(outer_to_inner) >= _MAX_EXCEPTION_CHAIN:
            next_error = _next_exception(current)
            truncated = next_error is not None
            break
        current = _next_exception(current)
    return tuple(reversed(outer_to_inner)), truncated


def _next_exception(error: BaseException) -> BaseException | None:
    if error.__cause__ is not None:
        return error.__cause__
    if not error.__suppress_context__:
        context = error.__context__
        # Some boundary adapters unwrap a transport exception by re-raising its
        # original cause. Python then points the cause's implicit context back
        # to that transport wrapper, while the wrapper explicitly points to the
        # cause. Ignore that redundant two-node cycle so the original exception
        # remains the root cause.
        if context is not None and context.__cause__ is error:
            return None
        return context
    return None


def _module_is_trusted(module: str, prefixes: Sequence[str]) -> bool:
    return any(
        module == prefix or module.startswith(f"{prefix}.")
        for prefix in prefixes
        if prefix
    )


def _bounded_single_line(message: str) -> str:
    normalized = " ".join(message.split()) or "<empty message>"
    if len(normalized) <= _MAX_MESSAGE_LENGTH:
        return normalized
    return normalized[: _MAX_MESSAGE_LENGTH - 3] + "..."


def _display_source_path(filename: str, source_root: Path | None) -> str:
    if filename.startswith("<") and filename.endswith(">"):
        return filename
    source = Path(filename)
    resolved = source.resolve()
    if source_root is not None:
        try:
            return resolved.relative_to(source_root).as_posix()
        except ValueError:
            pass
    parts = resolved.parts
    for marker in ("site-packages", "dist-packages"):
        if marker in parts:
            index = parts.index(marker)
            return f"<{marker}>/" + "/".join(parts[index + 1 :])
    return f"<external>/{resolved.name}"


__all__ = ["exception_diagnostics"]
