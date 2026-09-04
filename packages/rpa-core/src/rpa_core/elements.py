"""Load one application's ``elements.toml`` element catalog.

The catalog is deliberately a single application-local file. Cross-application
element sharing is not modelled: until a third application genuinely needs the
same locator, copying it is cheaper than a package manager (see ADR-028).

``expect_count`` is the distinguishing feature. It states the match count that
must hold **right now**, so ``verify-elements`` can detect a locator that the
site has broken. A recorded historical match count cannot do that.

It is always paired with ``check_at``, the navigation stage the expectation
describes. The first real run of ``verify-elements`` proved why: checked at one
arbitrary moment, seven entries reported as broken when nothing was broken —
login inputs match zero once you are logged in, and a "module is active" marker
stops matching once you navigate deeper. An expectation without a stage is not
falsifiable in a useful way; it just moves the ambiguity into the report.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import tomllib
from typing import Any, Mapping

from .browser import ElementSpec, Locator


_COUNT_PATTERN = re.compile(r"^(?:(>=|>|<=|<|=)\s*)?(\d+)$")

_SUB_LOCATORS = (
    ("option_locator", "option_locator"),
    ("selected_option_locator", "selected_option_locator"),
    ("popup_locator", "popup_locator"),
    ("dismiss_locator", "dismiss_locator"),
)


class ElementCatalogError(ValueError):
    """The application's element catalog is unusable."""

    error_code = "element_catalog_invalid"


@dataclass(frozen=True, slots=True)
class ExpectedCount:
    """A match-count assertion that must hold on the live page right now."""

    operator: str
    value: int

    @classmethod
    def parse(cls, raw: Any, element_id: str) -> "ExpectedCount":
        if isinstance(raw, bool):
            raise ElementCatalogError(f"{element_id}: expect_count must not be a boolean")
        if isinstance(raw, int):
            if raw < 0:
                raise ElementCatalogError(f"{element_id}: expect_count must not be negative")
            return cls("=", raw)
        if not isinstance(raw, str):
            raise ElementCatalogError(f"{element_id}: expect_count must be an int or string")
        match = _COUNT_PATTERN.fullmatch(raw.strip())
        if match is None:
            raise ElementCatalogError(
                f"{element_id}: expect_count must look like 1, '>0' or '>=2', got {raw!r}"
            )
        operator = match.group(1) or "="
        return cls(operator, int(match.group(2)))

    def holds(self, actual: int) -> bool:
        match self.operator:
            case "=":
                return actual == self.value
            case ">":
                return actual > self.value
            case ">=":
                return actual >= self.value
            case "<":
                return actual < self.value
            case "<=":
                return actual <= self.value
        raise ElementCatalogError(f"unsupported expect_count operator: {self.operator}")

    def __str__(self) -> str:
        return f"{self.value}" if self.operator == "=" else f"{self.operator}{self.value}"


@dataclass(frozen=True, slots=True)
class ElementEntry:
    """One catalog entry: the runtime spec plus its verification metadata."""

    spec: ElementSpec
    expect: ExpectedCount
    check_at: str
    weak_assertion: bool
    note: str

    @property
    def id(self) -> str:
        return self.spec.id


def load_element_catalog(path: str | Path) -> dict[str, ElementEntry]:
    """Parse ``elements.toml`` into ordered element entries."""

    source = Path(path)
    try:
        document = tomllib.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as error:
        raise ElementCatalogError(
            f"cannot read element catalog: {type(error).__name__}"
        ) from error

    if document.get("schema_version") != 2:
        raise ElementCatalogError("elements.toml schema_version must equal 2")
    raw_elements = document.get("elements")
    if not isinstance(raw_elements, Mapping) or not raw_elements:
        raise ElementCatalogError("elements.toml must define a non-empty [elements] table")

    entries: dict[str, ElementEntry] = {}
    for element_id, raw in raw_elements.items():
        if not isinstance(raw, Mapping):
            raise ElementCatalogError(f"{element_id}: element entry must be a table")
        unknown = set(raw) - {
            "name",
            "page",
            "locator",
            "frame",
            "expect_count",
            "check_at",
            "assertion_strength",
            "note",
            "option_locator",
            "selected_option_locator",
            "popup_locator",
            "dismiss_locator",
        }
        if unknown:
            raise ElementCatalogError(
                f"{element_id}: unknown keys {sorted(unknown)!r}"
            )
        if "expect_count" not in raw:
            raise ElementCatalogError(
                f"{element_id}: expect_count is required — without it the entry "
                "records history instead of asserting the present"
            )
        if "check_at" not in raw:
            raise ElementCatalogError(
                f"{element_id}: check_at is required — a match count without a "
                "navigation stage cannot be asserted meaningfully"
            )
        strength = str(raw.get("assertion_strength", "strong"))
        if strength not in {"strong", "weak"}:
            raise ElementCatalogError(
                f"{element_id}: assertion_strength must be 'strong' or 'weak'"
            )
        kwargs: dict[str, Any] = {
            "id": str(element_id),
            "name": str(raw["name"]),
            "page": str(raw["page"]),
            "locator": _locator(raw.get("locator")),
            "frame_locator": _locator(raw.get("frame")),
        }
        for source_key, spec_key in _SUB_LOCATORS:
            kwargs[spec_key] = _locator(raw.get(source_key))
        try:
            spec = ElementSpec(**kwargs)
        except (ValueError, TypeError) as error:
            raise ElementCatalogError(f"{element_id}: {error}") from error
        entries[spec.id] = ElementEntry(
            spec=spec,
            expect=ExpectedCount.parse(raw["expect_count"], str(element_id)),
            check_at=str(raw["check_at"]),
            weak_assertion=strength == "weak",
            note=str(raw.get("note", "")),
        )
    return entries


def element_specs(entries: Mapping[str, ElementEntry]) -> dict[str, ElementSpec]:
    """Project catalog entries down to the mapping the runtime binds as a service."""

    return {key: entry.spec for key, entry in entries.items()}


@dataclass(frozen=True, slots=True)
class ElementCheck:
    """The outcome of asserting one element's ``expect_count`` on a live page."""

    element_id: str
    expected: str
    actual: int | None
    ok: bool
    weak: bool
    detail: str

    @property
    def symbol(self) -> str:
        if not self.ok:
            return "FAIL"
        return "WEAK" if self.weak else "OK"

    def render(self) -> str:
        actual = "-" if self.actual is None else str(self.actual)
        line = (
            f"{self.symbol:<4} {self.element_id:<50} "
            f"expect={self.expected:<4} actual={actual}"
        )
        return f"{line}  {self.detail}" if self.detail else line


def check_element_expectations(
    browser: Any,
    entries: Mapping[str, ElementEntry],
    *,
    stage: str,
) -> list[ElementCheck]:
    """Assert the entries declared for ``stage`` against the current page.

    This is what makes an element catalog worth keeping: when the site changes,
    one run says exactly which entry to repair instead of leaving a step to fail
    with an opaque lookup error. Entries belonging to other stages are skipped
    rather than reported, because a login input matching zero after login is
    correct, not broken.
    """

    checks: list[ElementCheck] = []
    for element_id, entry in entries.items():
        if entry.check_at != stage:
            continue
        if not entry.spec.is_resolved:
            checks.append(
                ElementCheck(
                    element_id,
                    str(entry.expect),
                    None,
                    False,
                    entry.weak_assertion,
                    "locator 尚未捕获",
                )
            )
            continue
        try:
            actual = int(browser.count(entry.spec))
        except Exception as error:  # noqa: BLE001 - report, never abort the sweep
            checks.append(
                ElementCheck(
                    element_id,
                    str(entry.expect),
                    None,
                    False,
                    entry.weak_assertion,
                    f"查找失败：{type(error).__name__}",
                )
            )
            continue
        ok = entry.expect.holds(actual)
        detail = ""
        if not ok:
            detail = "元素已失效，修这一个条目即可"
        elif entry.weak_assertion:
            detail = entry.note or "断言过弱：能匹配成功但区分不了页面状态"
        checks.append(
            ElementCheck(element_id, str(entry.expect), actual, ok, entry.weak_assertion, detail)
        )
    return checks


def _locator(value: Any) -> Locator | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ElementCatalogError("locator values must be non-empty strings")
    return Locator(value)


__all__ = [
    "ElementCatalogError",
    "ElementCheck",
    "ElementEntry",
    "ExpectedCount",
    "check_element_expectations",
    "element_specs",
    "load_element_catalog",
]
