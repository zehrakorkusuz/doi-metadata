"""Funding landscape — merged, deduplicated funding map from all sources.

Combines:
- CrossRef → funder name + Funder Registry DOI + award numbers
- Europe PMC → grantId + agency + acronym
- OpenAIRE → EU project linkages with validation, trust, funding stream
- NIH Reporter → full project details: activity code, institute, PI, costs, abstract
- Zenodo → funder + code (from metadata.grants)
- Dryad → funders with CrossRef Funder IDs
- DataCite → fundingReferences with funderIdentifier
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from doi_metadata.models import AggregatedResult, Grant, SourceName


class FundingEntry(BaseModel):
    """A single deduplicated funding entry with all known details."""
    grant_id: str | None = None
    funder_name: str | None = None
    funder_doi: str | None = None  # CrossRef Funder Registry
    funder_ror: str | None = None
    award_numbers: list[str] = Field(default_factory=list)
    title: str | None = None
    # NIH-specific enrichment
    activity_code: str | None = None
    nih_institute: str | None = None
    award_amount: float | None = None
    project_start: str | None = None
    project_end: str | None = None
    pi_names: list[str] = Field(default_factory=list)
    # OpenAIRE-specific
    funding_stream: str | None = None
    jurisdiction: str | None = None
    validated_by_funder: bool | None = None
    trust_score: float | None = None
    openaire_project_id: str | None = None
    # Provenance
    sources: list[str] = Field(default_factory=list)
    sibling_publication_count: int | None = None


class FundingLandscape(BaseModel):
    doi: str
    total_funders: int = 0
    total_grants: int = 0
    entries: list[FundingEntry] = Field(default_factory=list)
    # Breakdown
    nih_grants: list[FundingEntry] = Field(default_factory=list)
    eu_grants: list[FundingEntry] = Field(default_factory=list)
    other_grants: list[FundingEntry] = Field(default_factory=list)
    total_award_amount: float | None = None
    funding_agencies: list[str] = Field(default_factory=list)
    narrative: str = ""


def _normalize_grant_id(gid: str | None) -> str | None:
    if not gid:
        return None
    return gid.strip().upper().replace(" ", "")


def _merge_entry(existing: FundingEntry, grant: Grant, source_name: str) -> None:
    """Merge new grant info into existing entry."""
    if source_name not in existing.sources:
        existing.sources.append(source_name)
    if not existing.funder_name and grant.agency:
        existing.funder_name = grant.agency
    if not existing.funder_doi and grant.funder_doi:
        existing.funder_doi = grant.funder_doi
    if not existing.title and grant.title:
        existing.title = grant.title
    if not existing.activity_code and grant.activity_code:
        existing.activity_code = grant.activity_code
    if not existing.nih_institute and grant.nih_institute:
        existing.nih_institute = grant.nih_institute
    if not existing.award_amount and grant.award_amount:
        existing.award_amount = grant.award_amount
    if not existing.project_start and grant.project_start:
        existing.project_start = grant.project_start
    if not existing.project_end and grant.project_end:
        existing.project_end = grant.project_end
    if grant.pi_names:
        for pi in grant.pi_names:
            if pi and pi not in existing.pi_names:
                existing.pi_names.append(pi)
    if not existing.funding_stream and grant.funding_stream:
        existing.funding_stream = grant.funding_stream
    if not existing.jurisdiction and grant.jurisdiction:
        existing.jurisdiction = grant.jurisdiction
    if grant.validated_by_funder is not None and existing.validated_by_funder is None:
        existing.validated_by_funder = grant.validated_by_funder
    if grant.trust_score is not None and (existing.trust_score is None or grant.trust_score > existing.trust_score):
        existing.trust_score = grant.trust_score
    if not existing.openaire_project_id and grant.openaire_project_id:
        existing.openaire_project_id = grant.openaire_project_id


def analyze_funding(result: AggregatedResult) -> FundingLandscape:
    landscape = FundingLandscape(doi=result.doi)

    # Collect all grants from all sources, dedup by normalized grant_id
    entries_by_id: dict[str, FundingEntry] = {}
    entries_no_id: list[FundingEntry] = []

    for src_name, src in result.sources.items():
        if not src.found:
            continue

        all_grants = src.grants + src.nih_grants + src.openaire_projects

        for grant in all_grants:
            norm_id = _normalize_grant_id(grant.grant_id)

            if norm_id and norm_id in entries_by_id:
                _merge_entry(entries_by_id[norm_id], grant, src_name)
            elif norm_id:
                entry = FundingEntry(
                    grant_id=grant.grant_id,
                    funder_name=grant.agency,
                    funder_doi=grant.funder_doi,
                    title=grant.title,
                    activity_code=grant.activity_code,
                    nih_institute=grant.nih_institute,
                    award_amount=grant.award_amount,
                    project_start=grant.project_start,
                    project_end=grant.project_end,
                    pi_names=list(grant.pi_names),
                    funding_stream=grant.funding_stream,
                    jurisdiction=grant.jurisdiction,
                    validated_by_funder=grant.validated_by_funder,
                    trust_score=grant.trust_score,
                    openaire_project_id=grant.openaire_project_id,
                    sources=[src_name],
                )
                entries_by_id[norm_id] = entry
            else:
                # Grant with no ID — try to dedup by funder name
                entry = FundingEntry(
                    funder_name=grant.agency,
                    funder_doi=grant.funder_doi,
                    sources=[src_name],
                )
                entries_no_id.append(entry)

        # Also harvest from funders[] (CrossRef, DataCite, Dryad)
        for funder in src.funders:
            for award in funder.award_numbers:
                norm_id = _normalize_grant_id(award)
                if norm_id and norm_id in entries_by_id:
                    if src_name not in entries_by_id[norm_id].sources:
                        entries_by_id[norm_id].sources.append(src_name)
                    if not entries_by_id[norm_id].funder_doi and funder.doi:
                        entries_by_id[norm_id].funder_doi = funder.doi
                elif norm_id:
                    entries_by_id[norm_id] = FundingEntry(
                        grant_id=award,
                        funder_name=funder.name,
                        funder_doi=funder.doi,
                        funder_ror=funder.ror_id,
                        sources=[src_name],
                    )

    # NIH sibling counts
    nih = result.sources.get(SourceName.NIH_REPORTER.value)
    if nih and nih.found:
        for grant in nih.nih_grants:
            norm_id = _normalize_grant_id(grant.grant_id)
            if norm_id and norm_id in entries_by_id:
                entries_by_id[norm_id].sibling_publication_count = len(nih.sibling_pmids)

    # Assemble
    all_entries = list(entries_by_id.values()) + entries_no_id
    landscape.entries = all_entries
    landscape.total_grants = len(all_entries)

    # Unique funder names
    funder_names: set[str] = set()
    for e in all_entries:
        if e.funder_name:
            funder_names.add(e.funder_name)
    landscape.funding_agencies = sorted(funder_names)
    landscape.total_funders = len(funder_names)

    # Classify
    for e in all_entries:
        is_nih = (
            e.activity_code is not None
            or (e.funder_name and "NIH" in e.funder_name.upper())
            or (e.funder_name and "National Institute" in (e.funder_name or ""))
        )
        is_eu = (
            e.jurisdiction == "EU"
            or (e.funding_stream and "H2020" in (e.funding_stream or ""))
            or (e.funder_name and "European" in (e.funder_name or ""))
        )

        if is_nih:
            landscape.nih_grants.append(e)
        elif is_eu:
            landscape.eu_grants.append(e)
        else:
            landscape.other_grants.append(e)

    # Total award amount (from entries that have it)
    amounts = [e.award_amount for e in all_entries if e.award_amount]
    if amounts:
        landscape.total_award_amount = sum(amounts)

    # Narrative
    parts: list[str] = []
    if landscape.total_grants > 0:
        parts.append(f"Funded by {landscape.total_funders} agencies across {landscape.total_grants} grants")
    if landscape.nih_grants:
        codes = set(e.activity_code for e in landscape.nih_grants if e.activity_code)
        institutes = set(e.nih_institute for e in landscape.nih_grants if e.nih_institute)
        parts.append(
            f"{len(landscape.nih_grants)} NIH grants"
            + (f" ({', '.join(sorted(codes))})" if codes else "")
            + (f" from {', '.join(sorted(institutes))}" if institutes else "")
        )
    if landscape.eu_grants:
        parts.append(f"{len(landscape.eu_grants)} EU grants")
        validated = [e for e in landscape.eu_grants if e.validated_by_funder]
        if validated:
            parts.append(f"{len(validated)} validated by funder")
    if landscape.total_award_amount:
        parts.append(f"Total known funding: ${landscape.total_award_amount:,.0f}")

    # Sources corroboration
    multi_source = [e for e in all_entries if len(e.sources) > 1]
    if multi_source:
        parts.append(f"{len(multi_source)} grants confirmed by multiple sources")

    landscape.narrative = ". ".join(parts) + "." if parts else "No funding information found."

    return landscape
