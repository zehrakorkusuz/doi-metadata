"""Orchestrator — Phase 1→2→3 pipeline for DOI metadata aggregation."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from doi_metadata.crosswalk import build_crosswalk
from doi_metadata.fetchers import ALL_FETCHERS
from doi_metadata.fetchers.base import close_client, fetch_json
from doi_metadata.models import (
    AggregatedResult,
    AnalysesResult,
    RelatedWork,
    SourceName,
    SourceResult,
)
from doi_metadata.reconciliation import reconcile
from doi_metadata.resolver import resolve_registration_agency

logger = logging.getLogger(__name__)


async def lookup(doi: str, *, include_raw: bool = False, follow_links: bool = True) -> AggregatedResult:
    """Run the full 3-phase lookup pipeline for a single DOI."""

    # Phase 0: Resolve registration agency
    agency = await resolve_registration_agency(doi)
    logger.info("DOI %s registered with: %s", doi, agency)

    # Phase 1: Fetch everything in parallel
    logger.info("Phase 1: Fetching all %d sources in parallel...", len(ALL_FETCHERS))
    raw_results: list[SourceResult | BaseException] = await asyncio.gather(
        *(fetcher(doi) for fetcher in ALL_FETCHERS),
        return_exceptions=True,
    )

    # Organize results by source name
    results: dict[str, SourceResult] = {}
    for r in raw_results:
        if isinstance(r, BaseException):
            logger.error("Fetcher error: %s", r)
            continue
        if isinstance(r, SourceResult):
            if not include_raw:
                r.raw = {}
            results[r.source.value] = r
            status = "found" if r.found else ("error: " + (r.error or "not found"))
            logger.info("  %-20s %s", r.source.value, status)

    # Phase 2: Build identifier crosswalk
    logger.info("Phase 2: Building identifier crosswalk...")
    crosswalk = build_crosswalk(doi, results)
    logger.info("  PMID=%s PMCID=%s arXiv=%s ORCIDs=%d ROR=%d",
                crosswalk.pmid, crosswalk.pmcid, crosswalk.arxiv_id,
                len(crosswalk.orcids), len(crosswalk.ror_ids))

    # Phase 3: Follow discovered links
    datacite_linked_datasets: list[RelatedWork] = []
    if follow_links:
        logger.info("Phase 3: Following discovered links...")
        datacite_linked_datasets = await _datacite_reverse_search(doi)
        if datacite_linked_datasets:
            logger.info("  DataCite reverse search: %d linked datasets", len(datacite_linked_datasets))

    # Reconcile conflicts
    logger.info("Reconciling conflicts...")
    conflicts = reconcile(doi, results)
    logger.info("  %d conflicts, %d agreements", conflicts.conflict_count, conflicts.agreement_count)

    # Close HTTP client
    await close_client()

    aggregated = AggregatedResult(
        doi=doi,
        registration_agency=agency,
        retrieved_at=datetime.now(timezone.utc),
        sources=results,
        crosswalk=crosswalk,
        conflicts=conflicts,
        datacite_linked_datasets=datacite_linked_datasets,
    )

    # Phase 4: Derived analyses
    logger.info("Phase 4: Running derived analyses...")
    aggregated.analyses = _run_analyses(aggregated)
    logger.info("  Analyses complete: %s", ", ".join(aggregated.analyses.model_fields.keys()))

    # Phase 5: Comprehensive discrepancy report
    logger.info("Phase 5: Building cross-source discrepancy report...")
    from doi_metadata.reconciliation.discrepancy_report import build_discrepancy_report
    try:
        dr = build_discrepancy_report(aggregated)
        aggregated.discrepancy_report = dr.model_dump(exclude_none=True)
        logger.info("  %d discrepancies (%d high, %d medium, %d low risk)",
                     dr.total_discrepancies, dr.high_risk_count,
                     dr.medium_risk_count, dr.low_risk_count)
    except Exception as e:
        logger.warning("Discrepancy report failed: %s", e)
        aggregated.discrepancy_report = {"error": str(e)}

    return aggregated


def _run_analyses(result: AggregatedResult) -> AnalysesResult:
    """Run all derived analyses and return typed results."""
    from doi_metadata.analyses import (
        analyze_authors,
        analyze_dataset_reuse,
        analyze_funding,
        analyze_grant_siblings,
        analyze_impact,
        analyze_oa,
        analyze_topics,
    )

    data: dict[str, object] = {}
    for name, fn in [
        ("impact", analyze_impact),
        ("funding", analyze_funding),
        ("dataset_reuse", analyze_dataset_reuse),
        ("authors", analyze_authors),
        ("grant_siblings", analyze_grant_siblings),
        ("oa_audit", analyze_oa),
        ("topics", analyze_topics),
    ]:
        try:
            data[name] = fn(result).model_dump(exclude_none=True)
        except Exception as e:
            logger.warning("Analysis '%s' failed: %s", name, e)
            data[name] = {"error": str(e)}

    return AnalysesResult(**data)


async def _datacite_reverse_search(doi: str, max_results: int = 25) -> list[RelatedWork]:
    """Find DataCite records that reference this DOI (dataset reuse discovery)."""
    try:
        data = await fetch_json(
            "https://api.datacite.org/dois",
            params={
                "query": f"relatedIdentifiers.relatedIdentifier:{doi}",
                "page[size]": str(max_results),
            },
            source_name="DataCite-reverse",
        )
    except Exception:
        logger.debug("DataCite reverse search failed for %s", doi)
        return []

    if not data:
        return []

    datasets = []
    for item in data.get("data", []):
        attrs = item.get("attributes", {})
        titles = attrs.get("titles", [])
        title = titles[0].get("title") if titles else None
        datasets.append(
            RelatedWork(
                identifier=attrs.get("doi", item.get("id", "")),
                identifier_type="DOI",
                title=title,
                publisher=attrs.get("publisher") if isinstance(attrs.get("publisher"), str) else None,
                resource_type=attrs.get("types", {}).get("resourceTypeGeneral"),
                source=SourceName.DATACITE,
            )
        )

    return datasets
