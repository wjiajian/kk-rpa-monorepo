"""DrissionPage-backed implementation of the public browser action contract.

The adapter deliberately accepts an already managed Chromium tab. Browser
process creation, profile locking, debug-port leasing, and lifecycle policy
belong to the future BrowserManager and must not leak into business apps.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from time import monotonic, sleep
from typing import Any
from uuid import uuid4

from DrissionPage.common import Keys
from DrissionPage.errors import ContextLostError, ElementLostError, GetDocumentError

from .browser import (
    ArtifactRef,
    DownloadError,
    DownloadRef,
    ElementActionError,
    ElementLookupError,
    ElementSpec,
    NavigationError,
    SecretLike,
    SecretValue,
    Locator,
    ScopeLocator,
)

_SAFE_FILENAME_PATTERN = re.compile("^[A-Za-z0-9][A-Za-z0-9._-]{0,254}$")
_TRANSIENT_LOOKUP_ERRORS = (ContextLostError, ElementLostError, GetDocumentError)


class _TransientScopeUnavailable(RuntimeError):
    """An iframe is temporarily absent while its context is refreshing."""


_RETRYABLE_LOOKUP_ERRORS = _TRANSIENT_LOOKUP_ERRORS + (_TransientScopeUnavailable,)


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
    download_dir: Path | None = None
    _live: dict = field(default_factory=dict, init=False, repr=False)
    _aliases: dict = field(default_factory=dict, init=False, repr=False)
    _serial: int = field(default=0, init=False)
    _reference_session: str = field(default_factory=lambda: uuid4().hex[:12], init=False)

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

    def open(self, url: str, *, wait: str = "document") -> None:
        if not isinstance(url, str) or not url.strip():
            raise NavigationError("browser URL must not be empty")
        if wait not in {"none", "document", "complete"}:
            raise NavigationError(f"unsupported navigation wait policy: {wait!r}")
        try:
            loaded = self.tab.get(url)
            if loaded is False:
                raise NavigationError("browser navigation returned false")
            if wait != "none" and (
                not self.tab.wait.doc_loaded(
                    timeout=self.action_timeout, raise_err=False
                )
            ):
                raise NavigationError("document did not finish loading before timeout")
        except NavigationError:
            raise
        except Exception as error:
            raise NavigationError("browser navigation failed") from error

    def exists(self, element: ElementSpec, *, timeout: float = 0.0) -> bool:
        if timeout < 0:
            raise ValueError("timeout must be non-negative")
        return self._locate(element, timeout=timeout, required=False) is not None

    def count(self, element: ElementSpec, *, timeout: float = 0.0) -> int:
        """Return how many nodes the element's locator currently matches.

        An absent target is ``0``, not an error: an empty result set is a
        legitimate page state that a step must be able to assert on.
        """
        return len(self._match_all(element, timeout))

    def texts(self, element: ElementSpec, *, timeout: float = 0.0) -> list[str]:
        """Return the visible text of every current match, possibly empty."""
        matches = self._match_all(element, timeout)
        values: list[str] = []
        for node in matches:
            try:
                raw = (
                    node.attr("value")
                    if str(node.tag).lower() == "input"
                    else node.text
                )
            except Exception as error:
                raise ElementActionError(
                    f"element text read failed: {element.id}"
                ) from error
            values.append(raw if isinstance(raw, str) else "")
        return values

    def _match_all(self, element: ElementSpec, timeout: float) -> list[Any]:
        if timeout < 0:
            raise ValueError("timeout must be non-negative")
        locator = element.require_locator()
        lookup_timeout = timeout if timeout > 0 else self.action_timeout
        deadline = monotonic() + lookup_timeout
        first_attempt = True
        while True:
            remaining = max(0.0, deadline - monotonic())
            attempt_timeout = lookup_timeout if first_attempt else min(0.5, remaining)
            try:
                scope = self._scope(element, timeout=attempt_timeout)
                matches = scope.eles(locator.value, timeout=attempt_timeout)
                return list(matches) if matches else []
            except _RETRYABLE_LOOKUP_ERRORS:
                if not first_attempt and monotonic() >= deadline:
                    raise
                first_attempt = False
                sleep(min(0.05, max(0.0, deadline - monotonic())))
            except Exception as error:
                raise ElementLookupError(
                    f"element multi-match lookup failed: {element.id}"
                ) from error

    def click(self, element: ElementSpec) -> None:
        located = self._find(element)
        target = located.target
        try:
            if not target.wait.clickable(
                wait_moved=True, timeout=self.action_timeout, raise_err=False
            ):
                raise ElementActionError(f"element is not clickable: {element.id}")
            self._click_target(target, timeout=self.action_timeout)
        except ElementActionError:
            raise
        except Exception as error:
            raise ElementActionError(f"element click failed: {element.id}") from error

    def click_and_switch_to_new_tab(
        self, element: ElementSpec, *, timeout: float | None = None
    ) -> None:
        """Click an element, wait for one new tab, and bind later calls to it."""
        wait_timeout = self.action_timeout if timeout is None else timeout
        if wait_timeout <= 0:
            raise ValueError("new-tab timeout must be positive")
        source_tab = self.tab
        browser = getattr(source_tab, "browser", None)
        if browser is None:
            raise NavigationError("current tab does not expose its browser")
        try:
            previous_tab_ids = {str(item) for item in browser.tab_ids}
        except Exception:
            previous_tab_ids = set()
        self.click(element)
        try:
            tab_id = browser.wait.new_tab(
                timeout=min(1.0, wait_timeout), curr_tab=source_tab, raise_err=False
            )
            target_tab = None
            signalled_tab_id = str(tab_id) if tab_id else None
            if signalled_tab_id and signalled_tab_id not in previous_tab_ids:
                try:
                    target_tab = browser.get_tab(signalled_tab_id)
                except Exception:
                    target_tab = None
            deadline = monotonic() + wait_timeout
            while not target_tab and previous_tab_ids and (monotonic() < deadline):
                try:
                    new_ids = [
                        str(item)
                        for item in browser.tab_ids
                        if str(item) not in previous_tab_ids
                    ]
                except Exception:
                    break
                if len(new_ids) == 1:
                    try:
                        target_tab = browser.get_tab(new_ids[0])
                    except Exception:
                        target_tab = None
                if not target_tab:
                    sleep(min(0.05, max(0.0, deadline - monotonic())))
            if not target_tab:
                if not signalled_tab_id or signalled_tab_id in previous_tab_ids:
                    raise NavigationError("click did not open a new tab before timeout")
                raise NavigationError("new browser tab is unavailable")
            self.tab = target_tab
            if not target_tab.wait.doc_loaded(timeout=wait_timeout, raise_err=False):
                raise NavigationError("new tab did not finish loading before timeout")
        except NavigationError:
            raise
        except Exception as error:
            raise NavigationError("new browser tab switch failed") from error

    def input(self, element: ElementSpec, value: SecretLike) -> None:
        located = self._find(element)
        target = located.target
        revealed = _reveal(value)
        try:
            self._input_value(target, revealed, element, scope=located.scope)
        except ElementActionError:
            raise
        except Exception as error:
            raise ElementActionError(f"element input failed: {element.id}") from error

    def text(self, element: ElementSpec) -> str:
        located = self._find(element)
        target = located.target
        try:
            value = (
                target.attr("value")
                if str(target.tag).lower() == "input"
                else target.text
            )
            if value is None:
                return ""
            if not isinstance(value, str):
                raise ElementActionError(f"element text is not a string: {element.id}")
            return value
        except ElementActionError:
            raise
        except Exception as error:
            raise ElementActionError(
                f"element text read failed: {element.id}"
            ) from error

    def select(self, element: ElementSpec, value: SecretLike) -> None:
        located = self._find(element)
        target = located.target
        revealed = _reveal(value)
        try:
            tag = str(target.tag).lower()
            if tag == "select":
                target.select.by_text(revealed, timeout=self.action_timeout)
            elif tag == "input":
                if not target.wait.clickable(
                    wait_moved=True, timeout=self.action_timeout, raise_err=False
                ):
                    raise ElementActionError(
                        f"custom select trigger is not clickable: {element.id}"
                    )
                target.click(by_js=False)
                self._input_value(target, revealed, element, scope=located.scope)
                if element.option_locator is None:
                    target.input(Keys.ENTER, clear=False, by_js=False)
                elif element.selected_option_locator is not None:
                    self._ensure_exact_custom_selection(element, revealed)
                else:
                    self._click_exact_option(element, revealed)
            else:
                raise ElementActionError(
                    f"unsupported select element tag for {element.id}: {tag!r}"
                )
        except ElementActionError:
            raise
        except Exception as error:
            raise ElementActionError(f"element select failed: {element.id}") from error

    def download(
        self, element: ElementSpec, *, filename: str | None = None
    ) -> DownloadRef:
        if filename is not None:
            _validate_filename(filename)
        located = self._find(element)
        target = located.target
        download_dir = self.download_dir or self._artifact_directory("downloads")
        download_dir = Path(download_dir)
        download_dir.mkdir(parents=True, exist_ok=True)
        started = monotonic()
        try:
            self.tab.set.when_download_file_exists("rename")
            mission = target.click.to_download(
                str(download_dir),
                rename=filename,
                by_js=False,
                timeout=self.download_timeout,
            )
            if not mission:
                raise DownloadError("download did not start")
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
                raise DownloadError(
                    "download escaped the configured download directory"
                )
            return DownloadRef.from_path(final_path)
        except DownloadError:
            raise
        except Exception as error:
            raise DownloadError(f"download action failed: {element.id}") from error

    def screenshot(
        self, *, name: str | None = None, full_page: bool = False
    ) -> ArtifactRef:
        target_name = name or "browser-evidence.png"
        _validate_filename(target_name)
        evidence_dir = self._artifact_directory("evidence")
        try:
            result = self.tab.get_screenshot(
                path=str(evidence_dir), name=target_name, full_page=full_page
            )
            target = Path(result) if result else evidence_dir / target_name
            if not _is_within(target, evidence_dir):
                raise ElementActionError(
                    "screenshot escaped the run evidence directory"
                )
            return ArtifactRef.from_path(target)
        except ElementActionError:
            raise
        except Exception as error:
            raise ElementActionError("browser screenshot failed") from error

    def recovery_capabilities(self) -> dict:
        return {"protocol": 2, "features": ["live_refs", "query", "observe_fields", "act_expect_read", "scope_path"],
                "drissionpage": "4.1.1.4"}

    def release_recovery(self) -> None:
        self._live.clear()
        self._aliases.clear()

    @staticmethod
    def _object_key(node):
        owner = getattr(node, "owner", None)
        owner_id = getattr(owner, "_frame_id", None) or getattr(owner, "tab_id", None) or id(owner)
        return (getattr(node, "_type", type(node).__name__), owner_id,
                getattr(node, "_backend_id", id(node)))

    @staticmethod
    def _identity(node):
        # Exclude value, checked, class and other state changed by normal actions.
        tag = getattr(node, "tag", "")
        attrs = getattr(node, "attrs", {})
        stable = {key: value for key, value in attrs.items()
                  if key in {"id", "name", "type", "role", "aria-label", "href", "src"}
                  or key.startswith("data-")}
        text = "" if tag in {"input", "textarea", "select", "iframe", "frame"} else str(node.property("innerText") or "")
        return {"tag": tag, "attributes": stable, "text": text}

    def _document_key(self):
        # doc_ele belongs to ChromiumFrame, not ChromiumTab. Resolve the current
        # document element through the public tab API; its backend ID changes
        # when the document is replaced, including reloads at the same URL.
        root = self.tab.ele("xpath:/html", timeout=0)
        if not root:
            raise ElementLookupError("document root unavailable; query again")
        return (id(self.tab), self._object_key(root))

    def _remember(self, node, scope="page", *, kind="element", path=None):
        if getattr(node, "_type", "") == "ChromiumFrame":
            kind = "frame"
            if path is None:
                parent_path = [] if scope == "page" else self._live[scope]["path"]
                if parent_path is not None:
                    path = [*parent_path, {"kind": "frame", "locator": "xpath:" + node.xpath}]
        identity = self._identity(node) if kind != "shadow" else {"tag": "shadow-root"}
        document = self._document_key()
        key = self._object_key(node)
        for ref, record in self._live.items():
            if (record["key"], record["scope"], record["identity"], record["document"], record["scope_document"]) == (key, scope, identity, document, self._object_key(node.doc_ele) if kind == "frame" else None):
                return ref
        self._serial += 1
        ref = f"@{self._reference_session}:{self._serial}"
        self._live[ref] = {"node": node, "scope": scope, "kind": kind,
                           "path": path, "identity": identity, "document": document, "key": key,
                           "scope_document": self._object_key(node.doc_ele) if kind == "frame" else None}
        return ref

    def _live_record(self, ref, elements):
        if ref in self._aliases:
            ref = self._aliases[ref]
        if ref not in self._live:
            if ref not in elements:
                raise ElementLookupError("unknown reference; use query, not a locator in target")
            spec = elements[ref]
            scope = self._recovery_scope(spec)
            scope_ref = self._scope_ref(scope, spec)
            matches = list(scope.eles(spec.require_locator().value, timeout=0))
            if len(matches) != 1:
                raise ElementLookupError(f"formal target requires one match; found {len(matches)}; use query")
            resolved = self._remember(matches[0], scope_ref)
            self._aliases[ref] = resolved
            ref = resolved
        record = self._live[ref]
        if record["document"] != self._document_key():
            raise ElementLookupError("stale_reference: document changed; query again")
        if record["scope"] != "page":
            self._live_record(record["scope"], elements)
        node = record["node"]
        if not node.states.is_alive:
            raise ElementLookupError("stale_reference: element detached; query again")
        if record["kind"] == "frame" and record["scope_document"] != self._object_key(node.doc_ele):
            raise ElementLookupError("stale_reference: frame document changed; query again")
        if record["kind"] != "shadow" and self._identity(node) != record["identity"]:
            raise ElementLookupError("target_changed: live node represents different content; query again")
        return ref, record

    def _recovery_scope(self, spec):
        parts = spec.scope_path or ((ScopeLocator("frame", spec.frame_locator),) if spec.frame_locator else ())
        scope = self.tab
        for part in parts:
            matches = list(scope.eles(part.locator.value, timeout=0))
            if len(matches) != 1:
                raise ElementLookupError(f"scope requires exactly one match; found {len(matches)}")
            scope = scope.get_frame(part.locator.value, timeout=0) if part.kind == "frame" else matches[0].shadow_root
            if not scope:
                raise ElementLookupError("scope unavailable")
        return scope

    def _scope_ref(self, scope, spec=None):
        if scope is self.tab:
            return "page"
        # Preserve the complete reproducible path when resolving a formal ID.
        path = None
        if spec:
            path = [{"kind": part.kind, "locator": part.locator.value} for part in spec.scope_path]
            if spec.frame_locator:
                path = [{"kind": "frame", "locator": spec.frame_locator.value}]
        parent = getattr(scope, "_target_page", None)
        parent_ref = self._scope_ref(parent) if parent is not None and parent is not self.tab else "page"
        return self._remember(scope, parent_ref, kind="shadow" if getattr(scope, "_type", "") == "ShadowRoot" else "frame", path=path)

    def _query_scope(self, ref, elements):
        if not ref or ref == "page":
            return self.tab, "page"
        resolved, record = self._live_record(ref, elements)
        return record["node"], resolved

    def recovery_query(self, params, elements) -> dict:
        started = monotonic()
        limit, offset = params.get("limit", 50), params.get("offset", 0)
        if not isinstance(limit, int) or not 1 <= limit <= 500 or not isinstance(offset, int) or offset < 0:
            raise ValueError("invalid query pagination")
        root, scope = self._query_scope(params.get("scope"), elements)
        relation = params.get("relation", "descendants")
        locator = params.get("locator", "")
        if not isinstance(locator, str):
            raise ValueError("query locator must be a string")
        locator = locator.strip()
        # The SDK treats bare XPath strings as text selectors.
        if locator.startswith(("/", "./", "../")):
            locator = "xpath:" + locator
        if relation == "document":
            if scope != "page" and self._live[scope]["kind"] == "element":
                scope = self._live[scope]["scope"]
            if not locator:
                # Navigation is not a DOM search and says nothing about matches.
                return {"scope": scope, "queried": False}
            root, scope = self._query_scope(scope, elements)
            relation = "descendants"
        kind, path = "element", None
        if relation in {"frame", "shadow"}:
            if scope == "page":
                raise ValueError("frame/shadow requires a queried host reference")
            record = self._live[scope]
            parent = record["scope"]
            parent_path = [] if parent == "page" else self._live[parent]["path"]
            host_locator = "xpath:" + root.xpath if relation == "frame" else "css:" + root.css_path
            path = [*parent_path, {"kind": relation, "locator": host_locator}] if parent_path is not None else None
            node = root if relation == "frame" and getattr(root, "_type", "") == "ChromiumFrame" else (
                self._query_scope(parent, elements)[0].get_frame(host_locator, timeout=0) if relation == "frame" else root.shadow_root)
            nodes, kind, scope = ([node] if node else []), relation, parent
            if locator:
                if not node:
                    raise ElementLookupError("requested frame/shadow scope unavailable")
                scope_ref = self._remember(node, parent, kind=kind, path=path)
                return self.recovery_query({**params, "scope": scope_ref, "relation": "descendants"}, elements)
        elif relation == "descendants":
            if not isinstance(locator, str) or not locator.strip():
                raise ValueError("query requires a locator")
            nodes = list(root.eles(locator, timeout=0))
            if scope != "page" and self._live[scope]["kind"] == "element":
                scope = self._live[scope]["scope"]
        elif relation in {"children", "next", "prev", "parent", "over", "offset"}:
            if scope == "page":
                raise ValueError("relative query requires an element reference")
            if relation == "parent":
                node = root.parent(locator or 1, timeout=0)
                nodes = [node] if node else []
            elif relation == "over":
                node = self._covering_node(root)
                nodes = [node] if node else []
            elif relation == "offset":
                node = root.offset(locator or None, x=params.get("x"), y=params.get("y"), timeout=0)
                nodes = [node] if node else []
            else:
                nodes = list(getattr(root, {"next": "nexts", "prev": "prevs"}.get(relation, relation))(locator, timeout=0))
            scope = self._live[scope]["scope"]
        else:
            raise ValueError("unsupported query relation")
        queried = monotonic()
        result = []
        for node in nodes[offset:offset + limit]:
            owner = getattr(node, "owner", None)
            actual_scope = scope
            # SDK may return an element from a frame during a cross-layer search.
            if owner is not None and owner is not self.tab and getattr(owner, "_type", "") == "ChromiumFrame":
                actual_scope = self._scope_ref(owner)
            ref = self._remember(node, actual_scope, kind=kind, path=path)
            identity = self._live[ref]["identity"]
            result.append({"target": ref, "scope": actual_scope, "kind": kind, "tag": identity["tag"],
                           "text": identity.get("text", "")[:300], "text_truncated": len(identity.get("text", "")) > 300,
                           "attributes": identity.get("attributes", {})})
        return {"nodes": result, "scope": scope, "count": len(nodes), "offset": offset,
                "truncated": offset + limit < len(nodes), "next_offset": offset + limit if offset + limit < len(nodes) else None,
                "timings_ms": {"query": (queried - started) * 1000, "state": (monotonic() - queried) * 1000}}

    @staticmethod
    def _validate_fields(fields):
        allowed = {"tag", "value", "text", "attrs", "alive", "displayed", "enabled", "clickable", "checked", "covered", "rect"}
        if not isinstance(fields, list) or any(not isinstance(name, str) or
                (name not in allowed and not (name.startswith("attr:") and len(name) > 5)) for name in fields):
            raise ValueError("unsupported read fields")

    def _read_live(self, node, fields):
        self._validate_fields(fields)
        result = {}
        for name in fields:
            if name == "tag":
                result[name] = node.tag
            elif name == "value":
                result[name] = "<redacted>" if node.attr("type") == "password" else (node.value if node.tag in {"input", "textarea", "select", "option"} else None)
            elif name == "text":
                result[name] = str(node.property("innerText") or "")
            elif name == "attrs":
                result[name] = {k: v for k, v in node.attrs.items() if k != "value"}
            elif name == "covered":
                cover = self._covering_node(node)
                result[name] = cover._backend_id if cover else False
            elif name in {"alive", "displayed", "enabled", "clickable", "checked"}:
                result[name] = getattr(node.states, "is_" + name)
            elif name == "rect":
                result[name] = {"location": node.rect.location, "size": node.rect.size}
            elif name.startswith("attr:"):
                result[name] = "<redacted>" if name == "attr:value" else node.attr(name[5:])
            else:
                raise ValueError(f"unsupported read property: {name}")
        return result

    def recovery_observe(self, params, elements):
        started = monotonic()
        target = params.get("target")
        if not target or target == "page":
            result = self.recovery_query({"scope": params.get("scope", "page"),
                "locator": "css:button,a,input,textarea,select,option,[role],iframe,frame,label",
                "limit": params.get("limit", 50), "offset": params.get("offset", 0)}, elements)
            result["url"] = self.current_url
            return result
        ref, record = self._live_record(target, elements)
        if record["kind"] in {"frame", "shadow"} and "fields" not in params:
            result = self.recovery_query({"scope": ref, "locator": "css:button,a,input,textarea,select,option,[role],iframe,frame,label",
                "limit": params.get("limit", 50), "offset": params.get("offset", 0)}, elements)
            return {**result, "target": ref, "kind": record["kind"]}
        result = {"target": ref, "scope": record["scope"], "kind": record["kind"],
                  **self._read_live(record["node"], params.get("fields", ["value", "text", "displayed", "enabled"]))}
        if params.get("include_locators"):
            scope_path = [] if record["scope"] == "page" else self._live[record["scope"]]["path"]
            if scope_path is None:
                raise ElementLookupError("scope path unavailable; query each frame/shadow host before exporting")
            result["locator"] = "css:" + record["node"].css_path
            result["scope_path"] = scope_path
        result["timings_ms"] = {"state": (monotonic() - started) * 1000}
        return result

    def validate_recovery_overrides(self, elements, overrides):
        from .elements import override_element_locators
        replaced = override_element_locators(elements, overrides)
        for element_id, changes in overrides.items():
            spec = replaced[element_id]
            scope = self._recovery_scope(spec)
            for field_name, expression in changes.items():
                if field_name in {"frame", "scope_path"} or expression is None:
                    continue
                matches = list(scope.eles(expression, timeout=0))
                if len(matches) != 1:
                    raise ElementLookupError("override requires exactly one current match")
                candidates = [ref for ref, rec in self._live.items() if rec["key"] == self._object_key(matches[0])
                    and rec["identity"] == self._identity(matches[0]) and rec["document"] == self._document_key()]
                if not candidates:
                    raise ElementLookupError("locator override lacks actual DOM evidence")
                valid = False
                for ref in candidates:
                    try:
                        self._live_record(ref, elements)
                        valid = True
                        break
                    except ElementLookupError:
                        continue
                if not valid:
                    raise ElementLookupError("override target changed")
            # Scope-only overrides must also identify an observed live target.
            matches = list(scope.eles(spec.require_locator().value, timeout=0))
            if len(matches) != 1 or not any(rec["key"] == self._object_key(matches[0]) and
                    rec["identity"] == self._identity(matches[0]) and rec["document"] == self._document_key()
                    for rec in self._live.values()):
                raise ElementLookupError("override scope/target lacks current unique DOM evidence")
        return replaced

    def recovery_act(self, params, elements, check=lambda: None):
        started = monotonic()
        deadline = started + min(15, max(0.1, float(params.get("seconds", self.action_timeout))))
        operation = params["operation"]
        expected = params.get("expect")
        target = params.get("target")
        result = {"issued": False, "condition_met": None, "phase": "precondition", "operation": operation}
        node = None
        def remaining():
            check()
            return max(0, deadline - monotonic())
        def poll(predicate):
            while True:
                remaining()
                value = predicate()
                if value or remaining() <= 0:
                    return bool(value)
                sleep(min(0.05, remaining()))
        try:
            check()
            self._validate_fields(params.get("read", []))
            if operation in {"input", "select", "key"} and not isinstance(params.get("value"), (str, SecretValue)):
                raise ValueError("operation requires value")
            if expected:
                prop = expected.get("property")
                if prop not in {"exists", "url_changed", "new_tab"}:
                    self._validate_fields([prop])
                if expected.get("query") is not None and (not isinstance(expected["query"], str) or not expected["query"].strip()):
                    raise ValueError("expect query must be a non-empty locator")
                if prop not in {"url_changed", "new_tab"} and not (expected.get("target") or expected.get("query") or target):
                    raise ValueError("expect requires target or query")
            if target:
                ref, record = self._live_record(target, elements)
                node = record["node"]
                result.update(target=ref, scope=record["scope"])
            elif operation != "wait":
                raise ValueError("operation requires a reference")
            if operation not in {"read", "wait"}:
                if not poll(lambda: node.states.is_clickable):
                    raise ElementActionError("not_clickable")
                if not poll(lambda: node.wait.stop_moving(timeout=min(0.15, remaining()), gap=0.05, raise_err=False)):
                    raise ElementActionError("still_moving")
                node.scroll.to_see()
                cover = self._covering_node(node)
                if cover:
                    result["cover"] = self._remember(cover, record["scope"]) if cover else None
                    raise ElementActionError("covered")
                self._live_record(target, elements)
            before_tabs = set(self.tab.browser.tab_ids) if operation == "new_tab" or (expected and expected.get("property") == "new_tab") else set()
            before_url = self.current_url
            result["phase"] = "action"
            if operation in {"click", "new_tab"}:
                result["issued"] = True
                result["method"] = "js" if params.get("by_js", False) else "simulated"
                if self._click_target(node, timeout=remaining(), by_js=params.get("by_js", False)) is False:
                    raise ElementActionError("click_returned_false")
            elif operation == "input":
                result["issued"] = True
                # Same input primitive as the formal BrowserActions path.
                self._enter_value(node, _reveal(params["value"]))
            elif operation == "select":
                if node.tag != "select":
                    raise ElementActionError("native select required; custom controls use query/click/input")
                result["issued"] = True
                if node.select.by_text(params["value"], timeout=remaining()) is False:
                    raise ElementActionError("option_not_found")
            elif operation == "check":
                result["issued"] = True
                node.check(uncheck=not params.get("checked", True), by_js=False)
            elif operation == "hover":
                result["issued"] = True
                node.hover()
            elif operation == "scroll":
                direction = params.get("direction", "down")
                if direction not in {"up", "down", "left", "right"}:
                    raise ValueError("unsupported scroll direction")
                result["issued"] = True
                getattr(node.scroll, direction)(int(params.get("pixels", 300)))
            elif operation == "key":
                key = params.get("value")
                if key not in {"ENTER", "TAB", "ESC", "UP", "DOWN", "LEFT", "RIGHT", "BACKSPACE", "DELETE", "HOME", "END"}:
                    raise ValueError("unsupported key")
                result["issued"] = True
                node.input(getattr(Keys, key), clear=False, by_js=False)
            elif operation == "download":
                filename = params.get("filename")
                if filename:
                    _validate_filename(filename)
                folder = Path(self.download_dir or self._artifact_directory("downloads"))
                folder.mkdir(parents=True, exist_ok=True)
                self.tab.set.when_download_file_exists("rename")
                # Arm the pinned SDK download manager before clicking. Its public
                # to_download() waits without a cancellation hook; polling the
                # same mission flag keeps all browser work on this Worker thread.
                self.tab.set.download_path(str(folder))
                self.tab.set.download_file_name(filename)
                manager = self.tab.browser._dl_mgr
                tab_id = self.tab.tab_id
                manager.set_flag(tab_id, True)
                mission = None
                try:
                    result["issued"] = True
                    if self._click_target(node, timeout=remaining()) is False:
                        raise DownloadError("download_click_returned_false")
                    result["phase"] = "wait"
                    if not poll(lambda: not isinstance(manager.get_flag(tab_id), (bool, type(None)))):
                        raise DownloadError("download_begin_timeout; click may already have taken effect")
                    mission = manager.get_flag(tab_id)
                finally:
                    pending_mission = manager.get_flag(tab_id)
                    manager.set_flag(tab_id, None)
                    if mission is None:
                        if not isinstance(pending_mission, (bool, type(None))) and not pending_mission.is_done:
                            pending_mission.cancel()
                        self.tab.set.download_file_name(None)
                try:
                    result["phase"] = "wait"
                    if not poll(lambda: mission.is_done):
                        raise DownloadError("download_timeout")
                    if mission.state != "completed" or not mission.final_path or not _is_within(Path(mission.final_path), folder):
                        raise DownloadError("download_not_completed")
                    result["download"] = DownloadRef.from_path(mission.final_path).to_dict()
                finally:
                    if not mission.is_done:
                        mission.cancel()
            elif operation not in {"read", "wait"}:
                raise ValueError("unsupported browser operation")
            result["phase"] = "wait"
            if operation == "new_tab" and not expected:
                expected = {"property": "new_tab"}
            if expected:
                prop = expected["property"]
                def condition():
                    if prop == "new_tab":
                        actual = [item for item in self.tab.browser.tab_ids if item not in before_tabs]
                        result["actual"] = actual
                        if len(actual) == 1:
                            self.tab = self.tab.browser.get_tab(actual[0])
                            self.release_recovery()
                            return True
                        return False
                    if prop == "url_changed":
                        result["actual"] = self.current_url
                        return self.current_url != before_url
                    other = expected.get("target", target)
                    if expected.get("query"):
                        found = self.recovery_query({"scope": expected.get("scope", "page"), "locator": expected["query"], "limit": 1}, elements)
                        result["match_count"] = found["count"]
                        if prop == "exists":
                            result["actual"] = found["count"] > 0
                            return result["actual"] == expected.get("equals", True)
                        if found["count"] != 1:
                            result["actual"] = None
                            return False
                        other = found["nodes"][0]["target"]
                    try:
                        _, rec = self._live_record(other, elements)
                        result["actual"] = True if prop == "exists" else self._read_live(rec["node"], [prop])[prop]
                    except ElementLookupError as error:
                        if prop != "exists" or "detached" not in str(error):
                            raise
                        result["actual"] = False
                    return result["actual"] == expected.get("equals", True)
                result["condition_met"] = poll(condition)
                if not result["condition_met"]:
                    result["error"] = "condition_timeout"
                    if node is not None and params.get("read"):
                        result["state"] = self._read_live(node, params["read"])
                    return result
            elif operation == "wait":
                poll(lambda: False)
                result["waited_seconds"] = monotonic() - started
            result["phase"] = "read"
            if target and operation != "new_tab" and not (expected and expected.get("property") == "new_tab"):
                _, rec = self._live_record(target, elements)
                result["state"] = self._read_live(rec["node"], params.get("read", ["value", "text", "displayed", "enabled"]))
            result["phase"] = "complete"
        except Exception as error:
            check()  # Cancellation propagates; never turn it into a successful fact.
            result["effect_uncertain"] = result["issued"] and result["phase"] == "action"
            result["error"] = str(error)
            result["error_type"] = type(error).__name__
        finally:
            result["timings_ms"] = {"action_total": (monotonic() - started) * 1000}
        return result

    @staticmethod
    def _covering_node(target):
        if not target.states.is_covered:
            return None
        cover = target.over(timeout=0)
        # The SDK compares backend IDs: a button's own span/SVG therefore
        # counts as a cover. Descendants receive the same bubbling click.
        if cover and not target.run_js("return this.contains(arguments[0]);", cover):
            return cover
        return None

    @staticmethod
    def _click_target(target, *, timeout, by_js=False):
        target.scroll.to_see()
        if DrissionBrowserActions._covering_node(target):
            raise ElementActionError("covered")
        if target.click(by_js=by_js, timeout=timeout, wait_stop=False) is False:
            raise ElementActionError("click_returned_false")
        return True

    @staticmethod
    def _enter_value(target, value):
        target.clear(by_js=True)
        target.focus()
        target.input(value, clear=False, by_js=False)

    def observe_dom(self, element: ElementSpec | None = None, *, limit: int = 200) -> dict:
        """Bounded visible DOM evidence. No HTML, script execution or input values.

        xpath is obtained from the actual node, not generated by the model.
        A scoped observation uses the existing iframe/lookup stability handling.
        """
        if not 1 <= limit <= 500:
            raise ValueError("DOM observation limit must be between 1 and 500")
        root = self._find(element).target if element else self.tab
        nodes = root.eles("css:button,a,input,textarea,select,option,[role],iframe,label,[id],[class]", timeout=self.action_timeout)
        if element is not None and getattr(root, "tag", None) not in {"iframe", "frame"}:
            nodes = [root, *nodes]
        # SVG definitions may report displayed=True; they are not controls.
        decorative = {"symbol", "defs", "svg", "path", "use", "g", "style", "script"}
        controls = {"button", "a", "input", "textarea", "select", "option", "label"}
        nodes = [node for node in nodes if node.tag not in decorative]
        nodes.sort(key=lambda node: 0 if node.tag in {"iframe", "frame"} else
                   1 if node.tag in controls or node.attr("role") else 2)
        items, frames = [], []
        skipped = 0
        truncated = False
        for node in nodes:
            if not node.states.is_displayed:
                continue
            tag = node.tag
            if len(items) >= limit and tag not in {"iframe", "frame"}:
                truncated = True
                break
            xpath = node.xpath
            if not isinstance(xpath, str) or not xpath:
                # A detached node can lose its path between lookup and reading.
                # It cannot be offered as an actionable target.
                skipped += 1
                continue
            attributes = {key: node.attr(key) for key in ("id", "class", "name", "type", "role", "aria-label", "title", "placeholder")}
            tag = node.tag
            # ChromiumFrame exposes the frame element, not an element.text API.
            # Its document is observed separately using frame_target.
            text = "" if tag in {"input", "textarea", "iframe", "frame"} else str(node.property("innerText") or "")[:500]
            item = {"tag": tag, "text": text,
                          "attributes": attributes, "locator": "xpath:" + xpath,
                          "frame_locator": element.frame_locator.value if element and element.frame_locator else None}
            if tag in {"iframe", "frame"}:
                frames.append(item)
            if len(items) < limit:
                items.append(item)
            else:
                truncated = True
        body = root.ele("tag:body", timeout=0.2) if element is None or getattr(root, "tag", None) in {"iframe", "frame"} else root
        return {"url": self.current_url, "text": str(body.property("innerText") or "")[:16000] if body else "",
                "nodes": items, "frames": frames, "truncated": truncated, "skipped_nodes": skipped}

    def screenshot_redacted(self, *, name: str, sensitive_values: tuple[str, ...] = (), target_ref=None, elements=None) -> ArtifactRef:
        """Hide editable fields in all accessible frames before capturing evidence."""
        scopes, pending, seen = [], [self.tab], set()
        while pending:
            scope = pending.pop(0)
            key = getattr(scope, "_frame_id", None) or id(scope)
            if key in seen:
                continue
            seen.add(key)
            scopes.append(scope)
            # Capture existing documents; do not wait for hypothetical children
            # in every leaf frame (the SDK otherwise uses the base timeout).
            pending.extend(scope.get_frames(timeout=0))
        masked = []
        try:
            for scope in scopes:
                scope.run_js("""const values=Array.from(arguments);
                    const mask=(root)=>{
                        const walk=document.createTreeWalker(root,NodeFilter.SHOW_TEXT);
                        while(walk.nextNode()) {
                            const node=walk.currentNode;
                            if(values.some(v=>v && node.nodeValue.includes(v)))
                                node.parentElement?.setAttribute('data-rpa-secret-mask','true');
                        }
                        const s=document.createElement('style');
                        s.id='rpa-evidence-redaction';
                        s.textContent='input,textarea,[contenteditable=true],[data-rpa-secret-mask]'+(root instanceof ShadowRoot?',iframe,frame':'')+'{visibility:hidden!important}';
                        (root.head || root).appendChild(s);
                        root.querySelectorAll('*').forEach(e=>{if(e.shadowRoot) mask(e.shadowRoot)});
                    }; mask(document);""", *sensitive_values)
                masked.append(scope)
            if target_ref and target_ref != "page":
                _, record = self._live_record(target_ref, elements or {})
                target = record["node"]
                if record["kind"] == "shadow":
                    target = target.parent()
                _validate_filename(name)
                folder = self._artifact_directory("evidence")
                path = Path(target.get_screenshot(path=str(folder), name=name))
                if not _is_within(path, folder):
                    raise ElementActionError("screenshot escaped evidence directory")
                return ArtifactRef.from_path(path)
            return self.screenshot(name=name)
        finally:
            for scope in masked:
                scope.run_js("""const clean=(root)=>{
                    root.querySelector('#rpa-evidence-redaction')?.remove();
                    root.querySelectorAll('[data-rpa-secret-mask]').forEach(e=>e.removeAttribute('data-rpa-secret-mask'));
                    root.querySelectorAll('*').forEach(e=>{if(e.shadowRoot) clean(e.shadowRoot)});
                    }; clean(document);""")

    def _find(self, element: ElementSpec) -> _LocatedElement:
        located = self._locate(element, timeout=self.action_timeout, required=True)
        assert located is not None
        return located

    def _locate(
        self, element: ElementSpec, *, timeout: float, required: bool
    ) -> _LocatedElement | None:
        locator = element.require_locator().value
        deadline = monotonic() + timeout
        first_attempt = True
        while first_attempt or monotonic() < deadline:
            lookup_timeout = (
                timeout if first_attempt else min(0.5, max(0.0, deadline - monotonic()))
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
                target = scope.ele(locator, timeout=lookup_timeout)
                if target:
                    return _LocatedElement(scope=scope, target=target)
                break
            except _RETRYABLE_LOOKUP_ERRORS:
                pass
            except Exception as error:
                raise ElementLookupError(
                    f"element lookup failed: {element.id}"
                ) from error
            if timeout == 0 or monotonic() >= deadline:
                break
            sleep(min(0.05, max(0.0, deadline - monotonic())))
        if required:
            raise ElementLookupError(f"element was not found: {element.id}")
        return None

    def _scope(self, element: ElementSpec, *, timeout: float) -> Any:
        if element.scope_path:
            scope = self.tab
            deadline = monotonic() + timeout
            for part in element.scope_path:
                remaining = max(0, deadline - monotonic())
                if part.kind == "frame":
                    scope = scope.get_frame(part.locator.value, timeout=remaining)
                else:
                    host = scope.ele(part.locator.value, timeout=remaining)
                    scope = host.shadow_root if host else None
                if not scope:
                    raise _TransientScopeUnavailable(element.id)
            return scope
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

    def _input_value(
        self, target: Any, value: str, element: ElementSpec, *, scope: Any
    ) -> None:
        if not target.wait.clickable(
            wait_moved=False, timeout=self.action_timeout, raise_err=False
        ):
            raise ElementActionError(f"element is not ready for input: {element.id}")
        self._enter_value(target, value)

    def _click_exact_option(self, element: ElementSpec, value: str) -> None:
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
                        continue
            except _RETRYABLE_LOOKUP_ERRORS:
                continue
            except Exception as error:
                raise ElementActionError(
                    f"custom select option lookup failed: {element.id}"
                ) from error
            if len(matches) > 1:
                raise ElementActionError(
                    f"multiple exact custom select options are ready: {element.id}"
                )
            if len(matches) == 1:
                option = matches[0]
                if not option.wait.clickable(
                    wait_moved=True,
                    timeout=min(remaining, self.action_timeout),
                    raise_err=False,
                ):
                    raise ElementActionError(
                        f"exact custom select option is no longer clickable: {element.id}"
                    )
                option.click(by_js=False)
                return
            sleep(min(0.05, remaining))

    def _ensure_exact_custom_selection(self, element: ElementSpec, value: str) -> None:
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
                element, timeout=min(0.5, max(0.01, deadline - monotonic()))
            )
            target_count = sum((candidate == value for candidate in selected))
            if target_count > 1 or len(selected) != len(set(selected)):
                raise ElementActionError(
                    f"custom select returned duplicate selected options: {element.id}"
                )
            extras = [candidate for candidate in selected if candidate != value]
            if not extras and target_count == 1:
                self._dismiss_custom_select(element)
                return
            previous = selected
            if extras:
                self._click_exact_option(element, extras[0])
            else:
                self._click_exact_option(element, value)
            self._wait_for_custom_selection_change(
                element, previous=previous, deadline=deadline
            )
        raise ElementActionError(
            f"custom select did not reach one exact selection: {element.id}"
        )

    def _selected_custom_option_values(
        self, element: ElementSpec, *, timeout: float
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
            try:
                options = scope.eles(option_locator.value, timeout=lookup_timeout)
                if not options:
                    sleep(min(0.05, remaining))
                    continue
                selected_options = scope.eles(
                    selected_locator.value, timeout=lookup_timeout
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
            if monotonic() < deadline:
                sleep(min(0.05, max(0.0, deadline - monotonic())))
        raise ElementActionError(
            f"custom select options did not become observable: {element.id}"
        )

    def _wait_for_custom_selection_change(
        self, element: ElementSpec, *, previous: tuple[str, ...], deadline: float
    ) -> None:
        while monotonic() < deadline:
            current = self._selected_custom_option_values(
                element, timeout=min(0.2, max(0.01, deadline - monotonic()))
            )
            if current != previous:
                return
            sleep(min(0.05, max(0.0, deadline - monotonic())))
        raise ElementActionError(
            f"custom select state did not change after option click: {element.id}"
        )

    def _dismiss_custom_select(self, element: ElementSpec) -> None:
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
            try:
                if not self._visible_popup_exists(
                    scope, popup_locator.value, timeout=lookup_timeout
                ):
                    return
                dismiss_target = scope.ele(
                    dismiss_locator.value, timeout=lookup_timeout
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
            sleep(min(0.05, max(0.0, deadline - monotonic())))
        if dismiss_target is None or dismiss_scope is None:
            raise ElementActionError(
                f"custom select dismiss target was not found: {element.id}"
            )
        try:
            if not dismiss_target.wait.clickable(
                wait_moved=True,
                timeout=max(0.01, deadline - monotonic()),
                raise_err=False,
            ):
                raise ElementActionError(
                    f"custom select dismiss target is not clickable: {element.id}"
                )
            dismiss_target.click(by_js=False)
        except ElementActionError:
            raise
        except Exception as error:
            raise ElementActionError(
                f"custom select could not be dismissed safely: {element.id}"
            ) from error
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
            try:
                if not self._visible_popup_exists(
                    scope, popup_locator.value, timeout=lookup_timeout
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
    if (
        not _SAFE_FILENAME_PATTERN.fullmatch(filename)
        or Path(filename).name != filename
    ):
        raise DownloadError("artifact filename must be one safe basename")


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
    except (OSError, ValueError):
        return False
    return True


__all__ = ["DrissionBrowserActions"]
