"""CrossRef fetcher — journal articles, references, funders, licenses."""

from __future__ import annotations

import logging
from typing import Any

from doi_metadata.config import settings
from doi_metadata.fetchers.base import fetch_json
from doi_metadata.models import (
    Affiliation,
    Author,
    Funder,
    License,
    OALocation,
    PersonName,
    Reference,
    SourceName,
    SourceResult,
    Subject,
)

logger = logging.getLogger(__name__)
SOURCE = SourceName.CROSSREF


def _parse_date(d: dict | None) -> str | None:
    if not d:
        return None
    parts = d.get("date-parts", [[]])
    if not parts or not parts[0]:
        return None
    p = parts[0]
    if len(p) >= 3:
        return f"{p[0]:04d}-{p[1]:02d}-{p[2]:02d}"
    if len(p) >= 2:
        return f"{p[0]:04d}-{p[1]:02d}"
    return f"{p[0]:04d}"


def _parse_year(d: dict | None) -> int | None:
    if not d:
        return None
    parts = d.get("date-parts", [[]])
    if parts and parts[0]:
        return parts[0][0]
    return None


def _parse_authors(raw_authors: list[dict]) -> list[Author]:
    authors = []
    for a in raw_authors:
        affiliations = [
            Affiliation(name=aff.get("name"), source=SOURCE) for aff in a.get("affiliation", []) if aff.get("name")
        ]
        orcid_raw = a.get("ORCID", "")
        orcid = orcid_raw.replace("http://orcid.org/", "").replace("https://orcid.org/", "") if orcid_raw else None
        authors.append(
            Author(
                name=PersonName(
                    given=a.get("given"),
                    family=a.get("family"),
                    full_name=f"{a.get('given', '')} {a.get('family', '')}".strip() or a.get("name"),
                    sequence=a.get("sequence"),
                    orcid=orcid,
                    authenticated_orcid=a.get("authenticated-orcid", False),
                    source=SOURCE,
                ),
                affiliations=affiliations,
                sources=[SOURCE],
            )
        )
    return authors


def _parse_references(raw_refs: list[dict]) -> list[Reference]:
    refs = []
    for r in raw_refs:
        refs.append(
            Reference(
                doi=r.get("DOI"),
                key=r.get("key"),
                author=r.get("author"),
                year=int(r["year"]) if r.get("year") and r["year"].isdigit() else None,
                title=r.get("article-title"),
                unstructured=r.get("unstructured"),
                source=SOURCE,
            )
        )
    return refs


def _parse_funders(raw_funders: list[dict]) -> list[Funder]:
    return [
        Funder(
            name=f.get("name"),
            doi=f.get("DOI"),
            award_numbers=f.get("award", []),
            source=SOURCE,
        )
        for f in raw_funders
    ]


def _parse_licenses(raw_licenses: list[dict]) -> list[License]:
    return [
        License(
            url=lic.get("URL"),
            content_version=lic.get("content-version"),
            delay_in_days=lic.get("delay-in-days"),
            source=SOURCE,
        )
        for lic in raw_licenses
    ]


async def fetch_crossref(doi: str) -> SourceResult:
    result = SourceResult(source=SOURCE, doi=doi)
    params: dict[str, str] = {}
    if settings.crossref_email:
        params["mailto"] = settings.crossref_email

    try:
        data = await fetch_json(
            f"https://api.crossref.org/works/{doi}",
            params=params,
            source_name="CrossRef",
        )
    except Exception as exc:
        result.error = str(exc)
        return result

    if not data:
        return result

    msg: dict[str, Any] = data.get("message", {})
    result.found = True
    result.raw = msg

    # Basic metadata
    titles = msg.get("title", [])
    result.title = titles[0] if titles else None
    result.abstract = msg.get("abstract")  # often JATS XML
    result.work_type = msg.get("type")
    result.publisher = msg.get("publisher")
    result.language = msg.get("language")

    # Dates — pick earliest available
    result.publication_date = (
        _parse_date(msg.get("published"))
        or _parse_date(msg.get("published-online"))
        or _parse_date(msg.get("published-print"))
        or _parse_date(msg.get("issued"))
    )
    result.publication_year = (
        _parse_year(msg.get("published"))
        or _parse_year(msg.get("published-online"))
        or _parse_year(msg.get("published-print"))
        or _parse_year(msg.get("issued"))
    )

    # Container (journal)
    ct = msg.get("container-title", [])
    result.container_title = ct[0] if ct else None
    result.volume = msg.get("volume")
    result.issue = msg.get("issue")
    result.pages = msg.get("page") or msg.get("article-number")
    result.issn = [i["value"] for i in msg.get("issn-type", [])] or msg.get("ISSN", [])

    # Citation counts
    result.citation_count = msg.get("is-referenced-by-count")
    result.reference_count = msg.get("references-count")

    # Authors
    result.authors = _parse_authors(msg.get("author", []))

    # References (outbound)
    result.references = _parse_references(msg.get("reference", []))

    # Funders
    result.funders = _parse_funders(msg.get("funder", []))

    # Licenses
    result.licenses = _parse_licenses(msg.get("license", []))

    # OA links
    for link in msg.get("link", []):
        result.oa_locations.append(
            OALocation(
                url=link.get("URL"),
                host_type="publisher",
                source=SOURCE,
            )
        )

    # Subjects (ASJC categories)
    for s in msg.get("subject", []):
        result.subjects.append(Subject(value=s, scheme="ASJC", source=SOURCE))

    # CrossRef-specific: crossmark assertions
    result.crossmark_assertions = msg.get("assertion", [])

    # Clinical trial numbers
    result.clinical_trial_numbers = msg.get("clinical-trial-number", [])

    # Corrections / retractions
    result.update_to = msg.get("update-to", [])

    return result
