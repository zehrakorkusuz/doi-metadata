"""Derived analyses — high-value insights from aggregated DOI metadata."""

from doi_metadata.analyses.author_network import analyze_authors
from doi_metadata.analyses.citation_network import analyze_citation_network
from doi_metadata.analyses.dataset_reuse import analyze_dataset_reuse
from doi_metadata.analyses.funding_landscape import analyze_funding
from doi_metadata.analyses.grant_siblings import analyze_grant_siblings
from doi_metadata.analyses.impact_profile import analyze_impact
from doi_metadata.analyses.oa_audit import analyze_oa
from doi_metadata.analyses.topic_profile import analyze_topics

__all__ = [
    "analyze_authors",
    "analyze_citation_network",
    "analyze_dataset_reuse",
    "analyze_funding",
    "analyze_grant_siblings",
    "analyze_impact",
    "analyze_oa",
    "analyze_topics",
]
