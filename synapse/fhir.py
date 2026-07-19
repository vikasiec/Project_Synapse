"""
Real (scoped) FHIR JSON resource parser (Active_File.md task 15).

Modern instruments/middleware increasingly speak FHIR instead of, or
alongside, HL7v2. This module parses the common lab-reporting shape: a
`Bundle` of type message/collection containing inline `Patient` and
`Observation` resources, referencing each other by local
`"ResourceType/id"` reference strings -- the FHIR analogue of an HL7v2
ORU^R01 message.

Scoped, not full-spec: no external resource fetching, no `contained`
resources, no FHIR extensions, no terminology validation of LOINC/SNOMED
codes. Resource *semantics* (what makes something a lab result) are the
caller's job (see synapse/extraction.py's _extract_fhir_bundle), not this
module's -- this module only parses and resolves local references.
"""

from __future__ import annotations

import json
from typing import Any, Optional


class FhirParseError(ValueError):
    pass


def looks_like_fhir(text: str) -> bool:
    stripped = text.lstrip()
    return stripped.startswith("{") and '"resourceType"' in text


def parse_fhir_resource(text: str) -> dict[str, Any]:
    """Parse and minimally validate a single FHIR resource (Bundle or
    otherwise). Raises FhirParseError for anything not FHIR-shaped."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise FhirParseError(f"invalid JSON: {exc}") from exc
    if not isinstance(data, dict) or "resourceType" not in data:
        raise FhirParseError("missing resourceType")
    return data


def bundle_resources(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract inline resources from a Bundle's entry[].resource list."""
    out: list[dict[str, Any]] = []
    for entry in bundle.get("entry", []) or []:
        res = entry.get("resource")
        if isinstance(res, dict) and "resourceType" in res:
            out.append(res)
    return out


def resolve_local_reference(
    resources: list[dict[str, Any]], reference: Optional[str]
) -> Optional[dict[str, Any]]:
    """
    Resolve a local "ResourceType/id" reference against resources already
    present in the same bundle. Does not fetch external URLs.
    """
    if not reference or "/" not in reference:
        return None
    res_type, res_id = reference.split("/", 1)
    for res in resources:
        if res.get("resourceType") == res_type and res.get("id") == res_id:
            return res
    return None


def first_identifier_value(resource: dict[str, Any]) -> Optional[str]:
    ids = resource.get("identifier") or []
    if ids and isinstance(ids, list):
        return ids[0].get("value")
    return None


def human_name(resource: dict[str, Any]) -> tuple[str, str]:
    """Returns (family, given) from the first `name` entry, if present."""
    names = resource.get("name") or []
    if not names or not isinstance(names, list):
        return "", ""
    n = names[0]
    family = n.get("family", "") or ""
    given_list = n.get("given") or []
    given = given_list[0] if given_list else ""
    return family, given


def coding_display_and_code(field: Optional[dict[str, Any]]) -> tuple[str, str]:
    """Returns (display, code) from a CodeableConcept's first coding."""
    if not field:
        return "", ""
    codings = field.get("coding") or []
    if not codings or not isinstance(codings, list):
        return field.get("text", "") or "", ""
    c = codings[0]
    return c.get("display", "") or "", c.get("code", "") or ""


def reference_range_string(observation: dict[str, Any]) -> str:
    ranges = observation.get("referenceRange") or []
    if not ranges or not isinstance(ranges, list):
        return ""
    r = ranges[0]
    low = r.get("low", {}).get("value")
    high = r.get("high", {}).get("value")
    if low is not None and high is not None:
        return f"{low}-{high}"
    return ""
