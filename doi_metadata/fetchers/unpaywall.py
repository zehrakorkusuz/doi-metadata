"""Unpaywall fetcher — OA status, per-location version tracking, DOAJ."""

from __future__ import annotations

import logging

from doi_metadata.config import settings
from doi_metadata.fetchers.base import fetch_json
from doi_metadata.models import (
    Author,
    OALocation,
    OAStatus,
    PersonName,
    SourceName,
    SourceResult,
)

logger = logging.getLogger(__name__)
SOURCE = SourceName.UNPAYWALL

OA_MAP = {
    "gold": OAStatus.GOLD,
    "green": OAStatus.GREEN,
    "hybrid": OAStatus.HYBRID,
    "bronze": OAStatus.BRONZE,
    "closed": OAStatus.CLOSED,
}


def _parse_oa_location(loc: dict) -> OALocation:
    return OALocation(
        url=loc.get("url"),
        pdf_url=loc.get("url_for_pdf"),
        landing_page_url=loc.get("url_for_landing_page"),
        host_type=loc.get("host_type"),
        version=loc.get("version"),
        license=loc.get("license"),
        evidence=loc.get("evidence"),
        is_best=loc.get("is_best", False),
        repository_institution=loc.get("repository_institution"),
        source=SOURCE,
    )


async def fetch_unpaywall(doi: str) -> SourceResult:
    result = SourceResult(source=SOURCE, doi=doi)

    email = settings.unpaywall_email or settings.crossref_email
    if not email:
        result.error = "No email configured for Unpaywall"
        return result

    try:
        data = await fetch_json(
            f"https://api.unpaywall.org/v2/{doi}",
            params={"email": email},
            source_name="Unpaywall",
        )
    except Exception as exc:
        result.error = str(exc)
        return result

    if not data or "doi" not in data:
        return result

    result.found = True
    result.raw = data

    # Basic metadata
    result.title = data.get("title")
    result.work_type = data.get("genre")
    result.publisher = data.get("publisher")
    result.publication_date = data.get("published_date")
    result.publication_year = data.get("year")
    result.container_title = data.get("journal_name")
    if data.get("journal_issn_l"):
        result.issn = [data["journal_issn_l"]]
    if data.get("journal_issns"):
        result.issn = list(set(result.issn + data["journal_issns"].split(",")))

    # Open access — Unpaywall's core value
    result.is_oa = data.get("is_oa")
    result.oa_status = OA_MAP.get(data.get("oa_status", ""), OAStatus.UNKNOWN)

    # Best OA location
    best = data.get("best_oa_location")
    if best:
        loc = _parse_oa_location(best)
        loc.is_best = True
        result.oa_locations.append(loc)
        result.best_oa_url = best.get("url_for_pdf") or best.get("url")

    # All OA locations
    for raw_loc in data.get("oa_locations", []):
        result.oa_locations.append(_parse_oa_location(raw_loc))

    # Embargoed locations
    for raw_loc in data.get("oa_locations_embargoed", []):
        result.oa_locations.append(_parse_oa_location(raw_loc))

    # Authors (from CrossRef data embedded in Unpaywall)
    for a in data.get("z_authors", []) or []:
        orcid_raw = a.get("ORCID", "")
        orcid = orcid_raw.replace("http://orcid.org/", "").replace("https://orcid.org/", "") if orcid_raw else None
        result.authors.append(
            Author(
                name=PersonName(
                    given=a.get("given"),
                    family=a.get("family"),
                    orcid=orcid,
                    authenticated_orcid=a.get("authenticated-orcid", False),
                    source=SOURCE,
                ),
                sources=[SOURCE],
            )
        )

    return result
