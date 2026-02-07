"""Europe PMC fetcher — full-text mined entities, grants, MeSH, chemicals, corrections."""

from __future__ import annotations

import logging

from doi_metadata.fetchers.base import fetch_json
from doi_metadata.models import (
    Affiliation,
    Author,
    Grant,
    ImpactIndicator,
    MeSHTerm,
    OALocation,
    PersonName,
    SourceName,
    SourceResult,
    Subject,
)

logger = logging.getLogger(__name__)
SOURCE = SourceName.EUROPE_PMC


async def fetch_europe_pmc(doi: str) -> SourceResult:
    result = SourceResult(source=SOURCE, doi=doi)

    try:
        data = await fetch_json(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
            params={
                "query": f'DOI:"{doi}"',
                "format": "json",
                "resultType": "core",
                "pageSize": "1",
            },
            source_name="EuropePMC",
        )
    except Exception as exc:
        result.error = str(exc)
        return result

    if not data:
        return result

    results_list = data.get("resultList", {}).get("result", [])
    if not results_list:
        return result

    rec = results_list[0]
    result.found = True
    result.raw = rec

    # Basic metadata
    result.title = rec.get("title")
    result.abstract = rec.get("abstractText")
    result.publication_year = int(rec["pubYear"]) if rec.get("pubYear") else None
    result.work_type = rec.get("pubType")
    result.language = rec.get("language")
    result.publisher = rec.get("publisherName")

    # Identifiers
    result.pmid = rec.get("pmid")
    result.pmcid = rec.get("pmcid")

    # Journal
    journal_info = rec.get("journalInfo", {}) or {}
    journal = journal_info.get("journal", {}) or {}
    result.container_title = rec.get("journalTitle") or journal.get("title")
    result.volume = rec.get("journalVolume") or journal_info.get("volume")
    result.issue = rec.get("issue") or journal_info.get("issue")
    result.pages = rec.get("pageInfo")
    issn = journal.get("ISSN")
    essn = journal.get("ESSN")
    result.issn = [i for i in [issn, essn] if i]

    # Citation count
    cited_by = rec.get("citedByCount")
    if cited_by is not None:
        result.citation_count = cited_by
        result.impact_indicators.append(ImpactIndicator(name="cited_by_count", value=cited_by, source=SOURCE))

    # OA status
    is_oa = rec.get("isOpenAccess")
    result.is_oa = is_oa == "Y" if is_oa else None

    # Authors
    author_list = rec.get("authorList", {}).get("author", [])
    for a in author_list:
        orcid = None
        author_id = a.get("authorId")
        if author_id and author_id.get("type") == "ORCID":
            orcid = author_id.get("value")

        affiliations = []
        aff_details = a.get("authorAffiliationDetailsList", {}).get("authorAffiliation", [])
        for aff in aff_details:
            affiliations.append(Affiliation(name=aff.get("affiliation"), source=SOURCE))
        if not affiliations and a.get("affiliation"):
            affiliations.append(Affiliation(name=a["affiliation"], source=SOURCE))

        result.authors.append(
            Author(
                name=PersonName(
                    given=a.get("firstName"),
                    family=a.get("lastName"),
                    full_name=a.get("fullName"),
                    orcid=orcid,
                    source=SOURCE,
                ),
                affiliations=affiliations,
                sources=[SOURCE],
            )
        )

    # Grants (critical — links to NIH Reporter)
    grants_list = rec.get("grantsList", {}).get("grant", [])
    for g in grants_list:
        result.grants.append(
            Grant(
                grant_id=g.get("grantId"),
                agency=g.get("agency"),
                agency_abbreviation=g.get("acronym"),
                source=SOURCE,
            )
        )

    # MeSH headings
    mesh_list = rec.get("meshHeadingList", {}).get("meshHeading", [])
    for m in mesh_list:
        result.mesh_terms.append(
            MeSHTerm(
                descriptor_name=m.get("descriptorName", ""),
                is_major_topic=m.get("majorTopic_YN") == "Y",
                source=SOURCE,
            )
        )
        # Qualifiers
        for q in m.get("meshQualifierList", {}).get("meshQualifier", []):
            result.mesh_terms.append(
                MeSHTerm(
                    descriptor_name=m.get("descriptorName", ""),
                    qualifier_name=q.get("qualifierName"),
                    is_major_topic=q.get("majorTopic_YN") == "Y",
                    source=SOURCE,
                )
            )

    # Keywords
    kw_list = rec.get("keywordList", {}).get("keyword", [])
    result.keywords = kw_list

    # Chemicals (unique to Europe PMC)
    chem_list = rec.get("chemicalList", {}).get("chemical", [])
    result.chemicals = [{"name": c.get("name"), "registry_number": c.get("registryNumber")} for c in chem_list]

    # Text-mined accession numbers (GenBank, PDB, etc.)
    accessions = rec.get("tmAccessionTypeList", {}).get("accessionType", [])
    result.text_mined_accessions = accessions

    # Full text URLs
    ft_urls = rec.get("fullTextUrlList", {}).get("fullTextUrl", [])
    result.full_text_urls = [
        {
            "url": u.get("url"),
            "availability": u.get("availability"),
            "document_style": u.get("documentStyle"),
            "site": u.get("site"),
        }
        for u in ft_urls
    ]

    for u in ft_urls:
        if u.get("availabilityCode") == "OA":
            result.oa_locations.append(
                OALocation(
                    url=u.get("url"),
                    host_type=u.get("site"),
                    source=SOURCE,
                )
            )

    # Corrections / retractions
    corrections = rec.get("commentCorrectionList", {}).get("commentCorrection", [])
    result.corrections = [{"type": c.get("type"), "id": c.get("id"), "source": c.get("source")} for c in corrections]

    # Subjects from Europe PMC
    for subj in rec.get("subjectList", {}).get("subject", []):
        result.subjects.append(Subject(value=subj, scheme="europepmc", source=SOURCE))

    return result
