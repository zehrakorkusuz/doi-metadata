"""OA audit — cross-source open access verification.

Combines:
- Unpaywall → oa_status (gold/green/hybrid/bronze/closed), best_oa_location, all locations
- OpenAlex → oa_status, oa_locations with version info
- OpenAIRE → bestAccessRight, openAccessColor, isInDiamondJournal, instance-level access
- Europe PMC → isOpenAccess, full text URLs, license

Cross-checks OA claims across sources. A paper may be "gold" in Unpaywall
but "green" in OpenAlex if they disagree on the primary location. Some
repositories report OA that Unpaywall hasn't found yet, and vice versa.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from doi_metadata.models import AggregatedResult, OAStatus, SourceName


class OASourceClaim(BaseModel):
    """What a single source says about OA status."""
    source: str
    is_oa: bool | None = None
    oa_status: str | None = None  # gold, green, hybrid, bronze, closed, diamond
    best_url: str | None = None
    version: str | None = None  # publishedVersion, acceptedVersion
    license: str | None = None
    host_type: str | None = None  # publisher, repository
    evidence: str | None = None  # how OA was determined


class OALocation(BaseModel):
    """A single OA location discovered across all sources."""
    url: str
    pdf_url: str | None = None
    host_type: str | None = None
    version: str | None = None
    license: str | None = None
    repository: str | None = None
    is_best: bool = False
    evidence: str | None = None
    sources: list[str] = Field(default_factory=list)


class OAAudit(BaseModel):
    doi: str

    # Per-source OA claims
    source_claims: list[OASourceClaim] = Field(default_factory=list)

    # Consensus
    consensus_is_oa: bool | None = None
    consensus_status: str | None = None
    status_agrees: bool = False

    # All unique OA locations
    all_locations: list[OALocation] = Field(default_factory=list)
    total_locations: int = 0

    # Special flags
    is_diamond: bool | None = None  # OpenAIRE only
    has_publisher_version: bool = False
    has_accepted_manuscript: bool = False
    has_repository_copy: bool = False

    # License info
    licenses_found: list[str] = Field(default_factory=list)

    # Conflicts
    status_conflict: bool = False
    conflicting_statuses: dict[str, str] = Field(default_factory=dict)

    narrative: str = ""


def _normalize_status(status: OAStatus | str | None) -> str | None:
    if status is None:
        return None
    s = str(status).lower().strip()
    # Map variations
    for prefix in ["oastatus.", "oa_status."]:
        if s.startswith(prefix):
            s = s[len(prefix):]
    return s


def analyze_oa(result: AggregatedResult) -> OAAudit:
    audit = OAAudit(doi=result.doi)

    # Collect per-source OA claims
    oa_claims: list[OASourceClaim] = []

    for src_name, src in result.sources.items():
        if not src.found:
            continue

        if src.is_oa is not None or src.oa_status is not None:
            claim = OASourceClaim(
                source=src_name,
                is_oa=src.is_oa,
                oa_status=_normalize_status(src.oa_status),
                best_url=src.best_oa_url,
            )

            # Get best location details
            if src.oa_locations:
                best = next((loc for loc in src.oa_locations if loc.is_best), None) or (
                    src.oa_locations[0] if src.oa_locations else None
                )
                if best:
                    claim.version = best.version
                    claim.license = best.license
                    claim.host_type = best.host_type
                    claim.evidence = best.evidence

            oa_claims.append(claim)

    audit.source_claims = oa_claims

    # Consensus: majority vote on is_oa
    oa_votes = [c.is_oa for c in oa_claims if c.is_oa is not None]
    if oa_votes:
        audit.consensus_is_oa = sum(oa_votes) > len(oa_votes) / 2

    # Status consensus
    statuses = {c.source: c.oa_status for c in oa_claims if c.oa_status and c.oa_status != "unknown"}
    unique_statuses = set(statuses.values())

    if len(unique_statuses) == 1:
        audit.consensus_status = unique_statuses.pop()
        audit.status_agrees = True
    elif len(unique_statuses) > 1:
        audit.status_conflict = True
        audit.conflicting_statuses = statuses
        # Pick Unpaywall as canonical if available, else most common
        if SourceName.UNPAYWALL.value in statuses:
            audit.consensus_status = statuses[SourceName.UNPAYWALL.value]
        else:
            from collections import Counter
            most_common = Counter(statuses.values()).most_common(1)
            if most_common:
                audit.consensus_status = most_common[0][0]

    # Collect all OA locations, deduplicate by URL
    url_map: dict[str, OALocation] = {}
    for src_name, src in result.sources.items():
        if not src.found:
            continue
        for loc in src.oa_locations:
            url = loc.url or loc.pdf_url or loc.landing_page_url
            if not url:
                continue
            if url in url_map:
                if src_name not in url_map[url].sources:
                    url_map[url].sources.append(src_name)
            else:
                url_map[url] = OALocation(
                    url=url,
                    pdf_url=loc.pdf_url,
                    host_type=loc.host_type,
                    version=loc.version,
                    license=loc.license,
                    repository=loc.repository_institution,
                    is_best=loc.is_best,
                    evidence=loc.evidence,
                    sources=[src_name],
                )

    audit.all_locations = list(url_map.values())
    audit.total_locations = len(audit.all_locations)

    # Check version availability
    for loc in audit.all_locations:
        v = (loc.version or "").lower()
        if "published" in v:
            audit.has_publisher_version = True
        if "accepted" in v:
            audit.has_accepted_manuscript = True
        ht = (loc.host_type or "").lower()
        if "repository" in ht:
            audit.has_repository_copy = True

    # Diamond OA (OpenAIRE unique)
    oaire = result.sources.get(SourceName.OPENAIRE.value)
    if oaire and oaire.found:
        # Check raw data for diamond flag
        raw = oaire.raw or {}
        if raw:
            for r in raw.get("results", raw.get("data", [{}])):
                if isinstance(r, dict):
                    audit.is_diamond = r.get("isInDiamondJournal")
                    break

    # Licenses
    licenses: set[str] = set()
    for src in result.sources.values():
        if not src.found:
            continue
        for lic in src.licenses:
            if lic.spdx_id:
                licenses.add(lic.spdx_id)
            elif lic.url:
                licenses.add(lic.url)
        for loc in src.oa_locations:
            if loc.license:
                licenses.add(loc.license)
    audit.licenses_found = sorted(licenses)

    # Narrative
    parts: list[str] = []

    if audit.consensus_is_oa is True:
        parts.append(f"Open Access ({audit.consensus_status or 'status unclear'})")
    elif audit.consensus_is_oa is False:
        parts.append("Closed access")
    else:
        parts.append("OA status undetermined")

    if audit.status_conflict:
        disagree = ", ".join(f"{k}: {v}" for k, v in audit.conflicting_statuses.items())
        parts.append(f"Status disagrees across sources ({disagree})")

    if audit.total_locations > 0:
        parts.append(f"{audit.total_locations} unique OA locations found")

    if audit.has_publisher_version:
        parts.append("Publisher version available")
    if audit.has_accepted_manuscript:
        parts.append("Accepted manuscript available")
    if audit.has_repository_copy:
        parts.append("Repository copy available")

    if audit.is_diamond:
        parts.append("Published in a Diamond OA journal (no APCs)")

    multi_src_locs = [loc for loc in audit.all_locations if len(loc.sources) > 1]
    if multi_src_locs:
        parts.append(f"{len(multi_src_locs)} locations confirmed by multiple sources")

    if audit.licenses_found:
        parts.append(f"Licenses: {', '.join(audit.licenses_found)}")

    audit.narrative = ". ".join(parts) + "." if parts else "No OA information found."

    return audit
