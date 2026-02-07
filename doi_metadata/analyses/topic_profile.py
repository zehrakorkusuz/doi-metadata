"""Topic profile — unified multi-vocabulary subject mapping.

Combines:
- OpenAlex → concepts (Wikidata-based, hierarchical levels 0-5), topics, keywords, SDGs
- OpenAIRE → FOS (Field of Science), SDGs with trust scores
- Europe PMC → MeSH headings with qualifiers and major topic flags
- CrossRef → ASJC subject codes from container metadata
- S2 → s2FieldsOfStudy (S2FOS categories)
- DataCite → subjects with subjectScheme
- Dryad → fieldOfScience
- Zenodo → keywords, subjects

Produces a unified picture of what this work is "about" across every
classification vocabulary the scholarly infrastructure offers.
"""

from __future__ import annotations

from collections import defaultdict

from pydantic import BaseModel, Field

from doi_metadata.models import AggregatedResult, SourceName


class TopicEntry(BaseModel):
    """A single topic/concept/subject."""
    value: str
    scheme: str | None = None  # FOS, SDG, MeSH, ASJC, Wikidata, S2FOS, keyword, etc.
    score: float | None = None  # relevance score if available
    level: int | None = None  # hierarchy level (OpenAlex concepts)
    is_major: bool = False  # MeSH major topic
    trust: float | None = None  # OpenAIRE trust score
    sources: list[str] = Field(default_factory=list)


class SDGMapping(BaseModel):
    """UN Sustainable Development Goal mapping."""
    sdg_number: int | None = None
    sdg_label: str
    score: float | None = None
    trust: float | None = None
    sources: list[str] = Field(default_factory=list)


class MeSHEntry(BaseModel):
    """A MeSH heading with full detail."""
    descriptor: str
    descriptor_ui: str | None = None
    qualifier: str | None = None
    qualifier_ui: str | None = None
    is_major_topic: bool = False
    source: str | None = None


class TopicProfile(BaseModel):
    doi: str

    # High-level fields of study
    fields_of_study: list[TopicEntry] = Field(default_factory=list)

    # Keywords (from multiple sources)
    keywords: list[TopicEntry] = Field(default_factory=list)

    # MeSH (Europe PMC, OpenAlex)
    mesh_terms: list[MeSHEntry] = Field(default_factory=list)

    # SDGs
    sdg_mappings: list[SDGMapping] = Field(default_factory=list)

    # OpenAlex concepts (hierarchical)
    openalex_concepts: list[TopicEntry] = Field(default_factory=list)

    # S2 fields (Semantic Scholar)
    s2_fields: list[TopicEntry] = Field(default_factory=list)

    # ASJC codes (CrossRef/Scopus)
    asjc_subjects: list[TopicEntry] = Field(default_factory=list)

    # All unique topics across all vocabularies
    all_topics_flat: list[str] = Field(default_factory=list)

    # Cross-vocabulary agreement
    vocabulary_count: int = 0
    topics_by_vocabulary: dict[str, int] = Field(default_factory=dict)

    narrative: str = ""


def _extract_sdg_number(label: str) -> int | None:
    """Extract SDG number from labels like 'SDG 3 - Good Health' or '3'."""
    import re
    m = re.search(r'(\d+)', label)
    return int(m.group(1)) if m else None


def analyze_topics(result: AggregatedResult) -> TopicProfile:
    profile = TopicProfile(doi=result.doi)

    all_fos: list[TopicEntry] = []
    all_keywords: list[TopicEntry] = []
    all_mesh: list[MeSHEntry] = []
    all_sdgs: dict[str, SDGMapping] = {}
    all_concepts: list[TopicEntry] = []
    all_s2: list[TopicEntry] = []
    all_asjc: list[TopicEntry] = []

    vocab_sources: dict[str, set[str]] = defaultdict(set)

    for src_name, src in result.sources.items():
        if not src.found:
            continue

        # Subjects with scheme info
        for subj in src.subjects:
            scheme = (subj.scheme or "").lower()

            entry = TopicEntry(
                value=subj.value,
                scheme=subj.scheme,
                score=subj.score,
                level=subj.level,
                sources=[src_name],
            )

            if "fos" in scheme or "field" in scheme:
                all_fos.append(entry)
                vocab_sources["FOS"].add(src_name)
            elif "sdg" in scheme:
                key = subj.value.lower().strip()
                if key not in all_sdgs:
                    all_sdgs[key] = SDGMapping(
                        sdg_number=_extract_sdg_number(subj.value),
                        sdg_label=subj.value,
                        score=subj.score,
                        sources=[src_name],
                    )
                else:
                    if src_name not in all_sdgs[key].sources:
                        all_sdgs[key].sources.append(src_name)
                vocab_sources["SDG"].add(src_name)
            elif "asjc" in scheme or "scopus" in scheme:
                all_asjc.append(entry)
                vocab_sources["ASJC"].add(src_name)
            elif "wikidata" in scheme or "concept" in scheme:
                all_concepts.append(entry)
                vocab_sources["OpenAlex_Concepts"].add(src_name)
            elif "s2fos" in scheme or "semantic" in scheme:
                all_s2.append(entry)
                vocab_sources["S2FOS"].add(src_name)
            elif scheme == "" or "keyword" in scheme:
                all_keywords.append(entry)
                vocab_sources["Keywords"].add(src_name)
            else:
                # Generic: treat as FOS
                all_fos.append(entry)
                vocab_sources[scheme or "other"].add(src_name)

        # Keywords (separate field)
        for kw in src.keywords:
            all_keywords.append(TopicEntry(
                value=kw,
                scheme="keyword",
                sources=[src_name],
            ))
            vocab_sources["Keywords"].add(src_name)

        # MeSH terms
        for mesh in src.mesh_terms:
            all_mesh.append(MeSHEntry(
                descriptor=mesh.descriptor_name,
                descriptor_ui=mesh.descriptor_ui,
                qualifier=mesh.qualifier_name,
                qualifier_ui=mesh.qualifier_ui,
                is_major_topic=mesh.is_major_topic,
                source=src_name,
            ))
            vocab_sources["MeSH"].add(src_name)

    # OpenAIRE-specific: subjects have trust scores
    oaire = result.sources.get(SourceName.OPENAIRE.value)
    if oaire and oaire.found:
        for subj in oaire.subjects:
            scheme = (subj.scheme or "").lower()
            if "sdg" in scheme and subj.value.lower().strip() in all_sdgs:
                # Already captured, but update trust if we have raw data
                pass
            # Trust scores come through score field already

    # Deduplicate keywords
    seen_keywords: set[str] = set()
    deduped_keywords: list[TopicEntry] = []
    for kw in all_keywords:
        key = kw.value.lower().strip()
        if key not in seen_keywords:
            seen_keywords.add(key)
            deduped_keywords.append(kw)
        else:
            # Merge sources
            for existing in deduped_keywords:
                if existing.value.lower().strip() == key:
                    for s in kw.sources:
                        if s not in existing.sources:
                            existing.sources.append(s)
                    break

    # Deduplicate FOS
    seen_fos: set[str] = set()
    deduped_fos: list[TopicEntry] = []
    for fos in all_fos:
        key = fos.value.lower().strip()
        if key not in seen_fos:
            seen_fos.add(key)
            deduped_fos.append(fos)
        else:
            for existing in deduped_fos:
                if existing.value.lower().strip() == key:
                    for s in fos.sources:
                        if s not in existing.sources:
                            existing.sources.append(s)
                    break

    # Sort by score where available
    deduped_fos.sort(key=lambda x: x.score or 0, reverse=True)
    deduped_keywords.sort(key=lambda x: x.score or 0, reverse=True)
    all_concepts.sort(key=lambda x: (x.level or 99, -(x.score or 0)))

    profile.fields_of_study = deduped_fos
    profile.keywords = deduped_keywords
    profile.mesh_terms = all_mesh
    profile.sdg_mappings = sorted(all_sdgs.values(), key=lambda x: x.sdg_number or 99)
    profile.openalex_concepts = all_concepts
    profile.s2_fields = all_s2
    profile.asjc_subjects = all_asjc

    # All topics flat
    all_flat: set[str] = set()
    for t in deduped_fos + deduped_keywords + all_concepts + all_s2 + all_asjc:
        all_flat.add(t.value)
    for m in all_mesh:
        all_flat.add(m.descriptor)
    profile.all_topics_flat = sorted(all_flat)

    # Vocabulary counts
    profile.topics_by_vocabulary = {k: len(v) for k, v in vocab_sources.items()}
    if all_mesh:
        profile.topics_by_vocabulary["MeSH"] = len(all_mesh)
    profile.vocabulary_count = len([v for v in profile.topics_by_vocabulary.values() if v > 0])

    # Narrative
    parts: list[str] = []

    if profile.vocabulary_count > 0:
        parts.append(f"Classified in {profile.vocabulary_count} vocabularies")

    if deduped_fos:
        top_fos = [f.value for f in deduped_fos[:3]]
        parts.append(f"Fields of study: {', '.join(top_fos)}")

    if all_mesh:
        major = [m for m in all_mesh if m.is_major_topic]
        if major:
            top_mesh = [m.descriptor for m in major[:3]]
            parts.append(f"Major MeSH terms: {', '.join(top_mesh)}")
        else:
            parts.append(f"{len(all_mesh)} MeSH terms")

    if profile.sdg_mappings:
        sdg_labels = [s.sdg_label for s in profile.sdg_mappings[:3]]
        parts.append(f"SDG alignment: {', '.join(sdg_labels)}")

    if all_concepts:
        # Show top-level concepts (level 0 or 1)
        top_level = [c.value for c in all_concepts if (c.level or 99) <= 1][:3]
        if top_level:
            parts.append(f"Broad concepts: {', '.join(top_level)}")

    if all_s2:
        s2_labels = [s.value for s in all_s2[:3]]
        parts.append(f"S2 fields: {', '.join(s2_labels)}")

    if deduped_keywords:
        parts.append(f"{len(deduped_keywords)} unique keywords")

    # Cross-vocabulary agreement
    multi_src = [t for t in deduped_fos + deduped_keywords if len(t.sources) > 1]
    if multi_src:
        parts.append(f"{len(multi_src)} topics confirmed by multiple sources")

    profile.narrative = ". ".join(parts) + "." if parts else "No topic information found."

    return profile
