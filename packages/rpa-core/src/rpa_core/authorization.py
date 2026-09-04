"""Durable, exactly scoped authorization for real RPA operations.

An authorization record is application-local runtime state, not a credential.
Its immutable scope is proposed first, explicitly granted second, and atomically
claimed immediately before a real boundary is crossed.  Claiming is single-use:
a crash after claim burns the record and requires a new authorization.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import stat
from time import monotonic, sleep
from typing import Any, Literal
from urllib.parse import urlsplit
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .browser import (
    ArtifactRef,
    BrowserActions,
    DownloadRef,
    ElementSpec,
    SecretLike,
)
from .catalog import CatalogLock
from .contracts import APP_ID_PATTERN, HASH_PATTERN, RunMode, SEMVER_PATTERN
from .runtime import RunAlreadyActiveError, RunDirectoryLock, RunLockError


_SAFE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_ITEM_ID_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]*$")
_CANDIDATE_REF_PATTERN = re.compile(
    r"^(?:element|instruction):[A-Za-z][A-Za-z0-9_.:-]*$"
)
_ERROR_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,127}$")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _resolve_now(value: datetime | None) -> datetime:
    return _utc_now() if value is None else _require_aware(value, "now")


def _require_aware(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must include a timezone")
    return value


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _digest(value: object) -> str:
    return f"sha256:{sha256(_canonical_json(value).encode('utf-8')).hexdigest()}"


def _object_without_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise AuthorizationRecordInvalidError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _normalize_origin(value: str) -> str:
    candidate = value.strip()
    parsed = urlsplit(candidate)
    if parsed.scheme.casefold() not in {"http", "https"} or not parsed.hostname:
        raise ValueError(f"invalid HTTP(S) origin: {value!r}")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("an origin must not contain user information")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ValueError("allowed_origins entries must be origins without paths or queries")
    scheme = parsed.scheme.casefold()
    hostname = parsed.hostname.casefold()
    try:
        port = parsed.port
    except ValueError as error:
        raise ValueError(f"invalid origin port: {value!r}") from error
    default_port = 443 if scheme == "https" else 80
    rendered_host = f"[{hostname}]" if ":" in hostname else hostname
    authority = (
        rendered_host
        if port in {None, default_port}
        else f"{rendered_host}:{port}"
    )
    return f"{scheme}://{authority}"


def _origin_from_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme.casefold() not in {"http", "https"} or not parsed.hostname:
        raise BrowserOriginNotAuthorizedError("browser URL does not have an HTTP(S) origin")
    if parsed.username is not None or parsed.password is not None:
        raise BrowserOriginNotAuthorizedError("browser URL must not contain user information")
    scheme = parsed.scheme.casefold()
    hostname = parsed.hostname.casefold()
    try:
        port = parsed.port
    except ValueError as error:
        raise BrowserOriginNotAuthorizedError("browser URL has an invalid port") from error
    default_port = 443 if scheme == "https" else 80
    rendered_host = f"[{hostname}]" if ":" in hostname else hostname
    authority = (
        rendered_host
        if port in {None, default_port}
        else f"{rendered_host}:{port}"
    )
    return f"{scheme}://{authority}"


def _unique(values: Sequence[Any], name: str) -> tuple[Any, ...]:
    normalized = tuple(values)
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"{name} must not contain duplicates")
    return normalized


class _FrozenModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
        validate_default=True,
    )


class AuthorizationOperation(StrEnum):
    LOGIN = "login"
    VERIFY_CANDIDATES = "verify_candidates"
    VERIFY_ELEMENTS = "verify_elements"
    RUN = "run"
    RESUME = "resume"


class AuthorizationStatus(StrEnum):
    REQUESTED = "requested"
    GRANTED = "granted"
    CLAIMED = "claimed"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNKNOWN = "unknown"
    REVOKED = "revoked"


class BrowserAction(StrEnum):
    OPEN = "open"
    EXISTS = "exists"
    CLICK = "click"
    INPUT = "input"
    TEXT = "text"
    SELECT = "select"
    DOWNLOAD = "download"
    SCREENSHOT = "screenshot"


_ELEMENT_ACTIONS = frozenset(
    {
        BrowserAction.EXISTS,
        BrowserAction.CLICK,
        BrowserAction.INPUT,
        BrowserAction.TEXT,
        BrowserAction.SELECT,
        BrowserAction.DOWNLOAD,
    }
)


class ExternalWriteStatus(StrEnum):
    CLAIMED = "claimed"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNKNOWN = "unknown"


class ExternalWriteScope(_FrozenModel):
    write_id: str = Field(pattern=_SAFE_ID_PATTERN.pattern)
    step_id: str = Field(pattern=_ITEM_ID_PATTERN.pattern)
    target: str = Field(min_length=1)
    data_scope: dict[str, Any] = Field(default_factory=dict)
    expected_record_count: int = Field(ge=0)
    payload_digest: str = Field(pattern=HASH_PATTERN)
    adapter: str = Field(default="external", pattern=_ITEM_ID_PATTERN.pattern)

    @field_validator("data_scope")
    @classmethod
    def validate_data_scope(cls, value: dict[str, Any]) -> dict[str, Any]:
        try:
            encoded = _canonical_json(value)
            decoded = json.loads(encoded)
        except (TypeError, ValueError) as error:
            raise ValueError("data_scope must contain finite JSON values") from error
        if not isinstance(decoded, dict):  # defensive; the field type already enforces this
            raise ValueError("data_scope must be a JSON object")
        return decoded


class AuthorizationScope(_FrozenModel):
    app_id: str = Field(pattern=APP_ID_PATTERN)
    app_version: str = Field(pattern=SEMVER_PATTERN)
    program_id: str = Field(pattern=_ITEM_ID_PATTERN.pattern)
    program_version: str = Field(pattern=SEMVER_PATTERN)
    requirement_hash: str = Field(pattern=HASH_PATTERN)
    catalog_digest: str = Field(pattern=HASH_PATTERN)
    operation: AuthorizationOperation
    mode: RunMode
    run_id: str = Field(pattern=_SAFE_ID_PATTERN.pattern)
    resume_checkpoint_digest: str | None = Field(
        default=None,
        pattern=HASH_PATTERN,
    )
    resume_step_id: str | None = Field(
        default=None,
        pattern=_ITEM_ID_PATTERN.pattern,
    )
    account_id: str = Field(pattern=_SAFE_ID_PATTERN.pattern)
    profile_id: str = Field(pattern=_SAFE_ID_PATTERN.pattern)
    allowed_origins: tuple[str, ...] = Field(min_length=1)
    step_ids: tuple[str, ...] = Field(min_length=1)
    browser_actions: tuple[BrowserAction, ...] = Field(min_length=1)
    element_ids: tuple[str, ...] = ()
    candidate_asset_refs: tuple[str, ...] = ()
    external_writes: tuple[ExternalWriteScope, ...] = ()
    source_preview_run_id: str | None = Field(
        default=None,
        pattern=_SAFE_ID_PATTERN.pattern,
    )

    @field_validator("allowed_origins")
    @classmethod
    def validate_allowed_origins(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(_normalize_origin(value) for value in values)
        return _unique(normalized, "allowed_origins")

    @field_validator("step_ids", "element_ids")
    @classmethod
    def validate_item_ids(cls, values: tuple[str, ...], info: Any) -> tuple[str, ...]:
        invalid = [value for value in values if not _ITEM_ID_PATTERN.fullmatch(value)]
        if invalid:
            raise ValueError(f"{info.field_name} contains invalid IDs: {invalid!r}")
        return _unique(values, info.field_name)

    @field_validator("browser_actions")
    @classmethod
    def validate_browser_actions(
        cls,
        values: tuple[BrowserAction, ...],
    ) -> tuple[BrowserAction, ...]:
        return _unique(values, "browser_actions")

    @field_validator("candidate_asset_refs")
    @classmethod
    def validate_candidate_refs(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        invalid = [value for value in values if not _CANDIDATE_REF_PATTERN.fullmatch(value)]
        if invalid:
            raise ValueError(f"candidate_asset_refs contains invalid refs: {invalid!r}")
        return _unique(values, "candidate_asset_refs")

    @field_validator("external_writes")
    @classmethod
    def validate_external_writes(
        cls,
        values: tuple[ExternalWriteScope, ...],
    ) -> tuple[ExternalWriteScope, ...]:
        identifiers = [value.write_id for value in values]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("external_writes must have unique write_id values")
        return tuple(values)

    @model_validator(mode="after")
    def validate_operation_scope(self) -> "AuthorizationScope":
        resume_fields = (
            self.resume_checkpoint_digest,
            self.resume_step_id,
        )
        if self.operation is AuthorizationOperation.RESUME:
            if any(value is None for value in resume_fields):
                raise ValueError(
                    "resume authorization requires resume_checkpoint_digest and "
                    "resume_step_id"
                )
            if self.resume_step_id not in self.step_ids:
                raise ValueError("resume_step_id must appear in step_ids")
        elif any(value is not None for value in resume_fields):
            raise ValueError(
                "resume_checkpoint_digest and resume_step_id are only valid for "
                "resume authorization"
            )
        if self.operation in {
            AuthorizationOperation.LOGIN,
            AuthorizationOperation.VERIFY_CANDIDATES,
            AuthorizationOperation.VERIFY_ELEMENTS,
        } and self.mode is not RunMode.PREVIEW:
            raise ValueError(f"{self.operation.value} authorization must use preview mode")
        if self.operation is AuthorizationOperation.VERIFY_CANDIDATES:
            if not self.candidate_asset_refs:
                raise ValueError(
                    "verify_candidates authorization requires candidate_asset_refs"
                )
        elif self.candidate_asset_refs:
            raise ValueError(
                "candidate_asset_refs are only valid for verify_candidates authorization"
            )
        if self.mode is not RunMode.LIVE:
            if self.external_writes:
                raise ValueError("external_writes are only valid for live authorization")
            if self.source_preview_run_id is not None:
                raise ValueError(
                    "source_preview_run_id is only valid for live authorization"
                )
        elif self.external_writes and self.source_preview_run_id is None:
            raise ValueError(
                "live external_writes require source_preview_run_id"
            )
        invalid_write_steps = sorted(
            {
                write.step_id
                for write in self.external_writes
                if write.step_id not in self.step_ids
            }
        )
        if invalid_write_steps:
            raise ValueError(
                "external_writes reference steps outside step_ids: "
                f"{invalid_write_steps!r}"
            )
        missing_candidate_elements = sorted(
            ref.removeprefix("element:")
            for ref in self.candidate_asset_refs
            if ref.startswith("element:")
            and ref.removeprefix("element:") not in self.element_ids
        )
        if missing_candidate_elements:
            raise ValueError(
                "candidate element refs must also appear in element_ids: "
                f"{missing_candidate_elements!r}"
            )
        return self


class AuthorizationClaim(_FrozenModel):
    claim_id: str = Field(pattern=_SAFE_ID_PATTERN.pattern)
    claimed_at: datetime
    process_id: int = Field(ge=1)

    @field_validator("claimed_at")
    @classmethod
    def validate_claimed_at(cls, value: datetime) -> datetime:
        return _require_aware(value, "claimed_at")


class AuthorizationOutcome(_FrozenModel):
    status: Literal["succeeded", "failed", "unknown"]
    completed_at: datetime
    error_code: str | None = Field(default=None, pattern=_ERROR_CODE_PATTERN.pattern)
    evidence_refs: tuple[str, ...] = ()

    @field_validator("completed_at")
    @classmethod
    def validate_completed_at(cls, value: datetime) -> datetime:
        return _require_aware(value, "completed_at")

    @field_validator("evidence_refs")
    @classmethod
    def validate_evidence_refs(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not value for value in values):
            raise ValueError("evidence_refs must not contain empty values")
        return _unique(values, "evidence_refs")

    @model_validator(mode="after")
    def validate_error(self) -> "AuthorizationOutcome":
        if self.status == AuthorizationStatus.SUCCEEDED.value and self.error_code is not None:
            raise ValueError("a succeeded outcome must not include error_code")
        return self


class ExternalWriteClaim(_FrozenModel):
    write_id: str = Field(pattern=_SAFE_ID_PATTERN.pattern)
    status: ExternalWriteStatus = ExternalWriteStatus.CLAIMED
    claimed_at: datetime
    completed_at: datetime | None = None
    error_code: str | None = Field(default=None, pattern=_ERROR_CODE_PATTERN.pattern)

    @field_validator("claimed_at")
    @classmethod
    def validate_write_claimed_at(cls, value: datetime) -> datetime:
        return _require_aware(value, "claimed_at")

    @field_validator("completed_at")
    @classmethod
    def validate_write_completed_at(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _require_aware(value, "completed_at")

    @model_validator(mode="after")
    def validate_status_fields(self) -> "ExternalWriteClaim":
        if self.status is ExternalWriteStatus.CLAIMED:
            if self.completed_at is not None or self.error_code is not None:
                raise ValueError("a claimed external write must not be completed")
        elif self.completed_at is None:
            raise ValueError("a terminal external write requires completed_at")
        if self.status is ExternalWriteStatus.SUCCEEDED and self.error_code is not None:
            raise ValueError("a succeeded external write must not include error_code")
        return self


class AuthorizationRecord(_FrozenModel):
    schema_version: Literal[1] = 1
    authorization_id: str = Field(pattern=_SAFE_ID_PATTERN.pattern)
    status: AuthorizationStatus
    scope: AuthorizationScope
    scope_digest: str = Field(pattern=HASH_PATTERN)
    requested_by: str = Field(min_length=1)
    requested_at: datetime
    authorized_by: str | None = Field(default=None, min_length=1)
    approval_reference: str | None = Field(default=None, min_length=1)
    granted_at: datetime | None = None
    expires_at: datetime | None = None
    claim: AuthorizationClaim | None = None
    outcome: AuthorizationOutcome | None = None
    write_claims: tuple[ExternalWriteClaim, ...] = ()
    revoked_by: str | None = Field(default=None, min_length=1)
    revoked_at: datetime | None = None
    revocation_reason: str | None = Field(default=None, min_length=1)

    @field_validator("requested_at")
    @classmethod
    def validate_requested_at(cls, value: datetime) -> datetime:
        return _require_aware(value, "requested_at")

    @field_validator("granted_at", "expires_at", "revoked_at")
    @classmethod
    def validate_optional_times(
        cls,
        value: datetime | None,
        info: Any,
    ) -> datetime | None:
        return None if value is None else _require_aware(value, info.field_name)

    @model_validator(mode="after")
    def validate_lifecycle(self) -> "AuthorizationRecord":
        if self.scope_digest != authorization_scope_digest(self.scope):
            raise ValueError("scope_digest does not match scope")
        grant_fields = (
            self.authorized_by,
            self.approval_reference,
            self.granted_at,
            self.expires_at,
        )
        has_all_grant_fields = all(value is not None for value in grant_fields)
        if self.status is AuthorizationStatus.REQUESTED:
            if any(value is not None for value in grant_fields):
                raise ValueError("a requested record must not contain grant metadata")
            if self.claim is not None or self.outcome is not None or self.write_claims:
                raise ValueError("a requested record must not contain execution state")
        elif self.status is AuthorizationStatus.REVOKED:
            if not self.revoked_by or self.revoked_at is None or not self.revocation_reason:
                raise ValueError("a revoked record requires complete revocation metadata")
            if any(value is not None for value in grant_fields) and not has_all_grant_fields:
                raise ValueError(
                    "a revoked record must contain either all or no grant metadata"
                )
            if self.claim is not None or self.outcome is not None or self.write_claims:
                raise ValueError("a revoked record must not contain execution state")
        else:
            if not has_all_grant_fields:
                raise ValueError("a granted or consumed record requires grant metadata")
            assert self.granted_at is not None and self.expires_at is not None
            if self.expires_at <= self.granted_at:
                raise ValueError("expires_at must be later than granted_at")
            if self.status is AuthorizationStatus.GRANTED:
                if self.claim is not None or self.outcome is not None or self.write_claims:
                    raise ValueError("a granted record must not contain execution state")
            else:
                if self.claim is None:
                    raise ValueError("a consumed record requires a claim")
                if self.status is AuthorizationStatus.CLAIMED:
                    if self.outcome is not None:
                        raise ValueError("a claimed record must not contain an outcome")
                else:
                    if self.outcome is None or self.outcome.status != self.status.value:
                        raise ValueError("terminal record status must match its outcome")
        if self.status is not AuthorizationStatus.REVOKED and any(
            value is not None
            for value in (self.revoked_by, self.revoked_at, self.revocation_reason)
        ):
            raise ValueError("revocation metadata is only valid for a revoked record")
        write_ids = [claim.write_id for claim in self.write_claims]
        if len(set(write_ids)) != len(write_ids):
            raise ValueError("write_claims must have unique write_id values")
        allowed_write_ids = {write.write_id for write in self.scope.external_writes}
        unknown = sorted(set(write_ids) - allowed_write_ids)
        if unknown:
            raise ValueError(f"write_claims contain unknown write IDs: {unknown!r}")
        if self.granted_at is not None and self.granted_at < self.requested_at:
            raise ValueError("granted_at must not precede requested_at")
        if (
            self.granted_at is not None
            and self.expires_at is not None
            and self.expires_at <= self.granted_at
        ):
            raise ValueError("expires_at must be later than granted_at")
        if self.revoked_at is not None:
            earliest_revocation = self.granted_at or self.requested_at
            if self.revoked_at < earliest_revocation:
                raise ValueError("revoked_at must not precede the current lifecycle state")
        if self.claim is not None:
            assert self.granted_at is not None and self.expires_at is not None
            if self.claim.claimed_at < self.granted_at:
                raise ValueError("claimed_at must not precede granted_at")
            if self.claim.claimed_at >= self.expires_at:
                raise ValueError("claimed_at must precede expires_at")
            for write_claim in self.write_claims:
                if write_claim.claimed_at < self.claim.claimed_at:
                    raise ValueError(
                        "external write claimed_at must not precede invocation claimed_at"
                    )
                if (
                    write_claim.completed_at is not None
                    and write_claim.completed_at < write_claim.claimed_at
                ):
                    raise ValueError(
                        "external write completed_at must not precede claimed_at"
                    )
        if self.outcome is not None:
            assert self.claim is not None
            if self.outcome.completed_at < self.claim.claimed_at:
                raise ValueError("completed_at must not precede claimed_at")
            if any(
                write_claim.completed_at is not None
                and write_claim.completed_at > self.outcome.completed_at
                for write_claim in self.write_claims
            ):
                raise ValueError(
                    "external write completion must not follow invocation completion"
                )
            if any(
                write_claim.status is ExternalWriteStatus.CLAIMED
                for write_claim in self.write_claims
            ):
                raise ValueError(
                    "a terminal authorization cannot contain an unfinished write claim"
                )
            if self.status is AuthorizationStatus.SUCCEEDED and any(
                write_claim.status is not ExternalWriteStatus.SUCCEEDED
                for write_claim in self.write_claims
            ):
                raise ValueError(
                    "a succeeded authorization cannot contain an unsuccessful write"
                )
        return self


def authorization_scope_digest(scope: AuthorizationScope | Mapping[str, Any]) -> str:
    normalized = (
        scope
        if isinstance(scope, AuthorizationScope)
        else AuthorizationScope.model_validate(scope)
    )
    return _digest(normalized.model_dump(mode="json"))


def external_write_payload_digest(payload: object) -> str:
    """Return the canonical SHA-256 bound into an external write scope."""

    return _digest(payload)


def catalog_lock_digest(lock: CatalogLock | Mapping[str, Any]) -> str:
    """Hash semantic Catalog Lock content while ignoring copy timestamps."""

    normalized = lock if isinstance(lock, CatalogLock) else CatalogLock.model_validate(lock)
    document = normalized.model_dump(mode="json")
    items: list[dict[str, Any]] = []
    for raw_item in document["items"]:
        item = dict(raw_item)
        item.pop("copied_at", None)
        item["dependencies"] = sorted(
            item.get("dependencies", []),
            key=lambda dependency: (dependency["kind"], dependency["id"]),
        )
        items.append(item)
    document["items"] = sorted(items, key=lambda item: (item["kind"], item["id"]))
    return _digest(document)


class AuthorizationError(PermissionError):
    error_code = "authorization_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)


class AuthorizationRecordNotFoundError(AuthorizationError):
    error_code = "authorization_record_not_found"


class AuthorizationRecordInvalidError(AuthorizationError):
    error_code = "authorization_record_invalid"


class AuthorizationScopeMismatchError(AuthorizationError):
    error_code = "authorization_scope_mismatch"


class AuthorizationNotGrantedError(AuthorizationError):
    error_code = "authorization_not_granted"


class AuthorizationExpiredError(AuthorizationError):
    error_code = "authorization_expired"


class AuthorizationRevokedError(AuthorizationError):
    error_code = "authorization_revoked"


class AuthorizationAlreadyClaimedError(AuthorizationError):
    error_code = "authorization_already_claimed"


class AuthorizationStoreUnsafeError(AuthorizationError):
    error_code = "authorization_store_unsafe"


class BrowserActionNotAuthorizedError(AuthorizationError):
    error_code = "browser_action_not_authorized"


class BrowserOriginNotAuthorizedError(AuthorizationError):
    error_code = "browser_origin_not_authorized"


class BrowserStepNotAuthorizedError(AuthorizationError):
    error_code = "browser_step_not_authorized"


class BrowserElementNotAuthorizedError(AuthorizationError):
    error_code = "browser_element_not_authorized"


class ExternalWriteScopeMismatchError(AuthorizationError):
    error_code = "external_write_scope_mismatch"


class ExternalWriteAlreadyClaimedError(AuthorizationError):
    error_code = "external_write_already_claimed"


class _AuthorizationRecordLock:
    """Serialize one record transition with the runtime's POSIX flock wrapper."""

    def __init__(self, path: Path, *, timeout_seconds: float = 30.0) -> None:
        self._lock = RunDirectoryLock(path)
        self._timeout_seconds = timeout_seconds

    def __enter__(self) -> "_AuthorizationRecordLock":
        deadline = monotonic() + self._timeout_seconds
        while True:
            try:
                self._lock.acquire()
                return self
            except RunAlreadyActiveError as error:
                if monotonic() >= deadline:
                    raise AuthorizationStoreUnsafeError(
                        "timed out waiting for the authorization record lock"
                    ) from error
                sleep(0.01)
            except RunLockError as error:
                raise AuthorizationStoreUnsafeError(
                    "cannot safely lock the authorization record"
                ) from error

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self._lock.release()


class AuthorizationStore:
    """Persist and atomically transition application-local authorization records."""

    def __init__(
        self,
        root: str | Path,
        *,
        boundary: str | Path | None = None,
    ) -> None:
        self.root = Path(os.path.abspath(os.fspath(root)))
        self.boundary = (
            None
            if boundary is None
            else Path(os.path.abspath(os.fspath(boundary)))
        )
        self._ensure_within_boundary()

    def create_request(
        self,
        scope: AuthorizationScope | Mapping[str, Any],
        *,
        requested_by: str = "developer",
        authorization_id: str | None = None,
        now: datetime | None = None,
    ) -> AuthorizationRecord:
        normalized_scope = self._copy_scope(scope)
        identifier = authorization_id or f"auth-{uuid4().hex}"
        self._record_path(identifier)
        if not requested_by.strip():
            raise ValueError("requested_by must not be empty")
        with self._record_lock(identifier):
            path = self._record_path(identifier)
            if self._path_entry_exists(path):
                raise AuthorizationRecordInvalidError(
                    f"authorization record already exists: {identifier}"
                )
            record = AuthorizationRecord(
                authorization_id=identifier,
                status=AuthorizationStatus.REQUESTED,
                scope=normalized_scope,
                scope_digest=authorization_scope_digest(normalized_scope),
                requested_by=requested_by,
                requested_at=_resolve_now(now),
            )
            self._write_record(path, record)
        return record

    def grant(
        self,
        authorization_id: str,
        *,
        scope_digest: str,
        authorized_by: str,
        approval_reference: str,
        expires_at: datetime,
        now: datetime | None = None,
    ) -> AuthorizationRecord:
        expiry = _require_aware(expires_at, "expires_at")
        if not authorized_by.strip() or not approval_reference.strip():
            raise ValueError("authorized_by and approval_reference must not be empty")
        with self._record_lock(authorization_id):
            checked_at = _resolve_now(now)
            if expiry <= checked_at:
                raise ValueError("expires_at must be later than the grant time")
            record = self._load_unlocked(authorization_id)
            if record.status is AuthorizationStatus.REVOKED:
                raise AuthorizationRevokedError("authorization record has been revoked")
            if record.status is not AuthorizationStatus.REQUESTED:
                if record.status in {
                    AuthorizationStatus.CLAIMED,
                    AuthorizationStatus.SUCCEEDED,
                    AuthorizationStatus.FAILED,
                    AuthorizationStatus.UNKNOWN,
                }:
                    raise AuthorizationAlreadyClaimedError(
                        "authorization record has already been claimed"
                    )
                raise AuthorizationNotGrantedError(
                    f"authorization record cannot be granted from {record.status.value}"
                )
            if scope_digest != record.scope_digest:
                raise AuthorizationScopeMismatchError(
                    "acknowledged scope digest does not match the requested scope"
                )
            updated = record.model_copy(
                update={
                    "status": AuthorizationStatus.GRANTED,
                    "authorized_by": authorized_by,
                    "approval_reference": approval_reference,
                    "granted_at": checked_at,
                    "expires_at": expiry,
                }
            )
            updated = AuthorizationRecord.model_validate(updated.model_dump(mode="python"))
            self._write_record(self._record_path(authorization_id), updated)
            return updated

    def load(self, authorization_id: str) -> AuthorizationRecord:
        self._ensure_store()
        return self._load_unlocked(authorization_id)

    def claim(
        self,
        authorization_id: str,
        actual_scope: AuthorizationScope | Mapping[str, Any],
        *,
        now: datetime | None = None,
    ) -> "AuthorizationSession":
        normalized_scope = self._copy_scope(actual_scope)
        with self._record_lock(authorization_id):
            checked_at = _resolve_now(now)
            record = self._load_unlocked(authorization_id)
            self._require_claimable(record, checked_at)
            actual_digest = authorization_scope_digest(normalized_scope)
            if actual_digest != record.scope_digest or not self._same_scope(
                normalized_scope,
                record.scope,
            ):
                raise AuthorizationScopeMismatchError(
                    "actual execution scope does not match the granted scope"
                )
            claim = AuthorizationClaim(
                claim_id=f"claim-{uuid4().hex}",
                claimed_at=checked_at,
                process_id=os.getpid(),
            )
            updated = record.model_copy(
                update={"status": AuthorizationStatus.CLAIMED, "claim": claim}
            )
            updated = AuthorizationRecord.model_validate(updated.model_dump(mode="python"))
            self._write_record(self._record_path(authorization_id), updated)
        return AuthorizationSession(
            authorization_id=authorization_id,
            scope=self._copy_scope(updated.scope),
            scope_digest=updated.scope_digest,
            claim_id=claim.claim_id,
            expires_at=updated.expires_at,
            _store=self,
        )

    def revoke(
        self,
        authorization_id: str,
        *,
        revoked_by: str,
        reason: str,
        now: datetime | None = None,
    ) -> AuthorizationRecord:
        if not revoked_by.strip() or not reason.strip():
            raise ValueError("revoked_by and reason must not be empty")
        with self._record_lock(authorization_id):
            checked_at = _resolve_now(now)
            record = self._load_unlocked(authorization_id)
            if record.status not in {
                AuthorizationStatus.REQUESTED,
                AuthorizationStatus.GRANTED,
            }:
                raise AuthorizationAlreadyClaimedError(
                    "a claimed authorization record cannot be revoked"
                )
            updated = record.model_copy(
                update={
                    "status": AuthorizationStatus.REVOKED,
                    "revoked_by": revoked_by,
                    "revoked_at": checked_at,
                    "revocation_reason": reason,
                }
            )
            updated = AuthorizationRecord.model_validate(updated.model_dump(mode="python"))
            self._write_record(self._record_path(authorization_id), updated)
            return updated

    def _finish(
        self,
        session: "AuthorizationSession",
        *,
        status: AuthorizationStatus,
        error_code: str | None,
        evidence_refs: Sequence[str],
        now: datetime | None,
    ) -> AuthorizationRecord:
        if status not in {
            AuthorizationStatus.SUCCEEDED,
            AuthorizationStatus.FAILED,
            AuthorizationStatus.UNKNOWN,
        }:
            raise ValueError("authorization outcome must be succeeded, failed, or unknown")
        with self._record_lock(session.authorization_id):
            checked_at = _resolve_now(now)
            outcome = AuthorizationOutcome(
                status=status.value,
                completed_at=checked_at,
                error_code=error_code,
                evidence_refs=tuple(evidence_refs),
            )
            record = self._load_unlocked(session.authorization_id)
            self._require_session_claim(record, session)
            if record.status is not AuthorizationStatus.CLAIMED:
                raise AuthorizationAlreadyClaimedError(
                    "authorization record already has a terminal outcome"
                )
            updated = record.model_copy(update={"status": status, "outcome": outcome})
            updated = AuthorizationRecord.model_validate(updated.model_dump(mode="python"))
            self._write_record(self._record_path(session.authorization_id), updated)
            return updated

    def _claim_write(
        self,
        session: "AuthorizationSession",
        actual_scope: ExternalWriteScope | Mapping[str, Any],
        *,
        now: datetime | None,
    ) -> ExternalWriteClaim:
        normalized = (
            actual_scope
            if isinstance(actual_scope, ExternalWriteScope)
            else ExternalWriteScope.model_validate(actual_scope)
        )
        with self._record_lock(session.authorization_id):
            checked_at = _resolve_now(now)
            record = self._load_unlocked(session.authorization_id)
            self._require_session_claim(record, session)
            if record.status is not AuthorizationStatus.CLAIMED:
                raise AuthorizationAlreadyClaimedError(
                    "authorization record already has a terminal outcome"
                )
            if record.expires_at is None or checked_at >= record.expires_at:
                raise AuthorizationExpiredError("authorization session has expired")
            expected = next(
                (
                    scope
                    for scope in record.scope.external_writes
                    if scope.write_id == normalized.write_id
                ),
                None,
            )
            if expected is None or _canonical_json(
                expected.model_dump(mode="json")
            ) != _canonical_json(normalized.model_dump(mode="json")):
                raise ExternalWriteScopeMismatchError(
                    "external write does not match an authorized write scope"
                )
            if any(claim.write_id == normalized.write_id for claim in record.write_claims):
                raise ExternalWriteAlreadyClaimedError(
                    "external write authorization has already been claimed"
                )
            claim = ExternalWriteClaim(
                write_id=normalized.write_id,
                claimed_at=checked_at,
            )
            updated = record.model_copy(
                update={"write_claims": (*record.write_claims, claim)}
            )
            updated = AuthorizationRecord.model_validate(updated.model_dump(mode="python"))
            self._write_record(self._record_path(session.authorization_id), updated)
            return claim

    def _finish_write(
        self,
        session: "AuthorizationSession",
        write_id: str,
        *,
        status: ExternalWriteStatus,
        error_code: str | None,
        now: datetime | None,
    ) -> ExternalWriteClaim:
        if status not in {
            ExternalWriteStatus.SUCCEEDED,
            ExternalWriteStatus.FAILED,
            ExternalWriteStatus.UNKNOWN,
        }:
            raise ValueError("external write outcome must be succeeded, failed, or unknown")
        with self._record_lock(session.authorization_id):
            checked_at = _resolve_now(now)
            record = self._load_unlocked(session.authorization_id)
            self._require_session_claim(record, session)
            if record.status is not AuthorizationStatus.CLAIMED:
                raise AuthorizationAlreadyClaimedError(
                    "authorization record already has a terminal outcome"
                )
            claims = list(record.write_claims)
            for index, claim in enumerate(claims):
                if claim.write_id != write_id:
                    continue
                if claim.status is not ExternalWriteStatus.CLAIMED:
                    raise ExternalWriteAlreadyClaimedError(
                        "external write already has a terminal outcome"
                    )
                completed = claim.model_copy(
                    update={
                        "status": status,
                        "completed_at": checked_at,
                        "error_code": error_code,
                    }
                )
                completed = ExternalWriteClaim.model_validate(
                    completed.model_dump(mode="python")
                )
                claims[index] = completed
                updated = record.model_copy(update={"write_claims": tuple(claims)})
                updated = AuthorizationRecord.model_validate(
                    updated.model_dump(mode="python")
                )
                self._write_record(self._record_path(session.authorization_id), updated)
                return completed
        raise ExternalWriteScopeMismatchError(
            f"external write has not been claimed: {write_id}"
        )

    def _require_claimable(self, record: AuthorizationRecord, now: datetime) -> None:
        if record.status is AuthorizationStatus.REVOKED:
            raise AuthorizationRevokedError("authorization record has been revoked")
        if record.status is AuthorizationStatus.REQUESTED:
            raise AuthorizationNotGrantedError("authorization record has not been granted")
        if record.status is not AuthorizationStatus.GRANTED:
            raise AuthorizationAlreadyClaimedError(
                "authorization record has already been claimed"
            )
        if record.expires_at is None or now >= record.expires_at:
            raise AuthorizationExpiredError("authorization record has expired")

    def _assert_active_session(
        self,
        session: "AuthorizationSession",
        *,
        now: datetime | None,
    ) -> None:
        with self._record_lock(session.authorization_id):
            checked_at = _resolve_now(now)
            record = self._load_unlocked(session.authorization_id)
            self._require_session_claim(record, session)
            if record.status is not AuthorizationStatus.CLAIMED:
                raise AuthorizationAlreadyClaimedError(
                    "authorization record already has a terminal outcome"
                )
            if record.expires_at is None or checked_at >= record.expires_at:
                raise AuthorizationExpiredError("authorization session has expired")

    @staticmethod
    def _require_session_claim(
        record: AuthorizationRecord,
        session: "AuthorizationSession",
    ) -> None:
        if record.claim is None or record.claim.claim_id != session.claim_id:
            raise AuthorizationScopeMismatchError(
                "authorization session does not own the persisted claim"
            )
        if (
            record.scope_digest != session.scope_digest
            or not AuthorizationStore._same_scope(record.scope, session.scope)
        ):
            raise AuthorizationScopeMismatchError(
                "authorization session scope does not match the persisted claim"
            )
        if record.status not in {
            AuthorizationStatus.CLAIMED,
            AuthorizationStatus.SUCCEEDED,
            AuthorizationStatus.FAILED,
            AuthorizationStatus.UNKNOWN,
        }:
            raise AuthorizationNotGrantedError(
                "authorization record is not associated with an active claim"
            )

    @staticmethod
    def _same_scope(left: AuthorizationScope, right: AuthorizationScope) -> bool:
        return _canonical_json(left.model_dump(mode="json")) == _canonical_json(
            right.model_dump(mode="json")
        )

    @staticmethod
    def _copy_scope(
        value: AuthorizationScope | Mapping[str, Any],
    ) -> AuthorizationScope:
        if isinstance(value, AuthorizationScope):
            value = value.model_dump(mode="json")
        return AuthorizationScope.model_validate(value)

    def _record_path(self, authorization_id: str) -> Path:
        if not _SAFE_ID_PATTERN.fullmatch(authorization_id):
            raise AuthorizationRecordInvalidError("invalid authorization_id")
        return self.root / f"{authorization_id}.json"

    def _lock_path(self, authorization_id: str) -> Path:
        self._record_path(authorization_id)
        return self.root / ".locks" / f"{authorization_id}.lock"

    def _record_lock(self, authorization_id: str) -> _AuthorizationRecordLock:
        self._ensure_store()
        return _AuthorizationRecordLock(self._lock_path(authorization_id))

    def _ensure_store(self) -> None:
        try:
            self._ensure_within_boundary()
            self._ensure_boundary_components()
            if self.root.is_symlink():
                raise AuthorizationStoreUnsafeError(
                    "authorization store must not be a symbolic link"
                )
            self.root.mkdir(parents=True, exist_ok=True)
            self._ensure_boundary_components()
            locks = self.root / ".locks"
            if self.root.is_symlink() or locks.is_symlink():
                raise AuthorizationStoreUnsafeError(
                    "authorization store paths must not be symbolic links"
                )
            locks.mkdir(exist_ok=True)
            if self.root.is_symlink() or locks.is_symlink():
                raise AuthorizationStoreUnsafeError(
                    "authorization store paths changed while creating them"
                )
            for path in (self.root, locks):
                metadata = path.stat()
                if not stat.S_ISDIR(metadata.st_mode):
                    raise AuthorizationStoreUnsafeError(
                        "authorization store path must be a directory"
                    )
        except AuthorizationError:
            raise
        except OSError as error:
            raise AuthorizationStoreUnsafeError(
                "cannot safely create authorization store"
            ) from error

    def _ensure_within_boundary(self) -> None:
        if self.boundary is None:
            return
        try:
            self.root.relative_to(self.boundary)
        except ValueError as error:
            raise AuthorizationStoreUnsafeError(
                "authorization store root must remain inside its trusted boundary"
            ) from error

    def _ensure_boundary_components(self) -> None:
        if self.boundary is None:
            return
        relative = self.root.relative_to(self.boundary)
        candidates = [self.boundary]
        current = self.boundary
        for part in relative.parts:
            current = current / part
            candidates.append(current)
        for candidate in candidates:
            try:
                metadata = os.lstat(candidate)
            except FileNotFoundError:
                continue
            if stat.S_ISLNK(metadata.st_mode):
                raise AuthorizationStoreUnsafeError(
                    "authorization store boundary path must not contain symbolic links"
                )
            if not stat.S_ISDIR(metadata.st_mode):
                raise AuthorizationStoreUnsafeError(
                    "authorization store boundary path components must be directories"
                )

    @staticmethod
    def _path_entry_exists(path: Path) -> bool:
        try:
            os.lstat(path)
        except FileNotFoundError:
            return False
        return True

    def _load_unlocked(self, authorization_id: str) -> AuthorizationRecord:
        path = self._record_path(authorization_id)
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        descriptor: int | None = None
        try:
            descriptor = os.open(path, flags)
        except FileNotFoundError as error:
            raise AuthorizationRecordNotFoundError(
                f"authorization record not found: {authorization_id}"
            ) from error
        except OSError as error:
            raise AuthorizationStoreUnsafeError(
                "cannot safely open authorization record"
            ) from error
        try:
            opened = os.fstat(descriptor)
            if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1:
                raise AuthorizationStoreUnsafeError(
                    "authorization record must be one regular file"
                )
            linked = os.lstat(path)
            if stat.S_ISLNK(linked.st_mode) or (
                opened.st_dev,
                opened.st_ino,
            ) != (linked.st_dev, linked.st_ino):
                raise AuthorizationStoreUnsafeError(
                    "authorization record path changed while opening"
                )
            with os.fdopen(descriptor, "r", encoding="utf-8") as stream:
                descriptor = None
                payload = json.load(stream, object_pairs_hook=_object_without_duplicate_keys)
            return AuthorizationRecord.model_validate(payload)
        except AuthorizationError:
            raise
        except Exception as error:
            raise AuthorizationRecordInvalidError(
                f"invalid authorization record: {authorization_id}"
            ) from error
        finally:
            if descriptor is not None:
                os.close(descriptor)

    def _write_record(self, path: Path, record: AuthorizationRecord) -> None:
        self._ensure_safe_existing_record(path)
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        flags = (
            os.O_CREAT
            | os.O_EXCL
            | os.O_WRONLY
            | getattr(os, "O_NOFOLLOW", 0)
        )
        descriptor: int | None = None
        try:
            descriptor = os.open(temporary, flags, 0o600)
            payload = (
                json.dumps(
                    record.model_dump(mode="json"),
                    ensure_ascii=False,
                    allow_nan=False,
                    indent=2,
                    sort_keys=True,
                )
                + "\n"
            ).encode("utf-8")
            written = 0
            while written < len(payload):
                count = os.write(descriptor, payload[written:])
                if count <= 0:  # pragma: no cover - defensive OS contract guard
                    raise OSError("authorization record write made no progress")
                written += count
            os.fsync(descriptor)
            os.close(descriptor)
            descriptor = None
            os.replace(temporary, path)
            directory = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        except AuthorizationError:
            raise
        except OSError as error:
            raise AuthorizationStoreUnsafeError(
                "cannot atomically persist authorization record"
            ) from error
        finally:
            if descriptor is not None:
                os.close(descriptor)
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass

    @staticmethod
    def _ensure_safe_existing_record(path: Path) -> None:
        try:
            linked = os.lstat(path)
        except FileNotFoundError:
            return
        if not stat.S_ISREG(linked.st_mode) or linked.st_nlink != 1:
            raise AuthorizationStoreUnsafeError(
                "authorization record target must be one regular file"
            )


@dataclass(frozen=True, slots=True)
class AuthorizationSession:
    authorization_id: str
    scope: AuthorizationScope
    scope_digest: str
    claim_id: str
    expires_at: datetime | None
    _store: AuthorizationStore = field(repr=False, compare=False)

    def assert_active(self, *, now: datetime | None = None) -> None:
        if now is not None:
            _require_aware(now, "now")
        self._store._assert_active_session(self, now=now)

    def authorize_browser_origin(
        self,
        url: str,
        *,
        now: datetime | None = None,
    ) -> None:
        self.assert_active(now=now)
        if _origin_from_url(url) not in self.scope.allowed_origins:
            raise BrowserOriginNotAuthorizedError("browser origin is not authorized")

    def authorize_browser_action(
        self,
        action: BrowserAction | str,
        *,
        step_id: str | None = None,
        element_id: str | None = None,
        url: str | None = None,
        now: datetime | None = None,
    ) -> None:
        self.assert_active(now=now)
        try:
            normalized_action = BrowserAction(action)
        except ValueError as error:
            raise BrowserActionNotAuthorizedError(
                f"unknown browser action: {action!r}"
            ) from error
        if normalized_action not in self.scope.browser_actions:
            raise BrowserActionNotAuthorizedError(
                f"browser action is not authorized: {normalized_action.value}"
            )
        if step_id is None or step_id not in self.scope.step_ids:
            raise BrowserStepNotAuthorizedError(
                "browser action requires an authorized step"
            )
        if normalized_action in _ELEMENT_ACTIONS and element_id is None:
            raise BrowserElementNotAuthorizedError(
                "browser action requires an authorized element"
            )
        if element_id is not None and element_id not in self.scope.element_ids:
            raise BrowserElementNotAuthorizedError(
                f"browser element is not authorized: {element_id}"
            )
        if normalized_action is BrowserAction.OPEN and url is None:
            raise BrowserOriginNotAuthorizedError(
                "browser open requires an authorized URL"
            )
        if url is not None and _origin_from_url(url) not in self.scope.allowed_origins:
            raise BrowserOriginNotAuthorizedError("browser origin is not authorized")

    def claim_write(
        self,
        scope: ExternalWriteScope | Mapping[str, Any],
        *,
        now: datetime | None = None,
    ) -> ExternalWriteClaim:
        return self._store._claim_write(self, scope, now=now)

    def finish_write(
        self,
        write_id: str,
        *,
        status: ExternalWriteStatus,
        error_code: str | None = None,
        now: datetime | None = None,
    ) -> ExternalWriteClaim:
        return self._store._finish_write(
            self,
            write_id,
            status=status,
            error_code=error_code,
            now=now,
        )

    def finish(
        self,
        *,
        status: AuthorizationStatus,
        error_code: str | None = None,
        evidence_refs: Sequence[str] = (),
        now: datetime | None = None,
    ) -> AuthorizationRecord:
        return self._store._finish(
            self,
            status=status,
            error_code=error_code,
            evidence_refs=evidence_refs,
            now=now,
        )


class AuthorizedBrowserActions:
    """Enforce a claimed Authorization Session at every browser API boundary."""

    def __init__(
        self,
        delegate: BrowserActions,
        session: AuthorizationSession,
        *,
        step_id_getter: Callable[[], str | None] | None = None,
    ) -> None:
        self._delegate = delegate
        self._session = session
        self._step_id_getter = step_id_getter

    @property
    def current_url(self) -> str | None:
        value = getattr(self._delegate, "current_url", None)
        return value() if callable(value) else value

    def open(self, url: str, *, wait: str = "document") -> None:
        self._authorize(BrowserAction.OPEN, url=url, check_current_origin=False)
        self._call_browser(lambda: self._delegate.open(url, wait=wait))

    def exists(self, element: ElementSpec, *, timeout: float = 0.0) -> bool:
        self._authorize(BrowserAction.EXISTS, element=element)
        return self._call_browser(
            lambda: self._delegate.exists(element, timeout=timeout)
        )

    def count(self, element: ElementSpec, *, timeout: float = 0.0) -> int:
        self._authorize(BrowserAction.EXISTS, element=element)
        return self._call_browser(
            lambda: self._delegate.count(element, timeout=timeout)
        )

    def click(self, element: ElementSpec) -> None:
        self._authorize(BrowserAction.CLICK, element=element)
        self._call_browser(lambda: self._delegate.click(element))

    def click_and_switch_to_new_tab(
        self,
        element: ElementSpec,
        *,
        timeout: float | None = None,
    ) -> None:
        self._authorize(BrowserAction.CLICK, element=element)
        self._call_browser(
            lambda: self._delegate.click_and_switch_to_new_tab(
                element,
                timeout=timeout,
            )
        )

    def input(self, element: ElementSpec, value: SecretLike) -> None:
        self._authorize(BrowserAction.INPUT, element=element)
        self._call_browser(lambda: self._delegate.input(element, value))

    def text(self, element: ElementSpec) -> str:
        self._authorize(BrowserAction.TEXT, element=element)
        return self._call_browser(lambda: self._delegate.text(element))

    def texts(self, element: ElementSpec, *, timeout: float = 0.0) -> list[str]:
        self._authorize(BrowserAction.TEXT, element=element)
        return self._call_browser(
            lambda: self._delegate.texts(element, timeout=timeout)
        )

    def select(self, element: ElementSpec, value: SecretLike) -> None:
        self._authorize(BrowserAction.SELECT, element=element)
        self._call_browser(lambda: self._delegate.select(element, value))

    def download(
        self,
        element: ElementSpec,
        *,
        filename: str | None = None,
    ) -> DownloadRef:
        self._authorize(BrowserAction.DOWNLOAD, element=element)
        return self._call_browser(
            lambda: self._delegate.download(
                element,
                filename=filename,
            )
        )

    def screenshot(
        self,
        *,
        name: str | None = None,
        full_page: bool = False,
    ) -> ArtifactRef:
        self._authorize(BrowserAction.SCREENSHOT)
        return self._call_browser(
            lambda: self._delegate.screenshot(name=name, full_page=full_page)
        )

    def _authorize(
        self,
        action: BrowserAction,
        *,
        element: ElementSpec | None = None,
        url: str | None = None,
        check_current_origin: bool = True,
    ) -> None:
        if check_current_origin:
            self._assert_current_origin()
        step_id = self._step_id_getter() if self._step_id_getter is not None else None
        self._session.authorize_browser_action(
            action,
            step_id=step_id,
            element_id=element.id if element is not None else None,
            url=url,
        )

    def _call_browser(self, operation: Callable[[], Any]) -> Any:
        try:
            return operation()
        finally:
            self._assert_current_origin()

    def _assert_current_origin(self) -> None:
        current = self.current_url
        if not isinstance(current, str) or not current.strip():
            raise BrowserOriginNotAuthorizedError(
                "browser did not expose a current authorized origin"
            )
        self._session.authorize_browser_origin(current)


__all__ = [
    "AuthorizationAlreadyClaimedError",
    "AuthorizationClaim",
    "AuthorizationError",
    "AuthorizationExpiredError",
    "AuthorizationNotGrantedError",
    "AuthorizationOperation",
    "AuthorizationOutcome",
    "AuthorizationRecord",
    "AuthorizationRecordInvalidError",
    "AuthorizationRecordNotFoundError",
    "AuthorizationRevokedError",
    "AuthorizationScope",
    "AuthorizationScopeMismatchError",
    "AuthorizationSession",
    "AuthorizationStatus",
    "AuthorizationStore",
    "AuthorizationStoreUnsafeError",
    "AuthorizedBrowserActions",
    "BrowserAction",
    "BrowserActionNotAuthorizedError",
    "BrowserElementNotAuthorizedError",
    "BrowserOriginNotAuthorizedError",
    "BrowserStepNotAuthorizedError",
    "ExternalWriteAlreadyClaimedError",
    "ExternalWriteClaim",
    "ExternalWriteScope",
    "ExternalWriteScopeMismatchError",
    "ExternalWriteStatus",
    "authorization_scope_digest",
    "catalog_lock_digest",
    "external_write_payload_digest",
]
