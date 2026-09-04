"""Browser contracts and a deterministic, side-effect-free test double.

Business applications depend on :class:`BrowserActions` only.  The concrete
DrissionPage adapter will live behind this contract; no DrissionPage type is
allowed to escape into application code or checkpoints.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
import re
from typing import Callable, Iterable, Mapping, Protocol, runtime_checkable


_ELEMENT_ID_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]*$")
_SAFE_FILENAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,254}$")


class BrowserError(RuntimeError):
    """Base error exposed by every browser adapter."""

    error_code = "browser_error"
    retryable = False


class BrowserContextGuardError(BrowserError):
    """Internal transport for a context guard rejection through an adapter."""

    error_code = "browser_context_guard_rejected"

    def __init__(self, cause: Exception) -> None:
        self.cause = cause
        super().__init__("browser context origin guard rejected the operation")


class NavigationError(BrowserError):
    error_code = "browser_navigation_failed"
    retryable = True


class ElementLookupError(BrowserError):
    error_code = "browser_element_not_found"
    retryable = True


class UnresolvedElementError(ElementLookupError):
    error_code = "browser_element_unresolved"
    retryable = False


class ElementActionError(BrowserError):
    error_code = "browser_element_action_failed"
    retryable = True


class DownloadError(BrowserError):
    error_code = "browser_download_failed"
    retryable = True


@dataclass(frozen=True, slots=True)
class Locator:
    """One adapter-owned locator expression.

    ``value`` is intentionally opaque to applications.  For the future
    DrissionPage adapter it may contain a DrissionPage locator string such as
    ``#stable-id`` or ``tag:button@@data-action=export``.
    """

    value: str

    def __post_init__(self) -> None:
        if not self.value.strip():
            raise ValueError("locator value must not be empty")


@dataclass(frozen=True, slots=True)
class ElementSpec:
    """Stable element identity with an optional, verified locator.

    A missing locator is deliberate: generated applications can retain their
    complete business flow while an ``UnresolvedElement`` is awaiting an
    authorized browser inspection.  Production adapters must call
    :meth:`require_locator`; the fake uses the stable ID directly.
    """

    id: str
    name: str
    page: str
    component: str | None = None
    locator: Locator | None = None
    frame_locator: Locator | None = None
    option_locator: Locator | None = None
    selected_option_locator: Locator | None = None
    popup_locator: Locator | None = None
    dismiss_locator: Locator | None = None

    def __post_init__(self) -> None:
        if not _ELEMENT_ID_PATTERN.fullmatch(self.id):
            raise ValueError(f"invalid element id: {self.id!r}")
        if not self.name.strip() or not self.page.strip():
            raise ValueError("element name and page must not be empty")
        if self.component is not None and not self.component.strip():
            raise ValueError("element component must not be empty when provided")
        if self.selected_option_locator is not None and self.option_locator is None:
            raise ValueError(
                "selected_option_locator requires option_locator"
            )
        if self.selected_option_locator is not None and (
            self.popup_locator is None or self.dismiss_locator is None
        ):
            raise ValueError(
                "selected_option_locator requires popup_locator and dismiss_locator"
            )

    @property
    def is_resolved(self) -> bool:
        return self.locator is not None

    def require_locator(self) -> Locator:
        if self.locator is None:
            raise UnresolvedElementError(
                f"element {self.id!r} has no verified locator"
            )
        return self.locator


class SecretValue:
    """A runtime-only value whose string and repr forms never reveal content."""

    __slots__ = ("_value", "label")

    def __init__(self, value: str, *, label: str) -> None:
        if not value:
            raise ValueError(f"secret value {label!r} must not be empty")
        if not label.strip():
            raise ValueError("secret label must not be empty")
        self._value = value
        self.label = label

    def reveal(self) -> str:
        """Return the value only at the final adapter boundary."""

        return self._value

    def __repr__(self) -> str:
        return f"SecretValue(label={self.label!r}, value=<redacted>)"

    def __str__(self) -> str:
        return "<redacted>"


SecretLike = str | SecretValue
BrowserContextGuard = Callable[[str | None], None]


@dataclass(frozen=True, slots=True)
class DownloadRef:
    path: Path
    sha256: str
    size_bytes: int
    status: str = "completed"

    @classmethod
    def from_path(cls, path: str | Path) -> "DownloadRef":
        source = Path(path)
        if source.is_symlink() or not source.is_file():
            raise DownloadError("download artifact must be one regular file")
        content = source.read_bytes()
        return cls(
            path=source,
            sha256=f"sha256:{sha256(content).hexdigest()}",
            size_bytes=len(content),
        )

    def to_dict(self) -> dict[str, str | int]:
        return {
            "path": str(self.path),
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "status": self.status,
        }


@dataclass(frozen=True, slots=True)
class ArtifactRef:
    path: Path
    sha256: str
    size_bytes: int

    @classmethod
    def from_path(cls, path: str | Path) -> "ArtifactRef":
        download = DownloadRef.from_path(path)
        return cls(download.path, download.sha256, download.size_bytes)

    def to_dict(self) -> dict[str, str | int]:
        return {
            "path": str(self.path),
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
        }


@runtime_checkable
class BrowserActions(Protocol):
    """The only browser surface visible to business applications."""

    @property
    def current_url(self) -> str | None: ...

    def open(self, url: str, *, wait: str = "document") -> None: ...

    def exists(self, element: ElementSpec, *, timeout: float = 0.0) -> bool: ...

    def count(self, element: ElementSpec, *, timeout: float = 0.0) -> int: ...

    def click(self, element: ElementSpec) -> None: ...

    def click_and_switch_to_new_tab(
        self,
        element: ElementSpec,
        *,
        timeout: float | None = None,
    ) -> None: ...

    def input(self, element: ElementSpec, value: SecretLike) -> None: ...

    def text(self, element: ElementSpec) -> str: ...

    def texts(self, element: ElementSpec, *, timeout: float = 0.0) -> list[str]: ...

    def select(self, element: ElementSpec, value: SecretLike) -> None: ...

    def download(
        self,
        element: ElementSpec,
        *,
        filename: str | None = None,
    ) -> DownloadRef: ...

    def screenshot(
        self,
        *,
        name: str | None = None,
        full_page: bool = False,
    ) -> ArtifactRef: ...


@runtime_checkable
class ContextGuardedBrowserActions(BrowserActions, Protocol):
    """Runtime adapter surface that accepts an origin guard per element call."""

    def exists(
        self,
        element: ElementSpec,
        *,
        timeout: float = 0.0,
        context_guard: BrowserContextGuard | None = None,
    ) -> bool: ...

    def count(
        self,
        element: ElementSpec,
        *,
        timeout: float = 0.0,
        context_guard: BrowserContextGuard | None = None,
    ) -> int: ...

    def click(
        self,
        element: ElementSpec,
        *,
        context_guard: BrowserContextGuard | None = None,
    ) -> None: ...

    def click_and_switch_to_new_tab(
        self,
        element: ElementSpec,
        *,
        timeout: float | None = None,
        context_guard: BrowserContextGuard | None = None,
    ) -> None: ...

    def input(
        self,
        element: ElementSpec,
        value: SecretLike,
        *,
        context_guard: BrowserContextGuard | None = None,
    ) -> None: ...

    def text(
        self,
        element: ElementSpec,
        *,
        context_guard: BrowserContextGuard | None = None,
    ) -> str: ...

    def texts(
        self,
        element: ElementSpec,
        *,
        timeout: float = 0.0,
        context_guard: BrowserContextGuard | None = None,
    ) -> list[str]: ...

    def select(
        self,
        element: ElementSpec,
        value: SecretLike,
        *,
        context_guard: BrowserContextGuard | None = None,
    ) -> None: ...

    def download(
        self,
        element: ElementSpec,
        *,
        filename: str | None = None,
        context_guard: BrowserContextGuard | None = None,
    ) -> DownloadRef: ...


@dataclass(frozen=True, slots=True)
class FakeDownload:
    filename: str
    content: bytes

    def __post_init__(self) -> None:
        _validate_filename(self.filename)
        if not self.content:
            raise ValueError("fake download content must not be empty")


@dataclass(frozen=True, slots=True)
class BrowserActionRecord:
    action: str
    element_id: str | None = None
    detail: str | None = None


@dataclass(slots=True)
class FakeBrowserActions:
    """A deterministic browser used only by no-side-effect application tests.

    The fake never launches a browser or performs network I/O.  It accepts
    unresolved ``ElementSpec`` objects so generated flows can be tested before
    real locators have been authorized and captured.
    """

    run_dir: Path | str
    visible_element_ids: Iterable[str] = field(default_factory=tuple)
    downloads: Mapping[str, FakeDownload] = field(default_factory=dict)
    text_values: Mapping[str, str] = field(default_factory=dict)
    context_urls: Mapping[str, str | None] = field(default_factory=dict)
    counts: Mapping[str, int] = field(default_factory=dict)
    text_lists: Mapping[str, Iterable[str]] = field(default_factory=dict)
    new_tab_urls: Mapping[str, str] = field(default_factory=dict)
    actions: list[BrowserActionRecord] = field(default_factory=list, init=False)
    current_url: str | None = field(default=None, init=False)
    _visible: frozenset[str] = field(init=False, repr=False)
    _text_values: dict[str, str] = field(init=False, repr=False)
    _counts: dict[str, int] = field(init=False, repr=False)
    _text_lists: dict[str, list[str]] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.run_dir = Path(self.run_dir)
        self._visible = frozenset(self.visible_element_ids)
        invalid = sorted(
            element_id
            for element_id in self._visible
            if not _ELEMENT_ID_PATTERN.fullmatch(element_id)
        )
        if invalid:
            raise ValueError(f"invalid fake element IDs: {invalid!r}")
        invalid_text_ids = sorted(
            element_id
            for element_id in self.text_values
            if not _ELEMENT_ID_PATTERN.fullmatch(element_id)
        )
        if invalid_text_ids:
            raise ValueError(f"invalid fake text element IDs: {invalid_text_ids!r}")
        if any(not isinstance(value, str) for value in self.text_values.values()):
            raise ValueError("fake text values must be strings")
        invalid_context_ids = sorted(
            element_id
            for element_id in self.context_urls
            if not _ELEMENT_ID_PATTERN.fullmatch(element_id)
        )
        if invalid_context_ids:
            raise ValueError(
                f"invalid fake context element IDs: {invalid_context_ids!r}"
            )
        if any(
            value is not None and not isinstance(value, str)
            for value in self.context_urls.values()
        ):
            raise ValueError("fake context URLs must be strings or None")
        self._text_values = dict(self.text_values)
        invalid_count_ids = sorted(
            element_id
            for element_id in self.counts
            if not _ELEMENT_ID_PATTERN.fullmatch(element_id)
        )
        if invalid_count_ids:
            raise ValueError(f"invalid fake count element IDs: {invalid_count_ids!r}")
        if any(
            not isinstance(value, int) or isinstance(value, bool) or value < 0
            for value in self.counts.values()
        ):
            raise ValueError("fake counts must be non-negative integers")
        invalid_list_ids = sorted(
            element_id
            for element_id in self.text_lists
            if not _ELEMENT_ID_PATTERN.fullmatch(element_id)
        )
        if invalid_list_ids:
            raise ValueError(f"invalid fake text-list element IDs: {invalid_list_ids!r}")
        self._counts = dict(self.counts)
        self._text_lists = {}
        for element_id, values in self.text_lists.items():
            items = list(values)
            if any(not isinstance(item, str) for item in items):
                raise ValueError("fake text list values must be strings")
            self._text_lists[element_id] = items
        invalid_new_tab_ids = sorted(
            element_id
            for element_id in self.new_tab_urls
            if not _ELEMENT_ID_PATTERN.fullmatch(element_id)
        )
        if invalid_new_tab_ids:
            raise ValueError(
                f"invalid fake new-tab element IDs: {invalid_new_tab_ids!r}"
            )
        if any(
            not isinstance(value, str) or not value.strip()
            for value in self.new_tab_urls.values()
        ):
            raise ValueError("fake new-tab URLs must be non-empty strings")

    def context_url(self, element: ElementSpec) -> str | None:
        """Return the deterministic browsing context URL for one element.

        Unconfigured fake elements share the fake tab's URL. Tests can supply
        ``None`` to model a lost frame context or another URL to model a
        cross-origin frame.
        """

        return self.context_urls.get(element.id, self.current_url)

    def open(self, url: str, *, wait: str = "document") -> None:
        if not url.strip():
            raise NavigationError("browser URL must not be empty")
        if wait not in {"none", "document", "complete"}:
            raise NavigationError(f"unsupported navigation wait policy: {wait!r}")
        self.current_url = url
        self.actions.append(BrowserActionRecord("open", detail=wait))

    def exists(
        self,
        element: ElementSpec,
        *,
        timeout: float = 0.0,
        context_guard: BrowserContextGuard | None = None,
    ) -> bool:
        if timeout < 0:
            raise ValueError("timeout must be non-negative")
        self._guard_context(element, context_guard)
        try:
            found = element.id in self._visible
            self.actions.append(
                BrowserActionRecord(
                    "exists", element.id, "present" if found else "missing"
                )
            )
            return found
        finally:
            self._guard_context(element, context_guard)

    def count(
        self,
        element: ElementSpec,
        *,
        timeout: float = 0.0,
        context_guard: BrowserContextGuard | None = None,
    ) -> int:
        """Return the configured match count.

        A multi-element query never raises for an absent target: an empty
        result set is a legitimate page state that a step must be able to
        assert on, not an error.
        """

        if timeout < 0:
            raise ValueError("timeout must be non-negative")
        self._guard_context(element, context_guard)
        try:
            value = self._counts.get(
                element.id,
                1 if element.id in self._visible else 0,
            )
            self.actions.append(
                BrowserActionRecord("count", element.id, str(value))
            )
            return value
        finally:
            self._guard_context(element, context_guard)

    def texts(
        self,
        element: ElementSpec,
        *,
        timeout: float = 0.0,
        context_guard: BrowserContextGuard | None = None,
    ) -> list[str]:
        """Return the configured text values for every match, possibly empty."""

        if timeout < 0:
            raise ValueError("timeout must be non-negative")
        self._guard_context(element, context_guard)
        try:
            if element.id in self._text_lists:
                values = list(self._text_lists[element.id])
            elif element.id in self._visible and element.id in self._text_values:
                values = [self._text_values[element.id]]
            else:
                values = []
            self.actions.append(
                BrowserActionRecord("texts", element.id, f"count={len(values)}")
            )
            return values
        finally:
            self._guard_context(element, context_guard)

    def click(
        self,
        element: ElementSpec,
        *,
        context_guard: BrowserContextGuard | None = None,
    ) -> None:
        self._guard_context(element, context_guard)
        try:
            self._require_visible(element)
            self.actions.append(BrowserActionRecord("click", element.id))
        finally:
            self._guard_context(element, context_guard)

    def click_and_switch_to_new_tab(
        self,
        element: ElementSpec,
        *,
        timeout: float | None = None,
        context_guard: BrowserContextGuard | None = None,
    ) -> None:
        if timeout is not None and timeout <= 0:
            raise ValueError("new-tab timeout must be positive")
        self.click(element, context_guard=context_guard)
        try:
            target_url = self.new_tab_urls[element.id]
        except KeyError as error:
            raise NavigationError(
                f"no fake new tab configured for element {element.id!r}"
            ) from error
        self.current_url = target_url
        self.actions.append(
            BrowserActionRecord("switch_new_tab", element.id, target_url)
        )

    def input(
        self,
        element: ElementSpec,
        value: SecretLike,
        *,
        context_guard: BrowserContextGuard | None = None,
    ) -> None:
        self._guard_context(element, context_guard)
        try:
            self._require_visible(element)
            _require_runtime_value(value)
            self.actions.append(BrowserActionRecord("input", element.id, "<redacted>"))
        finally:
            self._guard_context(element, context_guard)

    def text(
        self,
        element: ElementSpec,
        *,
        context_guard: BrowserContextGuard | None = None,
    ) -> str:
        self._guard_context(element, context_guard)
        try:
            self._require_visible(element)
            value = self._text_values[element.id]
            self.actions.append(BrowserActionRecord("text", element.id, "<redacted>"))
            return value
        except KeyError as error:
            raise ElementActionError(
                f"no fake text configured for element {element.id!r}"
            ) from error
        finally:
            self._guard_context(element, context_guard)

    def select(
        self,
        element: ElementSpec,
        value: SecretLike,
        *,
        context_guard: BrowserContextGuard | None = None,
    ) -> None:
        self._guard_context(element, context_guard)
        try:
            self._require_visible(element)
            _require_runtime_value(value)
            self.actions.append(BrowserActionRecord("select", element.id, "<redacted>"))
        finally:
            self._guard_context(element, context_guard)

    def download(
        self,
        element: ElementSpec,
        *,
        filename: str | None = None,
        context_guard: BrowserContextGuard | None = None,
    ) -> DownloadRef:
        self._guard_context(element, context_guard)
        try:
            self._require_visible(element)
            try:
                fixture = self.downloads[element.id]
            except KeyError as error:
                raise DownloadError(
                    f"no fake download configured for element {element.id!r}"
                ) from error
            target_name = filename or fixture.filename
            _validate_filename(target_name)
            target_dir = self.run_dir / "downloads"
            target_dir.mkdir(parents=True, exist_ok=True)
            target = target_dir / target_name
            if target.exists() and (target.is_symlink() or not target.is_file()):
                raise DownloadError("download target is not one regular file")
            target.write_bytes(fixture.content)
            reference = DownloadRef.from_path(target)
            self.actions.append(BrowserActionRecord("download", element.id, target_name))
            return reference
        finally:
            self._guard_context(element, context_guard)

    def screenshot(
        self,
        *,
        name: str | None = None,
        full_page: bool = False,
    ) -> ArtifactRef:
        target_name = name or "browser-evidence.txt"
        _validate_filename(target_name)
        target_dir = self.run_dir / "evidence"
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / target_name
        target.write_bytes(b"fake browser screenshot\n")
        reference = ArtifactRef.from_path(target)
        self.actions.append(
            BrowserActionRecord("screenshot", detail="full_page" if full_page else "viewport")
        )
        return reference

    def _require_visible(self, element: ElementSpec) -> None:
        if element.id not in self._visible:
            raise ElementLookupError(f"fake element is not visible: {element.id}")

    def _guard_context(
        self,
        element: ElementSpec,
        context_guard: BrowserContextGuard | None,
    ) -> None:
        if context_guard is not None:
            try:
                context_guard(self.context_url(element))
            except BrowserContextGuardError:
                raise
            except Exception as error:
                raise BrowserContextGuardError(error) from error


def _require_runtime_value(value: SecretLike) -> str:
    revealed = value.reveal() if isinstance(value, SecretValue) else value
    if not isinstance(revealed, str) or not revealed:
        raise ElementActionError("browser input/select value must not be empty")
    return revealed


def _validate_filename(filename: str) -> None:
    if not _SAFE_FILENAME_PATTERN.fullmatch(filename) or Path(filename).name != filename:
        raise DownloadError("artifact filename must be one safe basename")


__all__ = [
    "ArtifactRef",
    "BrowserActionRecord",
    "BrowserActions",
    "BrowserContextGuard",
    "BrowserContextGuardError",
    "ContextGuardedBrowserActions",
    "BrowserError",
    "DownloadError",
    "DownloadRef",
    "ElementActionError",
    "ElementLookupError",
    "ElementSpec",
    "FakeBrowserActions",
    "FakeDownload",
    "Locator",
    "NavigationError",
    "SecretLike",
    "SecretValue",
    "UnresolvedElementError",
]
