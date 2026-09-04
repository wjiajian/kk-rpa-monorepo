"""Versioned, side-effect-free contracts shared by every RPA application.

The models in this module deliberately describe data only.  Loading files,
computing hashes, and enforcing the two-file requirement gate live in
``rpa_core.requirements``.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


APP_ID_PATTERN = r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$"
APP_SLUG_PATTERN = r"^[a-z][a-z0-9_]*$"
ENTRYPOINT_PATTERN = r"^[a-zA-Z_][a-zA-Z0-9_.]*:[a-zA-Z_][a-zA-Z0-9_]*$"
HASH_PATTERN = r"^sha256:[0-9a-f]{64}$"
ITEM_ID_PATTERN = r"^[A-Za-z][A-Za-z0-9_.:-]*$"
SEMVER_PATTERN = r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:[-+][0-9A-Za-z.-]+)?$"


class ContractModel(BaseModel):
    """Common validation policy for persisted contracts."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
        validate_default=True,
    )


class AppStatus(StrEnum):
    """Application lifecycle states from ``AGENTS.md``."""

    DRAFT = "draft"
    PENDING_CONFIRMATION = "pending_confirmation"
    READY_FOR_TEST = "ready_for_test"
    TEST_FAILED = "test_failed"
    READY_FOR_REVIEW = "ready_for_review"
    APPROVED = "approved"
    READY_FOR_PUSH = "ready_for_push"


class RunMode(StrEnum):
    PREVIEW = "preview"
    LIVE = "live"


class StepStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    VERIFYING = "verifying"
    RETRY_WAIT = "retry_wait"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ResumePolicy(StrEnum):
    VERIFY_THEN_RUN = "verify_then_run"
    ALWAYS_RUN = "always_run"
    MANUAL = "manual"


class SideEffect(StrEnum):
    NONE = "none"
    READ = "read"
    WRITE = "write"


class ConfirmationStatus(StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"


class ElementResolutionStatus(StrEnum):
    UNRESOLVED = "unresolved"
    CANDIDATE = "candidate"
    RESOLVED = "resolved"


class InstructionResolutionStatus(StrEnum):
    UNRESOLVED = "unresolved"
    CANDIDATE = "candidate"
    RESOLVED = "resolved"


class VerificationStatus(StrEnum):
    NOT_RUN = "not_run"
    PASSED = "passed"
    FAILED = "failed"


class RetryPolicy(ContractModel):
    """Bounded retry settings used by both requirement and runtime steps."""

    max_attempts: int = Field(default=1, ge=1, le=100)
    delay_seconds: float = Field(default=0.0, ge=0.0)
    backoff_multiplier: float = Field(default=1.0, ge=1.0)
    retryable_errors: list[str] = Field(default_factory=list)

    @field_validator("retryable_errors")
    @classmethod
    def validate_retryable_errors(cls, values: list[str]) -> list[str]:
        return _require_unique_non_empty(values, "retryable_errors")


class AppCommands(ContractModel):
    """The fixed command surface every independent application exposes."""

    doctor: Literal["rpa-app doctor"] = "rpa-app doctor"
    check: Literal["rpa-app check"] = "rpa-app check"
    test: Literal["rpa-app test"] = "rpa-app test"
    preview: Literal["rpa-app run --mode preview"] = "rpa-app run --mode preview"
    live: Literal["rpa-app run --mode live"] = "rpa-app run --mode live"
    resume: Literal["rpa-app resume"] = "rpa-app resume"
    login: Literal["rpa-app login"] | None = None
    verify_candidates: Literal["rpa-app verify-candidates"] | None = None
    verify_elements: Literal["rpa-app verify-elements"] | None = None


class AppManifest(ContractModel):
    """Machine-readable contents of an application's ``app.toml``."""

    schema_version: Literal[1, 2] = 1
    app_id: str = Field(pattern=APP_ID_PATTERN)
    app_slug: str = Field(pattern=APP_SLUG_PATTERN)
    name: str = Field(min_length=1)
    version: str = Field(pattern=SEMVER_PATTERN)
    entrypoint: str = Field(pattern=ENTRYPOINT_PATTERN)
    python: str = Field(pattern=r"^3\.12(?:\.[0-9]+)?$")
    requirement_revision: int = Field(ge=0)
    requirement_hash: str = Field(pattern=HASH_PATTERN)
    configuration_schema: str = Field(default="config/config.schema.json", min_length=1)
    catalog_lock: str | None = None
    status: AppStatus = AppStatus.DRAFT
    latest_review: str = ""
    commands: AppCommands = Field(default_factory=AppCommands)

    @model_validator(mode="after")
    def validate_manifest_relationships(self) -> AppManifest:
        module_name = self.entrypoint.partition(":")[0].partition(".")[0]
        if module_name != self.app_slug:
            raise ValueError(
                "entrypoint package must start with app_slug "
                f"({self.app_slug!r}), got {module_name!r}"
            )
        _require_relative_path(self.configuration_schema, "configuration_schema")
        if self.schema_version == 1:
            if self.catalog_lock is not None:
                raise ValueError("schema_version 1 must not declare catalog_lock")
            if self.commands.login is not None or self.commands.verify_candidates is not None:
                raise ValueError("schema_version 1 must not declare V2 commands")
        else:
            if not self.catalog_lock:
                raise ValueError("schema_version 2 requires catalog_lock")
            _require_relative_path(self.catalog_lock, "catalog_lock")
            if self.commands.login != "rpa-app login":
                raise ValueError("schema_version 2 requires the standard login command")
            if self.commands.verify_candidates != "rpa-app verify-candidates":
                raise ValueError(
                    "schema_version 2 requires the standard verify-candidates command"
                )
        if self.latest_review:
            _require_relative_path(self.latest_review, "latest_review")
        if self.status in {AppStatus.APPROVED, AppStatus.READY_FOR_PUSH} and not self.latest_review:
            raise ValueError(f"status {self.status.value!r} requires latest_review")
        return self


class RequirementSource(ContractModel):
    document_id: str = Field(min_length=1)
    revision: int = Field(ge=0)
    requirement_hash: str = Field(pattern=HASH_PATTERN)
    document_url: str | None = None


class RequirementApplication(ContractModel):
    app_id: str = Field(pattern=APP_ID_PATTERN)
    app_slug: str = Field(pattern=APP_SLUG_PATTERN)
    name: str = Field(min_length=1)
    version: str = Field(pattern=SEMVER_PATTERN)
    entrypoint: str = Field(pattern=ENTRYPOINT_PATTERN)

    @model_validator(mode="after")
    def validate_entrypoint_matches_slug(self) -> RequirementApplication:
        module_name = self.entrypoint.partition(":")[0].partition(".")[0]
        if module_name != self.app_slug:
            raise ValueError(
                "entrypoint package must start with app_slug "
                f"({self.app_slug!r}), got {module_name!r}"
            )
        return self


class RequirementLoop(ContractModel):
    """A declarative loop; business code decides how its source is resolved."""

    item_name: str = Field(min_length=1)
    source: str = Field(min_length=1)
    max_iterations: int = Field(ge=1)


class RequirementStep(ContractModel):
    id: str = Field(pattern=ITEM_ID_PATTERN)
    name: str = Field(min_length=1)
    action: str = Field(min_length=1)
    inputs: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    success_conditions: list[str] = Field(min_length=1)
    conditions: list[str] = Field(default_factory=list)
    loop: RequirementLoop | None = None
    element_refs: list[str] = Field(default_factory=list)
    instruction_refs: list[str] = Field(default_factory=list)
    pending_confirmation_ids: list[str] = Field(default_factory=list)
    unresolved_element_ids: list[str] = Field(default_factory=list)
    unresolved_instruction_ids: list[str] = Field(default_factory=list)
    timeout_seconds: float = Field(default=30.0, gt=0.0)
    retry: RetryPolicy = Field(default_factory=RetryPolicy)
    resume: ResumePolicy = ResumePolicy.VERIFY_THEN_RUN
    recovery: list[str] = Field(default_factory=list)
    side_effect: SideEffect = SideEffect.NONE

    @field_validator(
        "inputs",
        "outputs",
        "success_conditions",
        "conditions",
        "element_refs",
        "instruction_refs",
        "pending_confirmation_ids",
        "unresolved_element_ids",
        "unresolved_instruction_ids",
        "recovery",
    )
    @classmethod
    def validate_unique_lists(cls, values: list[str], info: Any) -> list[str]:
        return _require_unique_non_empty(values, info.field_name)


class RequirementOutput(ContractModel):
    id: str = Field(pattern=ITEM_ID_PATTERN)
    name: str = Field(min_length=1)
    target: str = Field(min_length=1)
    write_mode: str = Field(min_length=1)
    fields: list[str] = Field(default_factory=list)
    unique_keys: list[str] = Field(default_factory=list)
    success_conditions: list[str] = Field(default_factory=list)
    side_effect: SideEffect = SideEffect.WRITE

    @field_validator("fields", "unique_keys", "success_conditions")
    @classmethod
    def validate_unique_lists(cls, values: list[str], info: Any) -> list[str]:
        return _require_unique_non_empty(values, info.field_name)


class PendingConfirmation(ContractModel):
    id: str = Field(pattern=r"^PC-[A-Za-z0-9_.:-]+$")
    requirement_step: str = Field(pattern=ITEM_ID_PATTERN)
    question: str = Field(min_length=1)
    risk: str = Field(min_length=1)
    source_location: str | None = None
    source_image: str | None = None
    status: ConfirmationStatus = ConfirmationStatus.OPEN
    developer_conclusion: str | None = None
    blocks_test: bool = True
    blocks_review: bool = True
    blocks_push: bool = True

    @model_validator(mode="after")
    def validate_resolution(self) -> PendingConfirmation:
        if self.source_image:
            _require_relative_path(self.source_image, "source_image")
        if self.status is ConfirmationStatus.RESOLVED and not self.developer_conclusion:
            raise ValueError("resolved confirmation requires developer_conclusion")
        return self

    @property
    def is_resolved(self) -> bool:
        return self.status is ConfirmationStatus.RESOLVED


class UnresolvedElement(ContractModel):
    id: str = Field(pattern=r"^UE-[A-Za-z0-9_.:-]+$")
    requirement_step: str = Field(pattern=ITEM_ID_PATTERN)
    platform: str = Field(min_length=1)
    page: str = Field(min_length=1)
    name: str = Field(min_length=1)
    screenshot: str | None = None
    reason: str = Field(min_length=1)
    resolution: str = Field(min_length=1)
    status: ElementResolutionStatus = ElementResolutionStatus.UNRESOLVED
    resolved_element_ref: str | None = None
    tested: bool = False
    blocks_test: bool = True
    blocks_review: bool = True
    blocks_push: bool = True

    @model_validator(mode="after")
    def validate_resolution(self) -> UnresolvedElement:
        if self.screenshot:
            _require_relative_path(self.screenshot, "screenshot")
        if self.status is ElementResolutionStatus.RESOLVED:
            if not self.resolved_element_ref:
                raise ValueError("resolved element requires resolved_element_ref")
            if not self.tested:
                raise ValueError("resolved element must be tested")
        elif self.resolved_element_ref:
            raise ValueError("resolved_element_ref is only valid for a resolved element")
        return self

    @property
    def is_resolved(self) -> bool:
        return self.status is ElementResolutionStatus.RESOLVED and self.tested


class UnresolvedInstruction(ContractModel):
    """A missing reusable capability retained inside a complete V2 flow."""

    id: str = Field(pattern=r"^UI-[A-Za-z0-9_.:-]+$")
    requirement_step: str = Field(pattern=ITEM_ID_PATTERN)
    platform: str = Field(min_length=1)
    capability: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    candidate_instruction_ref: str | None = Field(default=None, pattern=ITEM_ID_PATTERN)
    candidate_implementation: str | None = None
    fake_test_ref: str | None = None
    fake_test_status: VerificationStatus = VerificationStatus.NOT_RUN
    real_test_status: VerificationStatus = VerificationStatus.NOT_RUN
    real_test_evidence: str | None = None
    status: InstructionResolutionStatus = InstructionResolutionStatus.UNRESOLVED
    resolved_instruction_ref: str | None = Field(default=None, pattern=ITEM_ID_PATTERN)
    blocks_offline_test: bool = False
    blocks_real_run: bool = True
    blocks_review: bool = True
    blocks_push: bool = True

    @model_validator(mode="after")
    def validate_resolution(self) -> "UnresolvedInstruction":
        for field_name in (
            "candidate_implementation",
            "fake_test_ref",
            "real_test_evidence",
        ):
            value = getattr(self, field_name)
            if value:
                _require_relative_path(value, field_name)

        if self.status is InstructionResolutionStatus.UNRESOLVED:
            if any(
                value is not None
                for value in (
                    self.candidate_instruction_ref,
                    self.candidate_implementation,
                    self.fake_test_ref,
                    self.resolved_instruction_ref,
                    self.real_test_evidence,
                )
            ):
                raise ValueError(
                    "unresolved instruction must not declare candidate or resolved artifacts"
                )
            if self.fake_test_status is not VerificationStatus.NOT_RUN:
                raise ValueError("unresolved instruction fake test must be not_run")
            if self.real_test_status is not VerificationStatus.NOT_RUN:
                raise ValueError("unresolved instruction real test must be not_run")

        if self.status is InstructionResolutionStatus.CANDIDATE:
            if not all(
                (
                    self.candidate_instruction_ref,
                    self.candidate_implementation,
                    self.fake_test_ref,
                )
            ):
                raise ValueError(
                    "candidate instruction requires reference, implementation, and fake test"
                )
            if self.resolved_instruction_ref or self.real_test_evidence:
                raise ValueError("candidate instruction must not declare resolved evidence")
            if self.real_test_status is not VerificationStatus.NOT_RUN:
                raise ValueError("candidate instruction real test must be not_run")

        if self.status is InstructionResolutionStatus.RESOLVED:
            if not self.resolved_instruction_ref:
                raise ValueError("resolved instruction requires resolved_instruction_ref")
            if self.real_test_status is not VerificationStatus.PASSED:
                raise ValueError("resolved instruction requires a passed real test")
            if not self.real_test_evidence:
                raise ValueError("resolved instruction requires real_test_evidence")
        elif self.resolved_instruction_ref:
            raise ValueError(
                "resolved_instruction_ref is only valid for a resolved instruction"
            )
        return self

    @property
    def is_resolved(self) -> bool:
        return (
            self.status is InstructionResolutionStatus.RESOLVED
            and self.real_test_status is VerificationStatus.PASSED
            and bool(self.real_test_evidence)
        )


class TestRequirements(ContractModel):
    required_suites: list[str] = Field(
        default_factory=lambda: [
            "unit",
            "fake_services",
            "static",
            "architecture_boundary",
            "checkpoint_recovery",
            "sensitive_data",
        ]
    )
    real_browser_required: bool = True
    real_browser_authorization_required: bool = True
    external_write_preview_required: bool = True

    @field_validator("required_suites")
    @classmethod
    def validate_required_suites(cls, values: list[str]) -> list[str]:
        return _require_unique_non_empty(values, "required_suites")


class AuthorizationRequirements(ContractModel):
    real_browser_requires_authorization: bool = True
    live_requires_separate_authorization: bool = True
    live_scope_fields: list[str] = Field(
        default_factory=lambda: [
            "app_id",
            "app_version",
            "program_id",
            "program_version",
            "requirement_hash",
            "catalog_digest",
            "operation",
            "mode",
            "run_id",
            "resume_checkpoint_digest",
            "resume_step_id",
            "account_id",
            "profile_id",
            "allowed_origins",
            "step_ids",
            "browser_actions",
            "element_ids",
            "candidate_asset_refs",
            "external_writes",
            "external_writes.write_id",
            "external_writes.step_id",
            "external_writes.adapter",
            "external_writes.target",
            "external_writes.data_scope",
            "external_writes.expected_record_count",
            "external_writes.payload_digest",
            "source_preview_run_id",
        ]
    )

    @field_validator("live_scope_fields")
    @classmethod
    def validate_live_scope_fields(cls, values: list[str]) -> list[str]:
        values = _require_unique_non_empty(values, "live_scope_fields")
        if not values:
            raise ValueError("live_scope_fields must not be empty")
        return values


class RequirementSpec(ContractModel):
    """Canonical requirement contract persisted in Markdown and JSON."""

    schema_version: Literal[1, 2] = 1
    source: RequirementSource
    application: RequirementApplication
    steps: list[RequirementStep] = Field(min_length=1)
    outputs: list[RequirementOutput] = Field(default_factory=list)
    pending_confirmations: list[PendingConfirmation] = Field(default_factory=list)
    unresolved_elements: list[UnresolvedElement] = Field(default_factory=list)
    unresolved_instructions: list[UnresolvedInstruction] = Field(default_factory=list)
    test_requirements: TestRequirements = Field(default_factory=TestRequirements)
    authorization_requirements: AuthorizationRequirements = Field(
        default_factory=AuthorizationRequirements
    )

    @model_validator(mode="after")
    def validate_identifiers_and_references(self) -> RequirementSpec:
        groups: dict[str, list[str]] = {
            "steps": [step.id for step in self.steps],
            "outputs": [output.id for output in self.outputs],
            "pending_confirmations": [item.id for item in self.pending_confirmations],
            "unresolved_elements": [item.id for item in self.unresolved_elements],
            "unresolved_instructions": [item.id for item in self.unresolved_instructions],
        }
        for group_name, identifiers in groups.items():
            _raise_on_duplicates(identifiers, group_name)

        all_identifiers = [identifier for identifiers in groups.values() for identifier in identifiers]
        _raise_on_duplicates(all_identifiers, "all requirement objects")

        step_ids = set(groups["steps"])
        steps_by_id = {step.id: step for step in self.steps}
        pending_ids = set(groups["pending_confirmations"])
        unresolved_ids = set(groups["unresolved_elements"])
        unresolved_instruction_ids = set(groups["unresolved_instructions"])
        linked_pending: set[str] = set()
        linked_unresolved: set[str] = set()
        linked_unresolved_instructions: set[str] = set()

        if self.schema_version == 1:
            has_v2_fields = bool(self.unresolved_instructions) or any(
                step.instruction_refs or step.unresolved_instruction_ids
                for step in self.steps
            )
            if has_v2_fields:
                raise ValueError("schema_version 1 must not declare instruction fields")

        for step in self.steps:
            unknown_pending = set(step.pending_confirmation_ids) - pending_ids
            if unknown_pending:
                raise ValueError(
                    f"step {step.id!r} references unknown pending confirmations: "
                    f"{sorted(unknown_pending)!r}"
                )
            unknown_elements = set(step.unresolved_element_ids) - unresolved_ids
            if unknown_elements:
                raise ValueError(
                    f"step {step.id!r} references unknown unresolved elements: "
                    f"{sorted(unknown_elements)!r}"
                )
            unknown_instructions = (
                set(step.unresolved_instruction_ids) - unresolved_instruction_ids
            )
            if unknown_instructions:
                raise ValueError(
                    f"step {step.id!r} references unknown unresolved instructions: "
                    f"{sorted(unknown_instructions)!r}"
                )
            linked_pending.update(step.pending_confirmation_ids)
            linked_unresolved.update(step.unresolved_element_ids)
            linked_unresolved_instructions.update(step.unresolved_instruction_ids)

        for item in self.pending_confirmations:
            if item.requirement_step not in step_ids:
                raise ValueError(
                    f"pending confirmation {item.id!r} references unknown step "
                    f"{item.requirement_step!r}"
                )
            if item.id not in linked_pending:
                raise ValueError(f"pending confirmation {item.id!r} is not linked from its step")

        for item in self.unresolved_elements:
            if item.requirement_step not in step_ids:
                raise ValueError(
                    f"unresolved element {item.id!r} references unknown step "
                    f"{item.requirement_step!r}"
                )
            if item.id not in linked_unresolved:
                raise ValueError(f"unresolved element {item.id!r} is not linked from its step")
            if (
                item.is_resolved
                and item.resolved_element_ref not in steps_by_id[item.requirement_step].element_refs
            ):
                raise ValueError(
                    f"resolved element {item.id!r} is not referenced by its step"
                )

        for item in self.unresolved_instructions:
            if item.requirement_step not in step_ids:
                raise ValueError(
                    f"unresolved instruction {item.id!r} references unknown step "
                    f"{item.requirement_step!r}"
                )
            if item.id not in linked_unresolved_instructions:
                raise ValueError(
                    f"unresolved instruction {item.id!r} is not linked from its step"
                )
            if (
                item.is_resolved
                and item.resolved_instruction_ref
                not in steps_by_id[item.requirement_step].instruction_refs
            ):
                raise ValueError(
                    f"resolved instruction {item.id!r} is not referenced by its step"
                )

        return self

    @property
    def open_pending_confirmations(self) -> tuple[PendingConfirmation, ...]:
        return tuple(item for item in self.pending_confirmations if not item.is_resolved)

    @property
    def open_unresolved_elements(self) -> tuple[UnresolvedElement, ...]:
        return tuple(item for item in self.unresolved_elements if not item.is_resolved)

    @property
    def open_unresolved_instructions(self) -> tuple[UnresolvedInstruction, ...]:
        return tuple(item for item in self.unresolved_instructions if not item.is_resolved)

    @property
    def has_blockers(self) -> bool:
        return bool(
            self.open_pending_confirmations
            or self.open_unresolved_elements
            or self.open_unresolved_instructions
        )

    @property
    def blocking_item_ids(self) -> tuple[str, ...]:
        return tuple(
            [item.id for item in self.open_pending_confirmations]
            + [item.id for item in self.open_unresolved_elements]
            + [item.id for item in self.open_unresolved_instructions]
        )


def _require_unique_non_empty(values: list[str], field_name: str) -> list[str]:
    empty_indexes = [index for index, value in enumerate(values) if not value]
    if empty_indexes:
        raise ValueError(f"{field_name} contains empty values at indexes {empty_indexes!r}")
    _raise_on_duplicates(values, field_name)
    return values


def _raise_on_duplicates(values: list[str], field_name: str) -> None:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    if duplicates:
        raise ValueError(f"duplicate IDs in {field_name}: {sorted(duplicates)!r}")


def _require_relative_path(value: str, field_name: str) -> None:
    normalized = value.replace("\\", "/")
    if normalized.startswith("/") or normalized.startswith("~/"):
        raise ValueError(f"{field_name} must be repository-relative")
    if any(part == ".." for part in normalized.split("/")):
        raise ValueError(f"{field_name} must not escape its application directory")


__all__ = [
    "AppCommands",
    "AppManifest",
    "AppStatus",
    "AuthorizationRequirements",
    "ConfirmationStatus",
    "ElementResolutionStatus",
    "InstructionResolutionStatus",
    "PendingConfirmation",
    "RequirementApplication",
    "RequirementLoop",
    "RequirementOutput",
    "RequirementSource",
    "RequirementSpec",
    "RequirementStep",
    "ResumePolicy",
    "RetryPolicy",
    "RunMode",
    "SideEffect",
    "StepStatus",
    "TestRequirements",
    "UnresolvedElement",
    "UnresolvedInstruction",
    "VerificationStatus",
]
