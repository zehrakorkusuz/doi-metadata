"""OpenAIRE fetcher — EU funding, BIP! indicators, related software, FOS/SDG."""

from __future__ import annotations

import logging

from doi_metadata.config import settings
from doi_metadata.fetchers.base import fetch_json
from doi_metadata.models import (
    Author,
    Grant,
    ImpactIndicator,
    OALocation,
    OAStatus,
    PersonName,
    RelatedWork,
    SourceName,
    SourceResult,
    Subject,
    UsageStat,
)

logger = logging.getLogger(__name__)
SOURCE = SourceName.OPENAIRE


async def fetch_openaire(doi: str) -> SourceResult:
    result = SourceResult(source=SOURCE, doi=doi)

    headers: dict[str, str] = {}
    if settings.openaire_api_key:
        headers["Authorization"] = f"Bearer {settings.openaire_api_key}"

    # Use pid= for exact DOI match (search= does full-text and returns irrelevant results)
    url = "https://api.openaire.eu/graph/v2/researchProducts"
    params = {"pid": doi, "pageSize": "1"}
    try:
        data = await fetch_json(url, params=params, headers=headers, source_name="OpenAIRE")
    except Exception as first_exc:
        # Token may be expired (403) — retry without auth
        if headers:
            logger.info("OpenAIRE: auth failed (%s), retrying without token", first_exc)
            try:
                data = await fetch_json(url, params=params, source_name="OpenAIRE")
            except Exception as exc:
                result.error = str(exc)
                return result
        else:
            result.error = str(first_exc)
            return result

    if not data:
        return result

    results_list = data.get("results", [])
    if not results_list:
        return result

    rec = results_list[0]
    result.found = True
    result.raw = rec

    # Basic metadata
    result.title = rec.get("mainTitle")
    descriptions = rec.get("descriptions", [])
    result.abstract = descriptions[0] if descriptions else None
    result.publication_date = rec.get("publicationDate")
    if result.publication_date:
        try:
            result.publication_year = int(result.publication_date[:4])
        except (ValueError, IndexError):
            pass
    result.work_type = rec.get("type")
    lang = rec.get("language", {})
    result.language = lang.get("code") if isinstance(lang, dict) else None
    result.publisher = rec.get("publisher")

    # Identifiers — PIDs
    for pid in rec.get("pids", []):
        scheme = pid.get("scheme", "").lower()
        value = pid.get("value", "")
        if scheme == "pmid":
            result.pmid = value
        elif scheme == "arxiv":
            result.arxiv_id = value

    # Alternate IDs (the goldmine crosswalk)
    for inst in rec.get("instances", []):
        for alt_id in inst.get("alternateIdentifiers", []):
            id_str = f"{alt_id.get('scheme', '')}:{alt_id.get('value', '')}"
            result.alternate_ids.append(id_str)
        # Also harvest PIDs from instances
        for inst_pid in inst.get("pids", []):
            id_str = f"{inst_pid.get('scheme', '')}:{inst_pid.get('value', '')}"
            if id_str not in result.alternate_ids:
                result.alternate_ids.append(id_str)

    # Authors — v2 nests ORCID under pid.id
    for a in rec.get("authors", []):
        orcid = None
        pid = a.get("pid")
        if pid:
            pid_id = pid.get("id", pid)  # v2: nested under "id"; v1: flat
            if isinstance(pid_id, dict) and pid_id.get("scheme") == "orcid":
                orcid = pid_id.get("value")

        result.authors.append(
            Author(
                name=PersonName(
                    given=a.get("givenName"),
                    family=a.get("familyName"),
                    full_name=a.get("fullName"),
                    orcid=orcid,
                    source=SOURCE,
                ),
                sources=[SOURCE],
            )
        )

    # OA status
    best_access = rec.get("bestAccessRight", {}) or {}
    access_code = best_access.get("code", "").upper()
    if access_code == "OPEN":
        result.is_oa = True
    elif access_code in ("CLOSED", "RESTRICTED", "EMBARGO"):
        result.is_oa = False

    oa_color = rec.get("openAccessColor", "")
    oa_map = {"gold": OAStatus.GOLD, "green": OAStatus.GREEN, "hybrid": OAStatus.HYBRID, "bronze": OAStatus.BRONZE}
    result.oa_status = oa_map.get(oa_color, OAStatus.UNKNOWN)

    if rec.get("isInDiamondJournal"):
        result.oa_status = OAStatus.DIAMOND

    # Instances (per-repository copies)
    for inst in rec.get("instances", []):
        for url in inst.get("urls", []):
            hosted_by = inst.get("hostedby", {}) or {}
            result.oa_locations.append(
                OALocation(
                    url=url,
                    host_type=hosted_by.get("name"),
                    version=inst.get("type"),
                    license=inst.get("license"),
                    source=SOURCE,
                )
            )

    # Impact indicators (BIP!)
    indicators = rec.get("indicators", {}) or {}
    citation_impact = indicators.get("citationImpact", {}) or {}
    # v2 uses e.g. "citationClass" not "citationCountClass"
    class_key_map = {
        "citationCount": "citationClass",
        "influence": "influenceClass",
        "popularity": "popularityClass",
        "impulse": "impulseClass",
    }
    for name in ["citationCount", "influence", "popularity", "impulse"]:
        val = citation_impact.get(name)
        if val is not None:
            cls = citation_impact.get(class_key_map.get(name, f"{name}Class"))
            result.impact_indicators.append(
                ImpactIndicator(name=f"bip_{name}", value=val, class_label=cls, source=SOURCE)
            )

    # PageRank — BIP! influence is a PageRank-derived score on the citation graph
    bip_influence = citation_impact.get("influence")
    if bip_influence is not None:
        result.pagerank = float(bip_influence)

    # Citation count from BIP
    bip_citations = citation_impact.get("citationCount")
    if bip_citations is not None:
        result.citation_count = int(bip_citations)

    # Usage stats
    usage = indicators.get("usageCounts", {}) or {}
    if usage:
        result.usage_stats = UsageStat(
            downloads=usage.get("downloads"),
            views=usage.get("views"),
            source=SOURCE,
        )

    # Projects & Funding (UNIQUE VALUE of OpenAIRE)
    for proj in rec.get("projects", []):
        funder_raw = proj.get("funder", {}) or {}
        # v2 API returns funder as a string; v1 returned a dict
        if isinstance(funder_raw, str):
            funder_name = funder_raw
            funder_short = None
            funder_stream = None
            funder_jurisdiction = None
        else:
            funder_name = funder_raw.get("name")
            funder_short = funder_raw.get("shortName")
            funder_stream = funder_raw.get("fundingStream")
            funder_jurisdiction = funder_raw.get("jurisdiction")
        prov = proj.get("provenance", {}) or {}
        validated = proj.get("validated", {}) or {}
        result.openaire_projects.append(
            Grant(
                grant_id=proj.get("code"),
                agency=funder_name,
                agency_abbreviation=funder_short,
                title=proj.get("title"),
                openaire_project_id=proj.get("id"),
                funding_stream=funder_stream,
                jurisdiction=funder_jurisdiction,
                validated_by_funder=validated.get("validatedByFunder"),
                trust_score=float(prov["trust"]) if prov.get("trust") else None,
                source=SOURCE,
            )
        )
        result.grants.append(result.openaire_projects[-1])

    # Subjects with provenance (FOS, SDG)
    # v2 nests subject data under "subject" key
    for s in rec.get("subjects", []):
        subj = s.get("subject", s)  # v2: nested; v1: flat
        if isinstance(subj, dict):
            value = subj.get("value", "")
            scheme = subj.get("scheme")
        else:
            value = str(subj)
            scheme = None
        prov = s.get("provenance", {}) or {}
        result.subjects.append(
            Subject(
                value=value,
                scheme=scheme,
                score=float(prov["trust"]) if prov and prov.get("trust") else None,
                source=SOURCE,
            )
        )

    # Related software (OpenAIRE unique)
    for rel in rec.get("relatedSoftware", []):
        result.related_software.append(
            RelatedWork(
                identifier=rel.get("id", ""),
                identifier_type="openaire",
                relation_type="RelatedSoftware",
                title=rel.get("name"),
                source=SOURCE,
            )
        )

    # Related data
    for rel in rec.get("relatedDatasets", []):
        result.related_data.append(
            RelatedWork(
                identifier=rel.get("id", ""),
                identifier_type="openaire",
                relation_type="RelatedDataset",
                title=rel.get("name"),
                source=SOURCE,
            )
        )

    return result
