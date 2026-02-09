"""Comprehensive cross-source discrepancy report.

Pulls together ALL disagreements across the 11 sources into a single unified
report. Goes beyond scalar field comparison (engine.py) to surface deep
discrepancies in citations, OA status, authors, funding, topics, and related
works — drawing from both raw source data and the derived analyses.

Output: a DiscrepancyReport with per-domain sections, overall trust scores,
and a human-readable narrative suitable for inclusion in the summary output.
"""

from __future__ import annotations

from collections import Counter
from statistics import median as stat_median

from pydantic import BaseModel, Field

from doi_metadata.models import AggregatedResult, OAStatus, SourceName

# ---------------------------------------------------------------------------
# Sub-report models
# ---------------------------------------------------------------------------


class SourceCoverage(BaseModel):
    """Which sources returned data and which didn't."""
    source: str
    found: bool = False
    error: str | None = None
    has_title: bool = False
    has_citations: bool = False
    has_authors: bool = False
    has_oa_info: bool = False
    has_funding: bool = False
    has_subjects: bool = False
    has_related_works: bool = False


class ScalarDiscrepancy(BaseModel):
    """A single field where sources disagree on a scalar value."""
    field: str
    values: dict[str, object]  # source → value
    risk: str = "medium"  # low, medium, high
    spread: float | None = None  # for numeric fields: max - min
    spread_pct: float | None = None  # spread as % of max


class CitationDiscrepancy(BaseModel):
    """Detailed citation count divergence analysis."""
    counts_by_source: dict[str, int] = Field(default_factory=dict)
    min_count: int | None = None
    max_count: int | None = None
    median_count: int | None = None
    spread: int | None = None
    spread_pct: float | None = None  # spread as % of max
    divergence_level: str = "none"  # none, low (<20%), medium (20-50%), high (>50%)
    outlier_sources: list[str] = Field(default_factory=list)  # sources far from median


class OADiscrepancy(BaseModel):
    """OA status disagreements across sources."""
    is_oa_by_source: dict[str, bool] = Field(default_factory=dict)
    status_by_source: dict[str, str] = Field(default_factory=dict)
    is_oa_agrees: bool = True
    status_agrees: bool = True
    consensus_is_oa: bool | None = None
    consensus_status: str | None = None
    unique_oa_urls: int = 0
    sources_only_in: dict[str, list[str]] = Field(default_factory=dict)  # source → URLs only it found


class AuthorDiscrepancy(BaseModel):
    """Author list disagreements across sources."""
    count_by_source: dict[str, int] = Field(default_factory=dict)
    count_agrees: bool = True
    min_count: int | None = None
    max_count: int | None = None
    orcid_coverage: float | None = None
    sources_missing_orcids: list[str] = Field(default_factory=list)
    name_variant_examples: list[str] = Field(default_factory=list)  # examples of name disagreements


class FundingDiscrepancy(BaseModel):
    """Funding information gaps and conflicts."""
    grant_count_by_source: dict[str, int] = Field(default_factory=dict)
    total_unique_grants: int = 0
    grants_single_source: int = 0  # grants appearing in only one source
    grants_multi_source: int = 0  # grants confirmed by 2+ sources
    sources_with_no_funding: list[str] = Field(default_factory=list)
    sources_with_funding: list[str] = Field(default_factory=list)


class ReferenceDiscrepancy(BaseModel):
    """Reference/bibliography disagreements."""
    count_by_source: dict[str, int] = Field(default_factory=dict)
    count_agrees: bool = True
    min_count: int | None = None
    max_count: int | None = None


class TopicDiscrepancy(BaseModel):
    """Topic/subject classification gaps across vocabularies."""
    vocabulary_count: int = 0
    topics_by_source: dict[str, int] = Field(default_factory=dict)
    multi_source_topics: int = 0  # topics confirmed by 2+ sources
    single_source_topics: int = 0


class RelatedWorksDiscrepancy(BaseModel):
    """Related works / dataset linkage gaps."""
    related_count_by_source: dict[str, int] = Field(default_factory=dict)
    datacite_reverse_count: int = 0
    software_links: int = 0
    data_links: int = 0
    has_version_chain: bool = False


# ---------------------------------------------------------------------------
# Main report
# ---------------------------------------------------------------------------


class DiscrepancyReport(BaseModel):
    """Comprehensive cross-source discrepancy report for a single DOI."""
    doi: str

    # Overall metrics
    sources_queried: int = 11
    sources_found: int = 0
    sources_not_found: int = 0
    sources_errored: int = 0
    total_discrepancies: int = 0
    high_risk_count: int = 0
    medium_risk_count: int = 0
    low_risk_count: int = 0
    data_completeness_score: float | None = None  # 0-1, fraction of fields with 2+ sources

    # Coverage matrix
    source_coverage: list[SourceCoverage] = Field(default_factory=list)

    # Per-domain discrepancy sections
    scalar_discrepancies: list[ScalarDiscrepancy] = Field(default_factory=list)
    citations: CitationDiscrepancy = Field(default_factory=CitationDiscrepancy)
    oa_status: OADiscrepancy = Field(default_factory=OADiscrepancy)
    authors: AuthorDiscrepancy = Field(default_factory=AuthorDiscrepancy)
    funding: FundingDiscrepancy = Field(default_factory=FundingDiscrepancy)
    references: ReferenceDiscrepancy = Field(default_factory=ReferenceDiscrepancy)
    topics: TopicDiscrepancy = Field(default_factory=TopicDiscrepancy)
    related_works: RelatedWorksDiscrepancy = Field(default_factory=RelatedWorksDiscrepancy)

    # Narrative summary
    narrative: str = ""


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------


def build_discrepancy_report(result: AggregatedResult) -> DiscrepancyReport:
    """Build a comprehensive discrepancy report from an aggregated result."""
    report = DiscrepancyReport(doi=result.doi)

    _build_coverage(report, result)
    _build_scalar_discrepancies(report, result)
    _build_citation_discrepancy(report, result)
    _build_oa_discrepancy(report, result)
    _build_author_discrepancy(report, result)
    _build_funding_discrepancy(report, result)
    _build_reference_discrepancy(report, result)
    _build_topic_discrepancy(report, result)
    _build_related_works_discrepancy(report, result)
    _build_completeness_score(report, result)
    _count_totals(report)
    _build_narrative(report, result)

    return report


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------


def _build_coverage(report: DiscrepancyReport, result: AggregatedResult) -> None:
    for src_name, src in result.sources.items():
        cov = SourceCoverage(
            source=src_name,
            found=src.found,
            error=src.error,
        )
        if src.found:
            report.sources_found += 1
            cov.has_title = bool(src.title)
            cov.has_citations = src.citation_count is not None
            cov.has_authors = bool(src.authors)
            cov.has_oa_info = src.is_oa is not None or src.oa_status is not None
            cov.has_funding = bool(src.funders or src.grants or src.nih_grants or src.openaire_projects)
            cov.has_subjects = bool(src.subjects or src.mesh_terms or src.keywords)
            cov.has_related_works = bool(src.related_works or src.related_software or src.related_data)
        elif src.error:
            report.sources_errored += 1
        else:
            report.sources_not_found += 1
        report.source_coverage.append(cov)


def _build_scalar_discrepancies(report: DiscrepancyReport, result: AggregatedResult) -> None:
    """Compare scalar metadata fields across sources."""
    checks: list[tuple[str, str, object]] = [
        ("title", "low", lambda r: r.title.strip().rstrip(".") if r.title else None),
        ("publication_year", "low", lambda r: r.publication_year),
        ("work_type", "low", lambda r: r.work_type),
        ("publisher", "low", lambda r: r.publisher),
        ("container_title", "low", lambda r: r.container_title),
    ]

    for field, risk, extractor in checks:
        values: dict[str, object] = {}
        for name, src in result.sources.items():
            if not src.found:
                continue
            val = extractor(src)
            if val is not None:
                values[name] = val

        if len(values) <= 1:
            continue

        unique = set(str(v) for v in values.values())
        if len(unique) > 1:
            report.scalar_discrepancies.append(
                ScalarDiscrepancy(field=field, values=values, risk=risk)
            )


def _build_citation_discrepancy(report: DiscrepancyReport, result: AggregatedResult) -> None:
    counts: dict[str, int] = {}
    for name, src in result.sources.items():
        if src.found and src.citation_count is not None:
            counts[name] = src.citation_count

    if not counts:
        return

    vals = sorted(counts.values())
    cd = CitationDiscrepancy(
        counts_by_source=counts,
        min_count=vals[0],
        max_count=vals[-1],
        median_count=int(stat_median(vals)),
        spread=vals[-1] - vals[0] if len(vals) >= 2 else 0,
    )

    if cd.max_count and cd.max_count > 0 and cd.spread is not None:
        cd.spread_pct = round(cd.spread / cd.max_count * 100, 1)

        if cd.spread_pct > 50:
            cd.divergence_level = "high"
        elif cd.spread_pct > 20:
            cd.divergence_level = "medium"
        elif cd.spread_pct > 0:
            cd.divergence_level = "low"

    # Find outliers (>30% away from median)
    if cd.median_count and cd.median_count > 0:
        for src, count in counts.items():
            pct_diff = abs(count - cd.median_count) / cd.median_count
            if pct_diff > 0.3:
                cd.outlier_sources.append(src)

    report.citations = cd


def _build_oa_discrepancy(report: DiscrepancyReport, result: AggregatedResult) -> None:
    oa_disc = OADiscrepancy()

    for name, src in result.sources.items():
        if not src.found:
            continue
        if src.is_oa is not None:
            oa_disc.is_oa_by_source[name] = src.is_oa
        if src.oa_status and src.oa_status != OAStatus.UNKNOWN:
            oa_disc.status_by_source[name] = src.oa_status.value

    # Check is_oa agreement
    if oa_disc.is_oa_by_source:
        unique_oa = set(oa_disc.is_oa_by_source.values())
        oa_disc.is_oa_agrees = len(unique_oa) <= 1
        votes = list(oa_disc.is_oa_by_source.values())
        oa_disc.consensus_is_oa = sum(votes) > len(votes) / 2

    # Check status agreement
    if oa_disc.status_by_source:
        unique_status = set(oa_disc.status_by_source.values())
        oa_disc.status_agrees = len(unique_status) <= 1
        if len(unique_status) == 1:
            oa_disc.consensus_status = unique_status.pop()
        else:
            # Unpaywall is canonical
            if SourceName.UNPAYWALL.value in oa_disc.status_by_source:
                oa_disc.consensus_status = oa_disc.status_by_source[SourceName.UNPAYWALL.value]
            else:
                most_common = Counter(oa_disc.status_by_source.values()).most_common(1)
                if most_common:
                    oa_disc.consensus_status = most_common[0][0]

    # Count unique OA URLs and track source-exclusive URLs
    url_to_sources: dict[str, list[str]] = {}
    for name, src in result.sources.items():
        if not src.found:
            continue
        for loc in src.oa_locations:
            url = loc.url or loc.pdf_url or loc.landing_page_url
            if url:
                url_to_sources.setdefault(url, []).append(name)

    oa_disc.unique_oa_urls = len(url_to_sources)
    for url, sources in url_to_sources.items():
        if len(sources) == 1:
            oa_disc.sources_only_in.setdefault(sources[0], []).append(url)

    report.oa_status = oa_disc


def _build_author_discrepancy(report: DiscrepancyReport, result: AggregatedResult) -> None:
    ad = AuthorDiscrepancy()

    for name, src in result.sources.items():
        if src.found and src.authors:
            ad.count_by_source[name] = len(src.authors)

    if ad.count_by_source:
        vals = list(ad.count_by_source.values())
        ad.min_count = min(vals)
        ad.max_count = max(vals)
        ad.count_agrees = ad.min_count == ad.max_count

    # Check ORCID coverage per source
    for name, src in result.sources.items():
        if src.found and src.authors:
            has_orcid = sum(1 for a in src.authors if a.name.orcid)
            if has_orcid == 0 and len(src.authors) > 0:
                ad.sources_missing_orcids.append(name)

    # Compute overall ORCID coverage from analyses if available
    authors_data = result.analyses.authors
    if isinstance(authors_data, dict) and "orcid_coverage" in authors_data:
        ad.orcid_coverage = authors_data["orcid_coverage"]

    # Find name variant examples from analyses
    if isinstance(authors_data, dict) and "authors" in authors_data:
        for author in authors_data["authors"][:5]:
            if isinstance(author, dict):
                variants = author.get("name_variants", [])
                if len(variants) > 1:
                    ad.name_variant_examples.append(f"{variants[0]} / {variants[1]}")
                    if len(ad.name_variant_examples) >= 3:
                        break

    report.authors = ad


def _build_funding_discrepancy(report: DiscrepancyReport, result: AggregatedResult) -> None:
    fd = FundingDiscrepancy()

    for name, src in result.sources.items():
        if not src.found:
            continue
        all_grants = src.funders + src.grants + src.nih_grants + src.openaire_projects
        count = len(all_grants)
        if count > 0:
            fd.grant_count_by_source[name] = count
            fd.sources_with_funding.append(name)
        else:
            fd.sources_with_no_funding.append(name)

    # Use analyses data for multi-source grant info
    funding_data = result.analyses.funding
    if isinstance(funding_data, dict):
        entries = funding_data.get("entries", [])
        fd.total_unique_grants = len(entries)
        for entry in entries:
            if isinstance(entry, dict):
                src_list = entry.get("sources", [])
                if len(src_list) > 1:
                    fd.grants_multi_source += 1
                else:
                    fd.grants_single_source += 1

    report.funding = fd


def _build_reference_discrepancy(report: DiscrepancyReport, result: AggregatedResult) -> None:
    rd = ReferenceDiscrepancy()

    for name, src in result.sources.items():
        if src.found and src.reference_count is not None:
            rd.count_by_source[name] = src.reference_count
        elif src.found and src.references:
            rd.count_by_source[name] = len(src.references)

    if rd.count_by_source:
        vals = list(rd.count_by_source.values())
        rd.min_count = min(vals)
        rd.max_count = max(vals)
        rd.count_agrees = rd.min_count == rd.max_count

    report.references = rd


def _build_topic_discrepancy(report: DiscrepancyReport, result: AggregatedResult) -> None:
    td = TopicDiscrepancy()

    for name, src in result.sources.items():
        if not src.found:
            continue
        count = len(src.subjects) + len(src.mesh_terms) + len(src.keywords)
        if count > 0:
            td.topics_by_source[name] = count

    # Use analyses data for multi-source topic info
    topic_data = result.analyses.topics
    if isinstance(topic_data, dict):
        td.vocabulary_count = topic_data.get("vocabulary_count", 0)
        # Count multi-source vs single-source topics
        for topic_list_key in ["fields_of_study", "keywords"]:
            for topic in topic_data.get(topic_list_key, []):
                if isinstance(topic, dict):
                    srcs = topic.get("sources", [])
                    if len(srcs) > 1:
                        td.multi_source_topics += 1
                    else:
                        td.single_source_topics += 1

    report.topics = td


def _build_related_works_discrepancy(report: DiscrepancyReport, result: AggregatedResult) -> None:
    rwd = RelatedWorksDiscrepancy()

    for name, src in result.sources.items():
        if not src.found:
            continue
        count = len(src.related_works)
        if count > 0:
            rwd.related_count_by_source[name] = count
        rwd.software_links += len(src.related_software)
        rwd.data_links += len(src.related_data)
        if src.version_info:
            rwd.has_version_chain = True

    rwd.datacite_reverse_count = len(result.datacite_linked_datasets)

    report.related_works = rwd


def _build_completeness_score(report: DiscrepancyReport, result: AggregatedResult) -> None:
    """Score data completeness: fraction of key fields with 2+ source coverage."""
    checks = 0
    covered = 0

    def count_coverage(extractor):
        nonlocal checks, covered
        checks += 1
        n = sum(1 for src in result.sources.values() if src.found and extractor(src))
        if n >= 2:
            covered += 1

    count_coverage(lambda s: s.title)
    count_coverage(lambda s: s.citation_count is not None)
    count_coverage(lambda s: s.authors)
    count_coverage(lambda s: s.is_oa is not None)
    count_coverage(lambda s: s.funders or s.grants or s.nih_grants or s.openaire_projects)
    count_coverage(lambda s: s.subjects or s.mesh_terms or s.keywords)
    count_coverage(lambda s: s.reference_count is not None or s.references)
    count_coverage(lambda s: s.publication_year is not None)

    if checks > 0:
        report.data_completeness_score = round(covered / checks, 3)


def _count_totals(report: DiscrepancyReport) -> None:
    """Count total discrepancies by risk level."""
    # Scalars
    for d in report.scalar_discrepancies:
        if d.risk == "high":
            report.high_risk_count += 1
        elif d.risk == "medium":
            report.medium_risk_count += 1
        else:
            report.low_risk_count += 1

    # Citations
    if report.citations.divergence_level == "high":
        report.high_risk_count += 1
    elif report.citations.divergence_level == "medium":
        report.medium_risk_count += 1
    elif report.citations.divergence_level == "low":
        report.low_risk_count += 1

    # OA
    if not report.oa_status.is_oa_agrees:
        report.high_risk_count += 1
    if not report.oa_status.status_agrees and report.oa_status.status_by_source:
        report.medium_risk_count += 1

    # Authors
    if not report.authors.count_agrees and report.authors.count_by_source:
        report.high_risk_count += 1

    # References
    if not report.references.count_agrees and report.references.count_by_source:
        report.low_risk_count += 1

    report.total_discrepancies = (
        report.high_risk_count + report.medium_risk_count + report.low_risk_count
    )


def _build_narrative(report: DiscrepancyReport, result: AggregatedResult) -> None:
    """Build a human-readable narrative of discrepancies."""
    parts: list[str] = []

    # Coverage
    parts.append(
        f"{report.sources_found} of {report.sources_found + report.sources_not_found + report.sources_errored} "
        f"sources returned data"
    )

    if report.data_completeness_score is not None:
        pct = int(report.data_completeness_score * 100)
        parts.append(f"Data completeness: {pct}% of key fields have 2+ source coverage")

    # Citations
    cd = report.citations
    if cd.counts_by_source and cd.spread is not None and cd.spread > 0:
        parts.append(
            f"CITATIONS: {cd.min_count:,}–{cd.max_count:,} across {len(cd.counts_by_source)} sources "
            f"({cd.divergence_level} divergence, {cd.spread_pct:.0f}% spread)"
        )
        if cd.outlier_sources:
            parts.append(f"  Outlier sources: {', '.join(cd.outlier_sources)}")

    # OA
    oa = report.oa_status
    if not oa.status_agrees and oa.status_by_source:
        status_str = ", ".join(f"{k}: {v}" for k, v in oa.status_by_source.items())
        parts.append(f"OA STATUS CONFLICT: {status_str}")
    if not oa.is_oa_agrees:
        oa_str = ", ".join(f"{k}: {'OA' if v else 'closed'}" for k, v in oa.is_oa_by_source.items())
        parts.append(f"OA BOOLEAN CONFLICT: {oa_str}")
    if oa.sources_only_in:
        exclusive_count = sum(len(urls) for urls in oa.sources_only_in.values())
        parts.append(f"{exclusive_count} OA URLs found by only one source")

    # Authors
    ad = report.authors
    if not ad.count_agrees and ad.count_by_source:
        counts_str = ", ".join(f"{k}: {v}" for k, v in ad.count_by_source.items())
        parts.append(f"AUTHOR COUNT VARIES: {ad.min_count}–{ad.max_count} ({counts_str})")
    if ad.name_variant_examples:
        parts.append(f"Name variants detected: {'; '.join(ad.name_variant_examples[:2])}")

    # Funding
    fd = report.funding
    if fd.total_unique_grants > 0:
        parts.append(
            f"FUNDING: {fd.total_unique_grants} unique grants — "
            f"{fd.grants_multi_source} confirmed by multiple sources, "
            f"{fd.grants_single_source} from single source only"
        )

    # References
    rd = report.references
    if not rd.count_agrees and rd.count_by_source:
        parts.append(f"REFERENCES: {rd.min_count}–{rd.max_count} across sources")

    # Scalars
    for d in report.scalar_discrepancies:
        vals_str = ", ".join(f"{k}: {v}" for k, v in d.values.items())
        parts.append(f"{d.field.upper()} DIFFERS: {vals_str}")

    # Risk summary
    if report.total_discrepancies > 0:
        parts.append(
            f"Total: {report.total_discrepancies} discrepancies "
            f"({report.high_risk_count} high, {report.medium_risk_count} medium, "
            f"{report.low_risk_count} low risk)"
        )

    report.narrative = ". ".join(parts) + "." if parts else "No discrepancies detected — all sources agree."
