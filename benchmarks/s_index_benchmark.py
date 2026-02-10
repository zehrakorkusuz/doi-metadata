#!/usr/bin/env python3
"""S-index benchmark — run citation network analysis on a curated DOI set, rank by S-index.

Produces:
  1. Paper-level ranking (sorted by S-index, descending)
  2. Author-level ranking (aggregated across papers)
  3. Data completeness matrix (which sources returned data for each DOI)
  4. Detailed per-paper metrics

Two modes:
  --live     Hit all 11 real APIs (requires network access + API keys)
  (default)  Use built-in realistic fixtures (works offline, for testing/demo)

Usage:
    python benchmarks/s_index_benchmark.py
    python benchmarks/s_index_benchmark.py --live
    python benchmarks/s_index_benchmark.py --live --output-json results.json
    python benchmarks/s_index_benchmark.py --live --dois "10.1038/s41586-020-2649-2,10.1234/example"
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from doi_metadata.analyses.citation_network import CitationNetworkResult, analyze_citation_network
from doi_metadata.models import (
    AggregatedResult,
    Author,
    Citation,
    ConflictReport,
    Grant,
    IdentifierCrosswalk,
    ImpactIndicator,
    MeSHTerm,
    PersonName,
    Reference,
    RelatedWork,
    SourceName,
    SourceResult,
)

# ---------------------------------------------------------------------------
# Benchmark DOI set — curated for diversity
# ---------------------------------------------------------------------------

# Each tuple: (DOI, short label, expected domain)
BENCHMARK_DOIS: list[tuple[str, str, str]] = [
    # --- Landmark biomedical papers ---
    ("10.1038/nature11247", "ENCODE consortium", "genomics"),
    ("10.1038/s41586-020-2649-2", "NumPy paper", "computational"),
    ("10.1016/S0140-6736(20)30183-5", "Early COVID clinical", "clinical medicine"),

    # --- High-impact methods papers ---
    ("10.1038/nmeth.1923", "BWA-MEM aligner", "bioinformatics"),
    ("10.1093/bioinformatics/btp324", "SAMtools", "bioinformatics"),

    # --- Clinical trials / NIH-funded ---
    ("10.1056/NEJMoa2001017", "Remdesivir NEJM trial", "clinical trial"),
    ("10.1001/jama.2020.6775", "Hydroxychloroquine JAMA", "clinical trial"),

    # --- Dataset DOIs ---
    ("10.5061/dryad.8sf3tx0h5", "Dryad dataset", "dataset"),
    ("10.5281/zenodo.3509134", "Zenodo software record", "software"),

    # --- Moderately cited ---
    ("10.1371/journal.pone.0185809", "PLOS ONE article", "general biomedical"),
    ("10.7554/eLife.47612", "eLife article", "biomedical"),

    # --- Machine learning / AI ---
    ("10.48550/arXiv.1706.03762", "Attention Is All You Need", "machine learning"),

    # --- Retracted paper (for anti-gaming demo) ---
    ("10.1016/S0140-6736(20)30566-3", "Lancet retracted study", "epidemiology"),
]


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class PaperResult:
    """Aggregated benchmark result for one DOI."""
    doi: str
    label: str
    domain: str
    s_index: float = 0.0
    pagerank_standard: float = 0.0
    pagerank_time_decay: float = 0.0
    pagerank_standard_percentile: float = 0.0
    pagerank_time_decay_percentile: float = 0.0
    in_degree: int = 0
    out_degree: int = 0
    self_citation_fraction: float | None = None
    influential_fraction: float | None = None
    methodology_fraction: float | None = None
    dominant_intent: str | None = None
    fwci: float | None = None
    rcr: float | None = None
    bip_influence: float | None = None
    citation_velocity_trend: str | None = None
    has_mesh: bool = False
    has_clinical_trials: bool = False
    has_retraction: bool = False
    pmid_available: bool = False
    graph_truncated: bool = False
    known_citation_count: int | None = None
    sources_found: list[str] = field(default_factory=list)
    sources_not_found: list[str] = field(default_factory=list)
    sources_error: list[str] = field(default_factory=list)
    authors: list[dict] = field(default_factory=list)
    narrative: str = ""
    fetch_time_s: float = 0.0
    error: str | None = None


# ---------------------------------------------------------------------------
# Realistic fixture builder
# ---------------------------------------------------------------------------

def _make_authors(specs: list[tuple[str, str, str | None]]) -> list[Author]:
    """Build Author objects from (given, family, orcid) tuples."""
    return [
        Author(
            name=PersonName(
                given=g, family=f, full_name=f"{g} {f}",
                orcid=o, source=SourceName.OPENALEX,
            ),
            sources=[SourceName.OPENALEX],
        )
        for g, f, o in specs
    ]


def _make_citations(
    specs: list[dict],
    source: SourceName = SourceName.SEMANTIC_SCHOLAR,
) -> list[Citation]:
    """Build Citation objects. Each spec: {doi, year, intents, is_influential, s2_paper_id}."""
    return [
        Citation(
            doi=s.get("doi"),
            title=s.get("title"),
            year=s.get("year"),
            intents=s.get("intents", []),
            is_influential=s.get("is_influential"),
            s2_paper_id=s.get("s2_paper_id"),
            source=source,
        )
        for s in specs
    ]


def _make_references(
    specs: list[dict],
    source: SourceName = SourceName.CROSSREF,
) -> list[Reference]:
    return [
        Reference(
            doi=s.get("doi"),
            title=s.get("title"),
            year=s.get("year"),
            intents=s.get("intents", []),
            is_influential=s.get("is_influential"),
            source=source,
        )
        for s in specs
    ]


def build_fixture(doi: str, label: str, spec: dict) -> AggregatedResult:
    """Build an AggregatedResult from a fixture specification dict.

    Keys in spec:
        authors: list of (given, family, orcid) tuples
        crossref, openalex, semantic_scholar, europe_pmc, openaire, nih_reporter,
        unpaywall, datacite, zenodo, dryad, orcid: dicts with source-specific data
        pmid, pmcid: crosswalk identifiers
        datacite_linked_datasets: list of RelatedWork dicts
    """
    sources: dict[str, SourceResult] = {}
    authors = _make_authors(spec.get("authors", []))

    for src_name_str, src_spec in spec.get("sources", {}).items():
        src_name = SourceName(src_name_str)
        sr = SourceResult(
            source=src_name,
            found=src_spec.get("found", True),
            title=spec.get("title"),
            publication_year=spec.get("year"),
            authors=authors if src_spec.get("has_authors", False) else [],
            citation_count=src_spec.get("citation_count"),
            reference_count=src_spec.get("reference_count"),
            influential_citation_count=src_spec.get("influential_citation_count"),
            citations=_make_citations(src_spec.get("citations", []), src_name),
            references=_make_references(src_spec.get("references", []), src_name),
            counts_by_year=src_spec.get("counts_by_year", {}),
            pagerank=src_spec.get("pagerank"),
            relative_citation_ratio=src_spec.get("rcr"),
            related_works=[
                RelatedWork(
                    identifier=rw["identifier"],
                    identifier_type=rw.get("identifier_type", "DOI"),
                    relation_type=rw.get("relation_type"),
                    source=src_name,
                )
                for rw in src_spec.get("related_works", [])
            ],
        )

        # Impact indicators
        for ind in src_spec.get("impact_indicators", []):
            sr.impact_indicators.append(
                ImpactIndicator(
                    name=ind["name"], value=ind["value"],
                    class_label=ind.get("class_label"),
                    source=src_name,
                )
            )

        # MeSH terms
        for m in src_spec.get("mesh_terms", []):
            sr.mesh_terms.append(MeSHTerm(descriptor_name=m, source=src_name))

        # Clinical trials
        sr.clinical_trial_numbers = src_spec.get("clinical_trial_numbers", [])

        # Corrections / retractions
        sr.corrections = src_spec.get("corrections", [])
        sr.update_to = src_spec.get("update_to", [])

        # Grants
        for g in src_spec.get("grants", []):
            sr.grants.append(Grant(
                funder_name=g.get("funder", "Unknown"),
                grant_id=g.get("id"),
                source=src_name,
            ))
        for g in src_spec.get("nih_grants", []):
            sr.nih_grants.append(Grant(
                funder_name="NIH",
                grant_id=g.get("id"),
                source=src_name,
            ))

        sources[src_name_str] = sr

    # Crosswalk
    cw = IdentifierCrosswalk(doi=doi)
    cw.pmid = spec.get("pmid")
    cw.pmcid = spec.get("pmcid")

    # DataCite linked datasets
    datasets = [
        RelatedWork(
            identifier=d["doi"],
            identifier_type="DOI",
            title=d.get("title"),
            source=SourceName.DATACITE,
        )
        for d in spec.get("datacite_linked_datasets", [])
    ]

    return AggregatedResult(
        doi=doi,
        registration_agency="crossref",
        retrieved_at=datetime.now(timezone.utc),
        sources=sources,
        crosswalk=cw,
        conflicts=ConflictReport(doi=doi),
        datacite_linked_datasets=datasets,
    )


# ---------------------------------------------------------------------------
# Fixture data — realistic parameters modeled on real API patterns
# ---------------------------------------------------------------------------

FIXTURES: dict[str, dict] = {
    "10.1038/nature11247": {
        "title": "An integrated encyclopedia of DNA elements in the human genome",
        "year": 2012,
        "pmid": "22955616",
        "pmcid": "PMC3439153",
        "authors": [
            ("Ian", "Dunham", "0000-0003-2525-5598"),
            ("Ewan", "Birney", "0000-0001-8314-4688"),
            ("Michael", "Snyder", "0000-0003-0702-0479"),
        ],
        "datacite_linked_datasets": [
            {"doi": "10.6084/m9.figshare.1234561", "title": "ENCODE ChIP-seq data"},
            {"doi": "10.6084/m9.figshare.1234562", "title": "ENCODE RNA-seq data"},
            {"doi": "10.5281/zenodo.9876541", "title": "ENCODE annotations v3"},
        ],
        "sources": {
            "crossref": {
                "found": True, "citation_count": 14832, "reference_count": 84, "has_authors": True,
                "references": [{"doi": f"10.1000/encode_ref_{i}", "year": 2005 + i % 7} for i in range(40)],
            },
            "openalex": {
                "found": True, "citation_count": 18767, "has_authors": True,
                "counts_by_year": {2013: 1200, 2014: 1800, 2015: 1950, 2016: 1850, 2017: 1700,
                                   2018: 1650, 2019: 1600, 2020: 1550, 2021: 1480, 2022: 1400,
                                   2023: 1350, 2024: 1287, 2025: 800},
                "impact_indicators": [
                    {"name": "fwci", "value": 85.3},
                    {"name": "citation_normalized_percentile", "value": 99.8},
                ],
            },
            "semantic_scholar": {
                "found": True, "citation_count": 15938, "influential_citation_count": 1842,
                "has_authors": True,
                "citations": (
                    [{"doi": f"10.1000/enc_meth_{i}", "year": 2015 + i % 10, "intents": ["Methodology"],
                      "is_influential": True} for i in range(18)]
                    + [{"doi": f"10.1000/enc_res_{i}", "year": 2016 + i % 9, "intents": ["ResultComparison"],
                        "is_influential": i % 3 == 0} for i in range(12)]
                    + [{"doi": f"10.1000/enc_bg_{i}", "year": 2014 + i % 11, "intents": ["Background"],
                        "is_influential": False} for i in range(70)]
                ),
                "references": [{"doi": f"10.1000/encode_ref_{i}", "year": 2005 + i % 7,
                                 "intents": ["Background"]} for i in range(30)],
            },
            "europe_pmc": {
                "found": True, "citation_count": 15200,
                "mesh_terms": ["Genomics", "DNA", "Regulatory Elements, Nucleic Acid",
                               "Chromatin", "Transcription Factors", "Molecular Sequence Annotation"],
                "grants": [{"funder": "NHGRI", "id": "U01HG004695"}],
            },
            "openaire": {
                "found": True, "citation_count": 14500, "pagerank": 3.8e-5,
                "impact_indicators": [
                    {"name": "bip_influence", "value": 3.8e-5, "class_label": "C1"},
                    {"name": "bip_popularity", "value": 1.2e-4},
                    {"name": "bip_impulse", "value": 8.5e-5},
                ],
            },
            "nih_reporter": {
                "found": True, "citation_count": 14100, "rcr": 42.5,
                "nih_grants": [{"id": "U01HG004695"}, {"id": "U54HG004592"}],
            },
            "unpaywall": {"found": True},
            "orcid": {"found": True, "has_authors": True},
            "datacite": {"found": False},
            "zenodo": {"found": False},
            "dryad": {"found": False},
        },
    },

    "10.1038/s41586-020-2649-2": {
        "title": "Array programming with NumPy",
        "year": 2020,
        "pmid": "32939066",
        "pmcid": "PMC7759461",
        "authors": [
            ("Charles R.", "Harris", "0000-0002-7937-5095"),
            ("K. Jarrod", "Millman", "0000-0002-5263-5070"),
            ("Stefan J.", "van der Walt", "0000-0001-9276-1891"),
            ("Travis E.", "Oliphant", None),
        ],
        "sources": {
            "crossref": {
                "found": True, "citation_count": 8421, "reference_count": 58, "has_authors": True,
                "references": [{"doi": f"10.1000/numpy_ref_{i}", "year": 2010 + i % 10} for i in range(30)],
            },
            "openalex": {
                "found": True, "citation_count": 9832, "has_authors": True,
                "counts_by_year": {2020: 450, 2021: 1800, 2022: 2200, 2023: 2400, 2024: 2100, 2025: 882},
                "impact_indicators": [{"name": "fwci", "value": 312.5}],
            },
            "semantic_scholar": {
                "found": True, "citation_count": 8956, "influential_citation_count": 412,
                "citations": (
                    [{"doi": f"10.1000/np_meth_{i}", "year": 2021 + i % 4, "intents": ["Methodology"],
                      "is_influential": i % 5 == 0} for i in range(35)]
                    + [{"doi": f"10.1000/np_bg_{i}", "year": 2021 + i % 5, "intents": ["Background"],
                        "is_influential": False} for i in range(65)]
                ),
            },
            "europe_pmc": {"found": True, "citation_count": 7500},
            "openaire": {
                "found": True, "pagerank": 2.1e-5,
                "impact_indicators": [{"name": "bip_influence", "value": 2.1e-5, "class_label": "C1"}],
            },
            "nih_reporter": {"found": False},
            "unpaywall": {"found": True},
            "orcid": {"found": True, "has_authors": True},
            "datacite": {"found": False},
            "zenodo": {"found": False},
            "dryad": {"found": False},
        },
    },

    "10.1016/S0140-6736(20)30183-5": {
        "title": "Clinical features of patients infected with 2019 novel coronavirus in Wuhan, China",
        "year": 2020,
        "pmid": "31986264",
        "authors": [
            ("Chaolin", "Huang", None),
            ("Yeming", "Wang", None),
            ("Xingwang", "Li", None),
            ("Bin", "Cao", "0000-0001-6650-4056"),
        ],
        "sources": {
            "crossref": {
                "found": True, "citation_count": 28500, "reference_count": 22, "has_authors": True,
                "references": [{"doi": f"10.1000/covid_ref_{i}", "year": 2015 + i % 5} for i in range(22)],
            },
            "openalex": {
                "found": True, "citation_count": 32100,
                "counts_by_year": {2020: 12000, 2021: 8500, 2022: 5200, 2023: 3400, 2024: 2200, 2025: 800},
                "impact_indicators": [{"name": "fwci", "value": 1850.2}],
            },
            "semantic_scholar": {
                "found": True, "citation_count": 29800, "influential_citation_count": 2350,
                "citations": (
                    [{"doi": f"10.1000/cov_meth_{i}", "year": 2020 + i % 5, "intents": ["Methodology"],
                      "is_influential": True} for i in range(8)]
                    + [{"doi": f"10.1000/cov_res_{i}", "year": 2020 + i % 4, "intents": ["ResultComparison"],
                        "is_influential": i % 4 == 0} for i in range(25)]
                    + [{"doi": f"10.1000/cov_bg_{i}", "year": 2020 + i % 5, "intents": ["Background"],
                        "is_influential": False} for i in range(67)]
                ),
            },
            "europe_pmc": {
                "found": True, "citation_count": 27000,
                "mesh_terms": ["COVID-19", "Coronavirus", "Betacoronavirus", "Pneumonia, Viral",
                               "China", "Humans", "Cytokine Release Syndrome"],
            },
            "openaire": {
                "found": True, "pagerank": 8.5e-5,
                "impact_indicators": [{"name": "bip_influence", "value": 8.5e-5, "class_label": "C1"}],
            },
            "nih_reporter": {"found": True, "rcr": 385.0},
            "unpaywall": {"found": True},
            "orcid": {"found": True, "has_authors": True},
            "datacite": {"found": False},
            "zenodo": {"found": False},
            "dryad": {"found": False},
        },
    },

    "10.1038/nmeth.1923": {
        "title": "Aligning sequence reads, clone sequences and assembly contigs with BWA-MEM",
        "year": 2013,
        "pmid": "25505094",
        "authors": [("Heng", "Li", "0000-0003-4874-2874")],
        "sources": {
            "crossref": {
                "found": True, "citation_count": 22000, "reference_count": 14, "has_authors": True,
                "references": [{"doi": f"10.1000/bwa_ref_{i}", "year": 2009 + i % 4} for i in range(14)],
            },
            "openalex": {
                "found": True, "citation_count": 25400,
                "counts_by_year": {2014: 1200, 2015: 2400, 2016: 3000, 2017: 3200, 2018: 3100,
                                   2019: 2800, 2020: 2600, 2021: 2400, 2022: 2100, 2023: 1900, 2024: 1700},
                "impact_indicators": [{"name": "fwci", "value": 120.8}],
            },
            "semantic_scholar": {
                "found": True, "citation_count": 23500, "influential_citation_count": 3800,
                "citations": (
                    [{"doi": f"10.1000/bwa_meth_{i}", "year": 2014 + i % 11, "intents": ["Methodology"],
                      "is_influential": True} for i in range(50)]
                    + [{"doi": f"10.1000/bwa_bg_{i}", "year": 2015 + i % 10, "intents": ["Background"],
                        "is_influential": False} for i in range(50)]
                ),
            },
            "europe_pmc": {
                "found": True, "citation_count": 21000,
                "mesh_terms": ["Sequence Analysis, DNA", "Algorithms", "Software",
                               "Sequence Alignment", "Genomics"],
                "grants": [{"funder": "NHGRI", "id": "R01HG008164"}],
            },
            "openaire": {
                "found": True, "pagerank": 4.2e-5,
                "impact_indicators": [{"name": "bip_influence", "value": 4.2e-5, "class_label": "C1"}],
            },
            "nih_reporter": {"found": True, "rcr": 89.3, "nih_grants": [{"id": "R01HG008164"}]},
            "unpaywall": {"found": True},
            "orcid": {"found": True, "has_authors": True},
            "datacite": {"found": False},
            "zenodo": {"found": False},
            "dryad": {"found": False},
        },
    },

    "10.1093/bioinformatics/btp324": {
        "title": "The Sequence Alignment/Map format and SAMtools",
        "year": 2009,
        "pmid": "19505943",
        "authors": [
            ("Heng", "Li", "0000-0003-4874-2874"),
            ("Bob", "Handsaker", None),
            ("Richard", "Durbin", "0000-0002-0225-4829"),
        ],
        "sources": {
            "crossref": {
                "found": True, "citation_count": 35000, "reference_count": 18, "has_authors": True,
                "references": [{"doi": f"10.1000/sam_ref_{i}", "year": 2004 + i % 5} for i in range(18)],
            },
            "openalex": {
                "found": True, "citation_count": 42000,
                "counts_by_year": {2010: 1000, 2011: 2200, 2012: 3400, 2013: 4000, 2014: 4200,
                                   2015: 4100, 2016: 3900, 2017: 3600, 2018: 3400, 2019: 3100,
                                   2020: 2900, 2021: 2700, 2022: 2500, 2023: 2300, 2024: 2100},
                "impact_indicators": [{"name": "fwci", "value": 198.5}],
            },
            "semantic_scholar": {
                "found": True, "citation_count": 38000, "influential_citation_count": 6200,
                "citations": (
                    [{"doi": f"10.1000/sam_meth_{i}", "year": 2010 + i % 15, "intents": ["Methodology"],
                      "is_influential": True} for i in range(55)]
                    + [{"doi": f"10.1000/sam_bg_{i}", "year": 2011 + i % 14, "intents": ["Background"],
                        "is_influential": False} for i in range(45)]
                ),
            },
            "europe_pmc": {
                "found": True, "citation_count": 33000,
                "mesh_terms": ["Software", "Sequence Analysis, DNA", "Sequence Alignment",
                               "Genome, Human", "Algorithms", "Genomics"],
            },
            "openaire": {
                "found": True, "pagerank": 5.5e-5,
                "impact_indicators": [{"name": "bip_influence", "value": 5.5e-5, "class_label": "C1"}],
            },
            "nih_reporter": {"found": True, "rcr": 125.6},
            "unpaywall": {"found": True},
            "orcid": {"found": True, "has_authors": True},
            "datacite": {"found": False},
            "zenodo": {"found": False},
            "dryad": {"found": False},
        },
    },

    "10.1056/NEJMoa2001017": {
        "title": "Remdesivir for the Treatment of Covid-19 — Final Report",
        "year": 2020,
        "pmid": "32445440",
        "authors": [
            ("John H.", "Beigel", "0000-0002-1234-5001"),
            ("Kay M.", "Tomashek", None),
            ("Lori E.", "Dodd", None),
        ],
        "sources": {
            "crossref": {
                "found": True, "citation_count": 6800, "reference_count": 35, "has_authors": True,
                "clinical_trial_numbers": [
                    {"number": "NCT04280705", "type": "results"},
                ],
                "references": [{"doi": f"10.1000/rem_ref_{i}", "year": 2018 + i % 3} for i in range(35)],
            },
            "openalex": {
                "found": True, "citation_count": 7900,
                "counts_by_year": {2020: 2500, 2021: 2200, 2022: 1400, 2023: 1000, 2024: 600, 2025: 200},
                "impact_indicators": [{"name": "fwci", "value": 89.4}],
            },
            "semantic_scholar": {
                "found": True, "citation_count": 7100, "influential_citation_count": 580,
                "citations": (
                    [{"doi": f"10.1000/rem_meth_{i}", "year": 2020 + i % 5, "intents": ["Methodology"],
                      "is_influential": True} for i in range(6)]
                    + [{"doi": f"10.1000/rem_res_{i}", "year": 2020 + i % 4, "intents": ["ResultComparison"],
                        "is_influential": i % 3 == 0} for i in range(20)]
                    + [{"doi": f"10.1000/rem_bg_{i}", "year": 2020 + i % 5, "intents": ["Background"],
                        "is_influential": False} for i in range(74)]
                ),
            },
            "europe_pmc": {
                "found": True, "citation_count": 6500,
                "mesh_terms": ["COVID-19", "Antiviral Agents", "Randomized Controlled Trials as Topic",
                               "Treatment Outcome", "Adenosine Monophosphate"],
            },
            "openaire": {"found": True, "pagerank": 1.8e-5,
                         "impact_indicators": [{"name": "bip_influence", "value": 1.8e-5, "class_label": "C2"}]},
            "nih_reporter": {"found": True, "rcr": 65.2, "nih_grants": [{"id": "HHSN272201500002C"}]},
            "unpaywall": {"found": True},
            "orcid": {"found": True, "has_authors": True},
            "datacite": {"found": False},
            "zenodo": {"found": False},
            "dryad": {"found": False},
        },
    },

    "10.1001/jama.2020.6775": {
        "title": "Effect of Hydroxychloroquine in Hospitalized Patients with Covid-19",
        "year": 2020,
        "pmid": "32492114",
        "authors": [
            ("Wei", "Tang", None),
            ("Zhujun", "Cao", None),
        ],
        "sources": {
            "crossref": {
                "found": True, "citation_count": 1200, "reference_count": 28, "has_authors": True,
                "clinical_trial_numbers": [{"number": "ChiCTR2000029868", "type": "results"}],
                "references": [{"doi": f"10.1000/hcq_ref_{i}", "year": 2018 + i % 3} for i in range(28)],
            },
            "openalex": {
                "found": True, "citation_count": 1450,
                "counts_by_year": {2020: 600, 2021: 400, 2022: 200, 2023: 130, 2024: 80, 2025: 40},
                "impact_indicators": [{"name": "fwci", "value": 28.5}],
            },
            "semantic_scholar": {
                "found": True, "citation_count": 1300, "influential_citation_count": 85,
                "citations": (
                    [{"doi": f"10.1000/hcq_res_{i}", "year": 2020 + i % 4, "intents": ["ResultComparison"],
                      "is_influential": i % 4 == 0} for i in range(30)]
                    + [{"doi": f"10.1000/hcq_bg_{i}", "year": 2020 + i % 5,
                       "intents": ["Background"]} for i in range(70)]
                ),
            },
            "europe_pmc": {
                "found": True, "citation_count": 1100,
                "mesh_terms": ["COVID-19", "Hydroxychloroquine", "Treatment Outcome"],
            },
            "openaire": {"found": True, "pagerank": 5.2e-6,
                         "impact_indicators": [{"name": "bip_influence", "value": 5.2e-6, "class_label": "C3"}]},
            "nih_reporter": {"found": False},
            "unpaywall": {"found": True},
            "orcid": {"found": True},
            "datacite": {"found": False},
            "zenodo": {"found": False},
            "dryad": {"found": False},
        },
    },

    "10.5061/dryad.8sf3tx0h5": {
        "title": "Data from: Landscape genomics of a widely distributed snake",
        "year": 2021,
        "authors": [("Todd", "Castoe", "0000-0002-2132-0643")],
        "sources": {
            "datacite": {
                "found": True, "has_authors": True,
                "related_works": [
                    {"identifier": "10.1111/mec.16295", "relation_type": "IsSupplementTo"},
                ],
            },
            "dryad": {"found": True, "has_authors": True},
            "openalex": {"found": True, "citation_count": 3},
            "crossref": {"found": False},
            "semantic_scholar": {"found": False},
            "europe_pmc": {"found": False},
            "openaire": {"found": False},
            "nih_reporter": {"found": False},
            "unpaywall": {"found": False},
            "orcid": {"found": True, "has_authors": True},
            "zenodo": {"found": False},
        },
    },

    "10.5281/zenodo.3509134": {
        "title": "Astropy: A community Python package for astronomy",
        "year": 2019,
        "authors": [("Astropy", "Collaboration", None)],
        "sources": {
            "zenodo": {
                "found": True,
                "related_works": [
                    {"identifier": "10.5281/zenodo.3509133", "relation_type": "IsVersionOf"},
                ],
            },
            "datacite": {"found": True},
            "openalex": {"found": True, "citation_count": 15},
            "crossref": {"found": False},
            "semantic_scholar": {"found": False},
            "europe_pmc": {"found": False},
            "openaire": {"found": True, "pagerank": 1.2e-7},
            "nih_reporter": {"found": False},
            "unpaywall": {"found": False},
            "orcid": {"found": False},
            "dryad": {"found": False},
        },
    },

    "10.1371/journal.pone.0185809": {
        "title": "Comprehensive molecular characterization of muscle-invasive bladder cancer",
        "year": 2017,
        "pmid": "29019457",
        "authors": [
            ("John N.", "Weinstein", "0000-0003-1281-5878"),
            ("Eric A.", "Collisson", None),
        ],
        "sources": {
            "crossref": {
                "found": True, "citation_count": 85, "reference_count": 42, "has_authors": True,
                "references": [{"doi": f"10.1000/plos_ref_{i}", "year": 2010 + i % 7} for i in range(30)],
            },
            "openalex": {
                "found": True, "citation_count": 110,
                "counts_by_year": {2018: 15, 2019: 20, 2020: 18, 2021: 16, 2022: 14, 2023: 13, 2024: 10, 2025: 4},
                "impact_indicators": [{"name": "fwci", "value": 3.8}],
            },
            "semantic_scholar": {
                "found": True, "citation_count": 95, "influential_citation_count": 8,
                "citations": (
                    [{"doi": f"10.1000/plos_meth_{i}", "year": 2018 + i % 6, "intents": ["Methodology"],
                      "is_influential": True} for i in range(3)]
                    + [{"doi": f"10.1000/plos_res_{i}", "year": 2018 + i % 6,
                       "intents": ["ResultComparison"]} for i in range(5)]
                    + [{"doi": f"10.1000/plos_bg_{i}", "year": 2018 + i % 7,
                       "intents": ["Background"]} for i in range(40)]
                ),
            },
            "europe_pmc": {
                "found": True, "citation_count": 80,
                "mesh_terms": ["Urinary Bladder Neoplasms", "Neoplasm Staging", "Genomics"],
            },
            "openaire": {"found": True, "pagerank": 2.1e-7},
            "nih_reporter": {"found": True, "rcr": 2.8},
            "unpaywall": {"found": True},
            "orcid": {"found": True, "has_authors": True},
            "datacite": {"found": False},
            "zenodo": {"found": False},
            "dryad": {"found": False},
        },
    },

    "10.7554/eLife.47612": {
        "title": "High-throughput functional analysis of lncRNA core promoters",
        "year": 2019,
        "pmid": "31584428",
        "authors": [
            ("Xiang-Dong", "Fu", "0000-0002-9415-8764"),
            ("Sidi", "Chen", "0000-0002-5094-6902"),
        ],
        "sources": {
            "crossref": {
                "found": True, "citation_count": 42, "reference_count": 55, "has_authors": True,
                "references": [{"doi": f"10.1000/elife_ref_{i}", "year": 2012 + i % 7} for i in range(35)],
            },
            "openalex": {
                "found": True, "citation_count": 58,
                "counts_by_year": {2020: 12, 2021: 14, 2022: 11, 2023: 10, 2024: 7, 2025: 4},
                "impact_indicators": [{"name": "fwci", "value": 2.1}],
            },
            "semantic_scholar": {
                "found": True, "citation_count": 50, "influential_citation_count": 6,
                "citations": (
                    [{"doi": f"10.1000/elife_meth_{i}", "year": 2020 + i % 5, "intents": ["Methodology"],
                      "is_influential": True} for i in range(4)]
                    + [{"doi": f"10.1000/elife_bg_{i}", "year": 2020 + i % 5,
                       "intents": ["Background"]} for i in range(30)]
                ),
            },
            "europe_pmc": {
                "found": True, "citation_count": 38,
                "mesh_terms": ["RNA, Long Noncoding", "Promoter Regions, Genetic", "High-Throughput Screening Assays"],
            },
            "openaire": {"found": True, "pagerank": 8.5e-8},
            "nih_reporter": {"found": True, "rcr": 1.9, "nih_grants": [{"id": "R01GM118432"}]},
            "unpaywall": {"found": True},
            "orcid": {"found": True, "has_authors": True},
            "datacite": {"found": False},
            "zenodo": {"found": False},
            "dryad": {"found": False},
        },
    },

    "10.48550/arXiv.1706.03762": {
        "title": "Attention Is All You Need",
        "year": 2017,
        "authors": [
            ("Ashish", "Vaswani", None),
            ("Noam", "Shazeer", None),
            ("Niki", "Parmar", None),
            ("Jakob", "Uszkoreit", None),
            ("Llion", "Jones", None),
            ("Illia", "Polosukhin", None),
        ],
        "sources": {
            "semantic_scholar": {
                "found": True, "citation_count": 125000, "influential_citation_count": 18000,
                "has_authors": True,
                "citations": (
                    [{"doi": f"10.1000/attn_meth_{i}", "year": 2018 + i % 8, "intents": ["Methodology"],
                      "is_influential": True} for i in range(40)]
                    + [{"doi": f"10.1000/attn_res_{i}", "year": 2019 + i % 7, "intents": ["ResultComparison"],
                        "is_influential": i % 5 == 0} for i in range(20)]
                    + [{"doi": f"10.1000/attn_bg_{i}", "year": 2018 + i % 8,
                       "intents": ["Background"]} for i in range(40)]
                ),
            },
            "openalex": {
                "found": True, "citation_count": 130000,
                "counts_by_year": {2018: 1500, 2019: 5000, 2020: 12000, 2021: 22000, 2022: 28000,
                                   2023: 32000, 2024: 25000, 2025: 4500},
                "impact_indicators": [{"name": "fwci", "value": 4200.0}],
            },
            "openaire": {
                "found": True, "pagerank": 1.2e-4,
                "impact_indicators": [{"name": "bip_influence", "value": 1.2e-4, "class_label": "C1"}],
            },
            "crossref": {"found": False},
            "europe_pmc": {"found": False},
            "nih_reporter": {"found": False},
            "unpaywall": {"found": False},
            "orcid": {"found": False},
            "datacite": {"found": True},
            "zenodo": {"found": False},
            "dryad": {"found": False},
        },
    },

    "10.1016/S0140-6736(20)30566-3": {
        "title": "Hydroxychloroquine in patients with mainly mild to moderate COVID-19 (RETRACTED)",
        "year": 2020,
        "pmid": "32423584",
        "authors": [
            ("Mandeep R.", "Mehra", "0000-0002-1234-9999"),
            ("Sapan S.", "Desai", None),
        ],
        "sources": {
            "crossref": {
                "found": True, "citation_count": 2200, "reference_count": 30, "has_authors": True,
                "update_to": [{"type": "retraction", "DOI": "10.1016/S0140-6736(20)31324-6"}],
                "references": [{"doi": f"10.1000/lancet_ref_{i}", "year": 2018 + i % 3} for i in range(20)],
            },
            "openalex": {
                "found": True, "citation_count": 2800,
                "counts_by_year": {2020: 1500, 2021: 600, 2022: 300, 2023: 200, 2024: 100, 2025: 100},
                "impact_indicators": [{"name": "fwci", "value": 52.3}],
            },
            "semantic_scholar": {
                "found": True, "citation_count": 2500, "influential_citation_count": 120,
                "citations": (
                    [{"doi": f"10.1000/lancet_bg_{i}", "year": 2020 + i % 5, "intents": ["Background"],
                      "is_influential": False} for i in range(90)]
                    + [{"doi": f"10.1000/lancet_res_{i}", "year": 2020 + i % 4,
                       "intents": ["ResultComparison"]} for i in range(10)]
                ),
            },
            "europe_pmc": {
                "found": True, "citation_count": 2000,
                "corrections": [{"type": "Retraction", "id": "PMC7274621", "source": "PubMed"}],
                "mesh_terms": ["COVID-19", "Hydroxychloroquine"],
            },
            "openaire": {"found": True, "pagerank": 4.8e-6},
            "nih_reporter": {"found": False},
            "unpaywall": {"found": True},
            "orcid": {"found": True, "has_authors": True},
            "datacite": {"found": False},
            "zenodo": {"found": False},
            "dryad": {"found": False},
        },
    },
}


# ---------------------------------------------------------------------------
# Result extraction (shared between live and fixture modes)
# ---------------------------------------------------------------------------

def extract_paper_result(
    doi: str, label: str, domain: str,
    agg_result: AggregatedResult,
    cn_result: CitationNetworkResult | None,
    fetch_time: float,
) -> PaperResult:
    """Extract benchmark-relevant fields from the full pipeline output."""
    pr = PaperResult(doi=doi, label=label, domain=domain, fetch_time_s=round(fetch_time, 1))

    # Source completeness
    for name, src in sorted(agg_result.sources.items()):
        if src.found:
            pr.sources_found.append(name)
        elif src.error:
            pr.sources_error.append(name)
        else:
            pr.sources_not_found.append(name)

    # Authors from aggregated result
    seen_authors: dict[str, dict] = {}
    for src in agg_result.sources.values():
        if not src.found or not src.authors:
            continue
        for a in src.authors:
            orcid = a.name.orcid
            name = a.name.full_name or f"{a.name.given or ''} {a.name.family or ''}".strip()
            key = orcid if orcid else name.lower()
            if key and key not in seen_authors:
                seen_authors[key] = {"name": name, "orcid": orcid}
    pr.authors = list(seen_authors.values())

    if cn_result is None:
        return pr

    # PageRank
    pr.s_index = cn_result.s_index
    pr.pagerank_standard = cn_result.pagerank.standard
    pr.pagerank_time_decay = cn_result.pagerank.time_decay
    pr.pagerank_standard_percentile = cn_result.pagerank.standard_percentile
    pr.pagerank_time_decay_percentile = cn_result.pagerank.time_decay_percentile

    # Topology
    topo = cn_result.topology
    pr.in_degree = topo.in_degree
    pr.out_degree = topo.out_degree
    pr.self_citation_fraction = topo.self_citation_fraction
    pr.influential_fraction = topo.influential_fraction
    pr.graph_truncated = topo.graph_is_truncated
    pr.known_citation_count = topo.known_citation_count

    # Intent
    ip = cn_result.intent_profile
    pr.methodology_fraction = ip.methodology_fraction
    pr.dominant_intent = ip.dominant_intent

    # Field normalization
    fn = cn_result.field_normalization
    pr.fwci = fn.fwci
    pr.rcr = fn.relative_citation_ratio
    pr.bip_influence = fn.bip_influence

    # Velocity
    pr.citation_velocity_trend = cn_result.citation_velocity.trend

    # Biomedical
    bio = cn_result.biomedical
    pr.has_mesh = bio.has_mesh_terms
    pr.has_clinical_trials = bio.has_clinical_trials
    pr.has_retraction = bio.has_retraction
    pr.pmid_available = bio.pmid_available

    # Narrative
    pr.narrative = cn_result.narrative

    # Author PageRank from citation network
    for apr in cn_result.author_pagerank:
        for a in pr.authors:
            if a.get("orcid") and a["orcid"] == apr.orcid:
                a["pagerank_sum"] = apr.pagerank_sum
                break
            elif a.get("name", "").lower() == apr.name.lower():
                a["pagerank_sum"] = apr.pagerank_sum
                break

    return pr


# ---------------------------------------------------------------------------
# Live API mode
# ---------------------------------------------------------------------------

async def run_single_doi_live(doi: str, label: str, domain: str) -> PaperResult:
    """Run the full pipeline on a single DOI via live APIs."""
    from doi_metadata.orchestrator import lookup

    t0 = time.monotonic()
    try:
        agg = await lookup(doi, include_raw=False, follow_links=True)
        fetch_time = time.monotonic() - t0
        cn = None
        try:
            cn = analyze_citation_network(agg)
        except Exception as e:
            logging.warning("Citation network analysis failed for %s: %s", doi, e)
        return extract_paper_result(doi, label, domain, agg, cn, fetch_time)
    except Exception as e:
        fetch_time = time.monotonic() - t0
        pr = PaperResult(doi=doi, label=label, domain=domain, fetch_time_s=round(fetch_time, 1))
        pr.error = str(e)
        return pr


async def run_benchmark_live(dois: list[tuple[str, str, str]]) -> list[PaperResult]:
    """Run benchmark via live APIs (sequential, polite)."""
    results: list[PaperResult] = []
    total = len(dois)
    for i, (doi, label, domain) in enumerate(dois, 1):
        print(f"\n{'='*70}")
        print(f"[{i}/{total}] {label}")
        print(f"  DOI: {doi}")
        print(f"{'='*70}")
        result = await run_single_doi_live(doi, label, domain)
        _print_progress(result)
        results.append(result)
        if i < total:
            print("  Waiting 2s...")
            await asyncio.sleep(2)
    return results


# ---------------------------------------------------------------------------
# Fixture mode
# ---------------------------------------------------------------------------

def run_benchmark_fixture(dois: list[tuple[str, str, str]]) -> list[PaperResult]:
    """Run benchmark using built-in realistic fixtures."""
    results: list[PaperResult] = []
    total = len(dois)
    for i, (doi, label, domain) in enumerate(dois, 1):
        print(f"\n{'='*70}")
        print(f"[{i}/{total}] {label}")
        print(f"  DOI: {doi}")
        print(f"{'='*70}")

        spec = FIXTURES.get(doi)
        if spec is None:
            pr = PaperResult(doi=doi, label=label, domain=domain)
            pr.error = f"No fixture data for {doi}"
            _print_progress(pr)
            results.append(pr)
            continue

        t0 = time.monotonic()
        agg = build_fixture(doi, label, spec)
        cn = None
        try:
            cn = analyze_citation_network(agg)
        except Exception as e:
            logging.warning("Citation network analysis failed for %s: %s", doi, e)
        fetch_time = time.monotonic() - t0

        result = extract_paper_result(doi, label, domain, agg, cn, fetch_time)
        _print_progress(result)
        results.append(result)

    return results


def _print_progress(result: PaperResult) -> None:
    if result.error:
        print(f"  ERROR: {result.error}")
    else:
        print(f"  S-index: {result.s_index:.4f}")
        pr_str = f"{result.pagerank_standard:.4e}" if result.pagerank_standard > 0 else "N/A"
        pct_str = f"{result.pagerank_standard_percentile:.2f}" if result.pagerank_standard_percentile > 0 else "N/A"
        print(f"  PageRank: {pr_str} (percentile: {pct_str})")
        print(f"  Graph: {result.in_degree} inbound, {result.out_degree} outbound"
              f"{' [TRUNCATED]' if result.graph_truncated else ''}")
        total_src = len(result.sources_found) + len(result.sources_not_found) + len(result.sources_error)
        print(f"  Sources found: {len(result.sources_found)}/{total_src}")


# ---------------------------------------------------------------------------
# Report formatting
# ---------------------------------------------------------------------------

def print_paper_ranking(results: list[PaperResult]) -> None:
    ranked = sorted(results, key=lambda r: r.s_index, reverse=True)

    print("\n")
    print("=" * 110)
    print("  PAPER RANKING BY S-INDEX")
    print("=" * 110)
    print(f"{'Rank':>4}  {'S-index':>8}  {'PR-std':>10}  {'PR-%ile':>7}  {'In':>5}  {'Out':>4}  "
          f"{'FWCI':>8}  {'RCR':>6}  {'Trunc':>5}  {'Label'}")
    print("-" * 110)

    for i, r in enumerate(ranked, 1):
        fwci_str = f"{r.fwci:.1f}" if r.fwci is not None else "-"
        rcr_str = f"{r.rcr:.1f}" if r.rcr is not None else "-"
        trunc_str = "YES" if r.graph_truncated else ""
        retract_str = " [RETRACTED]" if r.has_retraction else ""
        err_str = " [ERROR]" if r.error else ""

        print(f"{i:>4}  {r.s_index:>8.4f}  {r.pagerank_standard:>10.4e}  "
              f"{r.pagerank_standard_percentile:>7.2f}  {r.in_degree:>5}  {r.out_degree:>4}  "
              f"{fwci_str:>8}  {rcr_str:>6}  {trunc_str:>5}  {r.label}{retract_str}{err_str}")

    print("-" * 110)


def print_detailed_metrics(results: list[PaperResult]) -> None:
    ranked = sorted(results, key=lambda r: r.s_index, reverse=True)

    print("\n")
    print("=" * 100)
    print("  DETAILED METRICS")
    print("=" * 100)

    for i, r in enumerate(ranked, 1):
        print(f"\n--- #{i} {r.label} (S-index: {r.s_index:.4f}) ---")
        print(f"  DOI: {r.doi}")
        print(f"  Domain: {r.domain}")

        if r.error:
            print(f"  ERROR: {r.error}")
            continue

        pr_std = f"{r.pagerank_standard:.6e}"
        pr_td = f"{r.pagerank_time_decay:.6e}"
        print(f"  PageRank (standard):   {pr_std}  (percentile: {r.pagerank_standard_percentile:.4f})")
        print(f"  PageRank (time-decay): {pr_td}  (percentile: {r.pagerank_time_decay_percentile:.4f})")
        print(f"  Graph: {r.in_degree} inbound, {r.out_degree} outbound"
              f"  {'[TRUNCATED from ~' + str(r.known_citation_count) + ']' if r.graph_truncated else ''}")

        if r.self_citation_fraction is not None:
            print(f"  Self-citation fraction: {r.self_citation_fraction:.1%}")
        if r.influential_fraction is not None:
            print(f"  Influential fraction: {r.influential_fraction:.1%}")

        if r.dominant_intent:
            meth_str = f"{r.methodology_fraction:.0%}" if r.methodology_fraction is not None else "-"
            print(f"  Dominant intent: {r.dominant_intent}  (methodology: {meth_str})")

        parts = []
        if r.fwci is not None:
            parts.append(f"FWCI={r.fwci:.2f}")
        if r.rcr is not None:
            parts.append(f"RCR={r.rcr:.2f}")
        if r.bip_influence is not None:
            parts.append(f"BIP!={r.bip_influence:.4e}")
        if parts:
            print(f"  Field normalization: {', '.join(parts)}")

        if r.citation_velocity_trend:
            print(f"  Citation velocity: {r.citation_velocity_trend}")

        bio_parts = []
        if r.has_mesh:
            bio_parts.append("MeSH")
        if r.has_clinical_trials:
            bio_parts.append("clinical-trials")
        if r.pmid_available:
            bio_parts.append("PMID")
        if r.has_retraction:
            bio_parts.append("RETRACTED")
        if bio_parts:
            print(f"  Biomedical signals: {', '.join(bio_parts)}")

        if r.narrative:
            # Print first 200 chars of narrative
            narr = r.narrative[:200] + ("..." if len(r.narrative) > 200 else "")
            print(f"  Narrative: {narr}")


def print_author_ranking(results: list[PaperResult]) -> None:
    author_agg: dict[str, dict] = {}

    for r in results:
        if r.error:
            continue
        for a in r.authors:
            orcid = a.get("orcid")
            name = a.get("name", "Unknown")
            key = orcid if orcid else name.lower()
            if not key:
                continue

            if key not in author_agg:
                author_agg[key] = {
                    "name": name,
                    "orcid": orcid,
                    "papers": [],
                    "total_s_index": 0.0,
                    "max_s_index": 0.0,
                    "pagerank_sum": 0.0,
                }

            entry = author_agg[key]
            entry["papers"].append({"doi": r.doi, "label": r.label, "s_index": r.s_index})
            entry["total_s_index"] += r.s_index
            entry["max_s_index"] = max(entry["max_s_index"], r.s_index)
            entry["pagerank_sum"] += a.get("pagerank_sum", 0.0)

    if not author_agg:
        print("\n  No author data available.")
        return

    ranked = sorted(
        author_agg.values(),
        key=lambda a: (a["total_s_index"], len(a["papers"])),
        reverse=True,
    )

    # Show authors on 2+ papers first, then top 30 single-paper
    multi_paper = [a for a in ranked if len(a["papers"]) >= 2]
    show = multi_paper if multi_paper else ranked[:30]

    print("\n")
    print("=" * 110)
    print("  AUTHOR RANKING (by cumulative S-index across benchmark papers)")
    print("=" * 110)
    print(f"{'Rank':>4}  {'Total-S':>8}  {'Max-S':>7}  {'Papers':>6}  {'ORCID':>25}  {'Name'}")
    print("-" * 110)

    for i, a in enumerate(show[:50], 1):
        orcid_str = a["orcid"] or "-"
        papers_str = ", ".join(p["label"][:20] for p in a["papers"])
        print(f"{i:>4}  {a['total_s_index']:>8.4f}  {a['max_s_index']:>7.4f}  "
              f"{len(a['papers']):>6}  {orcid_str:>25}  {a['name']}")
        if len(a["papers"]) > 1:
            print(f"        Papers: {papers_str}")

    if not multi_paper:
        print("\n  (No authors appeared on 2+ benchmark papers; showing top single-paper authors)")

    print("-" * 110)
    print(f"  Total unique authors across benchmark: {len(author_agg)}")


def print_data_completeness(results: list[PaperResult]) -> None:
    all_sources = sorted({
        s for r in results
        for s in r.sources_found + r.sources_not_found + r.sources_error
    })

    if not all_sources:
        return

    print("\n")
    print("=" * 120)
    print("  DATA COMPLETENESS MATRIX (source x paper)")
    print("=" * 120)

    label_width = 30
    print(f"{'Paper':<{label_width}}", end="")
    for src in all_sources:
        print(f" {src[:6]:>6}", end="")
    print(f"  {'Found':>5}")
    print("-" * (label_width + 7 * len(all_sources) + 8))

    for r in results:
        label = r.label[:label_width - 1]
        print(f"{label:<{label_width}}", end="")
        found_count = 0
        for src in all_sources:
            if src in r.sources_found:
                print(f"     {'Y':>1}", end="")
                found_count += 1
            elif src in r.sources_error:
                print(f"     {'E':>1}", end="")
            else:
                print(f"     {'-':>1}", end="")
        total = len(r.sources_found) + len(r.sources_not_found) + len(r.sources_error)
        print(f"  {found_count:>2}/{total}")

    print("-" * (label_width + 7 * len(all_sources) + 8))

    print(f"{'Hit rate':<{label_width}}", end="")
    total_papers = len(results)
    for src in all_sources:
        hits = sum(1 for r in results if src in r.sources_found)
        pct = int(hits / total_papers * 100) if total_papers > 0 else 0
        print(f" {pct:>5}%", end="")
    print()
    print()
    print("  Legend: Y=found, -=not found (expected for that DOI type), E=error")


def print_summary_stats(results: list[PaperResult]) -> None:
    valid = [r for r in results if not r.error]

    print("\n")
    print("=" * 70)
    print("  BENCHMARK SUMMARY")
    print("=" * 70)
    print(f"  Papers queried:      {len(results)}")
    print(f"  Successful:          {len(valid)}")
    print(f"  Errors:              {len(results) - len(valid)}")
    print()

    if valid:
        s_indices = [r.s_index for r in valid]
        print(f"  S-index range:       {min(s_indices):.4f} - {max(s_indices):.4f}")
        print(f"  S-index median:      {sorted(s_indices)[len(s_indices)//2]:.4f}")
        print(f"  S-index mean:        {sum(s_indices)/len(s_indices):.4f}")
        print()

        truncated = sum(1 for r in valid if r.graph_truncated)
        with_fwci = sum(1 for r in valid if r.fwci is not None)
        with_rcr = sum(1 for r in valid if r.rcr is not None)
        with_mesh = sum(1 for r in valid if r.has_mesh)
        with_pmid = sum(1 for r in valid if r.pmid_available)
        with_intents = sum(1 for r in valid if r.dominant_intent is not None)
        retracted = sum(1 for r in valid if r.has_retraction)

        print(f"  Graphs truncated:    {truncated}/{len(valid)}")
        print(f"  FWCI available:      {with_fwci}/{len(valid)}")
        print(f"  NIH RCR available:   {with_rcr}/{len(valid)}")
        print(f"  MeSH terms:          {with_mesh}/{len(valid)}")
        print(f"  PMID indexed:        {with_pmid}/{len(valid)}")
        print(f"  Citation intents:    {with_intents}/{len(valid)}")
        print(f"  Retracted:           {retracted}/{len(valid)}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="S-index benchmark")
    parser.add_argument("--live", action="store_true", help="Use live APIs (requires network access)")
    parser.add_argument("--dois", type=str, default=None, help="Comma-separated DOIs (live mode only)")
    parser.add_argument("--output-json", type=str, default=None, help="Path to write JSON results")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose logging")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    level = logging.DEBUG if args.verbose else logging.WARNING
    logging.basicConfig(level=level, format="%(levelname)-8s %(name)s: %(message)s", stream=sys.stderr)
    if not args.verbose:
        logging.getLogger("httpx").setLevel(logging.ERROR)
        logging.getLogger("httpcore").setLevel(logging.ERROR)

    if args.dois:
        dois = [(d.strip(), d.strip(), "custom") for d in args.dois.split(",") if d.strip()]
    else:
        dois = BENCHMARK_DOIS

    mode = "LIVE API" if args.live else "FIXTURE"
    print(f"S-index Benchmark ({mode}) - {len(dois)} DOIs")
    print(f"Started: {datetime.now(timezone.utc).isoformat()}")

    if args.live:
        results = asyncio.run(run_benchmark_live(dois))
    else:
        results = run_benchmark_fixture(dois)

    print_paper_ranking(results)
    print_detailed_metrics(results)
    print_author_ranking(results)
    print_data_completeness(results)
    print_summary_stats(results)

    if args.output_json:
        json_data = {
            "benchmark_date": datetime.now(timezone.utc).isoformat(),
            "mode": mode,
            "papers": [],
        }
        for rank, r in enumerate(sorted(results, key=lambda x: x.s_index, reverse=True), 1):
            json_data["papers"].append({
                "rank": rank, "doi": r.doi, "label": r.label, "domain": r.domain,
                "s_index": r.s_index,
                "pagerank_standard": r.pagerank_standard,
                "pagerank_time_decay": r.pagerank_time_decay,
                "pagerank_standard_percentile": r.pagerank_standard_percentile,
                "in_degree": r.in_degree, "out_degree": r.out_degree,
                "self_citation_fraction": r.self_citation_fraction,
                "influential_fraction": r.influential_fraction,
                "methodology_fraction": r.methodology_fraction,
                "dominant_intent": r.dominant_intent,
                "fwci": r.fwci, "rcr": r.rcr, "bip_influence": r.bip_influence,
                "citation_velocity_trend": r.citation_velocity_trend,
                "has_mesh": r.has_mesh, "has_clinical_trials": r.has_clinical_trials,
                "has_retraction": r.has_retraction, "pmid_available": r.pmid_available,
                "graph_truncated": r.graph_truncated, "known_citation_count": r.known_citation_count,
                "sources_found": r.sources_found, "sources_not_found": r.sources_not_found,
                "authors": r.authors, "narrative": r.narrative,
                "error": r.error,
            })
        with open(args.output_json, "w") as f:
            json.dump(json_data, f, indent=2, default=str)
        print(f"\nJSON results written to {args.output_json}")


if __name__ == "__main__":
    main()
