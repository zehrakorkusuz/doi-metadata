"""Grant siblings — find other publications sharing the same grants.

Combines:
- NIH Reporter → sibling PMIDs for each grant (all pubs under same award)
- OpenAIRE → projects linked to multiple publications
- CrossRef/Europe PMC/DataCite → shared funder + award number

Key insight: If ENCODE paper (DOI A) is funded by grant U01HG004695,
NIH Reporter tells us all ~724 other papers also under that grant.
This reveals the full "grant portfolio" of related work.
"""

from __future__ import annotations

from collections import defaultdict

from pydantic import BaseModel, Field

from doi_metadata.models import AggregatedResult, SourceName


class SiblingGrant(BaseModel):
    """A grant that funds this work, plus its sibling publications."""
    grant_id: str
    agency: str | None = None
    activity_code: str | None = None
    nih_institute: str | None = None
    title: str | None = None
    pi_names: list[str] = Field(default_factory=list)
    sibling_pmid_count: int = 0
    sibling_pmids: list[int] = Field(default_factory=list)  # capped
    # OpenAIRE project info
    openaire_project_id: str | None = None
    funding_stream: str | None = None
    sources: list[str] = Field(default_factory=list)


class GrantSiblingsProfile(BaseModel):
    doi: str
    grants_with_siblings: list[SiblingGrant] = Field(default_factory=list)
    total_sibling_pmids: int = 0
    unique_sibling_pmids: int = 0
    most_prolific_grant: str | None = None  # grant with most siblings
    most_prolific_count: int = 0
    # Cross-grant overlap: PMIDs appearing under multiple grants
    multi_grant_pmids: int = 0
    narrative: str = ""


def _normalize_grant_id(gid: str | None) -> str | None:
    if not gid:
        return None
    return gid.strip().upper().replace(" ", "")


def analyze_grant_siblings(result: AggregatedResult) -> GrantSiblingsProfile:
    profile = GrantSiblingsProfile(doi=result.doi)

    # Build map of grant_id → SiblingGrant
    grants_map: dict[str, SiblingGrant] = {}

    # NIH Reporter is the primary source of sibling PMIDs
    nih = result.sources.get(SourceName.NIH_REPORTER.value)
    if nih and nih.found:
        for grant in nih.nih_grants:
            norm_id = _normalize_grant_id(grant.grant_id)
            if not norm_id:
                continue
            sg = SiblingGrant(
                grant_id=grant.grant_id or norm_id,
                agency=grant.agency,
                activity_code=grant.activity_code,
                nih_institute=grant.nih_institute,
                title=grant.title,
                pi_names=list(grant.pi_names),
                sources=[SourceName.NIH_REPORTER.value],
            )
            grants_map[norm_id] = sg

        # NIH Reporter sibling PMIDs are stored at source level
        # Distribute to grants (in current model, all sibling_pmids are pooled)
        if nih.sibling_pmids:
            # Each NIH grant shares the sibling pool
            for norm_id, sg in grants_map.items():
                sg.sibling_pmids = list(nih.sibling_pmids[:500])  # cap at 500
                sg.sibling_pmid_count = len(nih.sibling_pmids)

    # Enrich with OpenAIRE project info
    oaire = result.sources.get(SourceName.OPENAIRE.value)
    if oaire and oaire.found:
        for project in oaire.openaire_projects:
            norm_id = _normalize_grant_id(project.grant_id)
            if norm_id and norm_id in grants_map:
                sg = grants_map[norm_id]
                if SourceName.OPENAIRE.value not in sg.sources:
                    sg.sources.append(SourceName.OPENAIRE.value)
                if not sg.openaire_project_id and project.openaire_project_id:
                    sg.openaire_project_id = project.openaire_project_id
                if not sg.funding_stream and project.funding_stream:
                    sg.funding_stream = project.funding_stream
            elif norm_id:
                # Grant only in OpenAIRE
                grants_map[norm_id] = SiblingGrant(
                    grant_id=project.grant_id or norm_id,
                    agency=project.agency,
                    title=project.title,
                    openaire_project_id=project.openaire_project_id,
                    funding_stream=project.funding_stream,
                    sources=[SourceName.OPENAIRE.value],
                )

    # Add grants from other sources that we haven't seen yet
    for src_name, src in result.sources.items():
        if not src.found:
            continue
        for grant in src.grants:
            norm_id = _normalize_grant_id(grant.grant_id)
            if norm_id and norm_id in grants_map:
                sg = grants_map[norm_id]
                if src_name not in sg.sources:
                    sg.sources.append(src_name)
                if not sg.title and grant.title:
                    sg.title = grant.title
            elif norm_id:
                grants_map[norm_id] = SiblingGrant(
                    grant_id=grant.grant_id or norm_id,
                    agency=grant.agency,
                    activity_code=grant.activity_code,
                    title=grant.title,
                    pi_names=list(grant.pi_names),
                    sources=[src_name],
                )

    # Assemble
    profile.grants_with_siblings = sorted(
        grants_map.values(),
        key=lambda g: g.sibling_pmid_count,
        reverse=True,
    )

    # Total and unique sibling PMIDs
    all_pmids: list[int] = []
    for sg in profile.grants_with_siblings:
        all_pmids.extend(sg.sibling_pmids)
    profile.total_sibling_pmids = len(all_pmids)
    unique = set(all_pmids)
    profile.unique_sibling_pmids = len(unique)

    # Most prolific grant
    if profile.grants_with_siblings:
        top = profile.grants_with_siblings[0]
        if top.sibling_pmid_count > 0:
            profile.most_prolific_grant = top.grant_id
            profile.most_prolific_count = top.sibling_pmid_count

    # Multi-grant overlap (PMIDs appearing under more than one grant)
    pmid_counts: dict[int, int] = defaultdict(int)
    for sg in profile.grants_with_siblings:
        for pmid in sg.sibling_pmids:
            pmid_counts[pmid] += 1
    profile.multi_grant_pmids = sum(1 for c in pmid_counts.values() if c > 1)

    # Narrative
    parts: list[str] = []

    grants_with_sibs = [g for g in profile.grants_with_siblings if g.sibling_pmid_count > 0]
    if grants_with_sibs:
        parts.append(
            f"{len(grants_with_sibs)} grants with known sibling publications"
        )
        parts.append(
            f"{profile.unique_sibling_pmids} unique sibling publications across all grants"
        )
        if profile.most_prolific_grant:
            parts.append(
                f"Most prolific: {profile.most_prolific_grant} "
                f"({profile.most_prolific_count} publications)"
            )
        if profile.multi_grant_pmids > 0:
            parts.append(
                f"{profile.multi_grant_pmids} publications appear under multiple grants"
            )
    elif profile.grants_with_siblings:
        parts.append(
            f"{len(profile.grants_with_siblings)} grants identified but no sibling publication data available"
        )

    # Multi-source grants
    multi_src = [g for g in profile.grants_with_siblings if len(g.sources) > 1]
    if multi_src:
        parts.append(f"{len(multi_src)} grants confirmed by multiple sources")

    profile.narrative = ". ".join(parts) + "." if parts else "No grant sibling information found."

    return profile
