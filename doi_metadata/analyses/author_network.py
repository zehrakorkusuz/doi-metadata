"""Author network — disambiguate authors across sources, enrich with ORCID data.

Combines:
- CrossRef → author names with authenticated ORCIDs, sequence (first/additional)
- OpenAlex → authorships with institutions (ROR), is_corresponding, OpenAlex author ID
- S2 → author IDs with name variants
- Europe PMC → authors with ORCID, affiliationDetails
- ORCID → expanded search: given-names, family-names, credit-name, institution
- NIH Reporter → PI names with NIH profile ID, title
- Dryad → authors with affiliationROR/affiliationISNI
- DataCite → creators with nameIdentifiers (ORCID), ROR affiliations
"""

from __future__ import annotations

from collections import defaultdict

from pydantic import BaseModel, Field

from doi_metadata.models import AggregatedResult, Author, SourceName


class AuthorEntry(BaseModel):
    """A single disambiguated author across sources."""
    given: str | None = None
    family: str | None = None
    full_name: str | None = None
    orcid: str | None = None
    authenticated_orcid: bool = False
    # Role
    sequence: str | None = None  # first, additional
    is_corresponding: bool | None = None
    # IDs
    openalex_author_id: str | None = None
    s2_author_id: str | None = None
    nih_profile_id: int | None = None
    # Affiliations from all sources
    affiliations: list[AffiliationEntry] = Field(default_factory=list)
    # Provenance
    sources: list[str] = Field(default_factory=list)
    name_variants: list[str] = Field(default_factory=list)


class AffiliationEntry(BaseModel):
    name: str | None = None
    ror_id: str | None = None
    isni: str | None = None
    country_code: str | None = None
    source: str | None = None


class AuthorNetwork(BaseModel):
    doi: str
    authors: list[AuthorEntry] = Field(default_factory=list)
    total_authors: int = 0
    authors_with_orcid: int = 0
    authors_with_authenticated_orcid: int = 0
    unique_institutions: list[str] = Field(default_factory=list)
    unique_countries: list[str] = Field(default_factory=list)
    orcid_coverage: float | None = None  # fraction of authors with ORCID
    # Cross-source agreement
    author_count_by_source: dict[str, int] = Field(default_factory=dict)
    narrative: str = ""


def _normalize_name(given: str | None, family: str | None) -> str:
    """Create a lowercase key for name matching."""
    g = (given or "").strip().lower()
    f = (family or "").strip().lower()
    return f"{f},{g}" if f else g


def _normalize_orcid(orcid: str | None) -> str | None:
    if not orcid:
        return None
    # Strip URL prefix if present
    orcid = orcid.strip()
    for prefix in ["https://orcid.org/", "http://orcid.org/"]:
        if orcid.startswith(prefix):
            orcid = orcid[len(prefix):]
    return orcid if orcid else None


def analyze_authors(result: AggregatedResult) -> AuthorNetwork:
    network = AuthorNetwork(doi=result.doi)

    # Collect authors from all sources
    all_authors: list[tuple[str, Author]] = []
    for src_name, src in result.sources.items():
        if src.found and src.authors:
            network.author_count_by_source[src_name] = len(src.authors)
            for author in src.authors:
                all_authors.append((src_name, author))

    # Group by ORCID first (strongest signal), then by name
    by_orcid: dict[str, list[tuple[str, Author]]] = defaultdict(list)
    no_orcid: list[tuple[str, Author]] = []

    for src_name, author in all_authors:
        orcid = _normalize_orcid(author.name.orcid)
        if orcid:
            by_orcid[orcid].append((src_name, author))
        else:
            no_orcid.append((src_name, author))

    # Build entries from ORCID groups
    entries: list[AuthorEntry] = []
    used_name_keys: dict[str, int] = {}  # name_key → index in entries

    for orcid, group in by_orcid.items():
        entry = AuthorEntry(orcid=orcid)
        name_variants: set[str] = set()

        for src_name, author in group:
            if src_name not in entry.sources:
                entry.sources.append(src_name)

            # Take the best name info
            if not entry.family and author.name.family:
                entry.family = author.name.family
            if not entry.given and author.name.given:
                entry.given = author.name.given
            if not entry.full_name and author.name.full_name:
                entry.full_name = author.name.full_name
            if author.name.authenticated_orcid:
                entry.authenticated_orcid = True
            if not entry.sequence and author.name.sequence:
                entry.sequence = author.name.sequence
            if author.is_corresponding:
                entry.is_corresponding = True
            if not entry.openalex_author_id and author.openalex_author_id:
                entry.openalex_author_id = author.openalex_author_id
            if not entry.s2_author_id and author.s2_author_id:
                entry.s2_author_id = author.s2_author_id
            if not entry.nih_profile_id and author.nih_profile_id:
                entry.nih_profile_id = author.nih_profile_id

            # Collect name variants
            full = author.name.full_name or f"{author.name.given or ''} {author.name.family or ''}".strip()
            if full:
                name_variants.add(full)

            # Affiliations
            for aff in author.affiliations:
                entry.affiliations.append(AffiliationEntry(
                    name=aff.name,
                    ror_id=aff.ror_id,
                    isni=aff.isni,
                    country_code=aff.country_code,
                    source=src_name,
                ))

        entry.name_variants = sorted(name_variants)
        if not entry.full_name:
            entry.full_name = f"{entry.given or ''} {entry.family or ''}".strip() or None

        name_key = _normalize_name(entry.given, entry.family)
        used_name_keys[name_key] = len(entries)
        entries.append(entry)

    # Try to match no-ORCID authors to existing entries by name, or create new
    for src_name, author in no_orcid:
        name_key = _normalize_name(author.name.given, author.name.family)
        matched = False

        if name_key and name_key in used_name_keys:
            idx = used_name_keys[name_key]
            existing = entries[idx]
            if src_name not in existing.sources:
                existing.sources.append(src_name)
            for aff in author.affiliations:
                existing.affiliations.append(AffiliationEntry(
                    name=aff.name,
                    ror_id=aff.ror_id,
                    isni=aff.isni,
                    country_code=aff.country_code,
                    source=src_name,
                ))
            full = author.name.full_name or f"{author.name.given or ''} {author.name.family or ''}".strip()
            if full and full not in existing.name_variants:
                existing.name_variants.append(full)
            if not existing.openalex_author_id and author.openalex_author_id:
                existing.openalex_author_id = author.openalex_author_id
            if not existing.s2_author_id and author.s2_author_id:
                existing.s2_author_id = author.s2_author_id
            matched = True

        if not matched:
            entry = AuthorEntry(
                given=author.name.given,
                family=author.name.family,
                full_name=(
                    author.name.full_name
                    or f"{author.name.given or ''} {author.name.family or ''}".strip()
                    or None
                ),
                sequence=author.name.sequence,
                is_corresponding=author.is_corresponding,
                openalex_author_id=author.openalex_author_id,
                s2_author_id=author.s2_author_id,
                nih_profile_id=author.nih_profile_id,
                sources=[src_name],
                affiliations=[
                    AffiliationEntry(
                        name=aff.name,
                        ror_id=aff.ror_id,
                        isni=aff.isni,
                        country_code=aff.country_code,
                        source=src_name,
                    )
                    for aff in author.affiliations
                ],
            )
            if name_key:
                used_name_keys[name_key] = len(entries)
            entries.append(entry)

    # Enrich from ORCID records
    orcid_src = result.sources.get(SourceName.ORCID.value)
    if orcid_src and orcid_src.found and orcid_src.orcid_records:
        for rec in orcid_src.orcid_records:
            rec_orcid = _normalize_orcid(rec.get("orcid-id"))
            if not rec_orcid:
                continue
            # Find matching entry
            for entry in entries:
                if entry.orcid == rec_orcid:
                    if rec.get("institution-name") and not any(
                        a.name == rec["institution-name"] for a in entry.affiliations
                    ):
                        entry.affiliations.append(AffiliationEntry(
                            name=rec["institution-name"],
                            source=SourceName.ORCID.value,
                        ))
                    if rec.get("email") and not entry.full_name:
                        pass  # don't overwrite
                    credit_name = rec.get("credit-name")
                    if credit_name and credit_name not in entry.name_variants:
                        entry.name_variants.append(credit_name)
                    break

    network.authors = entries
    network.total_authors = len(entries)
    network.authors_with_orcid = sum(1 for e in entries if e.orcid)
    network.authors_with_authenticated_orcid = sum(1 for e in entries if e.authenticated_orcid)

    if network.total_authors > 0:
        network.orcid_coverage = round(network.authors_with_orcid / network.total_authors, 3)

    # Unique institutions and countries
    institutions: set[str] = set()
    countries: set[str] = set()
    for entry in entries:
        for aff in entry.affiliations:
            if aff.name:
                institutions.add(aff.name)
            if aff.country_code:
                countries.add(aff.country_code)
    network.unique_institutions = sorted(institutions)
    network.unique_countries = sorted(countries)

    # Narrative
    parts: list[str] = []
    parts.append(f"{network.total_authors} unique authors across {len(network.author_count_by_source)} sources")

    if network.authors_with_orcid > 0:
        pct = int((network.orcid_coverage or 0) * 100)
        parts.append(f"{network.authors_with_orcid} have ORCID ({pct}% coverage)")
        if network.authors_with_authenticated_orcid > 0:
            parts.append(f"{network.authors_with_authenticated_orcid} with authenticated ORCID")

    if network.unique_institutions:
        parts.append(f"{len(network.unique_institutions)} institutions")
    if network.unique_countries:
        parts.append(f"Spanning {len(network.unique_countries)} countries ({', '.join(network.unique_countries)})")

    # Check for author count disagreement
    counts = list(network.author_count_by_source.values())
    if counts and max(counts) != min(counts):
        parts.append(
            f"Author count varies: {min(counts)}–{max(counts)} across sources"
        )

    # Multi-source authors
    multi = sum(1 for e in entries if len(e.sources) > 1)
    if multi > 0:
        parts.append(f"{multi} authors confirmed by multiple sources")

    network.narrative = ". ".join(parts) + "." if parts else "No author information found."

    return network
