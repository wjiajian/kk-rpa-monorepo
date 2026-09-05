"""Configured download destinations, independent from per-run evidence."""

import shutil
from collections.abc import Mapping
from pathlib import Path
from typing import Any


def resolve_download_directory(
    app_dir: Path, value: str = "../../runs/downloads"
) -> Path:
    path = Path(value).expanduser()
    return (path if path.is_absolute() else app_dir / path).resolve()


def prepare_download_directory(path: Path, *, app_dir: Path, run_dir: Path) -> None:
    destination = path.resolve()
    if destination == Path(destination.anchor) or any(
        protected.resolve().is_relative_to(destination)
        for protected in (app_dir, run_dir)
    ):
        raise ValueError(
            "download directory must not contain application code or run evidence"
        )
    destination.mkdir(parents=True, exist_ok=True)
    for child in destination.iterdir():
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child)
        else:
            child.unlink()


def download_result_is_valid(result: Mapping[str, Any], directory: Path) -> bool:
    raw = result.get("download_path")
    if not isinstance(raw, str) or not raw:
        return False
    path = Path(raw)
    try:
        return (
            result.get("status") == "completed"
            and not path.is_symlink()
            and path.is_file()
            and path.resolve().is_relative_to(directory.resolve())
            and path.stat().st_size > 0
        )
    except OSError:
        return False
