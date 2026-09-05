"""Successful baselines and explicit, falsifiable outcome checks."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any


class CounterexampleContractError(AssertionError):
    error_code = "step_assertion_not_falsifiable"


@dataclass(frozen=True, slots=True)
class FakeState:
    hidden: tuple[str, ...] = ()
    counts: Mapping[str, int] = field(default_factory=dict)
    texts: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    downloads_available: bool = True
    new_tabs_available: bool = True

    @property
    def is_default(self) -> bool:
        return (
            not (self.hidden or self.counts or self.texts)
            and self.downloads_available
            and self.new_tabs_available
        )


@dataclass(frozen=True, slots=True)
class Counterexample:
    label: str
    state: FakeState = field(default_factory=FakeState)
    metadata: Mapping[str, Any] = field(default_factory=dict)
    expected_error: type[Exception] | None = None
    after_execute: Callable[[Any, Mapping[str, Any]], None] | None = None

    def __post_init__(self) -> None:
        if not self.label.strip():
            raise ValueError("counterexample label must not be empty")
        if self.state.is_default and not self.metadata and self.after_execute is None:
            raise ValueError("counterexample changes nothing")
        if self.expected_error is not None and not issubclass(
            self.expected_error, Exception
        ):
            raise ValueError("expected_error must be an exception type")


@dataclass(frozen=True, slots=True)
class CounterexampleResult:
    step_id: str
    label: str
    rejected: bool
    reason: str
    phase: str

    @property
    def ok(self) -> bool:
        return self.rejected


def check_step_counterexamples(
    step: Any,
    context_factory: Callable[[Counterexample | None], Any],
) -> list[CounterexampleResult]:
    """None requests the same unmodified happy fixture used by application tests."""
    step_id = step.spec.step_id
    baseline = context_factory(None)
    try:
        result = step.execute(baseline)
        valid = isinstance(result, Mapping) and step.verify(baseline, result) is True
    except Exception as error:
        raise CounterexampleContractError(
            f"{step_id}: successful baseline raised {type(error).__name__}"
        ) from error
    if not valid:
        raise CounterexampleContractError(
            f"{step_id}: successful baseline was rejected"
        )

    cases = list(step.counterexamples())
    if not cases:
        raise CounterexampleContractError(f"{step_id}: provides no counterexample")
    results: list[CounterexampleResult] = []
    labels: set[str] = set()
    for case in cases:
        if case.label in labels:
            raise CounterexampleContractError(
                f"{step_id}: repeats counterexample label"
            )
        labels.add(case.label)
        context = context_factory(case)
        try:
            candidate = step.execute(context)
        except Exception as error:
            if case.expected_error is None or not isinstance(
                error, case.expected_error
            ):
                raise CounterexampleContractError(
                    f"{step_id}/{case.label}: unexpected execute error {type(error).__name__}"
                ) from error
            results.append(
                CounterexampleResult(
                    step_id,
                    case.label,
                    True,
                    f"expected {type(error).__name__}",
                    "execute",
                )
            )
            continue
        if case.expected_error is not None:
            results.append(
                CounterexampleResult(
                    step_id,
                    case.label,
                    False,
                    "expected execute error did not occur",
                    "execute",
                )
            )
            continue
        if case.after_execute is not None:
            case.after_execute(context, candidate)
        try:
            verified = step.verify(context, candidate)
        except Exception as error:
            raise CounterexampleContractError(
                f"{step_id}/{case.label}: verifier raised {type(error).__name__}"
            ) from error
        results.append(
            CounterexampleResult(
                step_id,
                case.label,
                verified is False,
                "verify returned false"
                if verified is False
                else "verify did not reject",
                "verify",
            )
        )
    return results


def assert_steps_are_falsifiable(
    steps: Iterable[Any],
    context_factory: Callable[[Any, Counterexample | None], Any],
) -> None:
    for step in steps:
        results = check_step_counterexamples(
            step, lambda case: context_factory(step, case)
        )
        failures = [item.label for item in results if not item.ok]
        if failures:
            raise CounterexampleContractError(
                f"{step.spec.step_id}: counterexamples did not fail: {', '.join(failures)}"
            )
        if not any(item.phase == "verify" and item.ok for item in results):
            raise CounterexampleContractError(
                f"{step.spec.step_id}: needs an outcome rejected by verify after execute succeeds"
            )
