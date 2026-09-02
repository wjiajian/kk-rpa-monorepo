"""Verified interactive login capability."""

from __future__ import annotations

from collections.abc import Mapping

from rpa_core.browser import ElementSpec
from rpa_core.contracts import SideEffect
from rpa_core.instructions import Instruction, InstructionSpec
from rpa_core.runtime import ExecutionContext


def _element(context: ExecutionContext, element_id: str) -> ElementSpec:
    catalog = context.services.get("elements")
    if not isinstance(catalog, Mapping):
        raise RuntimeError("execution context elements service is missing")
    element = catalog.get(element_id)
    if not isinstance(element, ElementSpec):
        raise RuntimeError(f"execution context element is missing: {element_id}")
    return element


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
            "jushuitan.erp.login.password_notice_confirm",
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
        authenticated_marker = _element(
            context,
            "jushuitan.erp.shell.authenticated_marker",
        )
        if browser.exists(authenticated_marker, timeout=1.0):
            return {"authenticated": True, "human_verification_required": False}

        browser.open(str(inputs["login_url"]), wait="complete")
        context.ensure_step_within_deadline()
        browser.input(
            _element(context, "jushuitan.erp.login.account_input"),
            inputs["username"],
        )
        browser.input(
            _element(context, "jushuitan.erp.login.password_input"),
            inputs["password"],
        )
        browser.click(_element(context, "jushuitan.erp.login.agreement_checkbox"))
        browser.click(_element(context, "jushuitan.erp.login.submit_button"))
        context.ensure_step_within_deadline()

        password_notice = _element(
            context,
            "jushuitan.erp.login.password_notice_confirm",
        )
        if browser.exists(password_notice, timeout=8.0):
            browser.click(password_notice)
        authenticated = browser.exists(authenticated_marker, timeout=15.0)
        human_verification = not authenticated
        if human_verification:
            browser.screenshot(name="human-verification-required.png")
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
