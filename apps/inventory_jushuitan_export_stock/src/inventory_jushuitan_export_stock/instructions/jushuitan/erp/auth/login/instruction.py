"""Candidate interactive login capability; real execution requires authorization."""

from __future__ import annotations

from collections.abc import Mapping

from rpa_core.contracts import SideEffect
from rpa_core.instructions import Instruction, InstructionSpec
from rpa_core.runtime import ExecutionContext

from inventory_jushuitan_export_stock.elements import get_element


class Login(Instruction):
    spec = InstructionSpec(
        instruction_id="jushuitan.auth.login",
        version="0.1.0",
        name="登录聚水潭 ERP",
        platform="jushuitan",
        declared_inputs=("login_url", "username", "password"),
        declared_outputs=("authenticated", "human_verification_required"),
        required_element_ids=(
            "jushuitan.erp.login.account_input",
            "jushuitan.erp.login.password_input",
            "jushuitan.erp.login.agreement_checkbox",
            "jushuitan.erp.login.submit_button",
            "jushuitan.erp.login.human_verification_marker",
            "jushuitan.erp.shell.authenticated_marker",
        ),
        preconditions=("browser profile is exclusively locked",),
        success_conditions=("authenticated page marker is visible",),
        side_effect=SideEffect.WRITE,
    )

    def execute(
        self,
        context: ExecutionContext,
        inputs: Mapping[str, object],
    ) -> Mapping[str, object]:
        browser = context.browser
        authenticated_marker = get_element("jushuitan.erp.shell.authenticated_marker")
        if browser.exists(authenticated_marker, timeout=1.0):
            return {"authenticated": True, "human_verification_required": False}

        browser.open(str(inputs["login_url"]), wait="complete")
        context.ensure_step_within_deadline()
        browser.input(get_element("jushuitan.erp.login.account_input"), inputs["username"])
        browser.input(get_element("jushuitan.erp.login.password_input"), inputs["password"])
        browser.click(get_element("jushuitan.erp.login.agreement_checkbox"))
        browser.click(get_element("jushuitan.erp.login.submit_button"))
        context.ensure_step_within_deadline()

        human_verification = browser.exists(
            get_element("jushuitan.erp.login.human_verification_marker"),
            timeout=2.0,
        )
        authenticated = False
        if not human_verification:
            authenticated = browser.exists(authenticated_marker, timeout=15.0)
        return {
            "authenticated": authenticated,
            "human_verification_required": human_verification,
        }

    def verify(
        self,
        context: ExecutionContext,
        result: Mapping[str, object],
    ) -> bool:
        return bool(result["authenticated"]) and not bool(
            result["human_verification_required"]
        )
