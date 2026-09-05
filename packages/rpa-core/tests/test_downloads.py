import pytest
import ctypes
from pathlib import Path
from types import SimpleNamespace
from rpa_core import downloads
from rpa_core.downloads import (
    download_result_is_valid,
    prepare_download_directory,
    resolve_download_directory,
)


def test_two_apps_default_to_system_downloads_and_preserve_existing_files(tmp_path, monkeypatch):
    first = tmp_path / "apps" / "first"
    second = tmp_path / "apps" / "second"
    monkeypatch.setattr(downloads, "default_download_directory", lambda: tmp_path / "Downloads")
    destination = resolve_download_directory(first)
    assert (
        destination
        == resolve_download_directory(second)
        == tmp_path / "Downloads"
    )
    destination.mkdir(parents=True)
    (destination / "old.xlsx").write_bytes(b"old")
    (destination / "nested").mkdir()
    (destination / "nested" / "partial").write_bytes(b"partial")
    outside = tmp_path / "outside.xlsx"
    outside.write_bytes(b"keep")
    (destination / "linked").symlink_to(outside)
    prepare_download_directory(
        destination, app_dir=second, run_dir=second / "runs" / "new"
    )
    assert (destination / "old.xlsx").read_bytes() == b"old"
    assert (destination / "nested" / "partial").read_bytes() == b"partial"
    assert (destination / "linked").is_symlink()
    assert outside.read_bytes() == b"keep"


@pytest.mark.parametrize("relative", [".", "app", "app/src", "app/src/nested", "app/runs/new/evidence"])
def test_source_evidence_and_their_ancestors_are_rejected_without_deleting_files(tmp_path, relative):
    app = tmp_path / "app"
    target = tmp_path / relative
    target.mkdir(parents=True, exist_ok=True)
    marker = target / "keep.txt"
    marker.write_text("keep")
    with pytest.raises(ValueError):
        prepare_download_directory(target, app_dir=app, run_dir=app / "runs" / "new")
    assert marker.read_text() == "keep"


def test_windows_default_uses_the_known_folder_api_and_frees_its_buffer(tmp_path, monkeypatch):
    redirected = tmp_path / "redirected-downloads"
    buffer = ctypes.create_unicode_buffer(str(redirected))
    calls = []

    def lookup(folder, flags, token, output):
        from uuid import UUID
        assert ctypes.string_at(folder, 16) == UUID("374DE290-123F-4565-9164-39C4925E467B").bytes_le
        assert flags == 0 and token is None
        ctypes.cast(output, ctypes.POINTER(ctypes.c_wchar_p))[0] = ctypes.cast(buffer, ctypes.c_wchar_p)
        return 0

    shell = SimpleNamespace(SHGetKnownFolderPath=lookup)
    ole = SimpleNamespace(
        CoInitializeEx=lambda *args: 0,
        CoTaskMemFree=lambda pointer: calls.append(("free", pointer.value)),
        CoUninitialize=lambda: calls.append(("uninitialize", None)),
    )
    monkeypatch.setattr(ctypes, "WinDLL", lambda name: shell if name == "shell32" else ole, raising=False)
    monkeypatch.setattr(downloads.sys, "platform", "win32")
    assert downloads.default_download_directory() == redirected
    assert calls == [("free", str(redirected)), ("uninitialize", None)]


def test_non_windows_development_default_and_explicit_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(downloads.sys, "platform", "darwin")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert resolve_download_directory(tmp_path / "app") == tmp_path / "Downloads"
    assert resolve_download_directory(tmp_path / "app", "../custom") == tmp_path / "custom"


def test_download_validation_checks_completion_and_actual_file(tmp_path):
    target = tmp_path / "shared" / "report.xlsx.zip"
    target.parent.mkdir()
    target.write_bytes(b"downloaded archive")
    result = {"download_path": str(target), "status": "completed"}
    assert download_result_is_valid(result, target.parent)
    assert not download_result_is_valid({**result, "status": "canceled"}, target.parent)
    assert not download_result_is_valid(result, tmp_path / "elsewhere")
    target.write_bytes(b"")
    assert not download_result_is_valid(result, target.parent)
    target.unlink()
    assert not download_result_is_valid(result, target.parent)
