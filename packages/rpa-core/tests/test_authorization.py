from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
import multiprocessing
import os
from pathlib import Path
import stat

import pytest
from pydantic import ValidationError

from rpa_core import authorization as authorization_module
from rpa_core.authorization import (
    AuthorizationAlreadyClaimedError,
    AuthorizationExpiredError,
    AuthorizationNotGrantedError,
    AuthorizationOperation,
    AuthorizationRecordInvalidError,
    AuthorizationRevokedError,
    AuthorizationScope,
    AuthorizationScopeMismatchError,
    AuthorizationSession,
    AuthorizationStatus,
    AuthorizationStore,
    AuthorizationStoreUnsafeError,
    AuthorizedBrowserActions,
    BrowserAction,
    BrowserActionNotAuthorizedError,
    BrowserElementNotAuthorizedError,
    BrowserOriginNotAuthorizedError,
    BrowserStepNotAuthorizedError,
    ExternalWriteAlreadyClaimedError,
    ExternalWriteScope,
    ExternalWriteScopeMismatchError,
    ExternalWriteStatus,
    authorization_scope_digest,
    catalog_lock_digest,
)
from rpa_core.browser import ElementSpec, FakeBrowserActions, Locator
from rpa_core.catalog import CatalogLock
from rpa_core.contracts import RunMode
from rpa_core.runtime import ExecutionContext, RuntimeContractError


BASE_TIME = datetime(2026, 9, 3, 8, 0, tzinfo=UTC)
HASH_A = "sha256:" + ("a" * 64)
HASH_B = "sha256:" + ("b" * 64)
ELEMENT = ElementSpec("example.inventory.marker", "marker", "inventory")
OTHER_ELEMENT = ElementSpec("example.inventory.other", "other", "inventory")
FRAMED_ELEMENT = ElementSpec(
    "example.inventory.framed-marker",
    "framed marker",
    "inventory",
    locator=Locator("#marker"),
    frame_locator=Locator("#inventory-frame"),
)


def make_scope(
    *,
    operation: AuthorizationOperation = AuthorizationOperation.RUN,
    mode: RunMode = RunMode.PREVIEW,
    run_id: str = "run-001",
    resume_checkpoint_digest: str | None = None,
    resume_step_id: str | None = None,
    browser_actions: tuple[BrowserAction, ...] = tuple(BrowserAction),
    element_ids: tuple[str, ...] = (ELEMENT.id,),
    candidate_asset_refs: tuple[str, ...] = (),
    external_writes: tuple[ExternalWriteScope, ...] = (),
    source_preview_run_id: str | None = None,
) -> AuthorizationScope:
    return AuthorizationScope(
        app_id="example.inventory.export",
        app_version="0.1.0",
        program_id="example.inventory.export.program",
        program_version="0.1.0",
        requirement_hash=HASH_A,
        catalog_digest=HASH_B,
        operation=operation,
        mode=mode,
        run_id=run_id,
        resume_checkpoint_digest=resume_checkpoint_digest,
        resume_step_id=resume_step_id,
        account_id="STORE_001",
        profile_id="PROFILE_001",
        allowed_origins=("https://example.invalid",),
        step_ids=("STEP-001",),
        browser_actions=browser_actions,
        element_ids=element_ids,
        candidate_asset_refs=candidate_asset_refs,
        external_writes=external_writes,
        source_preview_run_id=source_preview_run_id,
    )


def request_and_grant(
    store: AuthorizationStore,
    scope: AuthorizationScope,
    *,
    authorization_id: str = "auth-001",
    expires_at: datetime = BASE_TIME + timedelta(minutes=10),
) -> str:
    request = store.create_request(
        scope,
        requested_by="developer",
        authorization_id=authorization_id,
        now=BASE_TIME,
    )
    store.grant(
        authorization_id,
        scope_digest=request.scope_digest,
        authorized_by="developer",
        approval_reference="approval-001",
        expires_at=expires_at,
        now=BASE_TIME + timedelta(seconds=1),
    )
    return authorization_id


def claim_in_process(
    root: str,
    authorization_id: str,
    scope_payload: dict[str, object],
    start: object,
    results: object,
) -> None:
    start.wait(10)
    try:
        session = AuthorizationStore(root).claim(
            authorization_id,
            scope_payload,
            now=BASE_TIME + timedelta(seconds=2),
        )
    except Exception as error:
        results.put(("error", getattr(error, "error_code", type(error).__name__)))
    else:
        results.put(("claimed", session.claim_id))


def test_record_lifecycle_is_persisted_and_single_use(tmp_path: Path) -> None:
    store = AuthorizationStore(tmp_path / "authorizations")
    scope = make_scope()
    authorization_id = request_and_grant(store, scope)

    session = store.claim(
        authorization_id,
        scope,
        now=BASE_TIME + timedelta(seconds=2),
    )

    persisted = store.load(authorization_id)
    assert persisted.schema_version == 1
    assert persisted.status is AuthorizationStatus.CLAIMED
    assert persisted.claim is not None
    assert persisted.claim.claim_id == session.claim_id
    record_path = tmp_path / "authorizations" / "auth-001.json"
    assert stat.S_IMODE(record_path.stat().st_mode) == 0o600

    with pytest.raises(AuthorizationAlreadyClaimedError):
        store.claim(
            authorization_id,
            scope,
            now=BASE_TIME + timedelta(seconds=3),
        )

    completed = session.finish(
        status=AuthorizationStatus.SUCCEEDED,
        evidence_refs=("runs/run-001/evidence.json",),
        now=BASE_TIME + timedelta(seconds=4),
    )
    assert completed.status is AuthorizationStatus.SUCCEEDED
    assert completed.outcome is not None
    assert completed.outcome.evidence_refs == ("runs/run-001/evidence.json",)

    with pytest.raises(AuthorizationAlreadyClaimedError):
        session.assert_active(now=BASE_TIME + timedelta(seconds=5))


def test_scope_mismatch_does_not_consume_grant(tmp_path: Path) -> None:
    store = AuthorizationStore(tmp_path / "authorizations")
    scope = make_scope()
    authorization_id = request_and_grant(store, scope)
    different = make_scope(run_id="run-002")

    with pytest.raises(AuthorizationScopeMismatchError):
        store.claim(
            authorization_id,
            different,
            now=BASE_TIME + timedelta(seconds=2),
        )

    assert store.load(authorization_id).status is AuthorizationStatus.GRANTED
    assert store.claim(
        authorization_id,
        scope,
        now=BASE_TIME + timedelta(seconds=3),
    ).scope == scope


def test_request_must_be_granted_unexpired_and_not_revoked(tmp_path: Path) -> None:
    scope = make_scope()
    ungranted = AuthorizationStore(tmp_path / "ungranted")
    ungranted.create_request(
        scope,
        authorization_id="auth-requested",
        now=BASE_TIME,
    )
    with pytest.raises(AuthorizationNotGrantedError):
        ungranted.claim(
            "auth-requested",
            scope,
            now=BASE_TIME + timedelta(seconds=1),
        )

    expired = AuthorizationStore(tmp_path / "expired")
    request_and_grant(
        expired,
        scope,
        authorization_id="auth-expired",
        expires_at=BASE_TIME + timedelta(seconds=2),
    )
    with pytest.raises(AuthorizationExpiredError):
        expired.claim(
            "auth-expired",
            scope,
            now=BASE_TIME + timedelta(seconds=2),
        )

    revoked = AuthorizationStore(tmp_path / "revoked")
    request_and_grant(revoked, scope, authorization_id="auth-revoked")
    record = revoked.revoke(
        "auth-revoked",
        revoked_by="developer",
        reason="scope is no longer needed",
        now=BASE_TIME + timedelta(seconds=2),
    )
    assert record.status is AuthorizationStatus.REVOKED
    with pytest.raises(AuthorizationRevokedError):
        revoked.claim(
            "auth-revoked",
            scope,
            now=BASE_TIME + timedelta(seconds=3),
        )


def test_grant_requires_exact_acknowledged_digest_and_aware_expiry(
    tmp_path: Path,
) -> None:
    store = AuthorizationStore(tmp_path / "authorizations")
    request = store.create_request(
        make_scope(),
        authorization_id="auth-001",
        now=BASE_TIME,
    )

    with pytest.raises(AuthorizationScopeMismatchError):
        store.grant(
            request.authorization_id,
            scope_digest=HASH_A,
            authorized_by="developer",
            approval_reference="approval-001",
            expires_at=BASE_TIME + timedelta(minutes=1),
            now=BASE_TIME + timedelta(seconds=1),
        )
    assert store.load(request.authorization_id).status is AuthorizationStatus.REQUESTED

    with pytest.raises(ValueError, match="timezone"):
        store.grant(
            request.authorization_id,
            scope_digest=request.scope_digest,
            authorized_by="developer",
            approval_reference="approval-001",
            expires_at=datetime(2026, 9, 3, 9, 0),
            now=BASE_TIME + timedelta(seconds=1),
        )


def test_concurrent_claim_is_cross_process_atomic(tmp_path: Path) -> None:
    store = AuthorizationStore(tmp_path / "authorizations")
    scope = make_scope()
    authorization_id = request_and_grant(store, scope)
    context = multiprocessing.get_context("spawn")
    start = context.Event()
    results = context.Queue()
    payload = scope.model_dump(mode="json")
    processes = [
        context.Process(
            target=claim_in_process,
            args=(str(store.root), authorization_id, payload, start, results),
        )
        for _ in range(2)
    ]
    for process in processes:
        process.start()
    start.set()
    outcomes = [results.get(timeout=15) for _ in processes]
    for process in processes:
        process.join(timeout=15)
        assert process.exitcode == 0

    assert [kind for kind, _ in outcomes].count("claimed") == 1
    assert [value for kind, value in outcomes if kind == "error"] == [
        "authorization_already_claimed"
    ]


def test_default_clock_is_read_only_after_record_lock_is_acquired(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = AuthorizationStore(tmp_path / "authorizations")
    scope = make_scope()
    authorization_id = request_and_grant(store, scope)
    original_record_lock = store._record_lock
    events: list[str] = []

    class ObservedLock:
        def __init__(self, delegate: object) -> None:
            self.delegate = delegate

        def __enter__(self) -> object:
            entered = self.delegate.__enter__()
            events.append("locked")
            return entered

        def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
            self.delegate.__exit__(exc_type, exc, traceback)

    monkeypatch.setattr(
        store,
        "_record_lock",
        lambda selected_id: ObservedLock(original_record_lock(selected_id)),
    )

    def observed_now() -> datetime:
        events.append("now")
        return BASE_TIME + timedelta(seconds=2)

    monkeypatch.setattr(authorization_module, "_utc_now", observed_now)

    store.claim(authorization_id, scope)

    assert events[:2] == ["locked", "now"]


def test_atomic_writer_handles_short_os_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_write = os.write

    def short_write(descriptor: int, payload: bytes) -> int:
        return original_write(descriptor, payload[:17])

    monkeypatch.setattr(authorization_module.os, "write", short_write)
    store = AuthorizationStore(tmp_path / "authorizations")

    created = store.create_request(
        make_scope(),
        authorization_id="auth-short-write",
        now=BASE_TIME,
    )

    assert store.load(created.authorization_id) == created


def test_duplicate_json_keys_and_unsafe_links_fail_closed(tmp_path: Path) -> None:
    duplicate_store = AuthorizationStore(tmp_path / "duplicate")
    request_and_grant(duplicate_store, make_scope())
    duplicate_path = duplicate_store.root / "auth-001.json"
    duplicate_path.write_text('{"schema_version":1,"schema_version":1}\n')
    with pytest.raises(AuthorizationRecordInvalidError, match="duplicate JSON key"):
        duplicate_store.load("auth-001")

    linked_store = AuthorizationStore(tmp_path / "hardlink")
    request_and_grant(linked_store, make_scope())
    os.link(linked_store.root / "auth-001.json", linked_store.root / "alias.json")
    with pytest.raises(AuthorizationStoreUnsafeError):
        linked_store.load("auth-001")

    real_root = tmp_path / "real-root"
    real_root.mkdir()
    symlink_root = tmp_path / "linked-root"
    symlink_root.symlink_to(real_root, target_is_directory=True)
    with pytest.raises(AuthorizationStoreUnsafeError):
        AuthorizationStore(symlink_root).load("auth-missing")


def test_store_boundary_rejects_escape_and_symlinked_ancestors(
    tmp_path: Path,
) -> None:
    boundary = tmp_path / "app"
    boundary.mkdir()
    with pytest.raises(AuthorizationStoreUnsafeError, match="trusted boundary"):
        AuthorizationStore(
            tmp_path / "outside" / "authorizations",
            boundary=boundary,
        )
    with pytest.raises(AuthorizationStoreUnsafeError, match="trusted boundary"):
        AuthorizationStore(
            boundary / ".." / "escaped" / "authorizations",
            boundary=boundary,
        )
    assert not (tmp_path / "outside").exists()
    assert not (tmp_path / "escaped").exists()

    outside = tmp_path / "linked-target"
    outside.mkdir()
    runtime_link = boundary / "runtime"
    try:
        runtime_link.symlink_to(outside, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"symlinks are unavailable in this test environment: {error}")
    store = AuthorizationStore(
        runtime_link / "authorizations",
        boundary=boundary,
    )

    with pytest.raises(AuthorizationStoreUnsafeError, match="symbolic links"):
        store.create_request(
            make_scope(),
            authorization_id="auth-boundary",
            now=BASE_TIME,
        )
    assert list(outside.iterdir()) == []


def test_store_boundary_allows_safe_missing_directories_and_rejects_files(
    tmp_path: Path,
) -> None:
    boundary = tmp_path / "app"
    boundary.mkdir()
    safe_store = AuthorizationStore(
        boundary / "runtime" / "authorizations",
        boundary=boundary,
    )

    created = safe_store.create_request(
        make_scope(),
        authorization_id="auth-safe-boundary",
        now=BASE_TIME,
    )
    assert safe_store.load(created.authorization_id) == created

    file_boundary = tmp_path / "file-boundary"
    file_boundary.write_text("not a directory", encoding="utf-8")
    unsafe_store = AuthorizationStore(
        file_boundary / "authorizations",
        boundary=file_boundary,
    )
    with pytest.raises(AuthorizationStoreUnsafeError, match="must be directories"):
        unsafe_store.load("auth-missing")


def test_catalog_and_scope_digests_are_canonical() -> None:
    first = CatalogLock.model_validate(
        {
            "schema_version": 1,
            "items": [
                {
                    "kind": "element",
                    "id": "example.marker",
                    "version": "1.0.0",
                    "status": "candidate",
                    "source_type": "application_candidate",
                    "source_path": "src/example/elements/marker.toml",
                    "target_path": "src/example/elements/marker.toml",
                    "content_hash": HASH_A,
                    "dependencies": [],
                    "copied_at": "2026-09-03T08:00:00Z",
                }
            ],
        }
    )
    second = first.model_copy(
        update={
            "items": [
                first.items[0].model_copy(
                    update={"copied_at": "2026-09-04T08:00:00Z"}
                )
            ]
        }
    )

    assert catalog_lock_digest(first) == catalog_lock_digest(second)
    assert authorization_scope_digest(make_scope()) == authorization_scope_digest(
        make_scope().model_dump(mode="json")
    )


def claimed_session(
    tmp_path: Path,
    *,
    scope: AuthorizationScope | None = None,
    expires_at: datetime = BASE_TIME + timedelta(minutes=10),
) -> AuthorizationSession:
    store = AuthorizationStore(tmp_path / "authorizations")
    selected_scope = scope or make_scope()
    request_and_grant(store, selected_scope, expires_at=expires_at)
    return store.claim(
        "auth-001",
        selected_scope,
        now=BASE_TIME + timedelta(seconds=2),
    )


def test_authorized_browser_checks_origin_step_action_and_element(
    tmp_path: Path,
) -> None:
    scope = make_scope(browser_actions=(BrowserAction.TEXT,))
    session = claimed_session(tmp_path, scope=scope)
    fake = FakeBrowserActions(
        tmp_path / "run",
        visible_element_ids=(ELEMENT.id, OTHER_ELEMENT.id),
        text_values={ELEMENT.id: "expected", OTHER_ELEMENT.id: "other"},
    )
    fake.open("https://example.invalid/inventory")
    wrapped = AuthorizedBrowserActions(
        fake,
        session,
        step_id_getter=lambda: "STEP-001",
    )

    assert wrapped.text(ELEMENT) == "expected"
    assert fake.actions[-1].action == "text"

    with pytest.raises(BrowserActionNotAuthorizedError):
        wrapped.click(ELEMENT)
    with pytest.raises(BrowserElementNotAuthorizedError):
        wrapped.text(OTHER_ELEMENT)

    before = tuple(fake.actions)
    no_step = AuthorizedBrowserActions(fake, session)
    with pytest.raises(BrowserStepNotAuthorizedError):
        no_step.text(ELEMENT)
    assert tuple(fake.actions) == before

    fake.current_url = "https://unexpected.invalid/inventory"
    with pytest.raises(BrowserOriginNotAuthorizedError):
        wrapped.text(ELEMENT)
    assert tuple(fake.actions) == before


def test_authorized_browser_checks_navigation_before_and_after_delegate(
    tmp_path: Path,
) -> None:
    session = claimed_session(tmp_path)
    fake = FakeBrowserActions(
        tmp_path / "run",
        visible_element_ids=(ELEMENT.id,),
    )
    wrapped = AuthorizedBrowserActions(
        fake,
        session,
        step_id_getter=lambda: "STEP-001",
    )

    with pytest.raises(BrowserOriginNotAuthorizedError):
        wrapped.open("https://unexpected.invalid/login")
    assert fake.actions == []

    wrapped.open("https://example.invalid/login")
    assert fake.current_url == "https://example.invalid/login"

    class RedirectingBrowser:
        current_url = "https://example.invalid/inventory"

        def __init__(self) -> None:
            self.clicked = False

        def click(
            self,
            element: ElementSpec,
            *,
            context_guard: object = None,
        ) -> None:
            self.clicked = True
            self.current_url = "https://unexpected.invalid/redirect"

    redirecting = RedirectingBrowser()
    redirect_wrapped = AuthorizedBrowserActions(
        redirecting,  # type: ignore[arg-type]
        session,
        step_id_getter=lambda: "STEP-001",
    )
    with pytest.raises(BrowserOriginNotAuthorizedError):
        redirect_wrapped.click(ELEMENT)
    assert redirecting.clicked


def test_authorized_browser_does_not_authorize_embedded_origin_separately(
    tmp_path: Path,
) -> None:
    scope = make_scope(
        browser_actions=(BrowserAction.TEXT,),
        element_ids=(FRAMED_ELEMENT.id,),
    )
    session = claimed_session(tmp_path, scope=scope)

    class FrameContextBrowser:
        current_url = "https://example.invalid/inventory"

        def __init__(self) -> None:
            self.read = False

        def text(
            self,
            element: ElementSpec,
        ) -> str:
            assert element is FRAMED_ELEMENT
            self.read = True
            return "expected"

    embedded = FrameContextBrowser()
    wrapped = AuthorizedBrowserActions(
        embedded,  # type: ignore[arg-type]
        session,
        step_id_getter=lambda: "STEP-001",
    )

    assert wrapped.text(FRAMED_ELEMENT) == "expected"
    assert embedded.read is True


def test_external_write_has_independent_exact_single_use_claim(
    tmp_path: Path,
) -> None:
    write_scope = ExternalWriteScope(
        write_id="write-001",
        step_id="STEP-001",
        target="feishu://base/app/table",
        data_scope={"date": "2026-09-03", "stores": ["STORE_001"]},
        expected_record_count=2,
        payload_digest=HASH_A,
        adapter="feishu",
    )
    scope = make_scope(
        mode=RunMode.LIVE,
        external_writes=(write_scope,),
        source_preview_run_id="preview-001",
    )
    session = claimed_session(
        tmp_path,
        scope=scope,
        expires_at=BASE_TIME + timedelta(seconds=5),
    )
    mismatched = write_scope.model_copy(update={"expected_record_count": 3})

    with pytest.raises(ExternalWriteScopeMismatchError):
        session.claim_write(
            mismatched,
            now=BASE_TIME + timedelta(seconds=3),
        )
    assert session._store.load("auth-001").write_claims == ()

    claimed = session.claim_write(
        write_scope,
        now=BASE_TIME + timedelta(seconds=4),
    )
    assert claimed.status is ExternalWriteStatus.CLAIMED
    with pytest.raises(ExternalWriteAlreadyClaimedError):
        session.claim_write(
            write_scope,
            now=BASE_TIME + timedelta(seconds=4),
        )
    with pytest.raises(ValidationError, match="unfinished write claim"):
        session.finish(
            status=AuthorizationStatus.SUCCEEDED,
            now=BASE_TIME + timedelta(seconds=4),
        )

    completed = session.finish_write(
        write_scope.write_id,
        status=ExternalWriteStatus.SUCCEEDED,
        now=BASE_TIME + timedelta(seconds=6),
    )
    assert completed.status is ExternalWriteStatus.SUCCEEDED
    record = session.finish(
        status=AuthorizationStatus.SUCCEEDED,
        now=BASE_TIME + timedelta(seconds=7),
    )
    assert record.status is AuthorizationStatus.SUCCEEDED


def test_mutating_session_write_scope_cannot_expand_persisted_grant(
    tmp_path: Path,
) -> None:
    write_scope = ExternalWriteScope(
        write_id="write-001",
        step_id="STEP-001",
        target="database://inventory",
        data_scope={"stores": ["STORE_001"]},
        expected_record_count=1,
        payload_digest=HASH_A,
        adapter="database",
    )
    scope = make_scope(
        mode=RunMode.LIVE,
        external_writes=(write_scope,),
        source_preview_run_id="preview-001",
    )
    session = claimed_session(tmp_path, scope=scope)
    session.scope.external_writes[0].data_scope["stores"].append("STORE_002")

    with pytest.raises(AuthorizationScopeMismatchError):
        session.claim_write(session.scope.external_writes[0])
    assert session._store.load("auth-001").write_claims == ()


def test_scope_operation_rules_and_origin_normalization() -> None:
    with pytest.raises(ValidationError, match="resume authorization requires"):
        make_scope(operation=AuthorizationOperation.RESUME)
    with pytest.raises(ValidationError, match="resume authorization requires"):
        make_scope(
            operation=AuthorizationOperation.RESUME,
            resume_checkpoint_digest=HASH_A,
        )
    with pytest.raises(ValidationError, match="only valid for resume"):
        make_scope(resume_checkpoint_digest=HASH_A, resume_step_id="STEP-001")

    resumed = make_scope(
        operation=AuthorizationOperation.RESUME,
        resume_checkpoint_digest=HASH_A,
        resume_step_id="STEP-001",
    )
    assert resumed.resume_checkpoint_digest == HASH_A
    assert resumed.resume_step_id == "STEP-001"

    with pytest.raises(ValidationError, match="candidate_asset_refs"):
        make_scope(operation=AuthorizationOperation.VERIFY_CANDIDATES)
    with pytest.raises(ValidationError, match="only valid for verify_candidates"):
        make_scope(candidate_asset_refs=("element:example.marker",))
    with pytest.raises(ValidationError, match="source_preview_run_id"):
        make_scope(source_preview_run_id="preview-001")
    write_scope = ExternalWriteScope(
        write_id="write-001",
        step_id="STEP-001",
        target="database://inventory",
        expected_record_count=1,
        payload_digest=HASH_A,
    )
    with pytest.raises(ValidationError, match="require source_preview_run_id"):
        make_scope(mode=RunMode.LIVE, external_writes=(write_scope,))
    with pytest.raises(ValidationError, match="outside step_ids"):
        make_scope(
            mode=RunMode.LIVE,
            external_writes=(write_scope.model_copy(update={"step_id": "STEP-999"}),),
            source_preview_run_id="preview-001",
        )
    with pytest.raises(ValidationError, match="must also appear in element_ids"):
        make_scope(
            operation=AuthorizationOperation.VERIFY_CANDIDATES,
            candidate_asset_refs=("element:example.missing",),
        )

    verified = make_scope(
        operation=AuthorizationOperation.VERIFY_CANDIDATES,
        candidate_asset_refs=(f"element:{ELEMENT.id}",),
    )
    assert verified.operation.value == "verify_candidates"

    ipv6_document = make_scope().model_dump(mode="python")
    ipv6_document["allowed_origins"] = ("HTTPS://[::1]:443/",)
    assert AuthorizationScope.model_validate(ipv6_document).allowed_origins == (
        "https://[::1]",
    )


def test_execution_context_exposes_authorization_outside_checkpoint_identity(
    tmp_path: Path,
) -> None:
    session = claimed_session(tmp_path)
    context = ExecutionContext(
        app_id="example.inventory.export",
        program_id="example.inventory.export.program",
        program_version="0.1.0",
        requirement_hash=HASH_A,
        run_id="run-001",
        account_id="STORE_001",
        mode=RunMode.PREVIEW,
        run_dir=tmp_path / "run",
        services={"authorization": session},
    )

    assert context.authorization is session
    assert "authorization" not in context.identity
    assert "authorization_id" not in context.identity

    context.services["authorization"] = object()
    with pytest.raises(RuntimeContractError, match="AuthorizationSession"):
        _ = context.authorization
