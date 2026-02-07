"""NIH Reporter fetcher — grant↔publication linkages, project details, sibling PMIDs."""

from __future__ import annotations

import logging

from doi_metadata.fetchers.base import fetch_json
from doi_metadata.models import (
    Affiliation,
    Author,
    Grant,
    ImpactIndicator,
    PersonName,
    SourceName,
    SourceResult,
)

logger = logging.getLogger(__name__)
SOURCE = SourceName.NIH_REPORTER


async def fetch_nih_reporter(doi: str) -> SourceResult:
    result = SourceResult(source=SOURCE, doi=doi)

    # Step 1: Search publications by DOI
    try:
        pub_data = await fetch_json(
            "https://api.reporter.nih.gov/v2/publications/search",
            method="POST",
            json_body={"criteria": {"doi": doi}, "offset": 0, "limit": 50},
            source_name="NIH-publications",
        )
    except Exception as exc:
        result.error = str(exc)
        return result

    if not pub_data:
        return result

    pub_results = pub_data.get("results", [])
    if not pub_results:
        return result

    result.found = True
    result.raw = pub_data

    # Process each publication result (often multiple grants per DOI)
    grant_numbers: set[str] = set()
    all_pmids: set[int] = set()

    for pub in pub_results:
        # Basic metadata from first result
        if not result.title:
            result.title = pub.get("title")
            result.pmid = str(pub["pmid"]) if pub.get("pmid") else None
            result.pmcid = pub.get("pmcid")
            result.publication_year = pub.get("pubYear")
            result.publication_date = pub.get("pubDate")
            result.container_title = pub.get("journal")
            result.volume = pub.get("journalVolume")
            result.issue = pub.get("journalIssue")
            result.pages = pub.get("pagination")
            result.language = pub.get("language")

        # Citation metrics
        if pub.get("citationCount") is not None and result.citation_count is None:
            result.citation_count = pub["citationCount"]
        rcr = pub.get("relCitationRatio")
        if rcr is not None and result.relative_citation_ratio is None:
            result.relative_citation_ratio = rcr
            result.impact_indicators.append(
                ImpactIndicator(name="relative_citation_ratio", value=rcr, source=SOURCE)
            )

        # Authors
        if not result.authors:
            for a in pub.get("authorList", []) or []:
                result.authors.append(
                    Author(
                        name=PersonName(
                            given=a.get("firstName"),
                            family=a.get("lastName"),
                            full_name=f"{a.get('firstName', '')} {a.get('middleName', '')} {a.get('lastName', '')}".replace("  ", " ").strip(),
                            orcid=a.get("orcid"),
                            source=SOURCE,
                        ),
                        affiliations=[Affiliation(name=a["affiliation"], source=SOURCE)] if a.get("affiliation") else [],
                        is_corresponding=a.get("isCorrespondingAuthor"),
                        nih_profile_id=None,
                        sources=[SOURCE],
                    )
                )

        # Collect grant numbers
        core_proj = pub.get("coreProjectNum")
        if core_proj:
            grant_numbers.add(core_proj)

    # Step 2: For each grant, fetch project details and sibling publications
    for grant_num in grant_numbers:
        try:
            proj_data = await fetch_json(
                "https://api.reporter.nih.gov/v2/projects/search",
                method="POST",
                json_body={
                    "criteria": {"project_nums": [grant_num]},
                    "offset": 0,
                    "limit": 1,
                    "sort_field": "fiscal_year",
                    "sort_order": "desc",
                },
                source_name="NIH-projects",
            )
        except Exception:
            logger.debug("NIH project fetch failed for %s", grant_num)
            continue

        if not proj_data or not proj_data.get("results"):
            # Still record the grant with minimal info
            result.nih_grants.append(Grant(grant_id=grant_num, source=SOURCE))
            continue

        proj = proj_data["results"][0]
        org = proj.get("organization", {}) or {}

        # PI names
        pi_names = []
        for pi in proj.get("principal_investigators", []) or []:
            pi_names.append(pi.get("full_name", ""))

        # Funding breakdown
        agency_fundings = proj.get("agency_ic_fundings", []) or []
        nih_institute = None
        total_cost = None
        for af in agency_fundings:
            nih_institute = af.get("abbreviation") or af.get("name")
            total_cost = af.get("total_cost")
            break  # take first

        result.nih_grants.append(
            Grant(
                grant_id=grant_num,
                agency="NIH",
                agency_abbreviation=nih_institute,
                title=proj.get("project_title"),
                activity_code=proj.get("activity_code"),
                nih_institute=nih_institute,
                award_amount=total_cost or proj.get("award_amount"),
                project_start=proj.get("project_start_date"),
                project_end=proj.get("project_end_date"),
                pi_names=pi_names,
                source=SOURCE,
            )
        )
        result.grants.append(result.nih_grants[-1])

    # Step 3: Collect sibling PMIDs from linked publications
    for grant_num in grant_numbers:
        try:
            sibling_data = await fetch_json(
                "https://api.reporter.nih.gov/v2/publications/search",
                method="POST",
                json_body={
                    "criteria": {"core_project_nums": [grant_num]},
                    "offset": 0,
                    "limit": 50,
                },
                source_name="NIH-siblings",
            )
        except Exception:
            continue

        if sibling_data and sibling_data.get("results"):
            for sib in sibling_data["results"]:
                pmid = sib.get("pmid")
                if pmid:
                    all_pmids.add(pmid)

    # Remove the input DOI's own PMID from siblings
    own_pmid = int(result.pmid) if result.pmid and result.pmid.isdigit() else None
    all_pmids.discard(own_pmid)
    result.sibling_pmids = sorted(all_pmids)

    return result
