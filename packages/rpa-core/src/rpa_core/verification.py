"""Falsifiable step assertions — the framework's only mandatory constraint.

A ``verify()`` that no browser state can drive to ``False`` is not an
assertion. Two defects hide behind such a verifier:

* the *fake verifier* — ``verify()`` asserts something that is always true on
  the page, e.g. ``exists("css:table tbody")`` on a list page that renders its
  table shell before any filter is applied;
* the *fake executor* — ``execute()`` echoes its own inputs instead of reading
  back page state, e.g. ``return {"selection_visible": True}``.

A counterexample expressed as a plain result mapping only catches the first.
Only running ``execute()`` against a fake page catches the second, which is why
:class:`Counterexample` carries a :class:`FakeState` rather than a result.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol


class CounterexampleContractError(AssertionError):
    """A step failed the falsifiability contract."""

    error_code = "step_assertion_not_falsifiable"


@dataclass(frozen=True, slots=True)
class FakeState:
    """Declarative description of the page a counterexample needs.

    Steps describe the failing page instead of constructing a browser, so the
    same declaration works for any application's fake-browser fixture.

    * ``hidden`` — element IDs that must not be present
    * ``counts`` — match counts returned by ``count()``
    * ``texts`` — text values returned by ``texts()``
    * ``downloads_available`` — whether a download fixture is offered at all
    """

    hidden: tuple[str, ...] = ()
    counts: Mapping[str, int] = field(default_factory=dict)
    texts: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    downloads_available: bool = True

    @property
    def is_default(self) -> bool:
        return (
            not self.hidden
            and not self.counts
            and not self.texts
            and self.downloads_available
        )


@dataclass(frozen=True, slots=True)
class Counterexample:
    """One fake page state under which a step must fail.

    ``metadata`` overrides entries on the execution context, for the cases
    where the failure is driven by run inputs rather than by the page.
    """

    label: str
    state: FakeState = field(default_factory=FakeState)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.label.strip():
            raise ValueError("counterexample label must not be empty")
        if self.state.is_default and not self.metadata:
            raise ValueError(
                f"counterexample {self.label!r} changes nothing about the page "
                "or the inputs, so it cannot falsify anything"
            )


class SupportsCounterexamples(Protocol):
    def counterexamples(self) -> Iterable[Counterexample]: ...


@dataclass(frozen=True, slots=True)
class CounterexampleResult:
    step_id: str
    label: str
    rejected: bool
    reason: str

    @property
    def ok(self) -> bool:
        return self.rejected


def check_step_counterexamples(
    step: Any,
    context_factory: Callable[[Counterexample], Any],
) -> list[CounterexampleResult]:
    """Run every counterexample of one step and report whether it was rejected.

    ``context_factory`` builds a fresh ``ExecutionContext`` bound to the
    counterexample's browser, metadata and services. A step is considered to
    have rejected the state when ``execute()`` raises or ``verify()`` returns
    false.
    """

    step_id = str(getattr(step.spec, "step_id", getattr(step, "id", step)))
    cases = list(getattr(step, "counterexamples", lambda: ())())
    if not cases:
        raise CounterexampleContractError(
            f"step {step_id} provides no counterexample; an assertion that "
            "nothing can falsify is not an assertion"
        )

    results: list[CounterexampleResult] = []
    seen: set[str] = set()
    for case in cases:
        if case.label in seen:
            raise CounterexampleContractError(
                f"step {step_id} repeats counterexample label {case.label!r}"
            )
        seen.add(case.label)
        context = context_factory(case)
        try:
            result = step.execute(context)
        except Exception as error:  # noqa: BLE001 - any failure is a rejection
            results.append(
                CounterexampleResult(
                    step_id,
                    case.label,
                    True,
                    f"execute raised {type(error).__name__}",
                )
            )
            continue
        try:
            verified = bool(step.verify(context, result))
        except Exception as error:  # noqa: BLE001 - a raising verifier rejects
            results.append(
                CounterexampleResult(
                    step_id,
                    case.label,
                    True,
                    f"verify raised {type(error).__name__}",
                )
            )
            continue
        results.append(
            CounterexampleResult(
                step_id,
                case.label,
                not verified,
                "verify returned false" if not verified else "verify returned TRUE",
            )
        )
    return results


def assert_steps_are_falsifiable(
    steps: Iterable[Any],
    context_factory: Callable[[Any, Counterexample], Any],
) -> None:
    """Enforce the contract across a program's steps, raising on any survivor."""

    survivors: list[str] = []
    for step in steps:
        results = check_step_counterexamples(
            step,
            lambda case, bound=step: context_factory(bound, case),
        )
        survivors.extend(
            f"{item.step_id}/{item.label}" for item in results if not item.ok
        )
    if survivors:
        raise CounterexampleContractError(
            "these counterexamples did not fail, so the assertion is vacuous: "
            + ", ".join(survivors)
        )


__all__ = [
    "Counterexample",
    "FakeState",
    "CounterexampleContractError",
    "CounterexampleResult",
    "SupportsCounterexamples",
    "assert_steps_are_falsifiable",
    "check_step_counterexamples",
]
