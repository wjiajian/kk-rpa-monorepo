"""Business Step orchestration over application-local candidate instructions."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from rpa_core.contracts import ResumePolicy, RetryPolicy, SideEffect
from rpa_core.runtime import ExecutionContext, Step, StepSpec

from .models import StoreConfig


InputFactory = Callable[[ExecutionContext], Mapping[str, object]]


class InstructionStep(Step):
    def __init__(
        self,
        spec: StepSpec,
        instruction_id: str,
        input_factory: InputFactory | None = None,
    ) -> None:
        super().__init__(spec)
        self.instruction_id = instruction_id
        self.input_factory = input_factory or (lambda context: {})

    def execute(self, context: ExecutionContext) -> Mapping[str, object]:
        result = context.instructions.execute(
            self.instruction_id,
            context,
            self.input_factory(context),
        )
        context.outputs[self.spec.step_id] = dict(result)
        return result

    def verify(self, context: ExecutionContext, result: Any) -> bool:
        if not isinstance(result, Mapping):
            return False
        return context.instructions.get(self.instruction_id).verify(context, result)

    def verify_recovery(
        self,
        context: ExecutionContext,
        checkpoint: Mapping[str, Any],
    ) -> bool:
        result = checkpoint.get("result")
        if not isinstance(result, Mapping):
            return False
        verified = context.instructions.get(self.instruction_id).verify(context, result)
        if verified:
            context.outputs[self.spec.step_id] = dict(result)
        return verified


def _retry_policy() -> RetryPolicy:
    return RetryPolicy(
        max_attempts=2,
        delay_seconds=0.0,
        backoff_multiplier=1.0,
        retryable_errors=[
            "instruction_execution_failed",
            "instruction_verification_failed",
        ],
    )


def _download_retry_policy() -> RetryPolicy:
    return RetryPolicy(
        max_attempts=1,
        delay_seconds=0.0,
        backoff_multiplier=1.0,
        retryable_errors=[],
    )


def _store(context: ExecutionContext) -> StoreConfig:
    value = context.metadata.get("store_config")
    if not isinstance(value, StoreConfig):
        raise TypeError("execution context metadata must contain StoreConfig")
    return value


def build_steps() -> tuple[InstructionStep, ...]:
    common = {
        "retry_policy": _retry_policy(),
        "resume_policy": ResumePolicy.VERIFY_THEN_RUN,
        "side_effect": SideEffect.READ,
    }
    download_common = {**common, "retry_policy": _download_retry_policy()}
    return (
        InstructionStep(
            StepSpec(
                step_id="S001",
                name="打开库存模块",
                timeout_seconds=30.0,
                declared_outputs=("inventory_module_opened",),
                success_conditions=("inventory module marker is visible",),
                recovery=("verify module marker before repeating navigation",),
                **common,
            ),
            "jushuitan.inventory.open_module",
        ),
        InstructionStep(
            StepSpec(
                step_id="S002",
                name="进入商品库存",
                timeout_seconds=30.0,
                declared_outputs=("product_stock_opened",),
                success_conditions=("product stock page marker is visible",),
                recovery=("verify product stock marker before repeating navigation",),
                **common,
            ),
            "jushuitan.inventory.open_product_stock",
        ),
        InstructionStep(
            StepSpec(
                step_id="S003",
                name="选择本地配置品牌",
                timeout_seconds=30.0,
                declared_inputs=("brand_value",),
                declared_outputs=("selected_brand", "selection_visible"),
                success_conditions=("configured brand is visibly selected",),
                recovery=("re-read selection state before selecting again",),
                **common,
            ),
            "jushuitan.inventory.select_brand",
            lambda context: {"brand_value": _store(context).brand_value},
        ),
        InstructionStep(
            StepSpec(
                step_id="S004",
                name="搜索并验证筛选",
                timeout_seconds=60.0,
                declared_inputs=("brand_value",),
                declared_outputs=("filter_applied",),
                success_conditions=(
                    "filtered result marker is visible",
                    "configured brand remains selected after search",
                ),
                recovery=("verify filtered results before searching again",),
                **common,
            ),
            "jushuitan.inventory.search",
            lambda context: {"brand_value": _store(context).brand_value},
        ),
        InstructionStep(
            StepSpec(
                step_id="S005",
                name="导出并验证库存文件",
                timeout_seconds=360.0,
                declared_inputs=("filename", "brand_value"),
                declared_outputs=("download_path", "sha256", "size_bytes"),
                success_conditions=(
                    "download is inside the run directory",
                    "download is non-empty and hash is reproducible",
                ),
                recovery=("verify an existing completed download before downloading again",),
                **download_common,
            ),
            "jushuitan.inventory.export_stock",
            lambda context: {
                "filename": str(context.metadata["export_filename"]),
                "brand_value": _store(context).brand_value,
            },
        ),
    )


__all__ = ["InstructionStep", "build_steps"]
