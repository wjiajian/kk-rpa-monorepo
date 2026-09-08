"""Local, redacted application configuration models."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Mapping

import tomllib
from rpa_core.browser import SecretValue

_ACCOUNT_ID_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{2,63}$")
_ENV_NAME_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]+$")


class ConfigurationError(ValueError):
    """Stable local configuration error."""

    error_code = "application_configuration_invalid"


@dataclass(frozen=True, slots=True)
class StoreConfig:
    account_id: str
    platform: str
    login_url: str
    profile_directory: str
    debug_port: int
    brand_value: str
    username_env: str
    password_env: str
    identity_env: str | None = None
    download_directory: str | None = None

    def __post_init__(self) -> None:
        if not _ACCOUNT_ID_PATTERN.fullmatch(self.account_id):
            raise ConfigurationError(f"invalid account alias: {self.account_id!r}")
        if self.platform != "jushuitan":
            raise ConfigurationError("store platform must be 'jushuitan'")
        if not self.login_url.startswith("https://"):
            raise ConfigurationError("login_url must use HTTPS")
        profile = PurePosixPath(self.profile_directory.replace("\\", "/"))
        if (
            profile.is_absolute()
            or ".." in profile.parts
            or profile.parts[:1] != ("profiles",)
        ):
            raise ConfigurationError(
                "profile_directory must be a relative profiles/<alias> path"
            )
        if self.debug_port != 0 and not 1024 <= self.debug_port <= 65535:
            raise ConfigurationError("debug_port must be 0 or between 1024 and 65535")
        if not self.brand_value:
            raise ConfigurationError("brand_value must not be empty")
        for field_name in ("username_env", "password_env", "identity_env"):
            value = getattr(self, field_name)
            if value is not None and not _ENV_NAME_PATTERN.fullmatch(value):
                raise ConfigurationError(
                    f"invalid environment variable name: {field_name}"
                )

    @property
    def uses_placeholder_values(self) -> bool:
        return self.brand_value.startswith("<") or self.brand_value == "BRAND_001"


@dataclass(frozen=True, slots=True)
class LoginCredentials:
    username: SecretValue
    password: SecretValue
    expected_identity: SecretValue | None = None


def load_store_config(
    path: str | Path, account_id: str, overrides: Mapping[str, object] | None = None
) -> StoreConfig:
    source = Path(path)
    try:
        document = tomllib.loads(source.read_text(encoding="utf-8")) if source.exists() else {
            "schema_version": 1, "stores": {}
        }
        if document.get("schema_version") != 1:
            raise ConfigurationError("stores configuration schema_version must equal 1")
        stores = document.get("stores")
        if not isinstance(stores, Mapping):
            raise ConfigurationError("stores configuration must contain a stores table")
        raw = stores.get(account_id, {})
        if not isinstance(raw, Mapping):
            raise ConfigurationError(f"store {account_id!r} must be a table")
        values = {
            "platform": "jushuitan", "login_url": "https://www.erp321.com/login.aspx",
            "profile_directory": f"profiles/{account_id}", "debug_port": 0,
            "brand_value": "", "username_env": f"RPA_{account_id}_USERNAME",
            "password_env": f"RPA_{account_id}_PASSWORD",
            **dict(raw), **dict(overrides or {}),
        }
        return StoreConfig(account_id=account_id, **values)
    except KeyError as error:
        raise ConfigurationError(f"store alias not found: {account_id}") from error
    except (OSError, UnicodeError, tomllib.TOMLDecodeError, TypeError) as error:
        raise ConfigurationError(
            f"cannot load local store configuration: {type(error).__name__}"
        ) from error


def load_local_env(path: str | Path, environ: dict[str, str] | None = None) -> None:
    """Load a small dotenv subset without interpolation or command execution."""

    target = environ if environ is not None else os.environ
    source = Path(path)
    if not source.is_file():
        return
    for line_number, raw_line in enumerate(
        source.read_text(encoding="utf-8").splitlines(), 1
    ):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator or not _ENV_NAME_PATTERN.fullmatch(key.strip()):
            raise ConfigurationError(f"invalid .env entry at line {line_number}")
        normalized = value.strip()
        if (
            len(normalized) >= 2
            and normalized[0] == normalized[-1]
            and normalized[0] in {'"', "'"}
        ):
            normalized = normalized[1:-1]
        target.setdefault(key.strip(), normalized)


def load_login_credentials(
    store: StoreConfig,
    environ: Mapping[str, str] | None = None,
) -> LoginCredentials:
    values = environ if environ is not None else os.environ
    try:
        username = values[store.username_env]
        secret_value = values[store.password_env]
        identity_env = store.identity_env or store.username_env
        expected_identity = values.get(identity_env) if store.identity_env else None
    except KeyError as error:
        raise ConfigurationError(
            f"required credential variable is missing: {error.args[0]}"
        ) from error
    if (
        username.startswith("<")
        or secret_value.startswith("<")
    ):
        raise ConfigurationError("credential placeholders must be replaced locally")
    return LoginCredentials(
        SecretValue(username, label=store.username_env),
        SecretValue(secret_value, label=store.password_env),
        SecretValue(expected_identity, label=identity_env) if expected_identity else None,
    )


__all__ = [
    "ConfigurationError",
    "LoginCredentials",
    "StoreConfig",
    "load_local_env",
    "load_login_credentials",
    "load_store_config",
]
