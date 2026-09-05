"""Configured download destinations, independent from per-run evidence."""

import ctypes
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from uuid import UUID


def default_download_directory() -> Path:
    """Use the current user's Downloads folder, including Windows redirection."""
    if sys.platform == "win32":
        return _windows_download_directory()
    return Path.home() / "Downloads"


def _windows_download_directory() -> Path:
    # FOLDERID_Downloads / SHGetKnownFolderPath, not a machine-specific path.
    shell = ctypes.WinDLL("shell32")
    ole = ctypes.WinDLL("ole32")
    ole.CoInitializeEx.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    ole.CoInitializeEx.restype = ctypes.c_int32
    ole.CoUninitialize.argtypes = []
    ole.CoUninitialize.restype = None
    ole.CoTaskMemFree.argtypes = [ctypes.c_void_p]
    ole.CoTaskMemFree.restype = None
    shell.SHGetKnownFolderPath.argtypes = [
        ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.POINTER(ctypes.c_wchar_p)
    ]
    shell.SHGetKnownFolderPath.restype = ctypes.c_int32
    initialized = ole.CoInitializeEx(None, 2)
    if initialized < 0 and initialized != -2147417850:  # RPC_E_CHANGED_MODE: already initialized.
        raise OSError("cannot initialize Windows known-folder lookup")
    allocated = ctypes.c_wchar_p()
    folder_id = (ctypes.c_ubyte * 16).from_buffer_copy(
        UUID("374DE290-123F-4565-9164-39C4925E467B").bytes_le
    )
    try:
        result = shell.SHGetKnownFolderPath(ctypes.byref(folder_id), 0, None, ctypes.byref(allocated))
        if result != 0 or not allocated.value:
            raise OSError("cannot resolve Windows Downloads; pass --download-dir")
        return Path(allocated.value)
    finally:
        ole.CoTaskMemFree(allocated)
        if initialized >= 0:
            ole.CoUninitialize()


def resolve_download_directory(
    app_dir: Path, value: str | None = None
) -> Path:
    if value is None:
        return default_download_directory().resolve()
    if not isinstance(value, str) or not value.strip():
        raise ValueError("download directory must be a non-empty path")
    path = Path(value).expanduser()
    return (path if path.is_absolute() else app_dir / path).resolve()


def prepare_download_directory(path: Path, *, app_dir: Path, run_dir: Path) -> None:
    destination = path.resolve()
    if destination == Path(destination.anchor) or any(
        protected.resolve().is_relative_to(destination)
        or destination.is_relative_to(protected.resolve())
        for protected in (app_dir, run_dir)
    ):
        raise ValueError(
            "download directory must be outside application code and run evidence"
        )
    destination.mkdir(parents=True, exist_ok=True)
    # Downloads is a user's folder. Preparing a run must not delete its contents.


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
