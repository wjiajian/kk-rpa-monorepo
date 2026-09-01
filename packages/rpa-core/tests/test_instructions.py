from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import pytest

from rpa_core.contracts import RunMode, SideEffect
from rpa_core.instructions import (
    DuplicateInstructionError,
    Instruction,
    InstructionContractError,
    InstructionExecutionError,
    InstructionInputError,
    InstructionNotFoundError,
    InstructionOutputError,
    InstructionRegistry,
    InstructionSpec,
    InstructionVerificationError,
)
from rpa_core.runtime import ExecutionContext, RuntimeContractError


ZERO_HASH = "sha256:" + ("0" * 64)


def context(tmp_path: Path, registry: InstructionRegistry | None = None) -> ExecutionContext:
    services = {} if registry is None else {"instructions": registry}
    return ExecutionContext(
        app_id="example.instructions",
        program_id="example-program",
        program_version="0.1.0",
        requirement_hash=ZERO_HASH,
        run_id="test-run",
        account_id="STORE_001",
        mode=RunMode.PREVIEW,
        run_dir=tmp_path,
        services=services,
    )


class EchoInstruction(Instruction):
    spec = InstructionSpec(
        instruction_id="example.echo",
        version="1.0.0",
        name="Echo",
        platform="example",
        declared_inputs=("value",),
        declared_outputs=("echoed",),
        required_element_ids=("example.page.field",),
        preconditions=("field_visible",),
        success_conditions=("echo_matches",),
        side_effect=SideEffect.READ,
    )

    def execute(
        self,
        context: ExecutionContext,
        inputs: Mapping[str, object],
    ) -> Mapping[str, object]:
        assert context.outputs == {}
        return {"echoed": inputs["value"]}

    def verify(
        self,
        context: ExecutionContext,
        result: Mapping[str, object],
    ) -> bool:
        return result["echoed"] == "ok"


def test_instruction_spec_requires_verifiable_success_and_typed_side_effect() -> None:
    with pytest.raises(InstructionContractError, match="success_conditions"):
        InstructionSpec(
            instruction_id="example.invalid",
            version="1.0.0",
            name="Invalid",
            platform="example",
        )

    with pytest.raises(InstructionContractError, match="side_effect"):
        InstructionSpec(
            instruction_id="example.invalid",
            version="1.0.0",
            name="Invalid",
            platform="example",
            success_conditions=("observable_result",),
            side_effect="read",  # type: ignore[arg-type]
        )


def test_registry_executes_exact_contract_without_checkpoint_side_effects(
    tmp_path: Path,
) -> None:
    registry = InstructionRegistry([EchoInstruction()])
    runtime_context = context(tmp_path, registry)

    result = registry.execute("example.echo", runtime_context, {"value": "ok"})

    assert dict(result) == {"echoed": "ok"}
    assert runtime_context.outputs == {}
    assert runtime_context.instructions is registry
    with pytest.raises(TypeError):
        result["echoed"] = "changed"  # type: ignore[index]


def test_registry_rejects_duplicate_unknown_and_input_drift(tmp_path: Path) -> None:
    registry = InstructionRegistry([EchoInstruction()])
    with pytest.raises(DuplicateInstructionError):
        registry.register(EchoInstruction())
    with pytest.raises(InstructionNotFoundError):
        registry.get("example.missing")
    with pytest.raises(InstructionInputError, match="missing inputs"):
        registry.execute("example.echo", context(tmp_path), {})
    with pytest.raises(InstructionInputError, match="unexpected inputs"):
        registry.execute(
            "example.echo",
            context(tmp_path),
            {"value": "ok", "extra": True},
        )
    with pytest.raises(InstructionInputError, match="keys must be strings"):
        registry.execute(
            "example.echo",
            context(tmp_path),
            {1: "ok"},  # type: ignore[dict-item]
        )


def test_registry_rejects_output_drift_and_failed_verification(tmp_path: Path) -> None:
    class BadOutput(EchoInstruction):
        def execute(self, context, inputs):  # type: ignore[no-untyped-def]
            return {"wrong": inputs["value"]}

    with pytest.raises(InstructionOutputError, match="missing outputs"):
        InstructionRegistry([BadOutput()]).execute(
            "example.echo", context(tmp_path), {"value": "ok"}
        )

    with pytest.raises(InstructionVerificationError):
        InstructionRegistry([EchoInstruction()]).execute(
            "example.echo", context(tmp_path), {"value": "not-ok"}
        )


def test_registry_wraps_unexpected_errors_without_exposing_message(tmp_path: Path) -> None:
    class Exploding(EchoInstruction):
        def execute(self, context, inputs):  # type: ignore[no-untyped-def]
            raise RuntimeError("sensitive runtime detail")

    with pytest.raises(InstructionExecutionError) as caught:
        InstructionRegistry([Exploding()]).execute(
            "example.echo", context(tmp_path), {"value": "ok"}
        )
    assert caught.value.error_code == "instruction_execution_failed"
    assert "sensitive runtime detail" not in str(caught.value)
    assert isinstance(caught.value.__cause__, RuntimeError)


def test_execution_context_requires_typed_instruction_registry(tmp_path: Path) -> None:
    runtime_context = context(tmp_path)
    runtime_context.services["instructions"] = object()

    with pytest.raises(RuntimeContractError, match="InstructionRegistry"):
        _ = runtime_context.instructions
