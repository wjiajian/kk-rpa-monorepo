import pytest
from rpa_core.downloads import (
    download_result_is_valid,
    prepare_download_directory,
    resolve_download_directory,
)


def test_two_apps_can_use_the_same_configured_directory(tmp_path):
    first = tmp_path / "apps" / "first"
    second = tmp_path / "apps" / "second"
    destination = resolve_download_directory(first)
    assert (
        destination
        == resolve_download_directory(second)
        == tmp_path / "runs" / "downloads"
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
    assert list(destination.iterdir()) == []
    assert outside.read_bytes() == b"keep"


def test_cleaning_a_source_or_evidence_ancestor_is_rejected(tmp_path):
    app = tmp_path / "app"
    with pytest.raises(ValueError):
        prepare_download_directory(tmp_path, app_dir=app, run_dir=app / "runs" / "new")


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
