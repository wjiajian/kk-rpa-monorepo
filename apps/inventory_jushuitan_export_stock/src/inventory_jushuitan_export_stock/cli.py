"""Application entry point delegated to the shared CLI."""

from __future__ import annotations

from collections.abc import Sequence

from rpa_core.cli import main as core_main

from .program import APPLICATION


def main(argv: Sequence[str] | None = None) -> int:
    return core_main(APPLICATION, argv)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
