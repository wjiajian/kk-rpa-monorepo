"""DrissionPage-backed implementation of the public browser action contract.

The adapter deliberately accepts an already managed Chromium tab. Browser
process creation, profile locking, debug-port leasing, and lifecycle policy
belong to the future BrowserManager and must not leak into business apps.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from time import monotonic, sleep
from typing import Any

from DrissionPage.common import Keys
from DrissionPage.errors import ContextLostError, ElementLostError, GetDocumentError

from .browser import (
    ArtifactRef,
    BrowserContextGuard,
    BrowserContextGuardError,
    DownloadError,
    DownloadRef,
    ElementActionError,
    ElementLookupError,
    ElementSpec,
    NavigationError,
    SecretLike,
    SecretValue,
)


_SAFE_FILENAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,254}$")
_TRANSIENT_LOOKUP_ERRORS = (ContextLostError, ElementLostError, GetDocumentError)


class _TransientScopeUnavailable(RuntimeError):
    """An iframe is temporarily absent while its context is refreshing."""


class _TransientScopeOriginUnavailable(RuntimeError):
    """An iframe exists but has not committed its HTTP(S) document yet."""


_RETRYABLE_LOOKUP_ERRORS = _TRANSIENT_LOOKUP_ERRORS + (
    _TransientScopeUnavailable,
)


@dataclass(frozen=True, slots=True)
class _LocatedElement:
    scope: Any
    target: Any


@dataclass(slots=True)
class DrissionBrowserActions:
    """Translate ``BrowserActions`` calls to one managed DrissionPage tab.

    ``tab`` is intentionally typed as ``Any`` so the public package never
    exposes a DrissionPage class to applications. The concrete object is
    supplied by the runtime-owned browser manager.
    """

    tab: Any
    run_dir: Path | str
    action_timeout: float = 10.0
    download_timeout: float = 120.0

    def __post_init__(self) -> None:
        self.run_dir = Path(self.run_dir)
        if self.action_timeout <= 0:
            raise ValueError("action_timeout must be positive")
        if self.download_timeout <= 0:
            raise ValueError("download_timeout must be positive")
        if self.run_dir.is_symlink():
            raise ValueError("run_dir must not be a symbolic link")

    @property
    def current_url(self) -> str | None:
        """Expose only the current URL needed by the authorization boundary."""

        try:
            value = self.tab.url
        except Exception:
            return None
        return value if isinstance(value, str) and value.strip() else None

    def context_url(self, element: ElementSpec) -> str | None:
        """Return a freshly resolved browsing context URL for diagnostics.

        DrissionPage 4.1 exposes ``url`` on both ``ChromiumTab`` and
        ``ChromiumFrame``. Authorization does not rely on this separate lookup;
        guarded element calls validate the same scope object they act through.
        """

        if element.frame_locator is None:
            return self.current_url
        try:
            scope = self._scope(element, timeout=self.action_timeout)
            value = scope.url
        except Exception:
            return None
        return value if isinstance(value, str) and value.strip() else None

    def open(self, url: str, *, wait: str = "document") -> None:
        if not isinstance(url, str) or not url.strip():
            raise NavigationError("browser URL must not be empty")
        if wait not in {"none", "document", "complete"}:
            raise NavigationError(f"unsupported navigation wait policy: {wait!r}")
        try:
            loaded = self.tab.get(url)
            if loaded is False:
                raise NavigationError("browser navigation returned false")
            if wait != "none" and not self.tab.wait.doc_loaded(
                timeout=self.action_timeout,
                raise_err=False,
            ):
                raise NavigationError("document did not finish loading before timeout")
        except NavigationError:
            raise
        except Exception as error:
            raise NavigationError("browser navigation failed") from error

    def exists(
        self,
        element: ElementSpec,
        *,
        timeout: float = 0.0,
        context_guard: BrowserContextGuard | None = None,
    ) -> bool:
        if timeout < 0:
            raise ValueError("timeout must be non-negative")
        return (
            self._locate(
                element,
                timeout=timeout,
                required=False,
                context_guard=context_guard,
            )
            is not None
        )

    def count(
        self,
        element: ElementSpec,
        *,
        timeout: float = 0.0,
        context_guard: BrowserContextGuard | None = None,
    ) -> int:
        """Return how many nodes the element's locator currently matches.

        An absent target is ``0``, not an error: an empty result set is a
        legitimate page state that a step must be able to assert on.
        """

        return len(self._match_all(element, timeout, context_guard))

    def texts(
        self,
        element: ElementSpec,
        *,
        timeout: float = 0.0,
        context_guard: BrowserContextGuard | None = None,
    ) -> list[str]:
        """Return the visible text of every current match, possibly empty."""

        matches = self._match_all(element, timeout, context_guard)
        values: list[str] = []
        for node in matches:
            try:
                raw = node.attr("value") if str(node.tag).lower() == "input" else node.text
            except Exception as error:
                raise ElementActionError(
                    f"element text read failed: {element.id}"
                ) from error
            values.append(raw if isinstance(raw, str) else "")
        return values

    def _match_all(
        self,
        element: ElementSpec,
        timeout: float,
        context_guard: BrowserContextGuard | None,
    ) -> list[Any]:
        if timeout < 0:
            raise ValueError("timeout must be non-negative")
        locator = element.require_locator()
        lookup_timeout = timeout if timeout > 0 else self.action_timeout
        # Re-resolve the scope on every retry, exactly like the single-element
        # path. A business iframe is routinely re-created just after the outer
        # page marker appears, which invalidates an already-resolved frame and
        # raises ContextLostError mid-query. Retrying a stale scope object, or
        # failing outright, would report a healthy selector as broken.
        deadline = monotonic() + lookup_timeout
        first_attempt = True
        while True:
            remaining = max(0.0, deadline - monotonic())
            attempt_timeout = lookup_timeout if first_attempt else min(0.5, remaining)
            try:
                scope = self._scope(element, timeout=attempt_timeout)
                self._guard_scope_origin(scope, context_guard)
                try:
                    matches = scope.eles(locator.value, timeout=attempt_timeout)
                finally:
                    self._guard_scope_origin(scope, context_guard)
                return list(matches) if matches else []
            except BrowserContextGuardError:
                raise
            except _RETRYABLE_LOOKUP_ERRORS:
                if not first_attempt and monotonic() >= deadline:
                    raise
                first_attempt = False
                sleep(min(0.05, max(0.0, deadline - monotonic())))
            except Exception as error:
                raise ElementLookupError(
                    f"element multi-match lookup failed: {element.id}"
                ) from error

    def click(
        self,
        element: ElementSpec,
        *,
        context_guard: BrowserContextGuard | None = None,
    ) -> None:
        located = self._find(element, context_guard=context_guard)
        target = located.target
        self._guard_scope_origin(located.scope, context_guard)
        try:
            if not target.wait.clickable(
                wait_moved=True,
                timeout=self.action_timeout,
                raise_err=False,
            ):
                raise ElementActionError(f"element is not clickable: {element.id}")
            self._guard_scope_origin(located.scope, context_guard)
            target.click(by_js=False)
        except BrowserContextGuardError:
            raise
        except ElementActionError:
            raise
        except Exception as error:
            raise ElementActionError(f"element click failed: {element.id}") from error
        finally:
            self._guard_scope_origin(located.scope, context_guard)

    def input(
        self,
        element: ElementSpec,
        value: SecretLike,
        *,
        context_guard: BrowserContextGuard | None = None,
    ) -> None:
        located = self._find(element, context_guard=context_guard)
        target = located.target
        revealed = _reveal(value)
        self._guard_scope_origin(located.scope, context_guard)
        try:
            self._input_value(
                target,
                revealed,
                element,
                scope=located.scope,
                context_guard=context_guard,
            )
        except BrowserContextGuardError:
            raise
        except ElementActionError:
            raise
        except Exception as error:
            raise ElementActionError(f"element input failed: {element.id}") from error
        finally:
            self._guard_scope_origin(located.scope, context_guard)

    def text(
        self,
        element: ElementSpec,
        *,
        context_guard: BrowserContextGuard | None = None,
    ) -> str:
        located = self._find(element, context_guard=context_guard)
        target = located.target
        self._guard_scope_origin(located.scope, context_guard)
        try:
            value = target.attr("value") if str(target.tag).lower() == "input" else target.text
            if value is None:
                return ""
            if not isinstance(value, str):
                raise ElementActionError(f"element text is not a string: {element.id}")
            return value
        except ElementActionError:
            raise
        except Exception as error:
            raise ElementActionError(f"element text read failed: {element.id}") from error
        finally:
            self._guard_scope_origin(located.scope, context_guard)

    def select(
        self,
        element: ElementSpec,
        value: SecretLike,
        *,
        context_guard: BrowserContextGuard | None = None,
    ) -> None:
        located = self._find(element, context_guard=context_guard)
        target = located.target
        revealed = _reveal(value)
        self._guard_scope_origin(located.scope, context_guard)
        try:
            tag = str(target.tag).lower()
            if tag == "select":
                self._guard_scope_origin(located.scope, context_guard)
                target.select.by_text(revealed, timeout=self.action_timeout)
                self._guard_scope_origin(located.scope, context_guard)
            elif tag == "input":
                if not target.wait.clickable(
                    wait_moved=True,
                    timeout=self.action_timeout,
                    raise_err=False,
                ):
                    raise ElementActionError(
                        f"custom select trigger is not clickable: {element.id}"
                    )
                self._guard_scope_origin(located.scope, context_guard)
                target.click(by_js=False)
                self._guard_scope_origin(located.scope, context_guard)
                self._input_value(
                    target,
                    revealed,
                    element,
                    scope=located.scope,
                    context_guard=context_guard,
                )
                self._guard_scope_origin(located.scope, context_guard)
                if element.option_locator is None:
                    target.input(Keys.ENTER, clear=False, by_js=False)
                    self._guard_scope_origin(located.scope, context_guard)
                elif element.selected_option_locator is not None:
                    self._ensure_exact_custom_selection(
                        element,
                        revealed,
                        context_guard=context_guard,
                    )
                else:
                    self._click_exact_option(
                        element,
                        revealed,
                        context_guard=context_guard,
                    )
            else:
                raise ElementActionError(
                    f"unsupported select element tag for {element.id}: {tag!r}"
                )
        except BrowserContextGuardError:
            raise
        except ElementActionError:
            raise
        except Exception as error:
            raise ElementActionError(f"element select failed: {element.id}") from error
        finally:
            self._guard_scope_origin(located.scope, context_guard)

    def download(
        self,
        element: ElementSpec,
        *,
        filename: str | None = None,
        context_guard: BrowserContextGuard | None = None,
    ) -> DownloadRef:
        if filename is not None:
            _validate_filename(filename)
        located = self._find(element, context_guard=context_guard)
        target = located.target
        download_dir = self._artifact_directory("downloads")
        started = monotonic()
        self._guard_scope_origin(located.scope, context_guard)
        try:
            mission = target.click.to_download(
                str(download_dir),
                rename=filename,
                by_js=False,
                timeout=self.download_timeout,
            )
            self._guard_scope_origin(located.scope, context_guard)
            if not mission:
                raise DownloadError("download did not start")
            # One bounded budget covers both server-side export preparation and
            # transfer completion. A late mission does not receive a second
            # full timeout after it appears.
            deadline = started + self.download_timeout
            while not mission.is_done and monotonic() < deadline:
                sleep(min(0.05, max(0.0, deadline - monotonic())))
            if not mission.is_done:
                mission.cancel()
                raise DownloadError("download timed out and was canceled")
            if mission.state != "completed" or not mission.final_path:
                raise DownloadError(f"download ended with state {mission.state!r}")
            final_path = Path(mission.final_path)
            if not _is_within(final_path, download_dir):
                raise DownloadError("download escaped the run download directory")
            return DownloadRef.from_path(final_path)
        except BrowserContextGuardError:
            raise
        except DownloadError:
            raise
        except Exception as error:
            raise DownloadError(f"download action failed: {element.id}") from error
        finally:
            self._guard_scope_origin(located.scope, context_guard)

    def screenshot(
        self,
        *,
        name: str | None = None,
        full_page: bool = False,
    ) -> ArtifactRef:
        target_name = name or "browser-evidence.png"
        _validate_filename(target_name)
        evidence_dir = self._artifact_directory("evidence")
        try:
            result = self.tab.get_screenshot(
                path=str(evidence_dir),
                name=target_name,
                full_page=full_page,
            )
            target = Path(result) if result else evidence_dir / target_name
            if not _is_within(target, evidence_dir):
                raise ElementActionError("screenshot escaped the run evidence directory")
            return ArtifactRef.from_path(target)
        except ElementActionError:
            raise
        except Exception as error:
            raise ElementActionError("browser screenshot failed") from error

    def _find(
        self,
        element: ElementSpec,
        *,
        context_guard: BrowserContextGuard | None,
    ) -> _LocatedElement:
        located = self._locate(
            element,
            timeout=self.action_timeout,
            required=True,
            context_guard=context_guard,
        )
        assert located is not None
        return located

    def _locate(
        self,
        element: ElementSpec,
        *,
        timeout: float,
        required: bool,
        context_guard: BrowserContextGuard | None,
    ) -> _LocatedElement | None:
        locator = element.require_locator().value
        deadline = monotonic() + timeout
        first_attempt = True
        last_transient_scope = None
        while first_attempt or monotonic() < deadline:
            lookup_timeout = (
                timeout
                if first_attempt
                else min(0.5, max(0.0, deadline - monotonic()))
            )
            first_attempt = False
            try:
                scope = self._scope(element, timeout=lookup_timeout)
            except _RETRYABLE_LOOKUP_ERRORS:
                if timeout == 0 or monotonic() >= deadline:
                    break
                sleep(min(0.05, max(0.0, deadline - monotonic())))
                continue
            except ElementLookupError:
                raise
            try:
                self._guard_scope_origin(
                    scope,
                    context_guard,
                    allow_transient_blank=element.frame_locator is not None,
                )
            except _TransientScopeOriginUnavailable:
                last_transient_scope = scope
                if timeout == 0 or monotonic() >= deadline:
                    self._guard_scope_origin(scope, context_guard)
                    break
                sleep(min(0.05, max(0.0, deadline - monotonic())))
                continue
            last_transient_scope = None
            try:
                target = scope.ele(locator, timeout=lookup_timeout)
                if target:
                    return _LocatedElement(scope=scope, target=target)
                # DrissionPage already waited for the supplied timeout. A
                # normal miss is final; only context-refresh errors are retried.
                break
            except _RETRYABLE_LOOKUP_ERRORS:
                pass
            except Exception as error:
                raise ElementLookupError(
                    f"element lookup failed: {element.id}"
                ) from error
            finally:
                self._guard_scope_origin(scope, context_guard)
            if timeout == 0 or monotonic() >= deadline:
                break
            sleep(min(0.05, max(0.0, deadline - monotonic())))
        if last_transient_scope is not None:
            self._guard_scope_origin(last_transient_scope, context_guard)
        if required:
            raise ElementLookupError(f"element was not found: {element.id}")
        return None

    def _scope(self, element: ElementSpec, *, timeout: float) -> Any:
        if element.frame_locator is None:
            return self.tab
        try:
            frame = self.tab.get_frame(element.frame_locator.value, timeout=timeout)
        except _TRANSIENT_LOOKUP_ERRORS:
            raise
        except Exception as error:
            raise ElementLookupError(f"frame lookup failed: {element.id}") from error
        if not frame:
            raise _TransientScopeUnavailable(element.id)
        return frame

    @staticmethod
    def _guard_scope_origin(
        scope: Any,
        context_guard: BrowserContextGuard | None,
        *,
        allow_transient_blank: bool = False,
    ) -> None:
        if context_guard is None:
            return
        try:
            value = scope.url
        except Exception:
            value = None
        normalized = value if isinstance(value, str) and value.strip() else None
        if allow_transient_blank and (
            normalized is None or normalized.strip().casefold() == "about:blank"
        ):
            raise _TransientScopeOriginUnavailable()
        try:
            context_guard(normalized)
        except BrowserContextGuardError:
            raise
        except Exception as error:
            raise BrowserContextGuardError(error) from error

    def _input_value(
        self,
        target: Any,
        value: str,
        element: ElementSpec,
        *,
        scope: Any,
        context_guard: BrowserContextGuard | None,
    ) -> None:
        if not target.wait.clickable(
            wait_moved=False,
            timeout=self.action_timeout,
            raise_err=False,
        ):
            raise ElementActionError(f"element is not ready for input: {element.id}")
        # DrissionPage 4.1.1.4 uses JS clear on macOS internally. Calling it
        # explicitly keeps behavior deterministic across platforms.
        self._guard_scope_origin(scope, context_guard)
        target.clear(by_js=True)
        self._guard_scope_origin(scope, context_guard)
        target.focus()
        self._guard_scope_origin(scope, context_guard)
        target.input(value, clear=False, by_js=False)
        self._guard_scope_origin(scope, context_guard)

    def _click_exact_option(
        self,
        element: ElementSpec,
        value: str,
        *,
        context_guard: BrowserContextGuard | None,
    ) -> None:
        option_locator = element.option_locator
        if option_locator is None:
            raise ElementActionError(
                f"custom select option locator is missing: {element.id}"
            )
        deadline = monotonic() + self.action_timeout
        while True:
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise ElementActionError(
                    f"no unique exact custom select option became ready: {element.id}"
                )
            lookup_timeout = min(0.2, max(0.01, remaining))
            try:
                scope = self._scope(element, timeout=lookup_timeout)
            except _RETRYABLE_LOOKUP_ERRORS:
                continue
            except ElementLookupError:
                raise
            self._guard_scope_origin(scope, context_guard)
            try:
                candidates = scope.eles(option_locator.value, timeout=lookup_timeout)

                matches = []
                for candidate in candidates:
                    try:
                        states = candidate.states
                        if not (
                            states.is_displayed
                            and states.is_enabled
                            and states.is_clickable
                        ):
                            continue
                        candidate_text = candidate.text
                        if (
                            isinstance(candidate_text, str)
                            and candidate_text.strip() == value
                        ):
                            matches.append(candidate)
                    except Exception:
                        # Dynamic dropdown options may disappear while being
                        # inspected. Re-querying the locator is safer than
                        # retaining a stale object.
                        continue
            except _RETRYABLE_LOOKUP_ERRORS:
                continue
            except Exception as error:
                raise ElementActionError(
                    f"custom select option lookup failed: {element.id}"
                ) from error
            finally:
                self._guard_scope_origin(scope, context_guard)

            if len(matches) > 1:
                raise ElementActionError(
                    f"multiple exact custom select options are ready: {element.id}"
                )
            if len(matches) == 1:
                option = matches[0]
                self._guard_scope_origin(scope, context_guard)
                try:
                    if not option.wait.clickable(
                        wait_moved=True,
                        timeout=min(remaining, self.action_timeout),
                        raise_err=False,
                    ):
                        raise ElementActionError(
                            "exact custom select option is no longer clickable: "
                            f"{element.id}"
                        )
                    self._guard_scope_origin(scope, context_guard)
                    option.click(by_js=False)
                    return
                finally:
                    self._guard_scope_origin(scope, context_guard)
            sleep(min(0.05, remaining))

    def _ensure_exact_custom_selection(
        self,
        element: ElementSpec,
        value: str,
        *,
        context_guard: BrowserContextGuard | None,
    ) -> None:
        """Make one custom multi-select contain exactly ``value``.

        The option text is runtime data and is deliberately excluded from all
        errors. Dynamic menus are re-queried after every click so stale option
        objects never survive a selection-state transition.
        """

        if element.selected_option_locator is None:
            raise ElementActionError(
                f"custom select selected-option locator is missing: {element.id}"
            )
        deadline = monotonic() + self.action_timeout
        while monotonic() < deadline:
            selected = self._selected_custom_option_values(
                element,
                timeout=min(0.5, max(0.01, deadline - monotonic())),
                context_guard=context_guard,
            )
            target_count = sum(candidate == value for candidate in selected)
            if target_count > 1 or len(selected) != len(set(selected)):
                raise ElementActionError(
                    f"custom select returned duplicate selected options: {element.id}"
                )
            extras = [candidate for candidate in selected if candidate != value]
            if not extras and target_count == 1:
                self._dismiss_custom_select(
                    element,
                    context_guard=context_guard,
                )
                return

            previous = selected
            if extras:
                self._click_exact_option(
                    element,
                    extras[0],
                    context_guard=context_guard,
                )
            else:
                self._click_exact_option(
                    element,
                    value,
                    context_guard=context_guard,
                )
            self._wait_for_custom_selection_change(
                element,
                previous=previous,
                deadline=deadline,
                context_guard=context_guard,
            )
        raise ElementActionError(
            f"custom select did not reach one exact selection: {element.id}"
        )

    def _selected_custom_option_values(
        self,
        element: ElementSpec,
        *,
        timeout: float,
        context_guard: BrowserContextGuard | None,
    ) -> tuple[str, ...]:
        option_locator = element.option_locator
        selected_locator = element.selected_option_locator
        if option_locator is None or selected_locator is None:
            raise ElementActionError(
                f"custom select selection locators are incomplete: {element.id}"
            )
        deadline = monotonic() + timeout
        first_attempt = True
        while first_attempt or monotonic() < deadline:
            first_attempt = False
            remaining = max(0.0, deadline - monotonic())
            lookup_timeout = min(0.2, max(0.01, remaining))
            try:
                scope = self._scope(element, timeout=lookup_timeout)
            except _RETRYABLE_LOOKUP_ERRORS:
                if monotonic() < deadline:
                    sleep(min(0.05, max(0.0, deadline - monotonic())))
                continue
            except ElementLookupError:
                raise
            self._guard_scope_origin(scope, context_guard)
            try:
                options = scope.eles(option_locator.value, timeout=lookup_timeout)
                if not options:
                    sleep(min(0.05, remaining))
                    continue
                selected_options = scope.eles(
                    selected_locator.value,
                    timeout=lookup_timeout,
                )
                values: list[str] = []
                for selected in selected_options:
                    text = selected.text
                    if not isinstance(text, str) or not text.strip():
                        raise ElementActionError(
                            f"custom select returned an invalid selected option: {element.id}"
                        )
                    values.append(text.strip())
                return tuple(values)
            except _RETRYABLE_LOOKUP_ERRORS:
                pass
            except ElementActionError:
                raise
            except ElementLookupError:
                raise
            except Exception as error:
                raise ElementActionError(
                    f"custom select selected-option lookup failed: {element.id}"
                ) from error
            finally:
                self._guard_scope_origin(scope, context_guard)
            if monotonic() < deadline:
                sleep(min(0.05, max(0.0, deadline - monotonic())))
        raise ElementActionError(
            f"custom select options did not become observable: {element.id}"
        )

    def _wait_for_custom_selection_change(
        self,
        element: ElementSpec,
        *,
        previous: tuple[str, ...],
        deadline: float,
        context_guard: BrowserContextGuard | None,
    ) -> None:
        while monotonic() < deadline:
            current = self._selected_custom_option_values(
                element,
                timeout=min(0.2, max(0.01, deadline - monotonic())),
                context_guard=context_guard,
            )
            if current != previous:
                return
            sleep(min(0.05, max(0.0, deadline - monotonic())))
        raise ElementActionError(
            f"custom select state did not change after option click: {element.id}"
        )

    def _dismiss_custom_select(
        self,
        element: ElementSpec,
        *,
        context_guard: BrowserContextGuard | None,
    ) -> None:
        popup_locator = element.popup_locator
        dismiss_locator = element.dismiss_locator
        if popup_locator is None or dismiss_locator is None:
            raise ElementActionError(
                f"custom select dismiss locators are incomplete: {element.id}"
            )
        deadline = monotonic() + self.action_timeout
        dismiss_target = None
        dismiss_scope = None
        while monotonic() < deadline:
            remaining = deadline - monotonic()
            lookup_timeout = min(0.2, max(0.01, remaining))
            try:
                scope = self._scope(element, timeout=lookup_timeout)
            except _RETRYABLE_LOOKUP_ERRORS:
                sleep(min(0.05, max(0.0, deadline - monotonic())))
                continue
            except ElementLookupError:
                raise
            self._guard_scope_origin(scope, context_guard)
            try:
                if not self._visible_popup_exists(
                    scope,
                    popup_locator.value,
                    timeout=lookup_timeout,
                ):
                    return
                dismiss_target = scope.ele(
                    dismiss_locator.value,
                    timeout=lookup_timeout,
                )
                if dismiss_target:
                    dismiss_scope = scope
                    break
            except _RETRYABLE_LOOKUP_ERRORS:
                pass
            except ElementLookupError:
                raise
            except Exception as error:
                raise ElementActionError(
                    f"custom select dismiss target lookup failed: {element.id}"
                ) from error
            finally:
                self._guard_scope_origin(scope, context_guard)
            sleep(min(0.05, max(0.0, deadline - monotonic())))
        if dismiss_target is None or dismiss_scope is None:
            raise ElementActionError(
                f"custom select dismiss target was not found: {element.id}"
            )
        self._guard_scope_origin(dismiss_scope, context_guard)
        try:
            if not dismiss_target.wait.clickable(
                wait_moved=True,
                timeout=max(0.01, deadline - monotonic()),
                raise_err=False,
            ):
                raise ElementActionError(
                    f"custom select dismiss target is not clickable: {element.id}"
                )
            self._guard_scope_origin(dismiss_scope, context_guard)
            dismiss_target.click(by_js=False)
        except ElementActionError:
            raise
        except Exception as error:
            raise ElementActionError(
                f"custom select could not be dismissed safely: {element.id}"
            ) from error
        finally:
            self._guard_scope_origin(dismiss_scope, context_guard)

        # Never issue a second click after the dismiss action. Only re-query
        # the popup until it is observably hidden or the bounded wait expires.
        while monotonic() < deadline:
            remaining = deadline - monotonic()
            lookup_timeout = min(0.2, max(0.01, remaining))
            try:
                scope = self._scope(element, timeout=lookup_timeout)
            except _RETRYABLE_LOOKUP_ERRORS:
                sleep(min(0.05, max(0.0, deadline - monotonic())))
                continue
            except ElementLookupError:
                raise
            self._guard_scope_origin(scope, context_guard)
            try:
                if not self._visible_popup_exists(
                    scope,
                    popup_locator.value,
                    timeout=lookup_timeout,
                ):
                    return
            except _RETRYABLE_LOOKUP_ERRORS:
                pass
            except ElementLookupError:
                raise
            except Exception as error:
                raise ElementActionError(
                    f"custom select popup verification failed: {element.id}"
                ) from error
            finally:
                self._guard_scope_origin(scope, context_guard)
            sleep(min(0.05, max(0.0, deadline - monotonic())))
        raise ElementActionError(
            f"custom select popup remained visible after dismissal: {element.id}"
        )

    @staticmethod
    def _visible_popup_exists(scope: Any, locator: str, *, timeout: float) -> bool:
        for popup in scope.eles(locator, timeout=timeout):
            try:
                if popup.states.is_displayed:
                    return True
            except _TRANSIENT_LOOKUP_ERRORS:
                raise
            except Exception:
                # A disappearing popup is re-queried by the caller rather
                # than treated as proof of visibility.
                continue
        return False

    def _artifact_directory(self, name: str) -> Path:
        if self.run_dir.is_symlink():
            raise ElementActionError("run_dir became a symbolic link")
        self.run_dir.mkdir(parents=True, exist_ok=True)
        target = self.run_dir / name
        if target.is_symlink():
            raise ElementActionError(f"artifact directory is a symbolic link: {name}")
        target.mkdir(parents=False, exist_ok=True)
        if not _is_within(target, self.run_dir):
            raise ElementActionError("artifact directory escaped run_dir")
        return target


def _reveal(value: SecretLike) -> str:
    revealed = value.reveal() if isinstance(value, SecretValue) else value
    if not isinstance(revealed, str) or not revealed:
        raise ElementActionError("browser input/select value must not be empty")
    return revealed


def _validate_filename(filename: str) -> None:
    if not _SAFE_FILENAME_PATTERN.fullmatch(filename) or Path(filename).name != filename:
        raise DownloadError("artifact filename must be one safe basename")


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
    except (OSError, ValueError):
        return False
    return True


__all__ = ["DrissionBrowserActions"]
