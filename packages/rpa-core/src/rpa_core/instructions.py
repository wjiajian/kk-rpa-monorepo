"""Reusable instruction contracts and deterministic execution registry.

An instruction is a small, independently verifiable capability.  Applications
compose instructions inside runtime ``Step`` objects; the registry deliberately
does not know about checkpoints or step transitions.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
import re
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from .contracts import SideEffect

if TYPE_CHECKING:
    from .runtime import ExecutionContext


_INSTRUCTION_ID_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]*$")
_ELEMENT_ID_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]*$")
_SEMVER_PATTERN = re.compile(
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:[-+][0-9A-Za-z.-]+)?$"
)


class InstructionError(RuntimeError):
    """Base error with a stable code suitable for retries and reports."""

    error_code = "instruction_error"
    retryable = False


class InstructionContractError(InstructionError, ValueError):
    error_code = "instruction_contract_invalid"


class DuplicateInstructionError(InstructionContractError):
    error_code = "instruction_duplicate"


class InstructionNotFoundError(InstructionError, KeyError):
    error_code = "instruction_not_found"


class InstructionInputError(InstructionContractError):
    error_code = "instruction_input_invalid"


class InstructionOutputError(InstructionContractError):
    error_code = "instruction_output_invalid"


class InstructionExecutionError(InstructionError):
    error_code = "instruction_execution_failed"

    def __init__(self, instruction_id: str, message: str) -> None:
        super().__init__(message)
        self.instruction_id = instruction_id


class InstructionVerificationError(InstructionError):
    error_code = "instruction_verification_failed"

    def __init__(self, instruction_id: str) -> None:
        super().__init__(f"instruction {instruction_id!r} did not satisfy its verifier")
        self.instruction_id = instruction_id


@dataclass(frozen=True, slots=True)
class InstructionSpec:
    """Machine-readable contract for one reusable instruction.

    The four fields ``platform``, ``required_element_ids``, the declared input
    and output names, and the verifier together express the same useful split
    as an RPA designer's operation context, target, action, and result.
    """

    instruction_id: str
    version: str
    name: str
    platform: str
    declared_inputs: tuple[str, ...] = ()
    declared_outputs: tuple[str, ...] = ()
    required_element_ids: tuple[str, ...] = ()
    preconditions: tuple[str, ...] = ()
    success_conditions: tuple[str, ...] = ()
    side_effect: SideEffect = SideEffect.NONE

    def __post_init__(self) -> None:
        if not _INSTRUCTION_ID_PATTERN.fullmatch(self.instruction_id):
            raise InstructionContractError(
                f"invalid instruction_id: {self.instruction_id!r}"
            )
        if not _SEMVER_PATTERN.fullmatch(self.version):
            raise InstructionContractError(
                f"instruction version must be semantic: {self.version!r}"
            )
        if not self.name.strip():
            raise InstructionContractError("instruction name must not be empty")
        if not self.platform.strip():
            raise InstructionContractError("instruction platform must not be empty")
        if not isinstance(self.side_effect, SideEffect):
            raise InstructionContractError(
                "instruction side_effect must be a SideEffect value"
            )

        for field_name in (
            "declared_inputs",
            "declared_outputs",
            "required_element_ids",
            "preconditions",
            "success_conditions",
        ):
            values = tuple(getattr(self, field_name))
            if any(not isinstance(value, str) or not value.strip() for value in values):
                raise InstructionContractError(
                    f"{field_name} must contain only non-empty strings"
                )
            if len(values) != len(set(values)):
                raise InstructionContractError(f"{field_name} must not contain duplicates")
            object.__setattr__(self, field_name, values)

        if not self.success_conditions:
            raise InstructionContractError(
                "instruction success_conditions must not be empty"
            )
        invalid_elements = [
            value
            for value in self.required_element_ids
            if not _ELEMENT_ID_PATTERN.fullmatch(value)
        ]
        if invalid_elements:
            raise InstructionContractError(
                f"invalid required element IDs: {invalid_elements!r}"
            )


class Instruction(ABC):
    """One reusable capability invoked by an application ``Step``."""

    spec: InstructionSpec

    @abstractmethod
    def execute(
        self,
        context: "ExecutionContext",
        inputs: Mapping[str, object],
    ) -> Mapping[str, object]:
        """Perform the capability and return only declared result values."""

    @abstractmethod
    def verify(
        self,
        context: "ExecutionContext",
        result: Mapping[str, object],
    ) -> bool:
        """Return true only after the declared success state is observable."""


class InstructionRegistry:
    """Register and execute instructions behind one stable error surface."""

    def __init__(self, instructions: tuple[Instruction, ...] | list[Instruction] = ()) -> None:
        self._instructions: dict[str, Instruction] = {}
        for instruction in instructions:
            self.register(instruction)

    def register(self, instruction: Instruction) -> None:
        if not isinstance(instruction, Instruction):
            raise InstructionContractError(
                "registered object must implement the Instruction contract"
            )
        spec = getattr(instruction, "spec", None)
        if not isinstance(spec, InstructionSpec):
            raise InstructionContractError(
                "registered instruction must expose an InstructionSpec as spec"
            )
        if spec.instruction_id in self._instructions:
            raise DuplicateInstructionError(
                f"instruction ID is already registered: {spec.instruction_id!r}"
            )
        self._instructions[spec.instruction_id] = instruction

    def get(self, instruction_id: str) -> Instruction:
        try:
            return self._instructions[instruction_id]
        except KeyError as error:
            raise InstructionNotFoundError(instruction_id) from error

    def specs(self) -> tuple[InstructionSpec, ...]:
        return tuple(
            self._instructions[instruction_id].spec
            for instruction_id in sorted(self._instructions)
        )

    def execute(
        self,
        instruction_id: str,
        context: "ExecutionContext",
        inputs: Mapping[str, object] | None = None,
    ) -> Mapping[str, object]:
        instruction = self.get(instruction_id)
        normalized_inputs = dict(inputs or {})
        if any(not isinstance(key, str) for key in normalized_inputs):
            raise InstructionInputError(
                f"instruction {instruction_id!r} input keys must be strings"
            )
        self._validate_keys(
            instruction_id,
            "input",
            actual=set(normalized_inputs),
            declared=set(instruction.spec.declared_inputs),
        )

        context.ensure_step_within_deadline()
        try:
            raw_result = instruction.execute(
                context,
                MappingProxyType(normalized_inputs),
            )
        except InstructionError:
            raise
        except Exception as error:
            raise InstructionExecutionError(
                instruction_id,
                f"instruction {instruction_id!r} failed: {type(error).__name__}",
            ) from error

        if not isinstance(raw_result, Mapping):
            raise InstructionOutputError(
                f"instruction {instruction_id!r} must return a mapping"
            )
        result: dict[str, object] = dict(raw_result)
        self._validate_keys(
            instruction_id,
            "output",
            actual=set(result),
            declared=set(instruction.spec.declared_outputs),
        )

        context.ensure_step_within_deadline()
        try:
            verified = instruction.verify(context, MappingProxyType(result))
        except InstructionError:
            raise
        except Exception as error:
            raise InstructionExecutionError(
                instruction_id,
                f"instruction {instruction_id!r} verifier failed: {type(error).__name__}",
            ) from error
        if verified is not True:
            raise InstructionVerificationError(instruction_id)
        context.ensure_step_within_deadline()
        return MappingProxyType(result)

    @staticmethod
    def _validate_keys(
        instruction_id: str,
        kind: str,
        *,
        actual: set[str],
        declared: set[str],
    ) -> None:
        missing = sorted(declared - actual)
        unexpected = sorted(actual - declared)
        if not missing and not unexpected:
            return
        parts: list[str] = []
        if missing:
            parts.append(f"missing {kind}s: {missing!r}")
        if unexpected:
            parts.append(f"unexpected {kind}s: {unexpected!r}")
        error_type = InstructionInputError if kind == "input" else InstructionOutputError
        raise error_type(f"instruction {instruction_id!r} " + "; ".join(parts))


__all__ = [
    "DuplicateInstructionError",
    "Instruction",
    "InstructionContractError",
    "InstructionError",
    "InstructionExecutionError",
    "InstructionInputError",
    "InstructionNotFoundError",
    "InstructionOutputError",
    "InstructionRegistry",
    "InstructionSpec",
    "InstructionVerificationError",
]
