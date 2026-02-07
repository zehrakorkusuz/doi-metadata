"""Dataset reuse analysis — discover downstream data linked to a DOI.

Combines:
- DataCite reverse search → datasets citing this article (ENCODE→1158)
- DataCite relatedIdentifiers → IsSupplementTo, HasVersion, HasPart
- Dryad relatedWorks → article↔dataset links
- Zenodo related_identifiers → linked DOIs
- OpenAIRE related_data → ENA/repository records
- OpenAIRE related_software → GitHub repos
"""

from __future__ import annotations

from collections import Counter

from pydantic import BaseModel, Field

from doi_metadata.models import AggregatedResult, RelatedWork


class RelatedWorkEntry(BaseModel):
    """A single related work with merged provenance."""
    identifier: str
    identifier_type: str = "DOI"
    relation_type: str | None = None
    resource_type: str | None = None
    title: str | None = None
    publisher: str | None = None
    sources: list[str] = Field(default_factory=list)


class VersionChain(BaseModel):
    concept_doi: str | None = None
    concept_recid: str | None = None
    version_number: int | None = None
    is_latest: bool | None = None
    total_versions: int | None = None
    version_dois: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)


class DatasetReuseProfile(BaseModel):
    doi: str

    # DataCite reverse search
    datacite_linked_datasets: list[RelatedWorkEntry] = Field(default_factory=list)
    datacite_linked_count: int = 0
    publishers_breakdown: dict[str, int] = Field(default_factory=dict)  # publisher → count

    # Related works from source responses (DataCite, Dryad, Zenodo)
    supplements_to: list[RelatedWorkEntry] = Field(default_factory=list)  # articles this dataset supports
    supplemented_by: list[RelatedWorkEntry] = Field(default_factory=list)  # datasets for this article
    cites: list[RelatedWorkEntry] = Field(default_factory=list)
    cited_by: list[RelatedWorkEntry] = Field(default_factory=list)
    derived_from: list[RelatedWorkEntry] = Field(default_factory=list)
    source_of: list[RelatedWorkEntry] = Field(default_factory=list)
    parts: list[RelatedWorkEntry] = Field(default_factory=list)
    other_relations: list[RelatedWorkEntry] = Field(default_factory=list)

    # Software (OpenAIRE unique)
    related_software: list[RelatedWorkEntry] = Field(default_factory=list)

    # Related data (OpenAIRE unique)
    related_data: list[RelatedWorkEntry] = Field(default_factory=list)

    # Version chain
    version_chain: VersionChain | None = None

    # Files (Zenodo, Dryad)
    file_count: int = 0
    total_file_size_bytes: int | None = None
    file_types: list[str] = Field(default_factory=list)

    narrative: str = ""


def _to_entry(rw: RelatedWork, source_name: str) -> RelatedWorkEntry:
    return RelatedWorkEntry(
        identifier=rw.identifier,
        identifier_type=rw.identifier_type,
        relation_type=rw.relation_type,
        resource_type=rw.resource_type,
        title=rw.title,
        publisher=rw.publisher,
        sources=[source_name],
    )


def analyze_dataset_reuse(result: AggregatedResult) -> DatasetReuseProfile:
    profile = DatasetReuseProfile(doi=result.doi)

    # --- DataCite reverse search results (Phase 3) ---
    for ds in result.datacite_linked_datasets:
        profile.datacite_linked_datasets.append(
            RelatedWorkEntry(
                identifier=ds.identifier,
                identifier_type=ds.identifier_type,
                title=ds.title,
                publisher=ds.publisher,
                resource_type=ds.resource_type,
                sources=["datacite_reverse_search"],
            )
        )
    profile.datacite_linked_count = len(profile.datacite_linked_datasets)

    # Publisher breakdown
    publishers: Counter[str] = Counter()
    for ds in profile.datacite_linked_datasets:
        if ds.publisher:
            publishers[ds.publisher] += 1
    profile.publishers_breakdown = dict(publishers.most_common())

    # --- Related works from each source ---
    supplement_to_map = {"IsSupplementTo", "issupplementto"}
    supplemented_by_map = {"IsSupplementedBy", "issupplementedby"}
    cited_by_map = {"IsCitedBy", "iscitedby"}
    cites_map = {"Cites", "cites", "References", "references"}
    derived_from_map = {"IsDerivedFrom", "isderivedfrom"}
    source_of_map = {"IsSourceOf", "issourceof"}
    part_of_map = {"IsPartOf", "ispartof", "HasPart", "haspart"}

    for src_name, src in result.sources.items():
        if not src.found:
            continue

        for rw in src.related_works:
            entry = _to_entry(rw, src_name)
            rt = (rw.relation_type or "").strip()

            if rt in supplement_to_map:
                profile.supplements_to.append(entry)
            elif rt in supplemented_by_map:
                profile.supplemented_by.append(entry)
            elif rt in cited_by_map:
                profile.cited_by.append(entry)
            elif rt in cites_map:
                profile.cites.append(entry)
            elif rt in derived_from_map:
                profile.derived_from.append(entry)
            elif rt in source_of_map:
                profile.source_of.append(entry)
            elif rt in part_of_map:
                profile.parts.append(entry)
            elif rt:
                profile.other_relations.append(entry)

        # OpenAIRE software and data
        for sw in src.related_software:
            profile.related_software.append(_to_entry(sw, src_name))
        for rd in src.related_data:
            profile.related_data.append(_to_entry(rd, src_name))

    # --- Version chain (merge Zenodo + DataCite) ---
    for src_name, src in result.sources.items():
        if src.found and src.version_info:
            vi = src.version_info
            if profile.version_chain is None:
                profile.version_chain = VersionChain(
                    concept_doi=vi.concept_doi,
                    concept_recid=vi.concept_recid,
                    version_number=vi.version_number,
                    is_latest=vi.is_latest,
                    total_versions=vi.total_versions,
                    version_dois=list(vi.version_dois),
                    sources=[src_name],
                )
            else:
                if vi.concept_doi and not profile.version_chain.concept_doi:
                    profile.version_chain.concept_doi = vi.concept_doi
                if vi.concept_recid and not profile.version_chain.concept_recid:
                    profile.version_chain.concept_recid = vi.concept_recid
                if vi.version_number is not None and profile.version_chain.version_number is None:
                    profile.version_chain.version_number = vi.version_number
                if vi.total_versions and not profile.version_chain.total_versions:
                    profile.version_chain.total_versions = vi.total_versions
                for vd in vi.version_dois:
                    if vd not in profile.version_chain.version_dois:
                        profile.version_chain.version_dois.append(vd)
                profile.version_chain.sources.append(src_name)

    # --- Files ---
    all_files = []
    for src in result.sources.values():
        if src.found:
            all_files.extend(src.files)
    profile.file_count = len(all_files)
    sizes = [f.size_bytes for f in all_files if f.size_bytes]
    if sizes:
        profile.total_file_size_bytes = sum(sizes)
    profile.file_types = sorted(set(f.content_type or "" for f in all_files if f.content_type))

    # --- Narrative ---
    parts: list[str] = []

    if profile.datacite_linked_count > 0:
        top_pub = next(iter(profile.publishers_breakdown), None)
        parts.append(
            f"{profile.datacite_linked_count} downstream datasets reference this work"
            + (f" (mostly from {top_pub}: {profile.publishers_breakdown[top_pub]})" if top_pub else "")
        )

    if profile.supplements_to:
        parts.append(f"Supplements {len(profile.supplements_to)} article(s)")
    if profile.supplemented_by:
        parts.append(f"Has {len(profile.supplemented_by)} supplementary dataset(s)")

    if profile.related_software:
        parts.append(f"{len(profile.related_software)} related software repositories")

    if profile.related_data:
        parts.append(f"{len(profile.related_data)} related data records (ENA/OpenAIRE)")

    if profile.version_chain:
        vc = profile.version_chain
        parts.append(
            f"Version {vc.version_number or '?'} of {vc.total_versions or '?'}"
            + (" (latest)" if vc.is_latest else "")
            + (f", concept DOI: {vc.concept_doi}" if vc.concept_doi else "")
        )

    if profile.file_count > 0:
        size_str = ""
        if profile.total_file_size_bytes:
            mb = profile.total_file_size_bytes / (1024 * 1024)
            size_str = f", {mb:.1f} MB total" if mb < 1024 else f", {mb / 1024:.1f} GB total"
        parts.append(f"{profile.file_count} files{size_str}")

    profile.narrative = ". ".join(parts) + "." if parts else "No dataset reuse information found."

    return profile
