"""OpenAlex fetcher — merged scholarly graph, concepts, institutions, citations."""

from __future__ import annotations

import logging

from doi_metadata.config import settings
from doi_metadata.fetchers.base import fetch_json
from doi_metadata.models import (
    Affiliation,
    Author,
    Funder,
    Grant,
    ImpactIndicator,
    License,
    MeSHTerm,
    OALocation,
    OAStatus,
    PersonName,
    Reference,
    SourceName,
    SourceResult,
    Subject,
)

logger = logging.getLogger(__name__)
SOURCE = SourceName.OPENALEX

OA_STATUS_MAP = {
    "gold": OAStatus.GOLD,
    "green": OAStatus.GREEN,
    "hybrid": OAStatus.HYBRID,
    "bronze": OAStatus.BRONZE,
    "diamond": OAStatus.DIAMOND,
    "closed": OAStatus.CLOSED,
}


def _reconstruct_abstract(inv_index: dict | None) -> str | None:
    if not inv_index:
        return None
    length = max(pos for positions in inv_index.values() for pos in positions) + 1
    words = [""] * length
    for word, positions in inv_index.items():
        for pos in positions:
            words[pos] = word
    return " ".join(words)


def _parse_authorships(raw: list[dict]) -> list[Author]:
    authors = []
    for a in raw:
        author_obj = a.get("author", {})
        orcid_raw = author_obj.get("orcid") or ""
        orcid = orcid_raw.replace("https://orcid.org/", "") if orcid_raw else None

        affiliations = []
        for inst in a.get("institutions", []):
            affiliations.append(
                Affiliation(
                    name=inst.get("display_name"),
                    ror_id=inst.get("ror"),
                    country_code=inst.get("country_code"),
                    source=SOURCE,
                )
            )

        authors.append(
            Author(
                name=PersonName(
                    full_name=author_obj.get("display_name"),
                    orcid=orcid,
                    source=SOURCE,
                ),
                affiliations=affiliations,
                is_corresponding=a.get("is_corresponding"),
                openalex_author_id=author_obj.get("id"),
                sources=[SOURCE],
            )
        )
    return authors


def _parse_location(loc: dict | None) -> OALocation | None:
    if not loc:
        return None
    source_info = loc.get("source", {}) or {}
    return OALocation(
        url=loc.get("landing_page_url"),
        pdf_url=loc.get("pdf_url"),
        landing_page_url=loc.get("landing_page_url"),
        host_type=source_info.get("type"),
        version=loc.get("version"),
        license=loc.get("license"),
        is_best=loc.get("is_best", False),
        repository_institution=source_info.get("host_organization"),
        source=SOURCE,
    )


async def fetch_openalex(doi: str) -> SourceResult:
    result = SourceResult(source=SOURCE, doi=doi)
    params: dict[str, str] = {}
    if settings.openalex_api_key:
        params["api_key"] = settings.openalex_api_key
    elif settings.openalex_email:
        params["mailto"] = settings.openalex_email

    try:
        data = await fetch_json(
            f"https://api.openalex.org/works/doi:{doi}",
            params=params,
            source_name="OpenAlex",
        )
    except Exception as exc:
        result.error = str(exc)
        return result

    if not data or "id" not in data:
        return result

    result.found = True
    result.raw = data

    # Basic metadata
    result.title = data.get("display_name") or data.get("title")
    result.abstract = _reconstruct_abstract(data.get("abstract_inverted_index"))
    result.publication_date = data.get("publication_date")
    result.publication_year = data.get("publication_year")
    result.work_type = data.get("type")
    result.language = data.get("language")

    # Identifiers
    ids = data.get("ids", {})
    result.openalex_id = ids.get("openalex") or data.get("id")
    result.pmid = str(ids["pmid"]).replace("https://pubmed.ncbi.nlm.nih.gov/", "") if ids.get("pmid") else None
    result.pmcid = str(ids["pmcid"]).replace("https://www.ncbi.nlm.nih.gov/pmc/articles/", "") if ids.get("pmcid") else None

    # Container (journal/source)
    primary_loc = data.get("primary_location", {}) or {}
    source_info = primary_loc.get("source", {}) or {}
    result.container_title = source_info.get("display_name")
    biblio = data.get("biblio", {}) or {}
    result.volume = biblio.get("volume")
    result.issue = biblio.get("issue")
    first_page = biblio.get("first_page", "")
    last_page = biblio.get("last_page", "")
    if first_page:
        result.pages = f"{first_page}-{last_page}" if last_page else first_page
    result.issn = source_info.get("issn", []) or []
    result.publisher = source_info.get("host_organization")

    # Citation counts
    result.citation_count = data.get("cited_by_count")
    result.reference_count = len(data.get("referenced_works", []))

    # Counts by year
    for entry in data.get("counts_by_year", []):
        if entry.get("year") and entry.get("cited_by_count") is not None:
            result.counts_by_year[entry["year"]] = entry["cited_by_count"]

    # Impact indicators
    fwci = data.get("fwci")
    if fwci is not None:
        result.impact_indicators.append(ImpactIndicator(name="fwci", value=fwci, source=SOURCE))
    cnp = data.get("citation_normalized_percentile", {})
    if cnp:
        result.impact_indicators.append(
            ImpactIndicator(name="citation_normalized_percentile", value=cnp.get("value"), source=SOURCE)
        )

    # Authors
    result.authors = _parse_authorships(data.get("authorships", []))

    # Referenced works (OpenAlex IDs)
    for ref_id in data.get("referenced_works", []):
        result.references.append(Reference(doi=None, title=None, source=SOURCE))

    # Open access
    oa = data.get("open_access", {}) or {}
    result.is_oa = oa.get("is_oa")
    result.oa_status = OA_STATUS_MAP.get(oa.get("oa_status", ""), OAStatus.UNKNOWN)
    result.best_oa_url = oa.get("oa_url")

    # OA locations
    best_loc = _parse_location(data.get("best_oa_location"))
    if best_loc:
        best_loc.is_best = True
        result.oa_locations.append(best_loc)
    for loc in data.get("locations", []):
        parsed = _parse_location(loc)
        if parsed:
            result.oa_locations.append(parsed)

    # License from primary location
    if primary_loc.get("license"):
        result.licenses.append(License(spdx_id=primary_loc["license"], source=SOURCE))

    # Grants
    for g in data.get("grants", []):
        result.grants.append(
            Grant(grant_id=g.get("award_id"), agency=g.get("funder_display_name"), source=SOURCE)
        )

    # Funders
    for g in data.get("grants", []):
        result.funders.append(
            Funder(name=g.get("funder_display_name"), source=SOURCE)
        )

    # Topics/concepts/keywords/SDGs
    for topic in data.get("topics", []):
        result.subjects.append(
            Subject(
                value=topic.get("display_name", ""),
                scheme="openalex_topic",
                score=topic.get("score"),
                source=SOURCE,
            )
        )
    for concept in data.get("concepts", []):
        result.subjects.append(
            Subject(
                value=concept.get("display_name", ""),
                scheme="openalex_concept",
                score=concept.get("score"),
                level=concept.get("level"),
                source=SOURCE,
            )
        )
    for kw in data.get("keywords", []):
        result.keywords.append(kw.get("display_name", ""))
    for sdg in data.get("sustainable_development_goals", []):
        result.subjects.append(
            Subject(value=sdg.get("display_name", ""), scheme="SDG", score=sdg.get("score"), source=SOURCE)
        )

    # MeSH terms
    for m in data.get("mesh", []):
        result.mesh_terms.append(
            MeSHTerm(
                descriptor_name=m.get("descriptor_name", ""),
                descriptor_ui=m.get("descriptor_ui"),
                qualifier_name=m.get("qualifier_name"),
                qualifier_ui=m.get("qualifier_ui"),
                is_major_topic=m.get("is_major_topic", False),
                source=SOURCE,
            )
        )

    # APC
    apc = data.get("apc_list")
    if apc:
        result.impact_indicators.append(
            ImpactIndicator(name="apc_list_usd", value=apc.get("value_usd"), source=SOURCE)
        )

    return result
