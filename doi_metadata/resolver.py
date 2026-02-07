"""DOI resolver — classify DOI registration agency (CrossRef vs DataCite)."""

from __future__ import annotations

import logging

from doi_metadata.fetchers.base import fetch_json

logger = logging.getLogger(__name__)


async def resolve_registration_agency(doi: str) -> str:
    """Determine if a DOI is registered with CrossRef, DataCite, or unknown."""
    try:
        data = await fetch_json(
            f"https://api.crossref.org/works/{doi}/agency",
            source_name="DOI-agency",
        )
        if data and "message" in data:
            agency = data["message"].get("agency", {})
            label = agency.get("label", "").lower()
            if "crossref" in label:
                return "crossref"
            if "datacite" in label:
                return "datacite"
            return agency.get("id", "unknown")
    except Exception:
        logger.debug("Agency resolution failed for %s, trying prefix heuristic", doi)

    # Fallback: prefix-based heuristic
    prefix = doi.split("/")[0] if "/" in doi else ""
    datacite_prefixes = {"10.5061", "10.5281", "10.6084", "10.5281", "10.48550", "10.17632", "10.7910"}
    if prefix in datacite_prefixes:
        return "datacite"

    return "unknown"
