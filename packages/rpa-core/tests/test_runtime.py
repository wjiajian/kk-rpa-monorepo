import json
import time

import pytest
from rpa_core.runtime import (
    BaseProgram,
    ExecutionContext,
    ProgramSpec,
    Runner,
    Step,
    StepRunError,
    StepSpec,
)
from rpa_core.verification import Counterexample, FakeState


class RecordingStep(Step):
    def __init__(self, name, calls, fail=False, timeout=30):
        super().__init__(StepSpec(name, name, timeout))
        self.calls, self.fail = calls, fail

    def execute(self, ctx):
        self.calls.append(self.spec.step_id)
        return {"ok": not self.fail}

    def verify(self, ctx, result):
        return result["ok"]

    def counterexamples(self):
        yield Counterexample("wrong", FakeState(counts={"demo.page.rows": 0}))


def context(tmp_path, run_id="one"):
    return ExecutionContext(
        "demo", run_id, "STORE_001", tmp_path / "runs" / run_id, tmp_path / "downloads"
    )


def test_failure_is_recorded_and_a_new_run_starts_at_the_first_step(tmp_path):
    calls = []
    first = BaseProgram(
        ProgramSpec("demo", "Demo"),
        [
            RecordingStep("S1", calls),
            RecordingStep("S2", calls, True),
            RecordingStep("S3", calls),
        ],
    )
    ctx = context(tmp_path)
    with pytest.raises(StepRunError) as caught:
        Runner().run(first, ctx)
    assert caught.value.step_id == "S2"
    assert calls == ["S1", "S2"]
    report = json.loads((ctx.run_dir / "result.json").read_text())
    assert report["status"] == "failed" and report["completed_steps"] == ["S1"]
    assert report["failed_step"] == "S2"
    retry = BaseProgram(
        first.spec, [RecordingStep("S1", calls), RecordingStep("S2", calls)]
    )
    result = Runner().run(retry, context(tmp_path, "two"))
    assert result.status == "succeeded"
    assert calls == ["S1", "S2", "S1", "S2"]
    assert not list(tmp_path.rglob("checkpoint.json"))


def test_exceptions_stop_the_program_without_repeating_the_write(tmp_path):
    class Failing(RecordingStep):
        def execute(self, ctx):
            self.calls.append("write")
            raise RuntimeError("failed transaction")

    calls = []
    program = BaseProgram(
        ProgramSpec("demo", "Demo"), [Failing("S1", calls), RecordingStep("S2", calls)]
    )
    with pytest.raises(StepRunError):
        Runner().run(program, context(tmp_path))
    assert calls == ["write"]
    report = json.loads((tmp_path / "runs" / "one" / "result.json").read_text())
    cause = report["error"]["diagnostics"]["root_cause"]
    assert cause["type"] == "RuntimeError"
    assert cause["location"]["function"] == "execute"
    assert "failed transaction" not in json.dumps(report)


def test_timeout_cannot_be_recorded_as_success(tmp_path):
    class Slow(RecordingStep):
        def execute(self, ctx):
            ctx.step_deadline_monotonic = time.monotonic() - 1
            return {"ok": True}

    program = BaseProgram(ProgramSpec("demo", "Demo"), [Slow("S1", [])])
    with pytest.raises(StepRunError) as caught:
        Runner().run(program, context(tmp_path))
    assert caught.value.error_code == "step_timeout"


def test_unconfigured_services_do_not_fall_back_to_fakes(tmp_path):
    ctx = context(tmp_path)
    for name in ("feishu", "db", "excel"):
        with pytest.raises(ValueError, match="not been configured"):
            getattr(ctx, name)
        service = object()
        ctx.services[name] = service
        assert getattr(ctx, name) is service


def test_run_report_redacts_credentials(tmp_path):
    class Sensitive(RecordingStep):
        def execute(self, ctx):
            return {"ok": True, "password": "private-value"}

    ctx = context(tmp_path)
    Runner().run(BaseProgram(ProgramSpec("demo", "Demo"), [Sensitive("S1", [])]), ctx)
    assert "private-value" not in (ctx.run_dir / "result.json").read_text()


def test_agent_resume_preserves_inputs_and_does_not_recheck_old_pages(tmp_path):
    calls = []
    steps = [
        RecordingStep("S1", calls),
        RecordingStep("S2", calls, True),
        RecordingStep("S3", calls),
    ]
    program = BaseProgram(ProgramSpec("demo", "Demo"), steps)
    original = context(tmp_path)
    original.inputs = {"business_date": "2026-09-03"}
    original.metadata = {"password": "runtime-only-password"}
    with pytest.raises(StepRunError):
        Runner().run(program, original)
    source = original.run_dir / "result.json"
    original_bytes = source.read_bytes()
    previous = json.loads(original_bytes)
    assert "runtime-only-password" not in source.read_text()
    steps[0].verify = lambda *_: pytest.fail("completed page no longer exists")
    steps[1].fail = False
    resumed = context(tmp_path, "two")
    resumed.inputs = {"business_date": "2026-09-04"}
    result = Runner().run(program, resumed, previous=previous, from_step="S2")
    assert calls == ["S1", "S2", "S2", "S3"]
    assert result.completed_steps == ("S1", "S2", "S3")
    assert resumed.inputs == {"business_date": "2026-09-03"}
    assert result.outputs["S1"] == previous["outputs"]["S1"]
    assert source.read_bytes() == original_bytes
    report = json.loads((resumed.run_dir / "result.json").read_text())
    assert report["resumed_from"] == "one" and report["from_step"] == "S2"


@pytest.mark.parametrize("from_step", ["S1", "S2"])
def test_agent_can_rewind_and_recompute_results_from_a_selected_step(
    tmp_path, from_step
):
    calls = []
    program = BaseProgram(
        ProgramSpec("demo", "Demo"),
        [
            RecordingStep("S1", calls),
            RecordingStep("S2", calls),
            RecordingStep("S3", calls, True),
        ],
    )
    original = context(tmp_path)
    with pytest.raises(StepRunError):
        Runner().run(program, original)
    previous = json.loads((original.run_dir / "result.json").read_text())
    program.steps[-1].fail = False
    calls.clear()
    resumed = context(tmp_path, "two")
    assert (
        Runner().run(program, resumed, previous=previous, from_step=from_step).status
        == "succeeded"
    )
    assert calls == (["S1", "S2", "S3"] if from_step == "S1" else ["S2", "S3"])


@pytest.mark.parametrize("from_step", ["S3", "missing"])
def test_resume_cannot_silently_skip_an_unfinished_step(tmp_path, from_step):
    program = BaseProgram(
        ProgramSpec("demo", "Demo"),
        [
            RecordingStep("S1", []),
            RecordingStep("S2", [], True),
            RecordingStep("S3", []),
        ],
    )
    original = context(tmp_path)
    with pytest.raises(StepRunError):
        Runner().run(program, original)
    previous = json.loads((original.run_dir / "result.json").read_text())
    resumed = context(tmp_path, "two")
    with pytest.raises(ValueError):
        Runner().run(program, resumed, previous=previous, from_step=from_step)
    assert not resumed.run_dir.exists()


def test_successful_progress_is_on_disk_before_the_next_step_runs(tmp_path):
    class Observe(RecordingStep):
        def execute(self, ctx):
            report = json.loads((ctx.run_dir / "result.json").read_text())
            assert report["completed_steps"] == ["S1"]
            assert report["current_step"] == "S2"
            return super().execute(ctx)

    program = BaseProgram(
        ProgramSpec("demo", "Demo"), [RecordingStep("S1", []), Observe("S2", [])]
    )
    Runner().run(program, context(tmp_path))
