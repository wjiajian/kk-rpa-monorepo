from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from rpa_core.authorization import (
    AuthorizationExpiredError,
    AuthorizationOperation,
    AuthorizationSession,
    AuthorizationStatus,
    AuthorizationStore,
)
from rpa_core.browser import SecretValue
from rpa_core.browser_manager import (
    BrowserHandoff,
    BrowserLifecyclePolicy,
    BrowserStartError,
)
from rpa_core.catalog import (
    CatalogItemStatus,
    CatalogSourceType,
    verify_catalog_snapshot,
)

from inventory_jushuitan_export_stock import real_runtime
from inventory_jushuitan_export_stock.instructions import build_instruction_registry
from inventory_jushuitan_export_stock.models import LoginCredentials, load_login_credentials
from inventory_jushuitan_export_stock.program import (
    APP_ID,
    PROGRAM_ID,
    PROGRAM_VERSION,
)

from .helpers import REQUIREMENT_HASH, make_browser, make_store


SOURCE_APP_DIR = real_runtime.APP_DIR


def test_login_identity_uses_explicit_env_or_username_fallback() -> None:
    explicit_store = make_store()
    values = {
        explicit_store.username_env: "fixture-user",
        explicit_store.password_env: "fixture-secret",
        explicit_store.identity_env: "fixture-visible-identity",
    }

    explicit = load_login_credentials(explicit_store, values)
    fallback = load_login_credentials(
        replace(explicit_store, identity_env=None),
        values,
    )

    assert explicit.expected_identity is not None
    assert explicit.expected_identity.reveal() == "fixture-visible-identity"
    assert fallback.expected_identity is not None
    assert fallback.expected_identity.reveal() == "fixture-user"


class FakeBrowserManager:
    instances: list["FakeBrowserManager"] = []
    include_download = True
    authorization_store: AuthorizationStore | None = None
    expected_authorization_id: str | None = None
    start_error: Exception | None = None
    start_callback = None

    def __init__(self, runtime_root, *, port_range) -> None:
        self.runtime_root = runtime_root
        self.port_range = port_range
        self.shutdown_called = False
        self.finish_calls: list[bool] = []
        self.browser = None
        self.run_dir_existed_before_start = None
        self.authorization_status_on_construct = None
        if (
            self.__class__.authorization_store is not None
            and self.__class__.expected_authorization_id is not None
        ):
            record = self.__class__.authorization_store.load(
                self.__class__.expected_authorization_id
            )
            self.authorization_status_on_construct = record.status
        self.__class__.instances.append(self)

    def start(self, spec, *, run_id, run_dir, action_timeout, download_timeout):
        self.run_dir_existed_before_start = run_dir.exists()
        if self.__class__.start_error is not None:
            raise self.__class__.start_error
        self.browser = make_browser(
            run_dir,
            include_download=self.__class__.include_download,
        )
        if self.__class__.start_callback is not None:
            self.__class__.start_callback(run_dir)
        self.session = SimpleNamespace(
            actions=self.browser,
            profile_id=spec.profile_id,
            port=spec.requested_port,
            lifecycle=spec.lifecycle,
        )
        return self.session

    def finish(self, session, *, failed=False):
        self.finish_calls.append(failed)
        if session.lifecycle is not BrowserLifecyclePolicy.KEEP_OPEN_ON_FAILURE:
            raise AssertionError(f"unexpected lifecycle policy: {session.lifecycle}")
        if not failed:
            return None
        return BrowserHandoff(
            profile_id=session.profile_id,
            account_id="STORE_001",
            profile_dir=Path(self.runtime_root),
            port=session.port,
            browser_pid=4242,
            run_id="fixture-run",
            detached_at="2026-09-04T00:00:00+00:00",
        )

    def shutdown(self) -> None:
        self.shutdown_called = True


@pytest.fixture
def isolated_runtime(tmp_path, monkeypatch):
    source_lock = verify_catalog_snapshot(SOURCE_APP_DIR)
    store = make_store()
    plain_inputs = real_runtime._RuntimeInputs(REQUIREMENT_HASH, store, None)
    credential_inputs = real_runtime._RuntimeInputs(
        REQUIREMENT_HASH,
        store,
        LoginCredentials(
            SecretValue("fixture-user", label="fixture-user"),
            SecretValue("fixture-secret", label="fixture-secret"),
            SecretValue("fixture-user", label="fixture-identity"),
        ),
    )

    FakeBrowserManager.instances = []
    FakeBrowserManager.include_download = True
    FakeBrowserManager.expected_authorization_id = None
    FakeBrowserManager.start_error = None
    FakeBrowserManager.start_callback = None
    FakeBrowserManager.authorization_store = AuthorizationStore(
        tmp_path / "runtime" / "authorizations"
    )
    monkeypatch.setattr(real_runtime, "APP_DIR", tmp_path)
    monkeypatch.setattr(real_runtime, "BrowserManager", FakeBrowserManager)
    monkeypatch.setattr(
        real_runtime,
        "verify_catalog_snapshot",
        lambda app_dir: source_lock,
    )
    monkeypatch.setattr(
        real_runtime,
        "_load_runtime_inputs",
        lambda account, *, require_credentials: plain_inputs,
    )
    monkeypatch.setattr(
        real_runtime,
        "_load_credentials",
        lambda inputs: credential_inputs,
    )
    monkeypatch.setattr(
        real_runtime,
        "_validated_snapshot_registry",
        build_instruction_registry,
    )
    return SimpleNamespace(
        app_dir=tmp_path,
        authorization_store=FakeBrowserManager.authorization_store,
        source_lock=source_lock,
        inputs=plain_inputs,
        store=store,
    )


def _request_and_grant(
    *,
    operation: str,
    run_id: str,
    authorization_id: str,
) -> dict[str, object]:
    requested = real_runtime.create_authorization_request(
        operation=operation,
        account="STORE_001",
        mode="preview",
        run_id=run_id,
        requested_by="fixture-developer",
        authorization_id=authorization_id,
    )
    authorization = requested["authorization"]
    assert isinstance(authorization, dict)
    granted = real_runtime.grant_authorization_request(
        authorization_id=authorization_id,
        scope_digest=str(authorization["scope_digest"]),
        authorized_by="fixture-reviewer",
        approval_reference="fixture-approval-reference",
        ttl_seconds=60,
        now=datetime.now(UTC),
    )
    granted_authorization = granted["authorization"]
    assert isinstance(granted_authorization, dict)
    return granted_authorization


def test_request_and_grant_persist_exact_scope_without_creating_run_directory(
    isolated_runtime,
) -> None:
    requested = real_runtime.create_authorization_request(
        operation="run",
        account="STORE_001",
        mode="preview",
        run_id="authorization-scope-001",
        requested_by="fixture-developer",
        authorization_id="auth-scope-001",
    )

    authorization = requested["authorization"]
    assert isinstance(authorization, dict)
    scope = authorization["scope"]
    assert isinstance(scope, dict)
    assert authorization["status"] == AuthorizationStatus.REQUESTED.value
    assert scope["app_id"] == APP_ID
    assert scope["app_version"] == PROGRAM_VERSION
    assert scope["program_id"] == PROGRAM_ID
    assert scope["program_version"] == PROGRAM_VERSION
    assert scope["requirement_hash"] == REQUIREMENT_HASH
    assert scope["operation"] == AuthorizationOperation.RUN.value
    assert scope["mode"] == "preview"
    assert scope["run_id"] == "authorization-scope-001"
    assert scope["account_id"] == "STORE_001"
    assert scope["profile_id"] == real_runtime._profile_id(
        isolated_runtime.app_dir / isolated_runtime.store.profile_directory
    )
    assert scope["profile_id"].startswith("profile-")
    assert scope["resume_checkpoint_digest"] is None
    assert scope["resume_step_id"] is None
    assert scope["allowed_origins"] == ["https://www.erp321.com"]
    assert scope["step_ids"] == [
        "Prepare",
        "S001",
        "S002",
        "S003",
        "S004",
        "S005",
    ]
    assert scope["candidate_asset_refs"] == []
    assert scope["external_writes"] == []
    assert requested["run_directory_created"] is False
    assert not (isolated_runtime.app_dir / "runs").exists()
    assert FakeBrowserManager.instances == []
    with pytest.raises(real_runtime.ApplicationRuntimeError) as digest_mismatch:
        real_runtime.grant_authorization_request(
            authorization_id="auth-scope-001",
            scope_digest="sha256:" + "0" * 64,
            authorized_by="fixture-reviewer",
            approval_reference="fixture-approval-reference",
            ttl_seconds=30,
            now=datetime.now(UTC),
        )
    assert digest_mismatch.value.error_code == "authorization_scope_mismatch"
    assert (
        isolated_runtime.authorization_store.load("auth-scope-001").status
        is AuthorizationStatus.REQUESTED
    )

    granted = real_runtime.grant_authorization_request(
        authorization_id="auth-scope-001",
        scope_digest=str(authorization["scope_digest"]),
        authorized_by="fixture-reviewer",
        approval_reference="fixture-approval-reference",
        ttl_seconds=30,
        now=datetime.now(UTC),
    )
    granted_authorization = granted["authorization"]
    assert isinstance(granted_authorization, dict)
    assert granted_authorization["status"] == AuthorizationStatus.GRANTED.value
    assert granted_authorization["scope_digest"] == authorization["scope_digest"]
    assert not (isolated_runtime.app_dir / "runs").exists()
    assert FakeBrowserManager.instances == []


def test_requested_authorization_can_be_revoked_without_launching_browser(
    isolated_runtime,
) -> None:
    real_runtime.create_authorization_request(
        operation="run",
        account="STORE_001",
        mode="preview",
        run_id="authorization-revoke-001",
        requested_by="fixture-developer",
        authorization_id="auth-revoke-001",
    )

    revoked = real_runtime.revoke_authorization_request(
        authorization_id="auth-revoke-001",
        revoked_by="fixture-developer",
        reason="interactive_preview_declined",
    )

    authorization = revoked["authorization"]
    assert isinstance(authorization, dict)
    assert authorization["status"] == AuthorizationStatus.REVOKED.value
    assert authorization["revoked_by"] == "fixture-developer"
    assert authorization["revocation_reason"] == "interactive_preview_declined"
    assert revoked["run_directory_created"] is False
    assert revoked["real_browser_launched"] is False
    assert FakeBrowserManager.instances == []


def test_candidate_request_is_bound_to_current_candidate_refs(
    isolated_runtime,
    monkeypatch,
) -> None:
    with pytest.raises(real_runtime.CandidateScopeEmptyError):
        real_runtime.create_authorization_request(
            operation="verify_candidates",
            account="STORE_001",
            mode="preview",
            run_id="candidate-scope-empty-001",
            requested_by="fixture-developer",
        )

    document = isolated_runtime.source_lock.model_dump(mode="python")
    document["items"][0]["status"] = CatalogItemStatus.CANDIDATE
    document["items"][0]["source_type"] = CatalogSourceType.APPLICATION_CANDIDATE
    candidate_lock = type(isolated_runtime.source_lock).model_validate(document)
    candidate_item = candidate_lock.items[0]
    monkeypatch.setattr(
        real_runtime,
        "verify_catalog_snapshot",
        lambda app_dir: candidate_lock,
    )

    requested = real_runtime.create_authorization_request(
        operation="verify_candidates",
        account="STORE_001",
        mode="preview",
        run_id="candidate-scope-001",
        requested_by="fixture-developer",
        authorization_id="auth-candidate-scope-001",
    )

    authorization = requested["authorization"]
    assert isinstance(authorization, dict)
    scope = authorization["scope"]
    assert isinstance(scope, dict)
    assert scope["operation"] == AuthorizationOperation.VERIFY_CANDIDATES.value
    assert scope["candidate_asset_refs"] == [
        f"{candidate_item.kind.value}:{candidate_item.id}"
    ]
    assert not (isolated_runtime.app_dir / "runs").exists()
    assert FakeBrowserManager.instances == []


def test_exact_scope_claim_precedes_run_directory_and_browser_and_is_single_use(
    isolated_runtime,
) -> None:
    _request_and_grant(
        operation="run",
        run_id="standard-runtime-001",
        authorization_id="auth-standard-runtime-001",
    )

    with pytest.raises(real_runtime.ApplicationRuntimeError) as mismatch:
        real_runtime.execute_standard_run(
            command="run",
            account="STORE_001",
            mode="preview",
            run_id="different-run-id",
            authorization_id="auth-standard-runtime-001",
        )
    assert mismatch.value.error_code == "authorization_scope_mismatch"
    assert mismatch.value.real_browser_launched is False
    assert FakeBrowserManager.instances == []
    assert not (isolated_runtime.app_dir / "runs").exists()

    FakeBrowserManager.expected_authorization_id = "auth-standard-runtime-001"
    result = real_runtime.execute_standard_run(
        command="run",
        account="STORE_001",
        mode="preview",
        run_id="standard-runtime-001",
        authorization_id="auth-standard-runtime-001",
    )

    assert result["status"] == "succeeded"
    assert result["mode"] == "preview"
    assert result["authorization_id"] == "auth-standard-runtime-001"
    assert len(FakeBrowserManager.instances) == 1
    manager = FakeBrowserManager.instances[0]
    assert manager.authorization_status_on_construct is AuthorizationStatus.CLAIMED
    assert manager.run_dir_existed_before_start is False
    assert manager.shutdown_called is True
    record = isolated_runtime.authorization_store.load(
        "auth-standard-runtime-001"
    )
    assert record.status is AuthorizationStatus.SUCCEEDED
    assert record.outcome is not None
    assert record.outcome.evidence_refs

    with pytest.raises(real_runtime.ApplicationRuntimeError) as replayed:
        real_runtime.execute_standard_run(
            command="run",
            account="STORE_001",
            mode="preview",
            run_id="standard-runtime-001",
            authorization_id="auth-standard-runtime-001",
        )
    assert replayed.value.error_code == "authorization_already_claimed"
    assert len(FakeBrowserManager.instances) == 1


def test_setup_failure_after_claim_is_terminal_without_starting_browser(
    isolated_runtime,
    monkeypatch,
) -> None:
    _request_and_grant(
        operation="run",
        run_id="setup-failure-001",
        authorization_id="auth-setup-failure-001",
    )

    def fail_credentials(inputs):
        raise RuntimeError("fixture value must never be printed")

    monkeypatch.setattr(real_runtime, "_load_credentials", fail_credentials)
    with pytest.raises(real_runtime.ApplicationRuntimeError) as failed:
        real_runtime.execute_standard_run(
            command="run",
            account="STORE_001",
            mode="preview",
            run_id="setup-failure-001",
            authorization_id="auth-setup-failure-001",
        )

    assert failed.value.error_code == "application_runtime_failed"
    assert failed.value.real_browser_launched is False
    assert FakeBrowserManager.instances == []
    assert not (isolated_runtime.app_dir / "runs").exists()
    record = isolated_runtime.authorization_store.load("auth-setup-failure-001")
    assert record.status is AuthorizationStatus.FAILED
    assert record.outcome is not None
    assert record.outcome.error_code == "application_runtime_failed"


def test_post_launch_start_failure_is_reported_truthfully_and_terminal(
    isolated_runtime,
) -> None:
    _request_and_grant(
        operation="run",
        run_id="post-launch-failure-001",
        authorization_id="auth-post-launch-failure-001",
    )
    FakeBrowserManager.start_error = BrowserStartError(
        "fixture latest-tab failure",
        real_browser_launched=True,
    )

    with pytest.raises(real_runtime.ApplicationRuntimeError) as failed:
        real_runtime.execute_standard_run(
            command="run",
            account="STORE_001",
            mode="preview",
            run_id="post-launch-failure-001",
            authorization_id="auth-post-launch-failure-001",
        )

    assert failed.value.error_code == "browser_start_failed"
    assert failed.value.real_browser_launched is True
    assert len(FakeBrowserManager.instances) == 1
    assert FakeBrowserManager.instances[0].shutdown_called is True
    record = isolated_runtime.authorization_store.load(
        "auth-post-launch-failure-001"
    )
    assert record.status is AuthorizationStatus.FAILED


def test_changed_profile_directory_does_not_consume_granted_authorization(
    isolated_runtime,
    monkeypatch,
) -> None:
    _request_and_grant(
        operation="run",
        run_id="profile-mismatch-001",
        authorization_id="auth-profile-mismatch-001",
    )
    changed_inputs = replace(
        isolated_runtime.inputs,
        store=replace(
            isolated_runtime.store,
            profile_directory="profiles/STORE_002",
        ),
    )
    monkeypatch.setattr(
        real_runtime,
        "_load_runtime_inputs",
        lambda account, *, require_credentials: changed_inputs,
    )

    with pytest.raises(real_runtime.ApplicationRuntimeError) as mismatch:
        real_runtime.execute_standard_run(
            command="run",
            account="STORE_001",
            mode="preview",
            run_id="profile-mismatch-001",
            authorization_id="auth-profile-mismatch-001",
        )

    assert mismatch.value.error_code == "authorization_scope_mismatch"
    assert mismatch.value.real_browser_launched is False
    assert FakeBrowserManager.instances == []
    record = isolated_runtime.authorization_store.load(
        "auth-profile-mismatch-001"
    )
    assert record.status is AuthorizationStatus.GRANTED


def test_resume_reuses_run_id_but_requires_new_resume_authorization(
    isolated_runtime,
) -> None:
    FakeBrowserManager.include_download = False
    _request_and_grant(
        operation="run",
        run_id="failed-s005-001",
        authorization_id="auth-failed-s005-001",
    )

    with pytest.raises(real_runtime.ApplicationRuntimeError) as failed:
        real_runtime.execute_standard_run(
            command="run",
            account="STORE_001",
            mode="preview",
            run_id="failed-s005-001",
            authorization_id="auth-failed-s005-001",
        )
    assert failed.value.step_id == "S005"
    failed_record = isolated_runtime.authorization_store.load(
        "auth-failed-s005-001"
    )
    assert failed_record.status is AuthorizationStatus.FAILED

    FakeBrowserManager.include_download = True
    _request_and_grant(
        operation="resume",
        run_id="failed-s005-001",
        authorization_id="auth-resume-s005-001",
    )
    FakeBrowserManager.expected_authorization_id = "auth-resume-s005-001"
    resumed = real_runtime.execute_standard_run(
        command="resume",
        account="STORE_001",
        mode="preview",
        run_id="failed-s005-001",
        authorization_id="auth-resume-s005-001",
    )

    assert resumed["run_id"] == "failed-s005-001"
    assert resumed["authorization_id"] == "auth-resume-s005-001"
    assert resumed["completed_steps"] == ["S005"]
    assert resumed["skipped_steps"] == ["S001", "S002", "S003", "S004"]
    resume_record = isolated_runtime.authorization_store.load(
        "auth-resume-s005-001"
    )
    assert resume_record.status is AuthorizationStatus.SUCCEEDED
    assert resume_record.scope.operation is AuthorizationOperation.RESUME
    assert resume_record.scope.run_id == failed_record.scope.run_id
    assert resume_record.scope.resume_checkpoint_digest is not None
    assert resume_record.scope.resume_step_id == "S005"
    assert resume_record.authorization_id != failed_record.authorization_id
    assert all(instance.shutdown_called for instance in FakeBrowserManager.instances)


def test_checkpoint_change_after_resume_grant_does_not_consume_authorization(
    isolated_runtime,
) -> None:
    FakeBrowserManager.include_download = False
    _request_and_grant(
        operation="run",
        run_id="checkpoint-mismatch-001",
        authorization_id="auth-checkpoint-source-001",
    )
    with pytest.raises(real_runtime.ApplicationRuntimeError):
        real_runtime.execute_standard_run(
            command="run",
            account="STORE_001",
            mode="preview",
            run_id="checkpoint-mismatch-001",
            authorization_id="auth-checkpoint-source-001",
        )

    _request_and_grant(
        operation="resume",
        run_id="checkpoint-mismatch-001",
        authorization_id="auth-checkpoint-resume-001",
    )
    checkpoint_store = real_runtime.CheckpointStore(
        isolated_runtime.app_dir
        / "runs"
        / "checkpoint-mismatch-001"
        / "checkpoint.json"
    )
    checkpoint = checkpoint_store.load()
    assert checkpoint is not None
    checkpoint["steps"]["S005"]["attempts"] += 1
    checkpoint_store.save(checkpoint)

    with pytest.raises(real_runtime.ApplicationRuntimeError) as mismatch:
        real_runtime.execute_standard_run(
            command="resume",
            account="STORE_001",
            mode="preview",
            run_id="checkpoint-mismatch-001",
            authorization_id="auth-checkpoint-resume-001",
        )

    assert mismatch.value.error_code == "authorization_scope_mismatch"
    assert mismatch.value.real_browser_launched is False
    record = isolated_runtime.authorization_store.load(
        "auth-checkpoint-resume-001"
    )
    assert record.status is AuthorizationStatus.GRANTED


def test_checkpoint_change_during_browser_start_fails_before_program_prepare(
    isolated_runtime,
) -> None:
    FakeBrowserManager.include_download = False
    _request_and_grant(
        operation="run",
        run_id="checkpoint-start-race-001",
        authorization_id="auth-checkpoint-start-source-001",
    )
    with pytest.raises(real_runtime.ApplicationRuntimeError):
        real_runtime.execute_standard_run(
            command="run",
            account="STORE_001",
            mode="preview",
            run_id="checkpoint-start-race-001",
            authorization_id="auth-checkpoint-start-source-001",
        )

    FakeBrowserManager.include_download = True
    _request_and_grant(
        operation="resume",
        run_id="checkpoint-start-race-001",
        authorization_id="auth-checkpoint-start-resume-001",
    )

    def mutate_checkpoint(run_dir):
        checkpoint_store = real_runtime.CheckpointStore(run_dir / "checkpoint.json")
        checkpoint = checkpoint_store.load()
        assert checkpoint is not None
        checkpoint["updated_at"] = "changed-during-browser-start"
        checkpoint_store.save(checkpoint)

    FakeBrowserManager.start_callback = mutate_checkpoint
    with pytest.raises(real_runtime.ApplicationRuntimeError) as mismatch:
        real_runtime.execute_standard_run(
            command="resume",
            account="STORE_001",
            mode="preview",
            run_id="checkpoint-start-race-001",
            authorization_id="auth-checkpoint-start-resume-001",
        )

    assert mismatch.value.error_code == "authorization_scope_mismatch"
    assert mismatch.value.real_browser_launched is True
    record = isolated_runtime.authorization_store.load(
        "auth-checkpoint-start-resume-001"
    )
    assert record.status is AuthorizationStatus.FAILED
    assert FakeBrowserManager.instances[-1].shutdown_called is True


def test_expiry_is_rechecked_immediately_before_browser_start(
    isolated_runtime,
    monkeypatch,
) -> None:
    _request_and_grant(
        operation="run",
        run_id="prelaunch-expiry-001",
        authorization_id="auth-prelaunch-expiry-001",
    )
    original_assert_active = AuthorizationSession.assert_active

    def assert_expired(self, *, now=None):
        return original_assert_active(
            self,
            now=datetime.now(UTC) + real_runtime.timedelta(hours=1),
        )

    monkeypatch.setattr(AuthorizationSession, "assert_active", assert_expired)

    with pytest.raises(real_runtime.ApplicationRuntimeError) as expired:
        real_runtime.execute_standard_run(
            command="run",
            account="STORE_001",
            mode="preview",
            run_id="prelaunch-expiry-001",
            authorization_id="auth-prelaunch-expiry-001",
        )

    assert expired.value.error_code == AuthorizationExpiredError.error_code
    assert expired.value.real_browser_launched is False
    assert FakeBrowserManager.instances == []
    record = isolated_runtime.authorization_store.load(
        "auth-prelaunch-expiry-001"
    )
    assert record.status is AuthorizationStatus.FAILED


def test_live_is_always_unsupported_before_authorization_or_browser(
    isolated_runtime,
) -> None:
    with pytest.raises(real_runtime.LiveUnsupportedError) as request_error:
        real_runtime.create_authorization_request(
            operation="run",
            account="STORE_001",
            mode="live",
            run_id="live-unsupported-001",
            requested_by="fixture-developer",
        )
    assert request_error.value.error_code == "application_live_unsupported"

    with pytest.raises(real_runtime.LiveUnsupportedError) as run_error:
        real_runtime.execute_standard_run(
            command="run",
            account="STORE_001",
            mode="live",
            run_id="live-unsupported-001",
            authorization_id="auth-does-not-exist",
        )
    assert run_error.value.error_code == "application_live_unsupported"
    assert FakeBrowserManager.instances == []
    assert not (isolated_runtime.app_dir / "runs").exists()


def test_success_evidence_names_are_unique_safe_basenames() -> None:
    first = real_runtime._evidence_name("candidate-resume-succeeded")
    second = real_runtime._evidence_name("candidate-resume-succeeded")

    assert first != second
    assert first.endswith(".png")
    assert second.endswith(".png")
    assert "/" not in first and "\\" not in first


def test_failed_run_retains_the_browser_and_reports_it(isolated_runtime) -> None:
    """A failed run must leave the window open and say so, or resume is blind."""

    _request_and_grant(
        operation="run",
        run_id="retain-on-failure-001",
        authorization_id="auth-retain-on-failure-001",
    )
    # No download makes S005 fail after the browser is already up.
    FakeBrowserManager.include_download = False

    with pytest.raises(real_runtime.ApplicationRuntimeError) as failed:
        real_runtime.execute_standard_run(
            command="run",
            account="STORE_001",
            mode="preview",
            run_id="retain-on-failure-001",
            authorization_id="auth-retain-on-failure-001",
        )

    manager = FakeBrowserManager.instances[-1]
    assert manager.finish_calls == [True]
    retained = failed.value.retained_browser
    assert retained is not None
    assert retained["port"] == 9301
    assert retained["browser_pid"] == 4242


def test_successful_run_closes_the_browser(isolated_runtime) -> None:
    _request_and_grant(
        operation="run",
        run_id="close-on-success-001",
        authorization_id="auth-close-on-success-001",
    )

    payload = real_runtime.execute_standard_run(
        command="run",
        account="STORE_001",
        mode="preview",
        run_id="close-on-success-001",
        authorization_id="auth-close-on-success-001",
    )

    assert payload["ok"] is True
    manager = FakeBrowserManager.instances[-1]
    assert manager.finish_calls == [False]
    assert "retained_browser" not in payload
