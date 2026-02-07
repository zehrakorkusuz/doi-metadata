"""Semantic Scholar fetcher — citation intents, influential citations, TLDR, SPECTER2."""

from __future__ import annotations

import logging

from doi_metadata.config import settings
from doi_metadata.fetchers.base import fetch_json
from doi_metadata.models import (
    Author,
    Citation,
    ImpactIndicator,
    OALocation,
    PersonName,
    Reference,
    SourceName,
    SourceResult,
    Subject,
)

logger = logging.getLogger(__name__)
SOURCE = SourceName.SEMANTIC_SCHOLAR

# Request all available fields
FIELDS = ",".join([
    "title", "abstract", "year", "publicationDate", "publicationTypes",
    "authors", "journal", "venue", "publicationVenue",
    "citationCount", "referenceCount", "influentialCitationCount",
    "tldr", "externalIds", "isOpenAccess", "openAccessPdf",
    "s2FieldsOfStudy", "citationStyles",
])

# Fields for citations/references (via dot notation)
CITATION_FIELDS = "title,year,externalIds,intents,isInfluential,contexts"


async def fetch_semantic_scholar(doi: str) -> SourceResult:
    result = SourceResult(source=SOURCE, doi=doi)

    headers: dict[str, str] = {}
    if settings.semantic_scholar_api_key:
        headers["x-api-key"] = settings.semantic_scholar_api_key

    # Main paper data
    try:
        data = await fetch_json(
            f"https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}",
            params={"fields": FIELDS},
            headers=headers,
            source_name="SemanticScholar",
        )
    except Exception as exc:
        result.error = str(exc)
        return result

    if not data or "paperId" not in data:
        return result

    result.found = True
    result.raw = data

    # Basic metadata
    result.title = data.get("title")
    result.abstract = data.get("abstract")
    result.publication_year = data.get("year")
    result.publication_date = data.get("publicationDate")
    pub_types = data.get("publicationTypes") or []
    result.work_type = pub_types[0] if pub_types else None

    # Identifiers
    ext_ids = data.get("externalIds", {}) or {}
    result.s2_paper_id = data.get("paperId")
    result.s2_corpus_id = str(ext_ids["CorpusId"]) if ext_ids.get("CorpusId") else None
    result.pmid = str(ext_ids["PubMed"]) if ext_ids.get("PubMed") else None
    result.pmcid = str(ext_ids["PubMedCentral"]) if ext_ids.get("PubMedCentral") else None
    result.arxiv_id = ext_ids.get("ArXiv")

    # Journal
    journal = data.get("journal") or {}
    result.container_title = journal.get("name")
    result.volume = journal.get("volume")
    result.pages = journal.get("pages")
    venue = data.get("publicationVenue") or {}
    if not result.container_title and venue.get("name"):
        result.container_title = venue["name"]

    # Citation counts
    result.citation_count = data.get("citationCount")
    result.reference_count = data.get("referenceCount")
    result.influential_citation_count = data.get("influentialCitationCount")

    # Impact
    if result.influential_citation_count is not None:
        result.impact_indicators.append(
            ImpactIndicator(name="influential_citation_count", value=result.influential_citation_count, source=SOURCE)
        )

    # Authors
    for a in data.get("authors", []):
        result.authors.append(
            Author(
                name=PersonName(full_name=a.get("name"), source=SOURCE),
                s2_author_id=a.get("authorId"),
                sources=[SOURCE],
            )
        )

    # TLDR (unique to S2)
    tldr = data.get("tldr")
    if tldr:
        result.tldr = tldr.get("text")

    # Open access
    result.is_oa = data.get("isOpenAccess")
    oa_pdf = data.get("openAccessPdf")
    if oa_pdf:
        result.oa_locations.append(
            OALocation(
                pdf_url=oa_pdf.get("url"),
                host_type=oa_pdf.get("status"),
                source=SOURCE,
            )
        )
        result.best_oa_url = oa_pdf.get("url")

    # Fields of study
    for fos in data.get("s2FieldsOfStudy", []):
        result.subjects.append(
            Subject(
                value=fos.get("category", ""),
                scheme=f"s2_{fos.get('source', 'model')}",
                source=SOURCE,
            )
        )

    # Citation styles
    cs = data.get("citationStyles")
    if cs:
        result.citation_styles = cs

    # Fetch citations with intents (paginated, first page)
    try:
        cit_data = await fetch_json(
            f"https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}/citations",
            params={"fields": CITATION_FIELDS, "limit": "100"},
            headers=headers,
            source_name="S2-citations",
        )
        if cit_data and "data" in cit_data:
            for item in cit_data["data"]:
                cp = item.get("citingPaper", {})
                ext = cp.get("externalIds", {}) or {}
                result.citations.append(
                    Citation(
                        doi=ext.get("DOI"),
                        title=cp.get("title"),
                        year=cp.get("year"),
                        s2_paper_id=cp.get("paperId"),
                        intents=item.get("intents", []),
                        is_influential=item.get("isInfluential"),
                        contexts=item.get("contexts", []),
                        source=SOURCE,
                    )
                )
    except Exception:
        logger.debug("S2 citations fetch failed for %s", doi)

    # Fetch references with intents
    try:
        ref_data = await fetch_json(
            f"https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}/references",
            params={"fields": CITATION_FIELDS, "limit": "100"},
            headers=headers,
            source_name="S2-references",
        )
        if ref_data and "data" in ref_data:
            for item in ref_data["data"]:
                cp = item.get("citedPaper", {})
                ext = cp.get("externalIds", {}) or {}
                result.references.append(
                    Reference(
                        doi=ext.get("DOI"),
                        title=cp.get("title"),
                        year=cp.get("year"),
                        s2_paper_id=cp.get("paperId"),
                        intents=item.get("intents", []),
                        is_influential=item.get("isInfluential"),
                        contexts=item.get("contexts", []),
                        source=SOURCE,
                    )
                )
    except Exception:
        logger.debug("S2 references fetch failed for %s", doi)

    return result
