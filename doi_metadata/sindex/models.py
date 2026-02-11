"""Pydantic models for s-index / DataRank output."""

from __future__ import annotations

from pydantic import BaseModel, Field


class PaperEndowment(BaseModel):
    """Direct data-sharing evidence for a single paper."""

    doi: str

    # DataCite reverse search total (uncapped count of downstream datasets)
    datacite_reuse_total: int = 0

    # DataCite relation richness (distinct data-relation types found)
    datacite_relation_types: list[str] = Field(default_factory=list)

    # File deposits
    file_count: int = 0
    total_file_size_bytes: int = 0

    # Usage evidence
    downloads: int = 0
    views: int = 0

    # Version maintenance (actively updated data)
    has_version_chain: bool = False
    version_count: int = 0

    # OpenAlex work_type == 'dataset'
    is_dataset: bool = False

    # Open access (prerequisite for data sharing)
    is_oa: bool = False

    # The computed endowment score E(p)
    endowment: float = 0.0


class DataRankResult(BaseModel):
    """DataRank score for a single paper."""

    doi: str
    endowment: PaperEndowment

    # 1-hop DataRank components
    self_endowment_contribution: float = 0.0  # (1-d) * E(p)
    citer_contribution: float = 0.0  # d * Σ E(q)/outdeg(q)
    datarank: float = 0.0  # self + citer

    # Context for the score
    citer_count: int = 0  # number of citers found
    citers_with_endowment: int = 0  # citers that have nonzero endowment

    # Quantile class (assigned after corpus-wide ranking)
    quantile_class: str | None = None  # S1..S5
    corpus_rank: int | None = None
    corpus_percentile: float | None = None


class DataRankCorpus(BaseModel):
    """Corpus-wide DataRank results."""

    papers: list[DataRankResult] = Field(default_factory=list)
    total_papers: int = 0
    damping_factor: float = 0.85

    # Distribution stats
    mean_datarank: float = 0.0
    median_datarank: float = 0.0
    max_datarank: float = 0.0

    # Quantile thresholds
    s1_threshold: float = 0.0  # top 0.01%
    s2_threshold: float = 0.0  # top 0.1%
    s3_threshold: float = 0.0  # top 1%
    s4_threshold: float = 0.0  # top 10%
