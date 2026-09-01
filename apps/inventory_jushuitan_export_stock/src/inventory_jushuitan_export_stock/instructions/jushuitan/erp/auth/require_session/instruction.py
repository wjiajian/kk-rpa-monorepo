"""Candidate authenticated-session check."""

from collections.abc import Mapping

from rpa_core.contracts import SideEffect
from rpa_core.instructions import Instruction, InstructionSpec
from rpa_core.runtime import ExecutionContext

from inventory_jushuitan_export_stock.elements import get_element


class RequireSession(Instruction):
    spec = InstructionSpec(
        instruction_id="jushuitan.auth.require_session",
        version="0.1.0",
        name="验证登录态",
        platform="jushuitan",
        declared_outputs=("authenticated",),
        required_element_ids=("jushuitan.erp.shell.authenticated_marker",),
        preconditions=("persistent browser profile is open",),
        success_conditions=("authenticated page marker is visible",),
        side_effect=SideEffect.READ,
    )

    def execute(
        self,
        context: ExecutionContext,
        inputs: Mapping[str, object],
    ) -> Mapping[str, object]:
        authenticated = context.browser.exists(
            get_element("jushuitan.erp.shell.authenticated_marker"),
            timeout=5.0,
        )
        return {"authenticated": authenticated}

    def verify(
        self,
        context: ExecutionContext,
        result: Mapping[str, object],
    ) -> bool:
        return bool(result["authenticated"])
