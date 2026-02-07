"""Pydantic models for unified metadata, per-source raw data, and reconciliation."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class SourceName(str, Enum):
    CROSSREF = "crossref"
    DATACITE = "datacite"
    OPENALEX = "openalex"
    SEMANTIC_SCHOLAR = "semantic_scholar"
    UNPAYWALL = "unpaywall"
    EUROPE_PMC = "europe_pmc"
    OPENAIRE = "openaire"
    NIH_REPORTER = "nih_reporter"
    ZENODO = "zenodo"
    DRYAD = "dryad"
    ORCID = "orcid"


class OAStatus(str, Enum):
    GOLD = "gold"
    GREEN = "green"
    HYBRID = "hybrid"
    BRONZE = "bronze"
    DIAMOND = "diamond"
    CLOSED = "closed"
    UNKNOWN = "unknown"


class RelationType(str, Enum):
    IS_SUPPLEMENT_TO = "IsSupplementTo"
    IS_SUPPLEMENTED_BY = "IsSupplementedBy"
    IS_CITED_BY = "IsCitedBy"
    CITES = "Cites"
    REFERENCES = "References"
    IS_REFERENCED_BY = "IsReferencedBy"
    HAS_VERSION = "HasVersion"
    IS_VERSION_OF = "IsVersionOf"
    IS_NEW_VERSION_OF = "IsNewVersionOf"
    IS_PREVIOUS_VERSION_OF = "IsPreviousVersionOf"
    IS_PART_OF = "IsPartOf"
    HAS_PART = "HasPart"
    IS_DERIVED_FROM = "IsDerivedFrom"
    IS_SOURCE_OF = "IsSourceOf"
    IS_IDENTICAL_TO = "IsIdenticalTo"
    OTHER = "Other"


# ---------------------------------------------------------------------------
# Provenance wrapper — tracks which source provided a value
# ---------------------------------------------------------------------------

class Provenanced(BaseModel):
    """A value with provenance: which source(s) provided it."""
    value: Any
    sources: list[SourceName]


# ---------------------------------------------------------------------------
# Identifier Crosswalk
# ---------------------------------------------------------------------------

class IdentifierCrosswalk(BaseModel):
    """All identifiers discovered across sources for a single work."""
    doi: str
    pmid: str | None = None
    pmcid: str | None = None
    arxiv_id: str | None = None
    mag_id: str | None = None
    openalex_id: str | None = None
    s2_paper_id: str | None = None
    s2_corpus_id: str | None = None
    concept_doi: str | None = None
    concept_recid: str | None = None
    dblp_id: str | None = None
    handles: list[str] = Field(default_factory=list)
    orcids: list[str] = Field(default_factory=list)
    ror_ids: list[str] = Field(default_factory=list)
    # Track which source provided which ID
    pmid_source: SourceName | None = None
    pmcid_source: SourceName | None = None


# ---------------------------------------------------------------------------
# Shared sub-models
# ---------------------------------------------------------------------------

class PersonName(BaseModel):
    given: str | None = None
    family: str | None = None
    full_name: str | None = None
    sequence: str | None = None  # first, additional
    orcid: str | None = None
    authenticated_orcid: bool = False
    source: SourceName | None = None


class Affiliation(BaseModel):
    name: str | None = None
    ror_id: str | None = None
    grid_id: str | None = None
    isni: str | None = None
    country_code: str | None = None
    department: str | None = None
    source: SourceName | None = None


class Author(BaseModel):
    """Unified author with all fields any source provides."""
    name: PersonName
    affiliations: list[Affiliation] = Field(default_factory=list)
    is_corresponding: bool | None = None
    email: str | None = None
    # From OpenAlex
    openalex_author_id: str | None = None
    # From S2
    s2_author_id: str | None = None
    # From NIH Reporter
    nih_profile_id: int | None = None
    title: str | None = None  # e.g. "PROFESSOR"
    sources: list[SourceName] = Field(default_factory=list)


class Funder(BaseModel):
    name: str | None = None
    doi: str | None = None  # CrossRef Funder Registry DOI
    ror_id: str | None = None
    award_numbers: list[str] = Field(default_factory=list)
    source: SourceName | None = None


class Grant(BaseModel):
    """A grant/award linked to this work."""
    grant_id: str | None = None
    agency: str | None = None
    agency_abbreviation: str | None = None
    funder_doi: str | None = None
    title: str | None = None
    # NIH-specific
    activity_code: str | None = None  # R01, U01, P41, etc.
    nih_institute: str | None = None
    award_amount: float | None = None
    project_start: str | None = None
    project_end: str | None = None
    pi_names: list[str] = Field(default_factory=list)
    # OpenAIRE-specific
    openaire_project_id: str | None = None
    funding_stream: str | None = None
    jurisdiction: str | None = None
    validated_by_funder: bool | None = None
    trust_score: float | None = None
    source: SourceName | None = None


class License(BaseModel):
    url: str | None = None
    spdx_id: str | None = None  # e.g. "cc-by-4.0"
    content_version: str | None = None  # vor, am, tdm
    delay_in_days: int | None = None
    source: SourceName | None = None


class Reference(BaseModel):
    """An outbound reference (work this DOI cites)."""
    doi: str | None = None
    title: str | None = None
    year: int | None = None
    author: str | None = None
    unstructured: str | None = None
    # From CrossRef
    key: str | None = None
    # From S2
    s2_paper_id: str | None = None
    intents: list[str] = Field(default_factory=list)  # Background, Methodology, ResultComparison
    is_influential: bool | None = None
    contexts: list[str] = Field(default_factory=list)
    source: SourceName | None = None


class Citation(BaseModel):
    """An inbound citation (work that cites this DOI)."""
    doi: str | None = None
    title: str | None = None
    year: int | None = None
    # From S2
    s2_paper_id: str | None = None
    intents: list[str] = Field(default_factory=list)
    is_influential: bool | None = None
    contexts: list[str] = Field(default_factory=list)
    source: SourceName | None = None


class OALocation(BaseModel):
    url: str | None = None
    pdf_url: str | None = None
    landing_page_url: str | None = None
    host_type: str | None = None  # publisher, repository
    version: str | None = None  # publishedVersion, acceptedVersion, submittedVersion
    license: str | None = None
    evidence: str | None = None  # how OA was discovered
    is_best: bool = False
    repository_institution: str | None = None
    source: SourceName | None = None


class RelatedWork(BaseModel):
    """A related identifier from DataCite, Dryad, Zenodo, OpenAIRE."""
    identifier: str
    identifier_type: str = "DOI"  # DOI, URL, arXiv, PMID, Handle, URN
    relation_type: str | None = None  # IsSupplementTo, HasVersion, etc.
    resource_type: str | None = None  # Dataset, Software, Text, etc.
    title: str | None = None
    publisher: str | None = None
    source: SourceName | None = None


class VersionInfo(BaseModel):
    """Version chain information."""
    concept_doi: str | None = None
    concept_recid: str | None = None
    version_number: int | None = None
    is_latest: bool | None = None
    total_versions: int | None = None
    version_dois: list[str] = Field(default_factory=list)
    source: SourceName | None = None


class FileInfo(BaseModel):
    """A file attached to a dataset (Zenodo, Dryad)."""
    filename: str
    size_bytes: int | None = None
    checksum: str | None = None  # md5:...
    download_url: str | None = None
    content_type: str | None = None
    source: SourceName | None = None


class MeSHTerm(BaseModel):
    descriptor_name: str
    descriptor_ui: str | None = None
    qualifier_name: str | None = None
    qualifier_ui: str | None = None
    is_major_topic: bool = False
    source: SourceName | None = None


class Subject(BaseModel):
    """A subject/topic/concept from any source."""
    value: str
    scheme: str | None = None  # FOS, SDG, ASJC, MeSH, Wikidata, etc.
    score: float | None = None
    level: int | None = None  # OpenAlex concept level
    source: SourceName | None = None


class ImpactIndicator(BaseModel):
    """An impact/citation metric."""
    name: str  # cited_by_count, fwci, relative_citation_ratio, etc.
    value: float | None = None
    percentile: float | None = None
    class_label: str | None = None  # C1, C2, etc. (BIP!)
    source: SourceName | None = None


class UsageStat(BaseModel):
    downloads: int | None = None
    unique_downloads: int | None = None
    views: int | None = None
    unique_views: int | None = None
    source: SourceName | None = None


# ---------------------------------------------------------------------------
# Per-source normalized result
# ---------------------------------------------------------------------------

class SourceResult(BaseModel):
    """Normalized result from a single source."""
    source: SourceName
    found: bool = False
    error: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)

    # Basic metadata
    title: str | None = None
    abstract: str | None = None
    publication_date: str | None = None
    publication_year: int | None = None
    work_type: str | None = None  # article, dataset, preprint, software, etc.
    language: str | None = None
    publisher: str | None = None

    # Journal/container
    container_title: str | None = None  # journal name
    volume: str | None = None
    issue: str | None = None
    pages: str | None = None
    issn: list[str] = Field(default_factory=list)

    # Identifiers
    doi: str | None = None
    pmid: str | None = None
    pmcid: str | None = None
    arxiv_id: str | None = None
    openalex_id: str | None = None
    s2_paper_id: str | None = None
    s2_corpus_id: str | None = None

    # People
    authors: list[Author] = Field(default_factory=list)

    # Citations & References
    citation_count: int | None = None
    reference_count: int | None = None
    influential_citation_count: int | None = None
    references: list[Reference] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    counts_by_year: dict[int, int] = Field(default_factory=dict)  # year → count

    # Open Access
    is_oa: bool | None = None
    oa_status: OAStatus | None = None
    oa_locations: list[OALocation] = Field(default_factory=list)
    best_oa_url: str | None = None

    # Funding
    funders: list[Funder] = Field(default_factory=list)
    grants: list[Grant] = Field(default_factory=list)

    # Licensing
    licenses: list[License] = Field(default_factory=list)

    # Subjects, concepts, keywords
    subjects: list[Subject] = Field(default_factory=list)
    mesh_terms: list[MeSHTerm] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)

    # Related works / version chains
    related_works: list[RelatedWork] = Field(default_factory=list)
    version_info: VersionInfo | None = None

    # Files (datasets)
    files: list[FileInfo] = Field(default_factory=list)

    # Impact indicators
    impact_indicators: list[ImpactIndicator] = Field(default_factory=list)
    usage_stats: UsageStat | None = None

    # S2-specific
    tldr: str | None = None
    citation_styles: dict[str, str] = Field(default_factory=dict)  # bibtex, etc.

    # OpenAIRE-specific
    related_software: list[RelatedWork] = Field(default_factory=list)
    related_data: list[RelatedWork] = Field(default_factory=list)
    openaire_projects: list[Grant] = Field(default_factory=list)
    alternate_ids: list[str] = Field(default_factory=list)

    # Europe PMC-specific
    chemicals: list[dict[str, str]] = Field(default_factory=list)
    text_mined_accessions: list[str] = Field(default_factory=list)
    corrections: list[dict[str, str]] = Field(default_factory=list)
    full_text_urls: list[dict[str, str]] = Field(default_factory=list)

    # NIH Reporter-specific
    nih_grants: list[Grant] = Field(default_factory=list)
    sibling_pmids: list[int] = Field(default_factory=list)
    relative_citation_ratio: float | None = None

    # Dryad-specific
    methods: str | None = None
    usage_notes: str | None = None
    storage_size: int | None = None

    # CrossRef-specific
    crossmark_assertions: list[dict[str, Any]] = Field(default_factory=list)
    clinical_trial_numbers: list[dict[str, str]] = Field(default_factory=list)
    update_to: list[dict[str, Any]] = Field(default_factory=list)

    # ORCID-specific
    orcid_records: list[dict[str, Any]] = Field(default_factory=list)

    # Zenodo-specific
    communities: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Conflict report
# ---------------------------------------------------------------------------

class FieldConflict(BaseModel):
    """A single field where sources disagree."""
    field: str
    values: dict[str, Any]  # source_name → value
    risk: str = "medium"  # low, medium, high


class ConflictReport(BaseModel):
    """All detected conflicts for a single DOI lookup."""
    doi: str
    conflicts: list[FieldConflict] = Field(default_factory=list)
    agreement_count: int = 0
    conflict_count: int = 0


# ---------------------------------------------------------------------------
# Aggregated result
# ---------------------------------------------------------------------------

class AggregatedResult(BaseModel):
    """The final output: all source results + crosswalk + conflicts."""
    doi: str
    registration_agency: str | None = None  # crossref, datacite, unknown
    retrieved_at: datetime
    sources: dict[str, SourceResult] = Field(default_factory=dict)
    crosswalk: IdentifierCrosswalk
    conflicts: ConflictReport
    # Phase 3 discoveries
    datacite_linked_datasets: list[RelatedWork] = Field(default_factory=list)
    # Derived analyses (populated after aggregation)
    analyses: dict[str, Any] = Field(default_factory=dict)
