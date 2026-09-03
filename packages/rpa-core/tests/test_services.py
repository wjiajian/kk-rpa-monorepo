from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path

import pytest

from rpa_core.authorization import (
    AuthorizationOperation,
    AuthorizationScope,
    AuthorizationSession,
    AuthorizationStore,
    BrowserAction,
    ExternalWriteScope,
    ExternalWriteStatus,
    external_write_payload_digest,
)
from rpa_core.contracts import RunMode
from rpa_core.events import EventLogError, JsonlEventLogger
from rpa_core.services import (
    ApprovalContext,
    ExternalWriteVerificationError,
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
    authorization: AuthorizationSession | None = None,
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
        authorization=authorization,
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


def issue_write_authorization(
    tmp_path: Path,
    context: ApprovalContext,
    records: list[dict[str, object]],
    *,
    write_id: str | None = None,
) -> tuple[AuthorizationSession, AuthorizationStore]:
    selected_write_id = write_id or PreviewFeishuService.write_id_for(
        context.step_id,
        context.target,
    )
    write_scope = ExternalWriteScope(
        write_id=selected_write_id,
        step_id=context.step_id,
        target=context.target,
        data_scope=dict(context.data_scope),
        expected_record_count=len(records),
        payload_digest=external_write_payload_digest(records),
        adapter="feishu",
    )
    scope = AuthorizationScope(
        app_id=context.app_id,
        app_version="0.1.0",
        program_id="example.offline.export.program",
        program_version="0.1.0",
        requirement_hash="sha256:" + ("a" * 64),
        catalog_digest="sha256:" + ("b" * 64),
        operation=AuthorizationOperation.RUN,
        mode=RunMode.LIVE,
        run_id=context.run_id,
        account_id=context.account_id,
        profile_id="PROFILE_001",
        allowed_origins=("https://example.invalid",),
        step_ids=(context.step_id,),
        browser_actions=(BrowserAction.SCREENSHOT,),
        external_writes=(write_scope,),
        source_preview_run_id="preview-001",
    )
    store = AuthorizationStore(tmp_path / "authorizations")
    now = datetime.now(timezone.utc)
    request = store.create_request(
        scope,
        authorization_id="auth-live-write",
        now=now,
    )
    store.grant(
        request.authorization_id,
        scope_digest=request.scope_digest,
        authorized_by="developer",
        approval_reference="approval-live-write",
        expires_at=now + timedelta(minutes=5),
        now=now + timedelta(microseconds=1),
    )
    return (
        store.claim(
            request.authorization_id,
            scope,
            now=now + timedelta(microseconds=2),
        ),
        store,
    )


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
    assert payload["write_id"] == result.write_id
    assert payload["payload_digest"] == result.payload_digest
    assert result.payload_digest == external_write_payload_digest(payload["records"])
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


def test_live_without_durable_authorization_is_rejected_before_backend(
    tmp_path: Path,
) -> None:
    backend = FakeFeishuBackend()
    service = make_service(tmp_path, mode=RunMode.LIVE, backend=backend)

    with pytest.raises(ServiceAuthorizationError) as captured:
        service.upsert_base(
            [{"count": 2}],
            step_id="STEP-004",
            target="base://orders/summary",
            data_scope={"date": "2026-08-30", "stores": ["STORE_001"]},
        )

    assert captured.value.error_code == "live_write_authorization_missing"
    assert backend.write_calls == 0


def test_legacy_grant_alone_is_not_sufficient_for_live_write(tmp_path: Path) -> None:
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
    )

    with pytest.raises(ServiceAuthorizationError) as captured:
        service.upsert_base(
            [{"count": 2}],
            step_id="STEP-004",
            target="base://orders/summary",
            data_scope={"date": "2026-08-30", "stores": ["STORE_001"]},
        )

    assert captured.value.error_code == "live_write_authorization_missing"
    assert not grant.consumed
    assert backend.write_calls == 0


def test_wrong_grant_scope_is_rejected_without_consuming_grant(tmp_path: Path) -> None:
    backend = FakeFeishuBackend()
    records = [{"count": 2}]
    grant = LiveWriteGrant.issue(
        approved_context(),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
    )
    actual_context = approved_context(account_id="STORE_002")
    authorization, store = issue_write_authorization(
        tmp_path,
        actual_context,
        records,
    )
    service = make_service(
        tmp_path,
        mode=RunMode.LIVE,
        backend=backend,
        grant=grant,
        authorization=authorization,
        account_id="STORE_002",
    )

    with pytest.raises(ServiceAuthorizationError) as captured:
        service.upsert_base(
            records,
            step_id="STEP-004",
            target="base://orders/summary",
            data_scope={"date": "2026-08-30", "stores": ["STORE_001"]},
        )

    assert captured.value.error_code == "live_write_scope_mismatch"
    assert not grant.consumed
    assert store.load("auth-live-write").write_claims == ()
    assert backend.write_calls == 0


def test_live_grant_is_revalidated_consumed_and_cannot_be_replayed(tmp_path: Path) -> None:
    backend = FakeFeishuBackend()
    context = approved_context()
    grant = LiveWriteGrant.issue(
        context,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
    )
    records = [{"count": 2}]
    authorization, store = issue_write_authorization(tmp_path, context, records)
    service = make_service(
        tmp_path,
        mode=RunMode.LIVE,
        backend=backend,
        grant=grant,
        authorization=authorization,
    )
    kwargs = {
        "step_id": context.step_id,
        "target": context.target,
        "data_scope": dict(context.data_scope),
    }

    result = service.upsert_base(records, **kwargs)
    assert result.mode == "live"
    assert grant.consumed
    assert backend.write_calls == 1
    assert backend.read_back_calls == 1
    assert result.read_back_record_count == len(records)
    assert result.read_back_payload_digest == result.payload_digest
    persisted = store.load("auth-live-write")
    assert persisted.write_claims[0].status is ExternalWriteStatus.SUCCEEDED

    with pytest.raises(ServiceAuthorizationError) as captured:
        service.upsert_base([{"count": 3}], **kwargs)
    assert captured.value.error_code == "live_write_grant_consumed"
    assert backend.write_calls == 1


def test_expired_live_grant_is_rejected(tmp_path: Path) -> None:
    backend = FakeFeishuBackend()
    records = [{"count": 2}]
    context = approved_context()
    grant = LiveWriteGrant.issue(
        context,
        expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
    )
    authorization, store = issue_write_authorization(tmp_path, context, records)
    service = make_service(
        tmp_path,
        mode=RunMode.LIVE,
        backend=backend,
        grant=grant,
        authorization=authorization,
    )

    with pytest.raises(ServiceAuthorizationError) as captured:
        service.upsert_base(
            records,
            step_id="STEP-004",
            target="base://orders/summary",
            data_scope={"date": "2026-08-30", "stores": ["STORE_001"]},
        )
    assert captured.value.error_code == "live_write_grant_expired"
    assert store.load("auth-live-write").write_claims == ()
    assert backend.write_calls == 0


def test_durable_authorization_alone_executes_exact_live_write(
    tmp_path: Path,
) -> None:
    backend = FakeFeishuBackend()
    context = approved_context()
    records = [{"count": 2}]
    authorization, store = issue_write_authorization(tmp_path, context, records)
    service = make_service(
        tmp_path,
        mode=RunMode.LIVE,
        backend=backend,
        authorization=authorization,
    )

    result = service.upsert_base(
        records,
        step_id=context.step_id,
        target=context.target,
        data_scope=dict(context.data_scope),
    )

    assert result.mode == "live"
    assert result.write_id == PreviewFeishuService.write_id_for(
        context.step_id,
        context.target,
    )
    assert backend.write_calls == 1
    assert backend.read_back_calls == 1
    assert result.read_back_record_count == len(records)
    assert result.read_back_payload_digest == external_write_payload_digest(records)
    assert backend.read_backs == [
        {
            "target": context.target,
            "data_scope": {
                "date": "2026-08-30",
                "stores": ["STORE_001"],
            },
        }
    ]
    persisted = store.load("auth-live-write")
    assert persisted.write_claims[0].status is ExternalWriteStatus.SUCCEEDED


def test_durable_write_claim_rejects_changed_payload_before_backend(
    tmp_path: Path,
) -> None:
    backend = FakeFeishuBackend()
    context = approved_context()
    authorization, store = issue_write_authorization(
        tmp_path,
        context,
        [{"count": 2}],
    )
    service = make_service(
        tmp_path,
        mode=RunMode.LIVE,
        backend=backend,
        authorization=authorization,
    )

    with pytest.raises(ServiceAuthorizationError) as captured:
        service.upsert_base(
            [{"count": 3}],
            step_id=context.step_id,
            target=context.target,
            data_scope=dict(context.data_scope),
        )

    assert captured.value.error_code == "external_write_scope_mismatch"
    assert store.load("auth-live-write").write_claims == ()
    assert backend.write_calls == 0


def test_backend_exception_persists_unknown_write_outcome_and_is_reraised(
    tmp_path: Path,
) -> None:
    class BackendFailure(RuntimeError):
        error_code = "simulated_backend_failure"

    class FailingBackend(FakeFeishuBackend):
        def upsert_base(self, records, *, target, data_scope):
            self.write_calls += 1
            raise BackendFailure("sensitive backend details")

    backend = FailingBackend()
    context = approved_context()
    records = [{"count": 2}]
    authorization, store = issue_write_authorization(tmp_path, context, records)
    grant = LiveWriteGrant.issue(
        context,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
    )
    service = make_service(
        tmp_path,
        mode=RunMode.LIVE,
        backend=backend,
        grant=grant,
        authorization=authorization,
    )

    with pytest.raises(BackendFailure, match="sensitive backend details"):
        service.upsert_base(
            records,
            step_id=context.step_id,
            target=context.target,
            data_scope=dict(context.data_scope),
        )

    assert grant.consumed
    assert backend.write_calls == 1
    persisted = store.load("auth-live-write")
    assert persisted.write_claims[0].status is ExternalWriteStatus.UNKNOWN
    assert persisted.write_claims[0].error_code == "simulated_backend_failure"
    assert "sensitive backend details" not in (
        store.root / "auth-live-write.json"
    ).read_text(encoding="utf-8")


def test_live_write_without_read_back_capability_is_rejected_before_write(
    tmp_path: Path,
) -> None:
    class WriteOnlyBackend:
        def __init__(self) -> None:
            self.write_calls = 0

        def upsert_base(self, records, *, target, data_scope):
            self.write_calls += 1
            return {"written": len(records)}

    backend = WriteOnlyBackend()
    context = approved_context()
    records = [{"count": 2}]
    authorization, store = issue_write_authorization(tmp_path, context, records)
    service = PreviewFeishuService(
        mode=RunMode.LIVE,
        app_id=context.app_id,
        run_id=context.run_id,
        account_id=context.account_id,
        run_dir=tmp_path / "runs" / context.run_id,
        backend=backend,
        authorization=authorization,
    )

    with pytest.raises(ExternalWriteVerificationError) as captured:
        service.upsert_base(
            records,
            step_id=context.step_id,
            target=context.target,
            data_scope=dict(context.data_scope),
        )

    assert captured.value.error_code == "external_write_readback_unavailable"
    assert backend.write_calls == 0
    assert store.load("auth-live-write").write_claims == ()


def test_live_write_read_back_mismatch_is_unknown_and_not_success(
    tmp_path: Path,
) -> None:
    class MismatchingBackend(FakeFeishuBackend):
        def read_back_base(self, *, target, data_scope):
            self.read_back_calls += 1
            return [{"count": 999}]

    backend = MismatchingBackend()
    context = approved_context()
    records = [{"count": 2}]
    authorization, store = issue_write_authorization(tmp_path, context, records)
    service = make_service(
        tmp_path,
        mode=RunMode.LIVE,
        backend=backend,
        authorization=authorization,
    )

    with pytest.raises(ExternalWriteVerificationError) as captured:
        service.upsert_base(
            records,
            step_id=context.step_id,
            target=context.target,
            data_scope=dict(context.data_scope),
        )

    assert captured.value.error_code == "external_write_readback_mismatch"
    assert backend.write_calls == 1
    assert backend.read_back_calls == 1
    persisted = store.load("auth-live-write")
    assert persisted.write_claims[0].status is ExternalWriteStatus.UNKNOWN
    assert persisted.write_claims[0].error_code == "external_write_readback_mismatch"


def test_live_write_read_back_exception_is_unknown_and_reraised(
    tmp_path: Path,
) -> None:
    class ReadBackFailure(RuntimeError):
        error_code = "simulated_readback_failure"

    class ReadBackFailingBackend(FakeFeishuBackend):
        def read_back_base(self, *, target, data_scope):
            self.read_back_calls += 1
            raise ReadBackFailure("sensitive read-back details")

    backend = ReadBackFailingBackend()
    context = approved_context()
    records = [{"count": 2}]
    authorization, store = issue_write_authorization(tmp_path, context, records)
    service = make_service(
        tmp_path,
        mode=RunMode.LIVE,
        backend=backend,
        authorization=authorization,
    )

    with pytest.raises(ReadBackFailure, match="sensitive read-back details"):
        service.upsert_base(
            records,
            step_id=context.step_id,
            target=context.target,
            data_scope=dict(context.data_scope),
        )

    assert backend.write_calls == 1
    assert backend.read_back_calls == 1
    persisted = store.load("auth-live-write")
    assert persisted.write_claims[0].status is ExternalWriteStatus.UNKNOWN
    assert persisted.write_claims[0].error_code == "simulated_readback_failure"
    assert "sensitive read-back details" not in (
        store.root / "auth-live-write.json"
    ).read_text(encoding="utf-8")


def test_live_write_invalid_read_back_is_unknown(
    tmp_path: Path,
) -> None:
    class InvalidReadBackBackend(FakeFeishuBackend):
        def read_back_base(self, *, target, data_scope):
            self.read_back_calls += 1
            return {"records": [{"count": 2}]}

    backend = InvalidReadBackBackend()
    context = approved_context()
    records = [{"count": 2}]
    authorization, store = issue_write_authorization(tmp_path, context, records)
    service = make_service(
        tmp_path,
        mode=RunMode.LIVE,
        backend=backend,
        authorization=authorization,
    )

    with pytest.raises(ExternalWriteVerificationError) as captured:
        service.upsert_base(
            records,
            step_id=context.step_id,
            target=context.target,
            data_scope=dict(context.data_scope),
        )

    assert captured.value.error_code == "external_write_readback_invalid"
    assert backend.write_calls == 1
    assert backend.read_back_calls == 1
    persisted = store.load("auth-live-write")
    assert persisted.write_claims[0].status is ExternalWriteStatus.UNKNOWN
    assert persisted.write_claims[0].error_code == "external_write_readback_invalid"


def test_live_write_backend_cannot_mutate_authorized_payload_before_verification(
    tmp_path: Path,
) -> None:
    class MutatingBackend(FakeFeishuBackend):
        def upsert_base(self, records, *, target, data_scope):
            records[0]["count"] = 999
            data_scope["date"] = "2099-01-01"
            return super().upsert_base(records, target=target, data_scope=data_scope)

    backend = MutatingBackend()
    context = approved_context()
    records = [{"count": 2}]
    authorization, store = issue_write_authorization(tmp_path, context, records)
    service = make_service(
        tmp_path,
        mode=RunMode.LIVE,
        backend=backend,
        authorization=authorization,
    )

    with pytest.raises(ExternalWriteVerificationError) as captured:
        service.upsert_base(
            records,
            step_id=context.step_id,
            target=context.target,
            data_scope=dict(context.data_scope),
        )

    assert captured.value.error_code == "external_write_readback_mismatch"
    assert records == [{"count": 2}]
    persisted = store.load("auth-live-write")
    assert persisted.write_claims[0].status is ExternalWriteStatus.UNKNOWN
    assert persisted.write_claims[0].error_code == "external_write_readback_mismatch"


def test_external_write_payload_digest_is_strict_and_canonical() -> None:
    assert external_write_payload_digest([{"b": 2, "a": 1}]) == (
        external_write_payload_digest([{"a": 1, "b": 2}])
    )
    assert external_write_payload_digest([{"id": 1}, {"id": 2}]) != (
        external_write_payload_digest([{"id": 2}, {"id": 1}])
    )
    with pytest.raises(ValueError):
        external_write_payload_digest([{"count": float("nan")}])


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
