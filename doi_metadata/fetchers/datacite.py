"""DataCite fetcher — datasets, software, version chains, relatedIdentifiers."""

from __future__ import annotations

import logging

from doi_metadata.fetchers.base import fetch_json
from doi_metadata.models import (
    Affiliation,
    Author,
    FileInfo,
    Funder,
    ImpactIndicator,
    License,
    PersonName,
    RelatedWork,
    SourceName,
    SourceResult,
    Subject,
    VersionInfo,
)

logger = logging.getLogger(__name__)
SOURCE = SourceName.DATACITE


def _parse_creators(raw: list[dict]) -> list[Author]:
    authors = []
    for c in raw:
        orcid = None
        for nid in c.get("nameIdentifiers", []):
            if nid.get("nameIdentifierScheme") == "ORCID":
                orcid = nid.get("nameIdentifier", "").replace("https://orcid.org/", "")
                break

        affiliations = []
        for aff in c.get("affiliation", []):
            aff_name = aff if isinstance(aff, str) else aff.get("name")
            aff_id = aff.get("affiliationIdentifier") if isinstance(aff, dict) else None
            ror_id = aff_id if aff_id and "ror.org" in str(aff_id) else None
            affiliations.append(Affiliation(name=aff_name, ror_id=ror_id, source=SOURCE))

        authors.append(
            Author(
                name=PersonName(
                    given=c.get("givenName"),
                    family=c.get("familyName"),
                    full_name=c.get("name"),
                    orcid=orcid,
                    source=SOURCE,
                ),
                affiliations=affiliations,
                sources=[SOURCE],
            )
        )
    return authors


def _parse_related_identifiers(raw: list[dict]) -> list[RelatedWork]:
    return [
        RelatedWork(
            identifier=ri.get("relatedIdentifier", ""),
            identifier_type=ri.get("relatedIdentifierType", "DOI"),
            relation_type=ri.get("relationType"),
            resource_type=ri.get("resourceTypeGeneral"),
            source=SOURCE,
        )
        for ri in raw
        if ri.get("relatedIdentifier")
    ]


def _build_version_info(attrs: dict, rels: dict) -> VersionInfo | None:
    version_data = rels.get("versions", {}).get("data", [])
    version_of_data = rels.get("versionOf", {}).get("data", [])

    # Collect version DOIs from relatedIdentifiers
    version_dois = []
    for ri in attrs.get("relatedIdentifiers", []):
        if ri.get("relationType") in ("HasVersion", "IsVersionOf", "IsNewVersionOf", "IsPreviousVersionOf"):
            if ri.get("relatedIdentifierType") == "DOI":
                version_dois.append(ri["relatedIdentifier"])

    # Also from relationships
    for v in version_data:
        if v.get("id"):
            version_dois.append(v["id"])
    for v in version_of_data:
        if v.get("id"):
            version_dois.append(v["id"])

    if not version_dois and not attrs.get("version"):
        return None

    return VersionInfo(
        version_number=None,
        total_versions=attrs.get("versionCount"),
        version_dois=list(set(version_dois)),
        source=SOURCE,
    )


async def fetch_datacite(doi: str) -> SourceResult:
    result = SourceResult(source=SOURCE, doi=doi)

    try:
        data = await fetch_json(
            f"https://api.datacite.org/dois/{doi}",
            params={"affiliation": "true"},
            source_name="DataCite",
        )
    except Exception as exc:
        result.error = str(exc)
        return result

    if not data:
        return result

    attrs = data.get("data", {}).get("attributes", {})
    rels = data.get("data", {}).get("relationships", {})
    result.found = True
    result.raw = data.get("data", {})

    # Basic metadata
    titles = attrs.get("titles", [])
    result.title = titles[0].get("title") if titles else None
    descriptions = attrs.get("descriptions", [])
    for desc in descriptions:
        if desc.get("descriptionType") == "Abstract":
            result.abstract = desc.get("description")
            break
    result.publication_year = attrs.get("publicationYear")
    result.publication_date = attrs.get("published")
    result.publisher = attrs.get("publisher") if isinstance(attrs.get("publisher"), str) else None
    result.language = attrs.get("language")

    # Types
    types = attrs.get("types", {})
    result.work_type = types.get("resourceTypeGeneral") or types.get("resourceType")

    # Container
    container = attrs.get("container", {})
    result.container_title = container.get("title")
    result.volume = container.get("volume")
    result.issue = container.get("issue")
    result.pages = f"{container.get('firstPage', '')}-{container.get('lastPage', '')}".strip("-") or None

    # Counts
    result.citation_count = attrs.get("citationCount")
    result.reference_count = attrs.get("referenceCount")

    # Impact
    for name, key in [("view_count", "viewCount"), ("download_count", "downloadCount")]:
        val = attrs.get(key)
        if val is not None:
            result.impact_indicators.append(ImpactIndicator(name=name, value=val, source=SOURCE))

    # Creators
    result.authors = _parse_creators(attrs.get("creators", []))

    # Related identifiers (critical for version chains and dataset linkage)
    result.related_works = _parse_related_identifiers(attrs.get("relatedIdentifiers", []))

    # Version info
    result.version_info = _build_version_info(attrs, rels)

    # Rights / licenses
    for r in attrs.get("rightsList", []):
        result.licenses.append(
            License(
                url=r.get("rightsUri"),
                spdx_id=r.get("rightsIdentifier"),
                source=SOURCE,
            )
        )

    # Funding
    for fr in attrs.get("fundingReferences", []):
        result.funders.append(
            Funder(
                name=fr.get("funderName"),
                doi=fr.get("funderIdentifier") if fr.get("funderIdentifierType") == "Crossref Funder ID" else None,
                ror_id=fr.get("funderIdentifier") if fr.get("funderIdentifierType") == "ROR" else None,
                award_numbers=[fr["awardNumber"]] if fr.get("awardNumber") else [],
                source=SOURCE,
            )
        )

    # Subjects
    for s in attrs.get("subjects", []):
        result.subjects.append(
            Subject(
                value=s.get("subject", ""),
                scheme=s.get("subjectScheme"),
                source=SOURCE,
            )
        )

    # Geolocations (store in raw for now)

    return result
