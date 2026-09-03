"""Export checked-in JSON Schemas from the authoritative Pydantic models."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from rpa_core.authorization import AuthorizationRecord
from rpa_core.catalog import CatalogLock
from rpa_core.contracts import AppManifest, RequirementSpec


SCHEMA_FILENAMES = {
    "app-manifest.schema.json": AppManifest,
    "authorization-record.schema.json": AuthorizationRecord,
    "catalog-lock.schema.json": CatalogLock,
    "requirement-spec.schema.json": RequirementSpec,
}


def schema_documents() -> dict[str, dict[str, Any]]:
    """Build validation-mode schemas with stable key ordering on write."""

    return {
        filename: model.model_json_schema(mode="validation")
        for filename, model in SCHEMA_FILENAMES.items()
    }


def export_schemas(output_dir: str | Path | None = None) -> tuple[Path, ...]:
    """Write all public schemas and return their paths.

    The default is the package's checked-in ``schemas`` directory.  Tests can
    pass a temporary directory and compare the generated documents without
    mutating the source tree.
    """

    destination = (
        Path(output_dir)
        if output_dir is not None
        else Path(__file__).resolve().parent / "schemas"
    )
    destination.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for filename, schema in schema_documents().items():
        target = destination / filename
        target.write_text(
            json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        written.append(target)
    return tuple(written)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args(argv)
    for path in export_schemas(args.output_dir):
        print(path)
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised as a maintenance command
    raise SystemExit(main())


__all__ = ["SCHEMA_FILENAMES", "export_schemas", "schema_documents"]
