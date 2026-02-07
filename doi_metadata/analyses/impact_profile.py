"""Impact profile — multi-dimensional impact story, not just a citation count.

Combines:
- CrossRef, OpenAlex, S2, Europe PMC, DataCite, OpenAIRE, NIH → citation counts
- OpenAlex → FWCI, citation percentile, counts_by_year
- S2 → influential citation count + ratio
- NIH Reporter → Relative Citation Ratio
- OpenAIRE → BIP! indicators (influence, popularity, impulse) + usage counts
- Zenodo → download/view stats
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from doi_metadata.models import AggregatedResult, SourceName


class CitationComparison(BaseModel):
    """Citation counts from every source that reports one."""
    values: dict[str, int] = Field(default_factory=dict)
    min: int | None = None
    max: int | None = None
    spread: int | None = None  # max - min
    median: int | None = None


class TrendPoint(BaseModel):
    year: int
    count: int


class ImpactProfile(BaseModel):
    doi: str

    # Raw citation counts per source
    citation_comparison: CitationComparison = Field(default_factory=CitationComparison)

    # Field-normalized (OpenAlex)
    fwci: float | None = None
    citation_percentile: float | None = None
    is_top_1_percent: bool | None = None
    is_top_10_percent: bool | None = None

    # Quality signal (S2)
    influential_citation_count: int | None = None
    influential_ratio: float | None = None  # influential / total

    # NIH benchmark
    relative_citation_ratio: float | None = None

    # BIP! indicators (OpenAIRE)
    bip_influence: float | None = None
    bip_influence_class: str | None = None
    bip_popularity: float | None = None
    bip_popularity_class: str | None = None
    bip_impulse: float | None = None
    bip_impulse_class: str | None = None

    # Usage (reads vs cites)
    downloads: int | None = None
    views: int | None = None
    download_source: str | None = None

    # Trend
    citation_trend: list[TrendPoint] = Field(default_factory=list)
    trend_direction: str | None = None  # "rising", "stable", "declining", "peaking"

    # Dataset reuse as impact
    dataset_reuse_count: int = 0

    # Narrative
    narrative: str = ""


def analyze_impact(result: AggregatedResult) -> ImpactProfile:
    profile = ImpactProfile(doi=result.doi)

    # --- Citation counts from every source ---
    counts: dict[str, int] = {}
    for name, src in result.sources.items():
        if src.found and src.citation_count is not None:
            counts[name] = src.citation_count

    vals = sorted(counts.values())
    profile.citation_comparison = CitationComparison(
        values=counts,
        min=vals[0] if vals else None,
        max=vals[-1] if vals else None,
        spread=(vals[-1] - vals[0]) if len(vals) >= 2 else None,
        median=vals[len(vals) // 2] if vals else None,
    )

    # --- Field-normalized impact (OpenAlex) ---
    oa = result.sources.get(SourceName.OPENALEX.value)
    if oa and oa.found:
        for ind in oa.impact_indicators:
            if ind.name == "fwci":
                profile.fwci = ind.value
            elif ind.name == "citation_normalized_percentile":
                profile.citation_percentile = ind.value

        # Check top percentile flags from raw data
        cnp = oa.raw.get("citation_normalized_percentile", {}) if oa.raw else {}
        if cnp:
            profile.is_top_1_percent = cnp.get("is_in_top_1_percent")
            profile.is_top_10_percent = cnp.get("is_in_top_10_percent")

        # Citation trend
        for year, count in sorted(oa.counts_by_year.items()):
            profile.citation_trend.append(TrendPoint(year=year, count=count))

        if len(profile.citation_trend) >= 3:
            recent = [p.count for p in profile.citation_trend[-3:]]
            if recent[-1] > recent[0] * 1.2:
                profile.trend_direction = "rising"
            elif recent[-1] < recent[0] * 0.8:
                profile.trend_direction = "declining"
            elif max(recent) == recent[1]:
                profile.trend_direction = "peaking"
            else:
                profile.trend_direction = "stable"

    # --- Influential citations (S2) ---
    s2 = result.sources.get(SourceName.SEMANTIC_SCHOLAR.value)
    if s2 and s2.found:
        profile.influential_citation_count = s2.influential_citation_count
        if s2.influential_citation_count is not None and s2.citation_count and s2.citation_count > 0:
            profile.influential_ratio = round(s2.influential_citation_count / s2.citation_count, 3)

    # --- NIH Relative Citation Ratio ---
    nih = result.sources.get(SourceName.NIH_REPORTER.value)
    if nih and nih.found:
        profile.relative_citation_ratio = nih.relative_citation_ratio

    # --- BIP! indicators (OpenAIRE) ---
    oaire = result.sources.get(SourceName.OPENAIRE.value)
    if oaire and oaire.found:
        for ind in oaire.impact_indicators:
            if ind.name == "bip_influence":
                profile.bip_influence = ind.value
                profile.bip_influence_class = ind.class_label
            elif ind.name == "bip_popularity":
                profile.bip_popularity = ind.value
                profile.bip_popularity_class = ind.class_label
            elif ind.name == "bip_impulse":
                profile.bip_impulse = ind.value
                profile.bip_impulse_class = ind.class_label

        if oaire.usage_stats:
            profile.downloads = oaire.usage_stats.downloads
            profile.views = oaire.usage_stats.views
            profile.download_source = "openaire"

    # --- Zenodo usage stats (if OpenAIRE didn't have them) ---
    zen = result.sources.get(SourceName.ZENODO.value)
    if zen and zen.found and zen.usage_stats and profile.downloads is None:
        profile.downloads = zen.usage_stats.downloads
        profile.views = zen.usage_stats.views
        profile.download_source = "zenodo"

    # --- Dataset reuse count ---
    profile.dataset_reuse_count = len(result.datacite_linked_datasets)

    # --- Build narrative ---
    parts: list[str] = []
    median = profile.citation_comparison.median
    if median is not None:
        parts.append(f"Cited ~{median} times across sources")
        if profile.citation_comparison.spread and profile.citation_comparison.spread > median * 0.3:
            parts.append(
                f"(counts range {profile.citation_comparison.min}–{profile.citation_comparison.max}, "
                f"significant cross-source divergence)"
            )

    if profile.fwci is not None:
        parts.append(f"FWCI {profile.fwci:.1f}x field average")
    if profile.is_top_1_percent:
        parts.append("Top 1% by citation percentile")
    elif profile.is_top_10_percent:
        parts.append("Top 10% by citation percentile")

    if profile.influential_ratio is not None and profile.influential_ratio > 0.05:
        pct = int(profile.influential_ratio * 100)
        parts.append(f"{pct}% of citations are influential (S2), well above typical ~2%")

    if profile.relative_citation_ratio is not None:
        parts.append(f"RCR {profile.relative_citation_ratio:.1f}x NIH median")

    if profile.trend_direction:
        parts.append(f"Citation trend: {profile.trend_direction}")

    if profile.dataset_reuse_count > 0:
        parts.append(f"{profile.dataset_reuse_count} downstream datasets reference this work")

    if profile.downloads:
        parts.append(f"{profile.downloads:,} downloads")

    profile.narrative = ". ".join(parts) + "." if parts else "Insufficient data for impact narrative."

    return profile
