"""Zenodo fetcher — files with checksums, communities, version chains, download stats."""

from __future__ import annotations

import logging

from doi_metadata.fetchers.base import fetch_json
from doi_metadata.models import (
    Author,
    FileInfo,
    Funder,
    Grant,
    License,
    PersonName,
    RelatedWork,
    SourceName,
    SourceResult,
    Subject,
    UsageStat,
    VersionInfo,
)

logger = logging.getLogger(__name__)
SOURCE = SourceName.ZENODO


async def fetch_zenodo(doi: str) -> SourceResult:
    result = SourceResult(source=SOURCE, doi=doi)

    try:
        data = await fetch_json(
            "https://zenodo.org/api/records",
            params={"q": f'doi:"{doi}"', "size": "1"},
            source_name="Zenodo",
        )
    except Exception as exc:
        result.error = str(exc)
        return result

    if not data:
        return result

    hits = data.get("hits", {}).get("hits", [])
    if not hits:
        return result

    rec = hits[0]
    result.found = True
    result.raw = rec

    meta = rec.get("metadata", {})

    # Basic metadata
    result.title = meta.get("title")
    result.abstract = meta.get("description")
    result.publication_date = meta.get("publication_date")
    if result.publication_date:
        try:
            result.publication_year = int(result.publication_date[:4])
        except (ValueError, IndexError):
            pass
    result.language = meta.get("language")

    # Resource type
    rt = meta.get("resource_type", {})
    result.work_type = rt.get("type")

    # DOI and concept DOI
    result.doi = rec.get("doi") or meta.get("doi")

    # Creators
    for c in meta.get("creators", []):
        result.authors.append(
            Author(
                name=PersonName(
                    full_name=c.get("name"),
                    orcid=c.get("orcid"),
                    source=SOURCE,
                ),
                sources=[SOURCE],
            )
        )

    # Contributors
    for c in meta.get("contributors", []):
        result.authors.append(
            Author(
                name=PersonName(
                    full_name=c.get("name"),
                    orcid=c.get("orcid"),
                    source=SOURCE,
                ),
                sources=[SOURCE],
            )
        )

    # Files
    for f in rec.get("files", []):
        result.files.append(
            FileInfo(
                filename=f.get("key") or f.get("filename", ""),
                size_bytes=f.get("size") or f.get("filesize"),
                checksum=f.get("checksum"),
                download_url=(f.get("links", {}) or {}).get("download"),
                content_type=f.get("type"),
                source=SOURCE,
            )
        )

    # Stats
    stats = rec.get("stats", {})
    if stats:
        result.usage_stats = UsageStat(
            downloads=stats.get("downloads"),
            unique_downloads=stats.get("unique_downloads"),
            views=stats.get("views"),
            unique_views=stats.get("unique_views"),
            source=SOURCE,
        )

    # Version chain
    relations = meta.get("relations", {})
    version_list = relations.get("version", [])
    version_info = VersionInfo(
        concept_doi=rec.get("conceptdoi"),
        concept_recid=rec.get("conceptrecid"),
        source=SOURCE,
    )
    if version_list:
        v = version_list[0]
        version_info.version_number = v.get("index")
        version_info.is_latest = v.get("is_last")
        version_info.total_versions = v.get("count")
    if meta.get("version"):
        pass  # resource version string, not chain position
    result.version_info = version_info

    # Related identifiers
    for ri in meta.get("related_identifiers", []):
        result.related_works.append(
            RelatedWork(
                identifier=ri.get("identifier", ""),
                identifier_type=ri.get("scheme", "DOI").upper(),
                relation_type=ri.get("relation"),
                resource_type=ri.get("resource_type"),
                source=SOURCE,
            )
        )

    # License
    lic = meta.get("license")
    if lic:
        lic_id = lic.get("id") if isinstance(lic, dict) else str(lic)
        result.licenses.append(License(spdx_id=lic_id, source=SOURCE))

    # Access right
    access = meta.get("access_right")
    if access == "open":
        result.is_oa = True

    # Grants
    for g in meta.get("grants", []):
        funder = g.get("funder", {}) or {}
        result.grants.append(
            Grant(
                grant_id=g.get("code"),
                agency=funder.get("name"),
                funder_doi=funder.get("doi"),
                title=g.get("title"),
                source=SOURCE,
            )
        )
        if funder.get("name"):
            result.funders.append(
                Funder(
                    name=funder["name"],
                    doi=funder.get("doi"),
                    award_numbers=[g["code"]] if g.get("code") else [],
                    source=SOURCE,
                )
            )

    # Keywords
    result.keywords = meta.get("keywords", [])

    # Subjects
    for s in meta.get("subjects", []):
        result.subjects.append(
            Subject(
                value=s.get("term", ""),
                scheme=s.get("scheme"),
                source=SOURCE,
            )
        )

    # Communities
    result.communities = [c.get("id", "") for c in meta.get("communities", [])]

    # Journal (if applicable)
    journal = meta.get("journal", {})
    if journal:
        result.container_title = journal.get("title")
        result.volume = journal.get("volume")
        result.issue = journal.get("issue")
        result.pages = journal.get("pages")

    return result
