"""Dryad fetcher — dataset files, methods, usage notes, ROR-linked affiliations."""

from __future__ import annotations

import logging
from urllib.parse import quote

from doi_metadata.fetchers.base import fetch_json
from doi_metadata.models import (
    Affiliation,
    Author,
    FileInfo,
    Funder,
    License,
    PersonName,
    RelatedWork,
    SourceName,
    SourceResult,
    VersionInfo,
)

logger = logging.getLogger(__name__)
SOURCE = SourceName.DRYAD


async def fetch_dryad(doi: str) -> SourceResult:
    result = SourceResult(source=SOURCE, doi=doi)

    # Dryad requires URL-encoding the DOI in the path
    encoded = quote(doi, safe="")
    try:
        data = await fetch_json(
            f"https://datadryad.org/api/v2/datasets/doi%3A{encoded}",
            source_name="Dryad",
        )
    except Exception as exc:
        result.error = str(exc)
        return result

    if not data or "identifier" not in data:
        return result

    result.found = True
    result.raw = data

    # Basic metadata
    result.title = data.get("title")
    result.abstract = data.get("abstract")
    result.methods = data.get("methods")
    result.usage_notes = data.get("usageNotes")
    result.publication_date = data.get("publicationDate")
    if result.publication_date:
        try:
            result.publication_year = int(result.publication_date[:4])
        except (ValueError, IndexError):
            pass
    result.work_type = "dataset"
    result.storage_size = data.get("storageSize")

    # License
    lic = data.get("license")
    if lic:
        result.licenses.append(License(url=lic, source=SOURCE))

    # Keywords
    result.keywords = data.get("keywords", [])

    # Field of science
    fos = data.get("fieldOfScience")
    if fos:
        from doi_metadata.models import Subject
        result.subjects.append(Subject(value=fos, scheme="fieldOfScience", source=SOURCE))

    # Related publication
    pub_name = data.get("publicationName")
    pub_issn = data.get("publicationISSN")
    if pub_name:
        result.container_title = pub_name
    if pub_issn:
        result.issn = [pub_issn]

    # Authors with ROR
    for a in data.get("authors", []):
        affiliations = []
        if a.get("affiliation"):
            affiliations.append(
                Affiliation(
                    name=a["affiliation"],
                    ror_id=a.get("affiliationROR"),
                    isni=a.get("affiliationISNI"),
                    source=SOURCE,
                )
            )
        result.authors.append(
            Author(
                name=PersonName(
                    given=a.get("firstName"),
                    family=a.get("lastName"),
                    full_name=f"{a.get('firstName', '')} {a.get('lastName', '')}".strip(),
                    orcid=a.get("orcid"),
                    source=SOURCE,
                ),
                affiliations=affiliations,
                email=a.get("email"),
                sources=[SOURCE],
            )
        )

    # Funders
    for f in data.get("funders", []):
        result.funders.append(
            Funder(
                name=f.get("organization"),
                doi=f.get("identifier") if f.get("identifierType") == "crossref_funder_id" else None,
                award_numbers=[f["awardNumber"]] if f.get("awardNumber") else [],
                source=SOURCE,
            )
        )

    # Related works (links to articles, software)
    for rw in data.get("relatedWorks", []):
        result.related_works.append(
            RelatedWork(
                identifier=rw.get("identifier", ""),
                identifier_type=rw.get("identifierType", "DOI"),
                relation_type=rw.get("relationship"),
                source=SOURCE,
            )
        )

    # Version info (Dryad uses single DOI, version via versionNumber)
    version_num = data.get("versionNumber")
    if version_num is not None:
        result.version_info = VersionInfo(
            version_number=version_num,
            source=SOURCE,
        )

    # Files — follow HATEOAS links
    links = data.get("_links", {})
    version_link = links.get("stash:version", {}).get("href")
    if version_link:
        try:
            version_data = await fetch_json(version_link, source_name="Dryad-version")
            if version_data:
                files_link = version_data.get("_links", {}).get("stash:files", {}).get("href")
                if files_link:
                    files_data = await fetch_json(files_link, source_name="Dryad-files")
                    if files_data:
                        for f in files_data.get("_embedded", {}).get("stash:files", []):
                            result.files.append(
                                FileInfo(
                                    filename=f.get("path", ""),
                                    size_bytes=f.get("size"),
                                    content_type=f.get("mimeType"),
                                    download_url=f.get("_links", {}).get("stash:download", {}).get("href"),
                                    source=SOURCE,
                                )
                            )
        except Exception:
            logger.debug("Dryad file fetch failed for %s", doi)

    return result
