"""Load the immutable application-local element snapshot."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import tomllib

from rpa_core.browser import ElementSpec, Locator


class ElementSnapshotContractError(ValueError):
    error_code = "element_snapshot_invalid"


@lru_cache(maxsize=1)
def element_catalog() -> dict[str, ElementSpec]:
    root = Path(__file__).parent
    elements: dict[str, ElementSpec] = {}
    for path in sorted(root.rglob("*.toml")):
        document = tomllib.loads(path.read_text(encoding="utf-8"))
        if document.get("kind") != "element" or document.get("status") != "verified":
            raise ElementSnapshotContractError(
                f"invalid verified element metadata: {path.name}"
            )
        locator = _optional_locator(document, "locator", path)
        frame_locator = _optional_locator(document, "frame_locator", path)
        option_locator = _optional_locator(document, "option_locator", path)
        selected_option_locator = _optional_locator(
            document,
            "selected_option_locator",
            path,
        )
        popup_locator = _optional_locator(document, "popup_locator", path)
        dismiss_locator = _optional_locator(document, "dismiss_locator", path)
        element = ElementSpec(
            id=str(document["id"]),
            name=str(document["name"]),
            page=str(document["page"]),
            component=str(document["component"]),
            locator=locator,
            frame_locator=frame_locator,
            option_locator=option_locator,
            selected_option_locator=selected_option_locator,
            popup_locator=popup_locator,
            dismiss_locator=dismiss_locator,
        )
        if element.id in elements:
            raise ElementSnapshotContractError(
                f"duplicate snapshot element ID: {element.id}"
            )
        elements[element.id] = element
    return elements


def get_element(element_id: str) -> ElementSpec:
    try:
        return element_catalog()[element_id]
    except KeyError as error:
        raise ElementSnapshotContractError(
            f"snapshot element not found: {element_id}"
        ) from error


def _optional_locator(document: dict[str, object], key: str, path: Path) -> Locator | None:
    data = document.get(key)
    if data is None:
        return None
    if not isinstance(data, dict) or not data.get("value"):
        raise ElementSnapshotContractError(
            f"invalid snapshot {key} metadata: {path.name}"
        )
    return Locator(str(data["value"]))


__all__ = ["ElementSnapshotContractError", "element_catalog", "get_element"]
