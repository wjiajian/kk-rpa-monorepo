from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path

import pytest

from rpa_core.contracts import RunMode
from rpa_core.events import EventLogError, JsonlEventLogger
from rpa_core.services import (
    ApprovalContext,
    FakeFeishuBackend,
    LiveWriteGrant,
    PreviewFeishuService,
    PreviewWriteError,
    ServiceAuthorizationError,
)


def make_service(
    tmp_path: Path,
    *,
    mode: RunMode,
    backend: FakeFeishuBackend,
    grant: LiveWriteGrant | None = None,
    account_id: str = "STORE_001",
) -> PreviewFeishuService:
    return PreviewFeishuService(
        mode=mode,
        app_id="example.offline.export",
        run_id="run-001",
        account_id=account_id,
        run_dir=tmp_path / "runs" / "run-001",
        backend=backend,
        live_grant=grant,
    )


def approved_context(**overrides: object) -> ApprovalContext:
    values: dict[str, object] = {
        "app_id": "example.offline.export",
        "run_id": "run-001",
        "account_id": "STORE_001",
        "step_id": "STEP-004",
        "target": "base://orders/summary",
        "data_scope": {"date": "2026-08-30", "stores": ["STORE_001"]},
        "expected_count": 1,
        "mode": RunMode.LIVE,
    }
    values.update(overrides)
    return ApprovalContext(**values)


def test_preview_writes_exact_artifact_without_calling_backend(tmp_path: Path) -> None:
    backend = FakeFeishuBackend()
    service = make_service(tmp_path, mode=RunMode.PREVIEW, backend=backend)

    result = service.upsert_base(
        [{"store": "STORE_001", "count": 2}],
        step_id="STEP-004",
        target="base://orders/summary",
        data_scope={"date": "2026-08-30", "stores": ["STORE_001"]},
    )

    expected_path = tmp_path / "runs/run-001/write-previews/feishu-base-upsert--STEP-004.json"
    assert result.preview_path == expected_path
    assert expected_path.is_file()
    payload = json.loads(expected_path.read_text(encoding="utf-8"))
    assert payload["write_executed"] is False
    assert payload["expected_count"] == 1
    assert payload["records"] == [{"store": "STORE_001", "count": 2}]
    assert backend.write_calls == 0


def test_preview_artifacts_do_not_clobber_across_steps(tmp_path: Path) -> None:
    backend = FakeFeishuBackend()
    service = make_service(tmp_path, mode=RunMode.PREVIEW, backend=backend)

    first = service.upsert_base(
        [{"count": 1}],
        step_id="STEP-004",
        target="base://orders/summary",
    )
    second = service.upsert_base(
        [{"count": 2}],
        step_id="STEP-005",
        target="base://orders/summary",
    )

    assert first.preview_path != second.preview_path
    assert json.loads(first.preview_path.read_text(encoding="utf-8"))["step_id"] == "STEP-004"
    assert json.loads(second.preview_path.read_text(encoding="utf-8"))["step_id"] == "STEP-005"
    assert backend.write_calls == 0


def test_preview_rejects_unsafe_step_id_before_creating_state(tmp_path: Path) -> None:
    backend = FakeFeishuBackend()
    service = make_service(tmp_path, mode=RunMode.PREVIEW, backend=backend)

    with pytest.raises(PreviewWriteError, match="step_id must use"):
        service.upsert_base(
            [{"count": 1}],
            step_id="../escape",
            target="base://orders/summary",
        )

    assert not (tmp_path / "runs").exists()
    assert backend.write_calls == 0


def test_preview_rejects_symlinked_output_directory(tmp_path: Path) -> None:
    backend = FakeFeishuBackend()
    service = make_service(tmp_path, mode=RunMode.PREVIEW, backend=backend)
    outside = tmp_path / "outside"
    outside.mkdir()
    preview_dir = tmp_path / "runs" / "run-001" / "write-previews"
    preview_dir.parent.mkdir(parents=True)
    try:
        preview_dir.symlink_to(outside, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"symlinks are unavailable in this test environment: {error}")

    with pytest.raises(PreviewWriteError, match="symbolic link"):
        service.upsert_base(
            [{"store": "STORE_001", "count": 2}],
            step_id="STEP-004",
            target="base://orders/summary",
            data_scope={"date": "2026-08-30"},
        )

    assert not (outside / "feishu-base-upsert--STEP-004.json").exists()
    assert backend.write_calls == 0


def test_preview_rejects_symlinked_run_directory_without_writing_outside(
    tmp_path: Path,
) -> None:
    backend = FakeFeishuBackend()
    outside = tmp_path / "outside"
    outside.mkdir()
    run_dir = tmp_path / "runs" / "run-001"
    run_dir.parent.mkdir()
    try:
        run_dir.symlink_to(outside, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"symlinks are unavailable in this test environment: {error}")
    service = make_service(tmp_path, mode=RunMode.PREVIEW, backend=backend)

    with pytest.raises(PreviewWriteError, match="run_dir must not be a symbolic link"):
        service.upsert_base(
            [{"store": "STORE_001", "count": 2}],
            step_id="STEP-004",
            target="base://orders/summary",
            data_scope={"date": "2026-08-30"},
        )

    assert list(outside.iterdir()) == []
    assert backend.write_calls == 0


def test_preview_rejects_symlinked_runs_root_without_writing_outside(
    tmp_path: Path,
) -> None:
    backend = FakeFeishuBackend()
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        (tmp_path / "runs").symlink_to(outside, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"symlinks are unavailable in this test environment: {error}")
    service = make_service(tmp_path, mode=RunMode.PREVIEW, backend=backend)

    with pytest.raises(PreviewWriteError, match="runs directory must not be a symbolic link"):
        service.upsert_base(
            [{"store": "STORE_001", "count": 2}],
            step_id="STEP-004",
            target="base://orders/summary",
            data_scope={"date": "2026-08-30"},
        )

    assert list(outside.iterdir()) == []
    assert backend.write_calls == 0


@pytest.mark.parametrize(
    "run_dir",
    [Path("runs/other-run"), Path("external/run-001")],
)
def test_preview_rejects_run_directory_identity_mismatch_before_creating_state(
    tmp_path: Path,
    run_dir: Path,
) -> None:
    backend = FakeFeishuBackend()
    target_run_dir = tmp_path / run_dir
    service = PreviewFeishuService(
        mode=RunMode.PREVIEW,
        app_id="example.offline.export",
        run_id="run-001",
        account_id="STORE_001",
        run_dir=target_run_dir,
        backend=backend,
    )

    with pytest.raises(PreviewWriteError, match="run_dir"):
        service.upsert_base(
            [{"store": "STORE_001", "count": 2}],
            step_id="STEP-004",
            target="base://orders/summary",
            data_scope={"date": "2026-08-30"},
        )

    assert not target_run_dir.exists()
    assert backend.write_calls == 0


def test_live_without_grant_is_rejected_before_backend(tmp_path: Path) -> None:
    backend = FakeFeishuBackend()
    service = make_service(tmp_path, mode=RunMode.LIVE, backend=backend)

    with pytest.raises(ServiceAuthorizationError) as captured:
        service.upsert_base(
            [{"count": 2}],
            step_id="STEP-004",
            target="base://orders/summary",
            data_scope={"date": "2026-08-30", "stores": ["STORE_001"]},
        )

    assert captured.value.error_code == "live_write_grant_missing"
    assert backend.write_calls == 0


def test_wrong_grant_scope_is_rejected_without_consuming_grant(tmp_path: Path) -> None:
    backend = FakeFeishuBackend()
    grant = LiveWriteGrant.issue(
        approved_context(),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
    )
    service = make_service(
        tmp_path,
        mode=RunMode.LIVE,
        backend=backend,
        grant=grant,
        account_id="STORE_002",
    )

    with pytest.raises(ServiceAuthorizationError) as captured:
        service.upsert_base(
            [{"count": 2}],
            step_id="STEP-004",
            target="base://orders/summary",
            data_scope={"date": "2026-08-30", "stores": ["STORE_001"]},
        )

    assert captured.value.error_code == "live_write_scope_mismatch"
    assert not grant.consumed
    assert backend.write_calls == 0


def test_live_grant_is_revalidated_consumed_and_cannot_be_replayed(tmp_path: Path) -> None:
    backend = FakeFeishuBackend()
    context = approved_context()
    grant = LiveWriteGrant.issue(
        context,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
    )
    service = make_service(tmp_path, mode=RunMode.LIVE, backend=backend, grant=grant)
    kwargs = {
        "step_id": context.step_id,
        "target": context.target,
        "data_scope": dict(context.data_scope),
    }

    result = service.upsert_base([{"count": 2}], **kwargs)
    assert result.mode == "live"
    assert grant.consumed
    assert backend.write_calls == 1

    with pytest.raises(ServiceAuthorizationError) as captured:
        service.upsert_base([{"count": 3}], **kwargs)
    assert captured.value.error_code == "live_write_grant_consumed"
    assert backend.write_calls == 1


def test_expired_live_grant_is_rejected(tmp_path: Path) -> None:
    backend = FakeFeishuBackend()
    grant = LiveWriteGrant.issue(
        approved_context(),
        expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
    )
    service = make_service(tmp_path, mode=RunMode.LIVE, backend=backend, grant=grant)

    with pytest.raises(ServiceAuthorizationError) as captured:
        service.upsert_base(
            [{"count": 2}],
            step_id="STEP-004",
            target="base://orders/summary",
            data_scope={"date": "2026-08-30", "stores": ["STORE_001"]},
        )
    assert captured.value.error_code == "live_write_grant_expired"
    assert backend.write_calls == 0


def test_jsonl_event_logger_writes_structured_redacted_events(tmp_path: Path) -> None:
    event_path = tmp_path / "runs/run-001/events.jsonl"
    logger = JsonlEventLogger(event_path)

    logger.emit(
        "step.failed",
        app_id="example.offline.export",
        run_id="run-001",
        program_id="offline-export",
        program_version="0.1.0",
        step_id="STEP-002",
        status="failed",
        attempt=2,
        duration_ms=15,
        error_code="fixture_failure",
        evidence_refs=["evidence/STEP-002.json"],
        details={"password": "must-not-leak", "nested": {"access_token": "also-secret"}},
    )

    raw = event_path.read_text(encoding="utf-8")
    assert "must-not-leak" not in raw
    assert "also-secret" not in raw
    event = json.loads(raw)
    assert event["event_type"] == "step.failed"
    assert event["app_id"] == "example.offline.export"
    assert event["run_id"] == "run-001"
    assert event["step_id"] == "STEP-002"
    assert event["attempt"] == 2
    assert event["error_code"] == "fixture_failure"
    assert event["details"]["password"] == "***REDACTED***"
    assert event["details"]["nested"]["access_token"] == "***REDACTED***"


def test_jsonl_event_logger_rejects_symlink_without_appending_outside(
    tmp_path: Path,
) -> None:
    event_path = tmp_path / "runs/run-001/events.jsonl"
    event_path.parent.mkdir(parents=True)
    outside = tmp_path / "outside.log"
    outside.write_text("original\n", encoding="utf-8")
    try:
        event_path.symlink_to(outside)
    except OSError as error:
        pytest.skip(f"symlinks are unavailable in this test environment: {error}")

    before = outside.read_bytes()
    with pytest.raises(EventLogError, match="symbolic link"):
        JsonlEventLogger(event_path)

    assert outside.read_bytes() == before


def test_jsonl_event_logger_rejects_non_regular_target(tmp_path: Path) -> None:
    event_path = tmp_path / "runs/run-001/events.jsonl"
    event_path.mkdir(parents=True)
    logger = JsonlEventLogger(event_path)

    with pytest.raises(EventLogError, match="safely open"):
        logger.emit(
            "run.started",
            app_id="example.offline.export",
            run_id="run-001",
        )


def test_jsonl_event_logger_rejects_hardlink_without_appending_outside(
    tmp_path: Path,
) -> None:
    event_path = tmp_path / "runs/run-001/events.jsonl"
    event_path.parent.mkdir(parents=True)
    outside = tmp_path / "outside.log"
    outside.write_text("original\n", encoding="utf-8")
    try:
        os.link(outside, event_path)
    except OSError as error:
        pytest.skip(f"hard links are unavailable in this test environment: {error}")

    before = outside.read_bytes()
    logger = JsonlEventLogger(event_path)
    with pytest.raises(EventLogError, match="hard link"):
        logger.emit(
            "run.started",
            app_id="example.offline.export",
            run_id="run-001",
        )

    assert outside.read_bytes() == before
