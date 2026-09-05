"""Ordered runs and explicit agent-directed continuation after failure."""

from __future__ import annotations

import json
import time
from abc import ABC, abstractmethod
from collections.abc import Iterable, Mapping, MutableMapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .contracts import RunMode
from .diagnostics import exception_diagnostics
from .events import JsonlEventLogger, sanitize_event_value
from .elements import override_element_locators
from .verification import Counterexample


class RuntimeContractError(ValueError):
    error_code = "runtime_contract_invalid"


class StepTimeoutError(TimeoutError):
    error_code = "step_timeout"


class StepRunError(RuntimeError):
    def __init__(
        self, step_id: str, error_code: str, message: str, *, run_id: str | None = None
    ) -> None:
        super().__init__(message)
        self.step_id = step_id
        self.error_code = error_code
        self.run_id = run_id


@dataclass(frozen=True, slots=True)
class ProgramSpec:
    app_id: str
    name: str


@dataclass(frozen=True, slots=True)
class StepSpec:
    step_id: str
    name: str
    timeout_seconds: float = 30.0

    def __post_init__(self) -> None:
        if not self.step_id.strip() or not self.name.strip():
            raise RuntimeContractError("step ID and name must not be empty")
        if self.timeout_seconds <= 0:
            raise RuntimeContractError("step timeout must be positive")


class Step(ABC):
    def __init__(self, spec: StepSpec) -> None:
        self.spec = spec

    @abstractmethod
    def execute(self, context: ExecutionContext) -> Mapping[str, object]: ...

    @abstractmethod
    def verify(
        self, context: ExecutionContext, result: Mapping[str, object]
    ) -> bool: ...

    @abstractmethod
    def counterexamples(self) -> Iterable[Counterexample]: ...


class BaseProgram:
    def __init__(self, spec: ProgramSpec, steps: Sequence[Step]) -> None:
        self.spec = spec
        self.steps = tuple(steps)
        ids = [step.spec.step_id for step in self.steps]
        if not spec.app_id or not ids or len(ids) != len(set(ids)):
            raise RuntimeContractError(
                "program needs an app ID and uniquely identified steps"
            )

    def step(self, step_id: str) -> Step:
        return next(step for step in self.steps if step.spec.step_id == step_id)


@dataclass(slots=True)
class ExecutionContext:
    app_id: str
    run_id: str
    account_id: str
    run_dir: Path
    download_dir: Path
    mode: RunMode = RunMode.LIVE
    services: MutableMapping[str, Any] = field(default_factory=dict)
    metadata: MutableMapping[str, Any] = field(default_factory=dict)
    inputs: MutableMapping[str, Any] = field(default_factory=dict)
    outputs: MutableMapping[str, Any] = field(default_factory=dict)
    current_step_id: str | None = field(default=None, init=False)
    step_deadline_monotonic: float | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        self.run_dir = Path(self.run_dir)
        self.download_dir = Path(self.download_dir)

    def service(self, name: str) -> Any:
        if name not in self.services:
            raise RuntimeContractError(f"service {name!r} has not been configured")
        return self.services[name]

    @property
    def browser(self) -> Any:
        return self.service("browser")

    @property
    def feishu(self) -> Any:
        return self.service("feishu")

    @property
    def db(self) -> Any:
        return self.service("db")

    @property
    def excel(self) -> Any:
        return self.service("excel")

    def ensure_step_within_deadline(self) -> None:
        if (
            self.step_deadline_monotonic is not None
            and time.monotonic() > self.step_deadline_monotonic
        ):
            raise StepTimeoutError(
                f"step {self.current_step_id} exceeded its time budget"
            )


@dataclass(frozen=True, slots=True)
class RunResult:
    run_id: str
    status: str
    completed_steps: tuple[str, ...]
    outputs: Mapping[str, Any]


def validate_resume(
    program: BaseProgram, previous: Mapping[str, Any], from_step: str
) -> tuple[str, ...]:
    """Check the recorded prefix without rechecking transient old page states."""
    if (
        previous.get("app_id") != program.spec.app_id
        or previous.get("status") != "failed"
    ):
        raise RuntimeContractError("resume needs a failed run of this application")
    if not isinstance(previous.get("inputs"), Mapping):
        raise RuntimeContractError("this run has no saved inputs; start a new run")
    ids = tuple(step.spec.step_id for step in program.steps)
    if from_step not in ids:
        raise RuntimeContractError("resume step does not exist in this program")
    prefix = ids[: ids.index(from_step)]
    completed = previous.get("completed_steps", [])
    outputs = previous.get("outputs", {})
    if not isinstance(completed, list) or tuple(completed[: len(prefix)]) != prefix:
        raise RuntimeContractError(
            "resume cannot skip a step without a successful result"
        )
    if not isinstance(outputs, Mapping) or any(
        not isinstance(outputs.get(step_id), Mapping) for step_id in prefix
    ):
        raise RuntimeContractError("resume is missing a previous step result")
    return prefix


class Runner:
    def run(
        self,
        program: BaseProgram,
        context: ExecutionContext,
        *,
        previous: Mapping[str, Any] | None = None,
        from_step: str | None = None,
        step_result: Mapping[str, Any] | None = None,
        locator_overrides: Mapping[str, Any] | None = None,
    ) -> RunResult:
        if program.spec.app_id != context.app_id:
            raise RuntimeContractError("program and context app IDs differ")
        completed: list[str] = []
        if previous is not None:
            if from_step is None:
                raise RuntimeContractError("agent must select a resume step")
            completed = list(validate_resume(program, previous, from_step))
            if previous.get("account_id") != context.account_id:
                raise RuntimeContractError("resume must use the original account")
            if previous.get("run_id") == context.run_id:
                raise RuntimeContractError("resume needs a new attempt directory")
            context.inputs = dict(previous["inputs"])
            context.mode = RunMode(previous["mode"])
            context.download_dir = Path(previous["download_dir"])
            context.outputs = {key: dict(previous["outputs"][key]) for key in completed}
        elif from_step is not None:
            raise RuntimeContractError("a starting step requires a previous failed run")
        if step_result is not None and (
            previous is None
            or previous.get("failed_step") != from_step
            or not isinstance(step_result, Mapping)
        ):
            raise RuntimeContractError("a supplied result must belong to the failed step")
        if locator_overrides and previous is None:
            raise RuntimeContractError("temporary locators require a failed run")
        original_elements = context.services.get("elements")
        patched_elements = (
            override_element_locators(context.service("elements"), locator_overrides)
            if locator_overrides
            else None
        )
        context.run_dir.mkdir(parents=True, exist_ok=True)
        report_path = context.run_dir / "result.json"
        if report_path.exists():
            raise RuntimeContractError("each invocation needs a new run directory")
        logger = JsonlEventLogger(context.run_dir / "events.jsonl")
        report: dict[str, Any] = {
            "app_id": context.app_id,
            "run_id": context.run_id,
            "account_id": context.account_id,
            "mode": context.mode.value,
            "inputs": dict(context.inputs),
            "download_dir": str(context.download_dir),
            "status": "running",
        }
        if previous is not None:
            report.update(resumed_from=previous["run_id"], from_step=from_step)
        if locator_overrides:
            report["locator_overrides"] = dict(locator_overrides)
        if step_result is not None:
            report["agent_result_step"] = from_step

        def emit(event: str, **details: Any) -> None:
            logger.emit(
                event,
                app_id=context.app_id,
                run_id=context.run_id,
                step_id=context.current_step_id,
                **details,
            )

        def save_report() -> None:
            report.update(completed_steps=list(completed), outputs=context.outputs)
            temporary = report_path.with_suffix(".tmp")
            temporary.write_text(
                json.dumps(sanitize_event_value(report), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            temporary.replace(report_path)

        emit(
            "run.started",
            status="running",
            details={
                "resumed_from": report.get("resumed_from"),
                "from_step": from_step,
            },
        )
        try:
            if patched_elements is not None:
                context.services["elements"] = patched_elements
            for step in program.steps[len(completed) :]:
                context.current_step_id = step.spec.step_id
                report["current_step"] = step.spec.step_id
                started = time.monotonic()
                context.step_deadline_monotonic = started + step.spec.timeout_seconds
                save_report()
                emit("step.started", status="running")
                agent_completed = step_result is not None and step.spec.step_id == from_step
                result = dict(step_result) if agent_completed else step.execute(context)
                context.ensure_step_within_deadline()
                if (
                    not isinstance(result, Mapping)
                    or step.verify(context, result) is not True
                ):
                    raise StepRunError(
                        step.spec.step_id,
                        "step_verification_failed",
                        "step result did not satisfy its success condition",
                    )
                context.ensure_step_within_deadline()
                context.outputs[step.spec.step_id] = dict(result)
                completed.append(step.spec.step_id)
                save_report()
                emit(
                    "step.succeeded",
                    status="succeeded",
                    duration_ms=int((time.monotonic() - started) * 1000),
                    details={"source": "agent" if agent_completed else "program"},
                )
            report["status"] = "succeeded"
            context.current_step_id = None
            emit("run.succeeded", status="succeeded")
        except Exception as error:
            code = getattr(error, "error_code", "step_execution_failed")
            report.update(
                status="failed",
                failed_step=context.current_step_id,
                error={
                    "code": code,
                    "type": type(error).__name__,
                    "diagnostics": exception_diagnostics(error),
                },
            )
            emit(
                "step.failed",
                status="failed",
                error_code=code,
                details={"exception_type": type(error).__name__},
            )
            emit("run.failed", status="failed", error_code=code)
            if isinstance(error, StepRunError):
                error.run_id = context.run_id
                raise
            raise StepRunError(
                context.current_step_id or "unknown",
                code,
                "program stopped at a failed step",
                run_id=context.run_id,
            ) from error
        finally:
            if patched_elements is not None:
                context.services["elements"] = original_elements
            context.current_step_id = None
            context.step_deadline_monotonic = None
            report.pop("current_step", None)
            save_report()
        return RunResult(
            context.run_id, "succeeded", tuple(completed), dict(context.outputs)
        )
