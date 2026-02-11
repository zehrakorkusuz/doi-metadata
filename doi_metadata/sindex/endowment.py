"""Compute the data-sharing endowment E(p) for a paper.

The endowment quantifies *direct* evidence that a paper involves data sharing.
It is the personalization vector in our DataRank (Personalized PageRank) metric.

Signals and weights (empirically motivated):
  - DataCite reverse search total    : strongest signal — actual downstream dataset count
  - DataCite relation types          : structural data-sharing links
  - File deposits                    : tangible shared artifacts
  - Downloads / views                : usage evidence
  - Version chain                    : actively maintained data
  - OpenAlex work_type == 'dataset'  : classification signal
  - Open access                      : prerequisite for data sharing
"""

from __future__ import annotations

import math

from doi_metadata.sindex.models import PaperEndowment

# Relation types that indicate data sharing (case-insensitive matching)
DATA_RELATION_TYPES = {
    "issupplementto", "issupplementedby",
    "isderivedfrom", "issourceof",
    "haspart", "ispartof",
    "hasversion", "isversionof",
    "isnewversionof", "ispreviousversionof",
    "cites", "iscitedby",
    "references", "isreferencedby",
    "isidenticalto",
}


def _extract_endowment_signals(result: dict) -> PaperEndowment:
    """Extract raw data-sharing signals from a benchmark result dict."""
    doi = result.get("doi", "")
    pe = PaperEndowment(doi=doi)

    # --- DataCite reverse search total (uncapped) ---
    # New field from the pipeline fix; fall back to len(datacite_linked_datasets)
    pe.datacite_reuse_total = result.get("datacite_linked_total", 0)
    if not pe.datacite_reuse_total:
        pe.datacite_reuse_total = len(result.get("datacite_linked_datasets", []))

    # --- DataCite relation types from all sources ---
    relation_types: set[str] = set()
    sources = result.get("sources", {})
    for _src_name, src in sources.items():
        if not isinstance(src, dict) or not src.get("found"):
            continue
        for rw in src.get("related_works", []):
            rt = (rw.get("relation_type") or "").strip().lower()
            if rt in DATA_RELATION_TYPES:
                relation_types.add(rt)
    pe.datacite_relation_types = sorted(relation_types)

    # --- File deposits (Zenodo, Dryad, DataCite) ---
    file_count = 0
    total_size = 0
    for src in sources.values():
        if not isinstance(src, dict) or not src.get("found"):
            continue
        for f in src.get("files", []):
            file_count += 1
            total_size += f.get("size_bytes") or 0
    pe.file_count = file_count
    pe.total_file_size_bytes = total_size

    # --- Downloads / views ---
    for src in sources.values():
        if not isinstance(src, dict) or not src.get("found"):
            continue
        us = src.get("usage_stats")
        if isinstance(us, dict):
            pe.downloads = max(pe.downloads, us.get("downloads") or 0)
            pe.views = max(pe.views, us.get("views") or 0)

    # --- Version chain ---
    dr = result.get("analyses", {}).get("dataset_reuse", {})
    vc = dr.get("version_chain")
    if vc:
        pe.has_version_chain = True
        pe.version_count = vc.get("total_versions") or len(vc.get("version_dois", []))

    # --- OpenAlex work_type ---
    oa = sources.get("openalex", {})
    if isinstance(oa, dict) and oa.get("found"):
        pe.is_dataset = oa.get("work_type") == "dataset"

    # --- Open access ---
    oa_audit = result.get("analyses", {}).get("oa_audit", {})
    pe.is_oa = bool(oa_audit.get("is_oa"))
    # Fallback to Unpaywall / OpenAlex
    if not pe.is_oa:
        for src_name in ("unpaywall", "openalex"):
            src = sources.get(src_name, {})
            if isinstance(src, dict) and src.get("found") and src.get("is_oa"):
                pe.is_oa = True
                break

    return pe


def compute_endowment(result: dict) -> PaperEndowment:
    """Compute the endowment score E(p) for a single paper.

    The score combines multiple signals with diminishing returns (log scaling)
    to prevent any single signal from dominating.

    Returns a PaperEndowment with the .endowment field populated.
    """
    pe = _extract_endowment_signals(result)

    score = 0.0

    # DataCite reuse total — strongest signal
    # log1p to handle diminishing returns: 1→0.69, 10→2.4, 100→4.6, 1000→6.9
    if pe.datacite_reuse_total > 0:
        score += 5.0 * math.log1p(pe.datacite_reuse_total)

    # Relation type richness — each distinct type adds signal
    score += 1.5 * len(pe.datacite_relation_types)

    # File deposits — tangible evidence of data sharing
    if pe.file_count > 0:
        score += 3.0 + 1.0 * math.log1p(pe.file_count)
        if pe.total_file_size_bytes > 0:
            # Bonus for substantial data (log of MB)
            mb = pe.total_file_size_bytes / (1024 * 1024)
            score += 0.5 * math.log1p(mb)

    # Downloads — usage evidence (log-scaled)
    if pe.downloads > 0:
        score += 2.0 * math.log1p(pe.downloads)
    if pe.views > 0:
        score += 0.5 * math.log1p(pe.views)

    # Version chain — actively maintained data
    if pe.has_version_chain:
        score += 2.0 + 0.5 * math.log1p(pe.version_count)

    # Dataset classification
    if pe.is_dataset:
        score += 3.0

    # Open access — necessary condition for data sharing
    if pe.is_oa:
        score += 1.0

    pe.endowment = score
    return pe


def compute_endowment_from_dict(result: dict) -> float:
    """Convenience: return just the scalar endowment value."""
    return compute_endowment(result).endowment
