"""Verified target-account session bootstrap and identity verification."""

from __future__ import annotations

from collections.abc import Mapping
import unicodedata

from rpa_core.browser import ElementSpec, SecretValue
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


def _normalized_secret(value: object) -> str:
    revealed = value.reveal() if isinstance(value, SecretValue) else value
    if not isinstance(revealed, str) or not revealed.strip():
        raise ValueError("expected account identity must be one non-empty string")
    return " ".join(unicodedata.normalize("NFKC", revealed).casefold().split())


def _identity_matches(page_text: str, expected_identity: object) -> bool:
    normalized_page = " ".join(
        unicodedata.normalize("NFKC", page_text).casefold().split()
    )
    return _normalized_secret(expected_identity) in normalized_page


def _capture_failure(context: ExecutionContext, name: str) -> None:
    try:
        context.browser.screenshot(name=name)
    except Exception:
        pass


class EnsureAccountSession(Instruction):
    spec = InstructionSpec(
        instruction_id="jushuitan.auth.ensure_account_session",
        version="0.1.0",
        name="确保目标账号登录会话",
        platform="jushuitan",
        declared_inputs=("login_url", "username", "password", "expected_identity"),
        declared_outputs=(
            "authenticated",
            "identity_verified",
            "login_performed",
            "human_verification_required",
        ),
        required_element_ids=(
            "jushuitan.erp.shell.authenticated_marker",
            "jushuitan.erp.shell.account_identity_surface",
        ),
        preconditions=(
            "browser profile is exclusively locked",
            "target-account credentials are available only at runtime",
        ),
        success_conditions=(
            "authenticated page marker is visible",
            "page identity contains the configured target-account identity",
        ),
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
        try:
            browser.open(str(inputs["login_url"]), wait="complete")
            context.ensure_step_within_deadline()
            authenticated = browser.exists(authenticated_marker, timeout=3.0)
            login_performed = not authenticated
            human_verification_required = False
            if login_performed:
                login_result = context.instructions.execute(
                    "jushuitan.auth.login",
                    context,
                    {
                        "login_url": inputs["login_url"],
                        "username": inputs["username"],
                        "password": inputs["password"],
                    },
                )
                authenticated = bool(login_result["authenticated"])
                human_verification_required = bool(
                    login_result["human_verification_required"]
                )

            identity_verified = False
            if authenticated:
                page_text = browser.text(
                    _element(
                        context,
                        "jushuitan.erp.shell.account_identity_surface",
                    )
                )
                identity_verified = _identity_matches(
                    page_text,
                    inputs["expected_identity"],
                )

            if not authenticated:
                _capture_failure(context, "account-session-unavailable.png")
            elif not identity_verified:
                _capture_failure(context, "account-identity-mismatch.png")
            return {
                "authenticated": authenticated,
                "identity_verified": identity_verified,
                "login_performed": login_performed,
                "human_verification_required": human_verification_required,
            }
        except Exception:
            _capture_failure(context, "account-session-error.png")
            raise

    def verify(
        self,
        context: ExecutionContext,
        result: Mapping[str, object],
    ) -> bool:
        return (
            bool(result["authenticated"])
            and bool(result["identity_verified"])
            and not bool(result["human_verification_required"])
        )


__all__ = ["EnsureAccountSession"]
