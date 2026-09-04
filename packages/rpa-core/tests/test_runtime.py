from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
import multiprocessing
import os
from pathlib import Path
import time

import pytest

from rpa_core import runtime as runtime_module
from rpa_core.authorization import (
    AuthorizationOperation,
    AuthorizationScope,
    AuthorizationStore,
    BrowserAction,
)
from rpa_core.contracts import RetryPolicy, RunMode, SideEffect
from rpa_core.events import JsonlEventLogger
from rpa_core.runtime import (
    BaseProgram,
    CheckpointAuthorizationMismatchError,
    CheckpointError,
    CheckpointIdentityError,
    CheckpointStore,
    ExecutionContext,
    ProgramVerificationError,
    ProgramSpec,
    ResumeBlockedError,
    RunAlreadyActiveError,
    RunDirectoryLock,
    RunLockUnsupportedError,
    Runner,
    RuntimeContractError,
    Step,
    StepRunError,
    StepSpec,
    checkpoint_digest,
)
from rpa_core.services import FakeFeishuBackend, PreviewFeishuService


REQUIREMENT_HASH = "sha256:" + ("0" * 64)


def make_run_dir(tmp_path: Path, run_id: str = "run-001") -> Path:
    return tmp_path / "app" / "runs" / run_id


def hold_run_lock(lock_path: str, ready: object, release: object) -> None:
    with RunDirectoryLock(lock_path):
        ready.set()
        release.wait(10)


def acquire_run_lock_and_exit(lock_path: str, ready: object) -> None:
    lock = RunDirectoryLock(lock_path)
    lock.acquire()
    ready.set()


class RecordingStep(Step):
    def __init__(
        self,
        step_id: str,
        calls: list[str],
        *,
        fail_times: int = 0,
        verification: bool = True,
        recovery_verification: bool = False,
        retry_policy: RetryPolicy | None = None,
        side_effect: SideEffect = SideEffect.NONE,
    ) -> None:
        super().__init__(
            StepSpec(
                step_id=step_id,
                name=step_id,
                retry_policy=retry_policy or RetryPolicy(),
                side_effect=side_effect,
            )
        )
        self.calls = calls
        self.fail_times = fail_times
        self.verification = verification
        self.recovery_verification = recovery_verification

    def execute(self, context: ExecutionContext) -> dict[str, object]:
        self.calls.append(self.spec.step_id)
        if self.fail_times:
            self.fail_times -= 1
            raise RuntimeError("deliberate test failure")
        return {
            "step": self.spec.step_id,
            "attempt": context.current_attempt,
            "evidence_refs": [f"evidence/{self.spec.step_id}.json"],
        }

    def verify(self, context: ExecutionContext, result: object) -> bool:
        return self.verification

    def verify_recovery(self, context: ExecutionContext, checkpoint: object) -> bool:
        return self.recovery_verification


def make_context(
    run_dir: Path,
    *,
    app_id: str = "example.offline.export",
    version: str = "0.1.0",
    account_id: str = "STORE_001",
    mode: RunMode = RunMode.PREVIEW,
    requirement_hash: str = REQUIREMENT_HASH,
) -> ExecutionContext:
    return ExecutionContext(
        app_id=app_id,
        program_id="offline-export",
        program_version=version,
        requirement_hash=requirement_hash,
        run_id=run_dir.name,
        account_id=account_id,
        mode=mode,
        run_dir=run_dir,
        metadata={"app_dir": str(run_dir.parent.parent)},
    )


def make_program(
    steps: list[Step],
    *,
    app_id: str = "example.offline.export",
    version: str = "0.1.0",
    requirement_hash: str = REQUIREMENT_HASH,
) -> BaseProgram:
    return BaseProgram(
        ProgramSpec(
            app_id=app_id,
            program_id="offline-export",
            version=version,
            requirement_hash=requirement_hash,
            name="offline test",
        ),
        steps,
    )


def read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_events(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_runner_retries_then_persists_verified_success(tmp_path: Path) -> None:
    calls: list[str] = []
    step = RecordingStep(
        "STEP-001",
        calls,
        fail_times=1,
        retry_policy=RetryPolicy(max_attempts=2, delay_seconds=0),
    )
    context = make_context(make_run_dir(tmp_path))

    result = Runner(sleep=lambda _: None).run(make_program([step]), context)

    assert result.status == "succeeded"
    assert calls == ["STEP-001", "STEP-001"]
    checkpoint = read_json(result.checkpoint_path)
    record = checkpoint["steps"]["STEP-001"]
    assert record["status"] == "succeeded"
    assert record["attempts"] == 2
    assert record["evidence_refs"] == ["evidence/STEP-001.json"]

    events = read_events(context.run_dir / "events.jsonl")
    statuses = [event.get("status") for event in events if event.get("step_id") == "STEP-001"]
    assert statuses == ["running", "retry_wait", "running", "verifying", "succeeded"]


def test_succeeded_is_never_written_when_verification_fails(tmp_path: Path) -> None:
    calls: list[str] = []
    step = RecordingStep("STEP-001", calls, verification=False)
    context = make_context(make_run_dir(tmp_path))

    with pytest.raises(StepRunError) as captured:
        Runner().run(make_program([step]), context)

    assert captured.value.error_code == "step_verification_failed"
    checkpoint = read_json(context.run_dir / "checkpoint.json")
    assert checkpoint["status"] == "failed"
    assert checkpoint["steps"]["STEP-001"]["status"] == "failed"
    event_types = [event["event_type"] for event in read_events(context.run_dir / "events.jsonl")]
    assert "step.verifying" in event_types
    assert "step.succeeded" not in event_types


def test_resume_skips_successful_steps_and_continues_from_failure(tmp_path: Path) -> None:
    calls: list[str] = []
    steps = [
        # Resume only skips a succeeded step that can still prove its effect.
        RecordingStep("STEP-001", calls, recovery_verification=True),
        RecordingStep("STEP-002", calls, fail_times=1),
        RecordingStep("STEP-003", calls),
    ]
    program = make_program(steps)
    first_context = make_context(make_run_dir(tmp_path))
    with pytest.raises(StepRunError):
        Runner().run(program, first_context)

    assert calls == ["STEP-001", "STEP-002"]
    resumed_context = make_context(make_run_dir(tmp_path))
    result = Runner().run(program, resumed_context, resume=True)

    assert result.status == "succeeded"
    assert result.skipped_steps == ("STEP-001",)
    assert calls == ["STEP-001", "STEP-002", "STEP-002", "STEP-003"]
    checkpoint = read_json(result.checkpoint_path)
    assert [checkpoint["steps"][step_id]["status"] for step_id in checkpoint["steps"]] == [
        "succeeded",
        "succeeded",
        "succeeded",
    ]


def test_resume_rechecks_authorized_checkpoint_under_run_lock_before_prepare(
    tmp_path: Path,
) -> None:
    calls: list[str] = []
    initial_program = make_program(
        [
            RecordingStep("STEP-001", calls),
            RecordingStep("STEP-002", calls, fail_times=1),
        ]
    )
    run_dir = make_run_dir(tmp_path)
    with pytest.raises(StepRunError):
        Runner().run(initial_program, make_context(run_dir))

    checkpoint_path = run_dir / "checkpoint.json"
    checkpoint = read_json(checkpoint_path)
    now = datetime.now(UTC)
    scope = AuthorizationScope(
        app_id="example.offline.export",
        app_version="0.1.0",
        program_id="offline-export",
        program_version="0.1.0",
        requirement_hash=REQUIREMENT_HASH,
        catalog_digest="sha256:" + ("1" * 64),
        operation=AuthorizationOperation.RESUME,
        mode=RunMode.PREVIEW,
        run_id="run-001",
        resume_checkpoint_digest=checkpoint_digest(checkpoint),
        resume_step_id="STEP-002",
        account_id="STORE_001",
        profile_id="PROFILE_001",
        allowed_origins=("https://example.invalid",),
        step_ids=("STEP-001", "STEP-002"),
        browser_actions=(BrowserAction.EXISTS,),
    )
    store = AuthorizationStore(tmp_path / "authorizations")
    request = store.create_request(scope, authorization_id="auth-resume-001", now=now)
    store.grant(
        request.authorization_id,
        scope_digest=request.scope_digest,
        authorized_by="developer",
        approval_reference="approval-001",
        expires_at=now + timedelta(minutes=10),
        now=now + timedelta(seconds=1),
    )
    authorization = store.claim(
        request.authorization_id,
        scope,
        now=now + timedelta(seconds=2),
    )

    checkpoint["updated_at"] = "changed-after-authorization"
    CheckpointStore(checkpoint_path).save(checkpoint)
    calls.clear()

    class PrepareRecordingProgram(BaseProgram):
        def prepare(self, context: ExecutionContext) -> None:
            calls.append("prepare")

    resumed_program = PrepareRecordingProgram(
        initial_program.spec,
        [
            RecordingStep("STEP-001", calls),
            RecordingStep("STEP-002", calls),
        ],
    )
    resumed_context = make_context(run_dir)
    resumed_context.services["authorization"] = authorization

    with pytest.raises(
        CheckpointAuthorizationMismatchError,
        match="checkpoint no longer matches",
    ):
        Runner().run(resumed_program, resumed_context, resume=True)

    assert calls == []


@pytest.mark.parametrize(
    ("context_overrides", "program_overrides", "mismatch_name"),
    [
        ({"app_id": "different.app"}, {"app_id": "different.app"}, "app_id"),
        ({"account_id": "STORE_002"}, {}, "account_id"),
        ({"mode": RunMode.LIVE}, {}, "mode"),
        ({"version": "0.2.0"}, {"version": "0.2.0"}, "program_version"),
        ({"requirement_hash": "sha256:" + ("1" * 64)}, {"requirement_hash": "sha256:" + ("1" * 64)}, "requirement_hash"),
    ],
)
def test_resume_rejects_identity_mismatch_without_mutating_checkpoint(
    tmp_path: Path,
    context_overrides: dict[str, object],
    program_overrides: dict[str, object],
    mismatch_name: str,
) -> None:
    calls: list[str] = []
    initial_context = make_context(make_run_dir(tmp_path))
    Runner().run(make_program([RecordingStep("STEP-001", calls)]), initial_context)
    checkpoint_path = initial_context.run_dir / "checkpoint.json"
    before = checkpoint_path.read_bytes()

    resumed_context = make_context(make_run_dir(tmp_path), **context_overrides)
    resumed_program = make_program(
        [RecordingStep("STEP-001", calls)],
        **program_overrides,
    )
    with pytest.raises(CheckpointIdentityError, match=mismatch_name):
        Runner().run(resumed_program, resumed_context, resume=True)

    assert checkpoint_path.read_bytes() == before
    assert calls == ["STEP-001"]


def test_checkpoint_atomic_save_leaves_no_temporary_file(tmp_path: Path) -> None:
    calls: list[str] = []
    context = make_context(make_run_dir(tmp_path))
    Runner().run(make_program([RecordingStep("STEP-001", calls)]), context)

    assert (context.run_dir / "checkpoint.json").is_file()
    assert not list(context.run_dir.glob(".*checkpoint.json.*.tmp"))


def test_runner_rejects_symlinked_run_directory(tmp_path: Path) -> None:
    target = tmp_path / "outside"
    target.mkdir()
    run_dir = make_run_dir(tmp_path)
    run_dir.parent.mkdir(parents=True)
    try:
        run_dir.symlink_to(target, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"symlinks are unavailable in this test environment: {error}")

    with pytest.raises(RuntimeContractError, match="symbolic link"):
        Runner().run(
            make_program([RecordingStep("STEP-001", [])]),
            make_context(run_dir),
        )

    assert not (target / "checkpoint.json").exists()


def test_runner_rejects_symlinked_application_runs_root_before_writing(
    tmp_path: Path,
) -> None:
    app_dir = tmp_path / "app"
    outside = tmp_path / "outside"
    app_dir.mkdir()
    outside.mkdir()
    try:
        (app_dir / "runs").symlink_to(outside, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"symlinks are unavailable in this test environment: {error}")

    context = make_context(outside / "run-001")
    context.metadata["app_dir"] = str(app_dir)

    with pytest.raises(RuntimeContractError, match="runs directory must not be a symbolic link"):
        Runner().run(make_program([RecordingStep("STEP-001", [])]), context)

    assert list(outside.iterdir()) == []


def test_runner_rejects_application_run_path_that_resolves_outside_root(
    tmp_path: Path,
) -> None:
    app_dir = tmp_path / "app"
    outside = tmp_path / "outside"
    runs_dir = app_dir / "runs"
    runs_dir.mkdir(parents=True)
    outside.mkdir()
    linked_parent = runs_dir / "linked-parent"
    try:
        linked_parent.symlink_to(outside, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"symlinks are unavailable in this test environment: {error}")
    context = make_context(linked_parent / "run-001")
    context.metadata["app_dir"] = str(app_dir)

    with pytest.raises(RuntimeContractError, match="run_dir escapes"):
        Runner().run(make_program([RecordingStep("STEP-001", [])]), context)

    assert list(outside.iterdir()) == []


def test_runner_rejects_explicit_run_directory_outside_application_root(
    tmp_path: Path,
) -> None:
    app_dir = tmp_path / "app"
    (app_dir / "runs").mkdir(parents=True)
    run_dir = tmp_path / "external-runs" / "run-001"
    context = make_context(run_dir)
    context.metadata["app_dir"] = str(app_dir)

    with pytest.raises(RuntimeContractError, match="run_dir escapes"):
        Runner().run(make_program([RecordingStep("STEP-001", [])]), context)

    assert not run_dir.exists()


def test_runner_requires_application_directory_before_creating_state(tmp_path: Path) -> None:
    run_dir = make_run_dir(tmp_path)
    context = make_context(run_dir)
    context.metadata.clear()

    with pytest.raises(RuntimeContractError, match="metadata.app_dir is required"):
        Runner().run(make_program([RecordingStep("STEP-001", [])]), context)

    assert not run_dir.exists()


@pytest.mark.parametrize(
    "run_id",
    ["../escape", "/tmp/escape", "nested/escape", "..", "-leading", "bad space", "x" * 129],
)
def test_execution_context_rejects_unsafe_run_id(tmp_path: Path, run_id: str) -> None:
    with pytest.raises(RuntimeContractError, match="run_id must use"):
        ExecutionContext(
            app_id="example.offline.export",
            program_id="offline-export",
            program_version="0.1.0",
            requirement_hash=REQUIREMENT_HASH,
            run_id=run_id,
            account_id="STORE_001",
            mode=RunMode.PREVIEW,
            run_dir=make_run_dir(tmp_path),
            metadata={"app_dir": str(tmp_path / "app")},
        )


def test_runner_revalidates_mutated_run_id_before_creating_state(tmp_path: Path) -> None:
    run_dir = make_run_dir(tmp_path)
    context = make_context(run_dir)
    context.run_id = "../escape"

    with pytest.raises(RuntimeContractError, match="run_id must use"):
        Runner().run(make_program([RecordingStep("STEP-001", [])]), context)

    assert not run_dir.exists()


def test_runner_binds_run_directory_name_to_context_run_id(tmp_path: Path) -> None:
    run_dir = make_run_dir(tmp_path, "different-run")
    context = make_context(run_dir)
    context.run_id = "run-001"

    with pytest.raises(RuntimeContractError, match="run_dir escapes"):
        Runner().run(make_program([RecordingStep("STEP-001", [])]), context)

    assert not run_dir.exists()


@pytest.mark.parametrize("artifact", ["checkpoint", "event log"])
def test_runner_rejects_injected_artifact_path_outside_run_before_writing(
    tmp_path: Path,
    artifact: str,
) -> None:
    run_dir = make_run_dir(tmp_path)
    context = make_context(run_dir)
    outside = tmp_path / ("outside-checkpoint.json" if artifact == "checkpoint" else "outside-events.jsonl")
    runner = (
        Runner(checkpoint_store=CheckpointStore(outside))
        if artifact == "checkpoint"
        else Runner(event_logger=JsonlEventLogger(outside))
    )

    with pytest.raises(RuntimeContractError, match=f"{artifact} path must stay"):
        runner.run(make_program([RecordingStep("STEP-001", [])]), context)

    assert not run_dir.exists()
    assert not outside.exists()


def test_checkpoint_store_rejects_symlink_without_reading_external_state(
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside-checkpoint.json"
    outside.write_text('{"schema_version": 1, "status": "succeeded"}\n', encoding="utf-8")
    checkpoint_path = tmp_path / "run" / "checkpoint.json"
    checkpoint_path.parent.mkdir()
    try:
        checkpoint_path.symlink_to(outside)
    except OSError as error:
        pytest.skip(f"symlinks are unavailable in this test environment: {error}")

    before = outside.read_bytes()
    with pytest.raises(CheckpointError, match="checkpoint"):
        CheckpointStore(checkpoint_path).load()

    assert outside.read_bytes() == before


def test_checkpoint_store_rejects_hardlink_without_reading_external_state(
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside-checkpoint.json"
    outside.write_text('{"schema_version": 1, "status": "succeeded"}\n', encoding="utf-8")
    checkpoint_path = tmp_path / "run" / "checkpoint.json"
    checkpoint_path.parent.mkdir()
    try:
        os.link(outside, checkpoint_path)
    except OSError as error:
        pytest.skip(f"hard links are unavailable in this test environment: {error}")

    before = outside.read_bytes()
    with pytest.raises(CheckpointError, match="hard link"):
        CheckpointStore(checkpoint_path).load()

    assert outside.read_bytes() == before


@pytest.mark.parametrize(
    ("attribute", "value"),
    [
        ("app_id", "different.app"),
        ("run_id", "different-run"),
        ("account_id", "STORE_002"),
    ],
)
def test_runner_rejects_service_identity_mismatch_before_creating_state(
    tmp_path: Path,
    attribute: str,
    value: str,
) -> None:
    run_dir = make_run_dir(tmp_path)
    context = make_context(run_dir)
    service = PreviewFeishuService(
        mode=RunMode.PREVIEW,
        app_id=context.app_id,
        run_id=context.run_id,
        account_id=context.account_id,
        run_dir=run_dir,
        backend=FakeFeishuBackend(),
    )
    setattr(service, attribute, value)
    context.services["feishu"] = service

    with pytest.raises(RuntimeContractError, match=attribute):
        Runner().run(make_program([RecordingStep("STEP-001", [])]), context)

    assert not run_dir.exists()


def test_runner_rejects_service_bound_to_different_run_directory(
    tmp_path: Path,
) -> None:
    run_dir = make_run_dir(tmp_path)
    outside_run_dir = tmp_path / "outside" / "runs" / run_dir.name
    context = make_context(run_dir)
    context.services["feishu"] = PreviewFeishuService(
        mode=RunMode.PREVIEW,
        app_id=context.app_id,
        run_id=context.run_id,
        account_id=context.account_id,
        run_dir=outside_run_dir,
        backend=FakeFeishuBackend(),
    )

    with pytest.raises(RuntimeContractError, match="run_dir does not match"):
        Runner().run(make_program([RecordingStep("STEP-001", [])]), context)

    assert not run_dir.exists()
    assert not outside_run_dir.exists()


def test_runner_fails_closed_when_os_file_locking_is_unavailable(
    tmp_path: Path,
    monkeypatch,
) -> None:
    run_dir = make_run_dir(tmp_path)
    context = make_context(run_dir)
    monkeypatch.setattr(runtime_module, "_fcntl", None)

    with pytest.raises(RunLockUnsupportedError) as captured:
        Runner().run(make_program([RecordingStep("STEP-001", [])]), context)

    assert captured.value.error_code == "run_lock_unsupported"
    assert not run_dir.exists()


def test_runner_rejects_same_run_while_os_lock_is_held_by_another_process(
    tmp_path: Path,
) -> None:
    try:
        RunDirectoryLock.ensure_supported()
    except RunLockUnsupportedError:
        pytest.skip("OS file locking is unavailable on this platform")
    run_dir = make_run_dir(tmp_path)
    run_dir.mkdir(parents=True)
    process_context = multiprocessing.get_context("spawn")
    ready = process_context.Event()
    release = process_context.Event()
    process = process_context.Process(
        target=hold_run_lock,
        args=(str(run_dir / ".run.lock"), ready, release),
    )
    process.start()
    try:
        assert ready.wait(10), "child process did not acquire the run lock"
        context = make_context(run_dir)
        with pytest.raises(RunAlreadyActiveError) as captured:
            Runner().run(make_program([RecordingStep("STEP-001", [])]), context)
        assert captured.value.error_code == "run_already_active"
        assert not (run_dir / "checkpoint.json").exists()
        assert not (run_dir / "events.jsonl").exists()
    finally:
        release.set()
        process.join(10)
        if process.is_alive():
            process.terminate()
            process.join(5)

    assert process.exitcode == 0


def test_os_releases_run_lock_when_holder_process_exits(tmp_path: Path) -> None:
    try:
        RunDirectoryLock.ensure_supported()
    except RunLockUnsupportedError:
        pytest.skip("OS file locking is unavailable on this platform")
    run_dir = make_run_dir(tmp_path)
    run_dir.mkdir(parents=True)
    process_context = multiprocessing.get_context("spawn")
    ready = process_context.Event()
    process = process_context.Process(
        target=acquire_run_lock_and_exit,
        args=(str(run_dir / ".run.lock"), ready),
    )
    process.start()
    assert ready.wait(10), "child process did not acquire the run lock"
    process.join(10)
    if process.is_alive():
        process.terminate()
        process.join(5)
        pytest.fail("child process did not exit after acquiring the run lock")
    assert process.exitcode == 0

    result = Runner().run(
        make_program([RecordingStep("STEP-001", [])]),
        make_context(run_dir),
    )

    assert result.status == "succeeded"
    assert (run_dir / "checkpoint.json").is_file()


def test_program_lifecycle_wraps_steps_in_order(tmp_path: Path) -> None:
    lifecycle: list[str] = []

    class LifecycleProgram(BaseProgram):
        def prepare(self, context: ExecutionContext) -> None:
            lifecycle.append("prepare")

        def verify(self, context: ExecutionContext) -> bool:
            lifecycle.append("verify")
            return True

        def cleanup(self, context: ExecutionContext) -> None:
            lifecycle.append("cleanup")

    step = RecordingStep("STEP-001", lifecycle)
    program = LifecycleProgram(
        ProgramSpec(
            app_id="example.offline.export",
            program_id="offline-export",
            version="0.1.0",
            requirement_hash=REQUIREMENT_HASH,
        ),
        [step],
    )

    context = make_context(make_run_dir(tmp_path))
    Runner().run(program, context)

    assert lifecycle == ["prepare", "STEP-001", "verify", "cleanup"]
    events = read_events(context.run_dir / "events.jsonl")
    event_types = [event["event_type"] for event in events]
    assert event_types[0] == "run.started"
    assert events[0]["details"]["requirement_hash"] == REQUIREMENT_HASH
    assert "run.prepared" in event_types
    assert "run.verifying" in event_types
    assert "run.cleaned" in event_types
    assert event_types[-1] == "run.succeeded"


def test_program_verification_failure_marks_run_failed_and_cleans_up(tmp_path: Path) -> None:
    lifecycle: list[str] = []

    class FailingVerificationProgram(BaseProgram):
        def verify(self, context: ExecutionContext) -> bool:
            lifecycle.append("verify")
            return False

        def cleanup(self, context: ExecutionContext) -> None:
            lifecycle.append("cleanup")

    program = FailingVerificationProgram(
        ProgramSpec(
            app_id="example.offline.export",
            program_id="offline-export",
            version="0.1.0",
            requirement_hash=REQUIREMENT_HASH,
        ),
        [RecordingStep("STEP-001", lifecycle)],
    )
    context = make_context(make_run_dir(tmp_path))

    with pytest.raises(ProgramVerificationError):
        Runner().run(program, context)

    checkpoint = read_json(context.run_dir / "checkpoint.json")
    assert checkpoint["status"] == "failed"
    assert lifecycle == ["STEP-001", "verify", "cleanup"]


def test_step_spec_normalizes_declared_contract_lists() -> None:
    spec = StepSpec(
        step_id="STEP-001",
        name="Contract step",
        declared_inputs=["source"],
        declared_outputs=["result"],
        success_conditions=["result_valid"],
        recovery=["verify_then_retry"],
    )

    assert spec.declared_inputs == ("source",)
    assert spec.declared_outputs == ("result",)
    assert spec.success_conditions == ("result_valid",)
    assert spec.recovery == ("verify_then_retry",)


def test_runner_enforces_cooperative_step_deadline(tmp_path: Path) -> None:
    class SlowStep(Step):
        def __init__(self) -> None:
            super().__init__(
                StepSpec(
                    step_id="STEP-SLOW",
                    name="Slow step",
                    timeout_seconds=0.001,
                )
            )

        def execute(self, context: ExecutionContext) -> dict[str, bool]:
            time.sleep(0.01)
            return {"finished": True}

        def verify(self, context: ExecutionContext, result: object) -> bool:
            return True

    context = make_context(make_run_dir(tmp_path))

    with pytest.raises(StepRunError) as captured:
        Runner().run(make_program([SlowStep()]), context)

    assert captured.value.error_code == "step_timeout"
    checkpoint = read_json(context.run_dir / "checkpoint.json")
    assert checkpoint["steps"]["STEP-SLOW"]["error"]["code"] == "step_timeout"


def test_cleanup_failure_emits_specific_event_and_fails_run(tmp_path: Path) -> None:
    class CleanupFailureProgram(BaseProgram):
        def cleanup(self, context: ExecutionContext) -> None:
            raise RuntimeError("cleanup failed")

    context = make_context(make_run_dir(tmp_path))
    program = CleanupFailureProgram(
        ProgramSpec(
            app_id="example.offline.export",
            program_id="offline-export",
            version="0.1.0",
            requirement_hash=REQUIREMENT_HASH,
        ),
        [RecordingStep("STEP-001", [])],
    )

    with pytest.raises(RuntimeError, match="cleanup failed"):
        Runner().run(program, context)

    event_types = [event["event_type"] for event in read_events(context.run_dir / "events.jsonl")]
    assert "run.cleanup_failed" in event_types
    assert event_types[-1] == "run.failed"


def test_recovery_verification_uses_step_deadline(tmp_path: Path) -> None:
    class SlowRecoveryStep(Step):
        def __init__(self) -> None:
            super().__init__(
                StepSpec(
                    step_id="STEP-RECOVER",
                    name="Slow recovery",
                    timeout_seconds=0.001,
                )
            )

        def execute(self, context: ExecutionContext) -> object:
            raise RuntimeError("initial failure")

        def verify(self, context: ExecutionContext, result: object) -> bool:
            return False

        def verify_recovery(self, context: ExecutionContext, checkpoint: object) -> bool:
            time.sleep(0.01)
            return False

    context = make_context(make_run_dir(tmp_path))
    program = make_program([SlowRecoveryStep()])
    with pytest.raises(StepRunError):
        Runner().run(program, context)

    with pytest.raises(TimeoutError) as captured:
        Runner().run(program, make_context(make_run_dir(tmp_path)), resume=True)

    assert getattr(captured.value, "error_code") == "step_timeout"
    checkpoint = read_json(context.run_dir / "checkpoint.json")
    assert checkpoint["status"] == "failed"
    assert checkpoint["steps"]["STEP-RECOVER"]["status"] == "failed"
    assert checkpoint["steps"]["STEP-RECOVER"]["error"] == {
        "code": "step_timeout",
        "type": "StepTimeoutError",
    }
    events = read_events(context.run_dir / "events.jsonl")
    recovery_failure = [
        event
        for event in events
        if event["event_type"] == "step.failed"
        and event.get("step_id") == "STEP-RECOVER"
    ][-1]
    assert recovery_failure["status"] == "failed"
    assert recovery_failure["error_code"] == "step_timeout"
    assert recovery_failure["details"]["exception_type"] == "StepTimeoutError"
    assert events[-1]["event_type"] == "run.failed"
    assert events[-1]["error_code"] == "step_timeout"


def test_recovery_exception_replaces_old_error_and_emits_step_failed(tmp_path: Path) -> None:
    class RecoveryProbeError(RuntimeError):
        error_code = "recovery_probe_failed"

    class FailingRecoveryStep(Step):
        def __init__(self) -> None:
            super().__init__(
                StepSpec(
                    step_id="STEP-RECOVER",
                    name="Failing recovery",
                )
            )

        def execute(self, context: ExecutionContext) -> object:
            raise RuntimeError("initial failure")

        def verify(self, context: ExecutionContext, result: object) -> bool:
            return False

        def verify_recovery(self, context: ExecutionContext, checkpoint: object) -> bool:
            raise RecoveryProbeError("recovery probe failed")

    context = make_context(make_run_dir(tmp_path))
    program = make_program([FailingRecoveryStep()])
    with pytest.raises(StepRunError):
        Runner().run(program, context)

    before_resume = read_json(context.run_dir / "checkpoint.json")
    assert before_resume["steps"]["STEP-RECOVER"]["error"]["code"] == (
        "step_execution_failed"
    )

    with pytest.raises(RecoveryProbeError, match="recovery probe failed"):
        Runner().run(program, make_context(make_run_dir(tmp_path)), resume=True)

    checkpoint = read_json(context.run_dir / "checkpoint.json")
    record = checkpoint["steps"]["STEP-RECOVER"]
    assert checkpoint["status"] == "failed"
    assert record["status"] == "failed"
    assert record["error"] == {
        "code": "recovery_probe_failed",
        "type": "RecoveryProbeError",
    }

    events = read_events(context.run_dir / "events.jsonl")
    recovery_failure = [
        event
        for event in events
        if event["event_type"] == "step.failed"
        and event.get("step_id") == "STEP-RECOVER"
    ][-1]
    assert recovery_failure["status"] == "failed"
    assert recovery_failure["error_code"] == "recovery_probe_failed"
    assert recovery_failure["details"]["exception_type"] == "RecoveryProbeError"
    assert events[-1]["event_type"] == "run.failed"
    assert events[-1]["error_code"] == "recovery_probe_failed"


class RaisingRecoveryStep(RecordingStep):
    """A step whose recovery read blows up, the way texts() does off-page."""

    def verify_recovery(self, context: ExecutionContext, checkpoint: object) -> bool:
        raise RuntimeError("frame is not on this page")


class PrepareProbeProgram(BaseProgram):
    """Records prepare activity and answers the resume satisfaction hook."""

    def __init__(self, *args, satisfied: object = False, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.satisfied = satisfied
        self.prepare_calls = 0
        self.satisfaction_calls = 0

    def prepare_is_satisfied(self, context: ExecutionContext) -> bool:
        self.satisfaction_calls += 1
        if isinstance(self.satisfied, Exception):
            raise self.satisfied
        return bool(self.satisfied)

    def prepare(self, context: ExecutionContext) -> None:
        self.prepare_calls += 1


def make_prepare_program(steps: list[Step], *, satisfied: object = False):
    return PrepareProbeProgram(
        ProgramSpec(
            app_id="example.offline.export",
            program_id="offline-export",
            version="0.1.0",
            requirement_hash=REQUIREMENT_HASH,
            name="offline test",
        ),
        steps,
        satisfied=satisfied,
    )


def run_then_resume(tmp_path: Path, program, run_id: str = "run-001"):
    """Fail one run, then resume the same program, returning the resume result."""

    with pytest.raises(StepRunError):
        Runner().run(program, make_context(make_run_dir(tmp_path, run_id)))
    return Runner().run(
        program,
        make_context(make_run_dir(tmp_path, run_id)),
        resume=True,
    )


def test_resume_replays_a_succeeded_step_whose_state_is_gone(tmp_path: Path) -> None:
    """A checkpoint records what happened, not what is still true."""

    calls: list[str] = []
    program = make_program(
        [
            RecordingStep("STEP-001", calls, recovery_verification=False),
            RecordingStep("STEP-002", calls, fail_times=1),
        ]
    )

    result = run_then_resume(tmp_path, program)

    assert result.status == "succeeded"
    # STEP-001 cannot prove its effect survived, so it is redone rather than
    # leaving STEP-002 without the state it depends on.
    assert result.skipped_steps == ()
    assert "STEP-001" in result.completed_steps
    assert calls == ["STEP-001", "STEP-002", "STEP-001", "STEP-002"]
    events = read_events(make_run_dir(tmp_path) / "events.jsonl")
    stale = [event for event in events if event["event_type"] == "step.checkpoint_stale"]
    assert [event["step_id"] for event in stale] == ["STEP-001"]
    assert stale[0]["details"]["reason"] == "recovery_unverified"


def test_resume_treats_a_raising_recovery_check_as_stale(tmp_path: Path) -> None:
    """texts()/count() raise when their frame is absent; that means gone, not crash."""

    calls: list[str] = []
    program = make_program(
        [
            RaisingRecoveryStep("STEP-001", calls),
            RecordingStep("STEP-002", calls, fail_times=1),
        ]
    )

    result = run_then_resume(tmp_path, program)

    assert result.status == "succeeded"
    assert "STEP-001" in result.completed_steps
    events = read_events(make_run_dir(tmp_path) / "events.jsonl")
    stale = [event for event in events if event["event_type"] == "step.checkpoint_stale"]
    assert stale[0]["details"] == {
        "reason": "recovery_error",
        "exception_type": "RuntimeError",
    }


def test_resume_blocks_a_succeeded_write_step_that_cannot_be_reverified(
    tmp_path: Path,
) -> None:
    """Redoing an external write is never silently safe."""

    calls: list[str] = []
    program = make_program(
        [
            RecordingStep(
                "STEP-001",
                calls,
                recovery_verification=False,
                side_effect=SideEffect.WRITE,
            ),
            RecordingStep("STEP-002", calls, fail_times=1),
        ]
    )
    with pytest.raises(StepRunError):
        Runner().run(program, make_context(make_run_dir(tmp_path)))

    with pytest.raises(ResumeBlockedError):
        Runner().run(program, make_context(make_run_dir(tmp_path)), resume=True)

    assert calls == ["STEP-001", "STEP-002"]


def test_resume_skips_prepare_when_the_program_reports_it_satisfied(
    tmp_path: Path,
) -> None:
    calls: list[str] = []
    program = make_prepare_program(
        [
            RecordingStep("STEP-001", calls, recovery_verification=True),
            RecordingStep("STEP-002", calls, fail_times=1),
        ],
        satisfied=True,
    )

    result = run_then_resume(tmp_path, program)

    assert result.status == "succeeded"
    # Once for the first run; the resume asked the hook instead.
    assert program.prepare_calls == 1
    assert program.satisfaction_calls == 1
    event_types = [
        event["event_type"] for event in read_events(make_run_dir(tmp_path) / "events.jsonl")
    ]
    assert "run.prepare_skipped" in event_types


def test_resume_runs_prepare_when_the_satisfaction_check_raises(tmp_path: Path) -> None:
    """Unable to answer means not satisfied: one wasted prepare beats a skipped one."""

    calls: list[str] = []
    program = make_prepare_program(
        [
            RecordingStep("STEP-001", calls, recovery_verification=True),
            RecordingStep("STEP-002", calls, fail_times=1),
        ],
        satisfied=RuntimeError("cannot read the page"),
    )

    result = run_then_resume(tmp_path, program)

    assert result.status == "succeeded"
    assert program.prepare_calls == 2
    event_types = [
        event["event_type"] for event in read_events(make_run_dir(tmp_path) / "events.jsonl")
    ]
    assert "run.prepare_check_failed" in event_types
    assert "run.prepare_skipped" not in event_types
    assert "run.prepared" in event_types


def test_fresh_run_never_consults_the_prepare_satisfaction_hook(tmp_path: Path) -> None:
    calls: list[str] = []
    program = make_prepare_program(
        [RecordingStep("STEP-001", calls)],
        satisfied=True,
    )

    Runner().run(program, make_context(make_run_dir(tmp_path)))

    assert program.prepare_calls == 1
    assert program.satisfaction_calls == 0
