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
)


_SAFE_FILENAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,254}$")


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

    def exists(self, element: ElementSpec, *, timeout: float = 0.0) -> bool:
        if timeout < 0:
            raise ValueError("timeout must be non-negative")
        locator = element.require_locator().value
        try:
            return bool(self.tab.ele(locator, timeout=timeout))
        except Exception as error:
            raise ElementLookupError(
                f"element lookup failed: {element.id}"
            ) from error

    def click(self, element: ElementSpec) -> None:
        target = self._find(element)
        try:
            if not target.wait.clickable(
                wait_moved=True,
                timeout=self.action_timeout,
                raise_err=False,
            ):
                raise ElementActionError(f"element is not clickable: {element.id}")
            target.click(by_js=False)
        except ElementActionError:
            raise
        except Exception as error:
            raise ElementActionError(f"element click failed: {element.id}") from error

    def input(self, element: ElementSpec, value: SecretLike) -> None:
        target = self._find(element)
        revealed = _reveal(value)
        try:
            if not target.wait.clickable(
                wait_moved=False,
                timeout=self.action_timeout,
                raise_err=False,
            ):
                raise ElementActionError(f"element is not ready for input: {element.id}")
            # DrissionPage 4.1.1.4 uses JS clear on macOS internally. Calling
            # it explicitly keeps behavior deterministic across platforms.
            target.clear(by_js=True)
            target.focus()
            target.input(revealed, clear=False, by_js=False)
        except ElementActionError:
            raise
        except Exception as error:
            raise ElementActionError(f"element input failed: {element.id}") from error

    def select(self, element: ElementSpec, value: SecretLike) -> None:
        target = self._find(element)
        revealed = _reveal(value)
        try:
            target.select.by_text(revealed, timeout=self.action_timeout)
        except Exception as error:
            raise ElementActionError(f"element select failed: {element.id}") from error

    def download(
        self,
        element: ElementSpec,
        *,
        filename: str | None = None,
    ) -> DownloadRef:
        if filename is not None:
            _validate_filename(filename)
        target = self._find(element)
        download_dir = self._artifact_directory("downloads")
        try:
            mission = target.click.to_download(
                str(download_dir),
                rename=filename,
                by_js=False,
                timeout=self.action_timeout,
            )
            if not mission:
                raise DownloadError("download did not start")
            deadline = monotonic() + self.download_timeout
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
        except DownloadError:
            raise
        except Exception as error:
            raise DownloadError(f"download action failed: {element.id}") from error

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

    def _find(self, element: ElementSpec) -> Any:
        locator = element.require_locator().value
        try:
            target = self.tab.ele(locator, timeout=self.action_timeout)
        except Exception as error:
            raise ElementLookupError(
                f"element lookup failed: {element.id}"
            ) from error
        if not target:
            raise ElementLookupError(f"element was not found: {element.id}")
        return target

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
