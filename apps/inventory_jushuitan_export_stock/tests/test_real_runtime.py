from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest
from rpa_core.browser import SecretValue

from inventory_jushuitan_export_stock import real_runtime
from inventory_jushuitan_export_stock.instructions import build_instruction_registry
from inventory_jushuitan_export_stock.models import LoginCredentials, load_login_credentials

from .helpers import REQUIREMENT_HASH, make_browser, make_store


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

    def __init__(self, runtime_root, *, port_range) -> None:
        self.runtime_root = runtime_root
        self.port_range = port_range
        self.shutdown_called = False
        self.browser = None
        self.__class__.instances.append(self)

    def start(self, spec, *, run_id, run_dir, action_timeout, download_timeout):
        self.browser = make_browser(
            run_dir,
            include_download=self.__class__.include_download,
        )
        return SimpleNamespace(actions=self.browser)

    def shutdown(self) -> None:
        self.shutdown_called = True


def test_candidate_preview_and_resume_use_one_run_checkpoint_and_cleanup_browser(
    tmp_path,
    monkeypatch,
) -> None:
    FakeBrowserManager.instances = []
    store = make_store()
    credentials = LoginCredentials(
        SecretValue("fixture-user", label="fixture-user"),
        SecretValue("fixture-secret", label="fixture-secret"),
    )
    runtime_inputs = real_runtime._RuntimeInputs(
        REQUIREMENT_HASH,
        store,
        credentials,
    )
    monkeypatch.setattr(real_runtime, "APP_DIR", tmp_path)
    monkeypatch.setattr(real_runtime, "BrowserManager", FakeBrowserManager)
    monkeypatch.setattr(
        real_runtime,
        "_load_runtime_inputs",
        lambda account, require_credentials: runtime_inputs,
    )
    monkeypatch.setattr(
        real_runtime,
        "_validated_snapshot_registry",
        lambda: build_instruction_registry(),
    )
    authorization_batch = "account-session-test-authorization"
    monkeypatch.setattr(
        real_runtime,
        "ACCOUNT_SESSION_CANDIDATE_AUTHORIZATION_BATCH_ID",
        authorization_batch,
    )

    first = real_runtime.execute_candidate_verification(
        account="STORE_001",
        batch_id=authorization_batch,
        run_id="candidate-runtime-001",
    )
    resumed = real_runtime.execute_candidate_verification(
        account="STORE_001",
        batch_id=authorization_batch,
        resume_run_id="candidate-runtime-001",
    )

    assert first["status"] == "succeeded"
    assert first["completed_steps"] == ["S001", "S002", "S003", "S004", "S005"]
    assert first["download"]["size_bytes"] > 0
    assert resumed["status"] == "succeeded"
    assert resumed["completed_steps"] == []
    assert resumed["skipped_steps"] == ["S001", "S002", "S003", "S004", "S005"]
    assert len(FakeBrowserManager.instances) == 2
    assert all(instance.shutdown_called for instance in FakeBrowserManager.instances)
    assert (
        tmp_path
        / "runs"
        / "candidate-runtime-001"
        / "downloads"
        / "inventory-export.xlsx"
    ).is_file()


def test_old_candidate_batch_is_invalid_for_the_changed_version(monkeypatch) -> None:
    constructed = False

    class UnexpectedBrowserManager:
        def __init__(self, *args, **kwargs) -> None:
            nonlocal constructed
            constructed = True

    monkeypatch.setattr(real_runtime, "BrowserManager", UnexpectedBrowserManager)

    try:
        real_runtime.execute_candidate_verification(
            account="STORE_001",
            batch_id=real_runtime.PATCH_C_AUTHORIZATION_BATCH_ID,
            run_id="candidate-runtime-002",
        )
    except real_runtime.CandidateAuthorizationError as error:
        assert error.real_browser_launched is False
    else:  # pragma: no cover - explicit fail-closed assertion
        raise AssertionError("candidate authorization mismatch must fail")
    assert constructed is False


def test_standard_preview_loads_credentials_and_ensures_account_in_same_browser(
    tmp_path,
    monkeypatch,
) -> None:
    FakeBrowserManager.instances = []
    FakeBrowserManager.include_download = True
    store = make_store()
    runtime_inputs = real_runtime._RuntimeInputs(
        REQUIREMENT_HASH,
        store,
        LoginCredentials(
            SecretValue("fixture-user", label="fixture-user"),
            SecretValue("fixture-secret", label="fixture-secret"),
            SecretValue("fixture-user", label="fixture-identity"),
        ),
    )
    credential_flags: list[bool] = []

    def fake_inputs(account, require_credentials):
        credential_flags.append(require_credentials)
        return runtime_inputs

    monkeypatch.setattr(real_runtime, "APP_DIR", tmp_path)
    monkeypatch.setattr(real_runtime, "BrowserManager", FakeBrowserManager)
    monkeypatch.setattr(real_runtime, "_load_runtime_inputs", fake_inputs)

    result = real_runtime.execute_standard_run(
        command="run",
        account="STORE_001",
        mode="preview",
        run_id="standard-runtime-001",
    )

    assert result["status"] == "succeeded"
    assert credential_flags == [True]
    browser = FakeBrowserManager.instances[-1].browser
    assert browser is not None
    assert browser.current_url == store.login_url
    assert any(
        record.action == "text"
        and record.element_id == "jushuitan.erp.shell.account_identity_surface"
        for record in browser.actions
    )
    assert all(instance.shutdown_called for instance in FakeBrowserManager.instances)


def test_failed_s005_resume_rebuilds_browser_state_before_retry(
    tmp_path,
    monkeypatch,
) -> None:
    FakeBrowserManager.instances = []
    store = make_store()
    runtime_inputs = real_runtime._RuntimeInputs(
        REQUIREMENT_HASH,
        store,
        LoginCredentials(
            SecretValue("fixture-user", label="fixture-user"),
            SecretValue("fixture-secret", label="fixture-secret"),
        ),
    )
    monkeypatch.setattr(real_runtime, "APP_DIR", tmp_path)
    monkeypatch.setattr(real_runtime, "BrowserManager", FakeBrowserManager)
    monkeypatch.setattr(
        real_runtime,
        "_load_runtime_inputs",
        lambda account, require_credentials: runtime_inputs,
    )
    monkeypatch.setattr(
        real_runtime,
        "_validated_snapshot_registry",
        lambda: build_instruction_registry(),
    )
    monkeypatch.setattr(FakeBrowserManager, "include_download", False)
    authorization_batch = "account-session-resume-test-authorization"
    monkeypatch.setattr(
        real_runtime,
        "ACCOUNT_SESSION_CANDIDATE_AUTHORIZATION_BATCH_ID",
        authorization_batch,
    )

    with pytest.raises(real_runtime.ApplicationRuntimeError) as caught:
        real_runtime.execute_candidate_verification(
            account="STORE_001",
            batch_id=authorization_batch,
            run_id="candidate-runtime-failed-s005",
        )
    assert caught.value.step_id == "S005"

    monkeypatch.setattr(FakeBrowserManager, "include_download", True)
    resumed = real_runtime.execute_candidate_verification(
        account="STORE_001",
        batch_id=authorization_batch,
        resume_run_id="candidate-runtime-failed-s005",
    )

    assert resumed["completed_steps"] == ["S005"]
    assert resumed["skipped_steps"] == ["S001", "S002", "S003", "S004"]
    recovery_browser = FakeBrowserManager.instances[-1].browser
    assert recovery_browser is not None
    recovery_actions = [
        record.element_id
        for record in recovery_browser.actions
        if record.action in {"click", "select", "download"}
    ]
    assert recovery_actions == [
        "jushuitan.erp.navigation.inventory_module",
        "jushuitan.erp.inventory.product_stock_entry",
        "jushuitan.erp.product_stock.reset_button",
        "jushuitan.erp.product_stock.brand_selector",
        "jushuitan.erp.product_stock.brand_selector",
        "jushuitan.erp.product_stock.search_button",
        "jushuitan.erp.product_stock.brand_selector",
        "jushuitan.erp.product_stock.brand_selector",
        "jushuitan.erp.product_stock.export_menu",
        "jushuitan.erp.product_stock.export_stock_option",
    ]
    assert all(instance.shutdown_called for instance in FakeBrowserManager.instances)


def test_success_evidence_names_are_unique_safe_basenames() -> None:
    first = real_runtime._evidence_name("candidate-resume-succeeded")
    second = real_runtime._evidence_name("candidate-resume-succeeded")

    assert first != second
    assert first.endswith(".png")
    assert second.endswith(".png")
    assert "/" not in first and "\\" not in first
