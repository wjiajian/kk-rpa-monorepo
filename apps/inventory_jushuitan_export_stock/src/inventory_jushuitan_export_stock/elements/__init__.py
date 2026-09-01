"""Load application-local candidate element descriptions."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import tomllib

from rpa_core.browser import ElementSpec, Locator


class CandidateElementContractError(ValueError):
    error_code = "candidate_element_invalid"


@lru_cache(maxsize=1)
def element_catalog() -> dict[str, ElementSpec]:
    root = Path(__file__).parent
    elements: dict[str, ElementSpec] = {}
    for path in sorted(root.rglob("*.toml")):
        document = tomllib.loads(path.read_text(encoding="utf-8"))
        if document.get("kind") != "element" or document.get("status") != "candidate":
            raise CandidateElementContractError(f"invalid candidate element metadata: {path.name}")
        locator_data = document.get("locator")
        locator = None
        if isinstance(locator_data, dict) and locator_data.get("value"):
            locator = Locator(str(locator_data["value"]))
        element = ElementSpec(
            id=str(document["id"]),
            name=str(document["name"]),
            page=str(document["page"]),
            component=str(document["component"]),
            locator=locator,
        )
        if element.id in elements:
            raise CandidateElementContractError(f"duplicate candidate element ID: {element.id}")
        elements[element.id] = element
    return elements


def get_element(element_id: str) -> ElementSpec:
    try:
        return element_catalog()[element_id]
    except KeyError as error:
        raise CandidateElementContractError(f"candidate element not found: {element_id}") from error


__all__ = ["CandidateElementContractError", "element_catalog", "get_element"]
