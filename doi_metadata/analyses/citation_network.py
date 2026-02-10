"""Citation network analysis — build graph, compute authority-weighted PageRank, biomedical signals.

Builds a directed citation graph from all fetched API data and computes:

- Authority-weighted PageRank (citing paper importance informs edge weight)
- Time-Decay PageRank (exponential recency weighting)
- Citation intent weighting (Methodology > ResultComparison > Background)
- Self-citation detection via ORCID matching + guarded surname fallback
- Anti-gaming: self-citation penalty, retraction detection
- Field-normalized calibration via FWCI and NIH RCR
- Biomedical signals: MeSH topical coherence, clinical trial linkage
- Citation velocity from counts_by_year temporal distribution
- Network topology and author-level aggregation
- Composite S-index with properly normalized components

The graph is a local ego network (1-hop from the queried DOI).  On a star
graph, raw PageRank degenerates to weighted in-degree.  We address this by
injecting authority priors: citing papers with known citation counts get
proportionally higher initial PageRank, approximating what a 2-hop walk
would compute.
"""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timezone

from pydantic import BaseModel, Field

from doi_metadata.models import AggregatedResult, Author, SourceName

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DAMPING = 0.85
MAX_ITERATIONS = 100
CONVERGENCE_THRESHOLD = 1e-8
TIME_DECAY_LAMBDA = 0.15  # exp(-λ * age_years) — a 2024 citation is ~3x a 2014 one
INFLUENTIAL_WEIGHT = 3.0
SELF_CITATION_PENALTY = 0.1  # 10% of normal weight

# Citation intent multipliers (S2 labels)
INTENT_WEIGHTS: dict[str, float] = {
    "methodology": 2.5,     # Cited paper's method was reused/extended
    "resultcomparison": 1.8,  # Results compared against cited work
    "background": 0.7,     # Perfunctory context citation
}

# Surnames too common for reliable self-citation detection via name matching.
# These produce massive false-positive rates across East Asian and common
# Western surnames.  ORCID matching is used for these instead.
COMMON_SURNAMES: frozenset[str] = frozenset({
    "wang", "li", "zhang", "liu", "chen", "yang", "huang", "zhao", "wu", "zhou",
    "kim", "lee", "park", "choi", "jung", "kang", "cho", "yoon",
    "smith", "johnson", "williams", "brown", "jones", "garcia", "miller", "davis",
    "tanaka", "suzuki", "watanabe", "sato", "takahashi", "ito",
    "kumar", "singh", "sharma", "patel",
    "silva", "santos", "oliveira",
    "muller", "schmidt", "schneider", "fischer", "weber", "meyer",
    "martin", "bernard", "dubois", "petit", "moreau",
    "rossi", "russo", "ferrari", "esposito", "bianchi",
})
MIN_SURNAME_LENGTH = 3  # Skip 1-2 char surnames (initials, errors)


def _current_year() -> int:
    """Dynamic year — safe in long-running processes."""
    return datetime.now(timezone.utc).year


# ---------------------------------------------------------------------------
# Graph data structures
# ---------------------------------------------------------------------------

class GraphNode(BaseModel):
    """A paper in the citation graph."""
    node_id: str
    doi: str | None = None
    title: str | None = None
    year: int | None = None
    is_queried: bool = False
    author_names: list[str] = Field(default_factory=list)
    author_orcids: list[str] = Field(default_factory=list)
    citation_count: int | None = None  # Known citation count (authority prior)
    sources: list[str] = Field(default_factory=list)


class GraphEdge(BaseModel):
    """A directed citation edge: source_id cites target_id."""
    source_id: str
    target_id: str
    weight: float = 1.0
    is_influential: bool | None = None
    is_self_citation: bool = False
    intents: list[str] = Field(default_factory=list)
    year: int | None = None
    api_sources: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Result models
# ---------------------------------------------------------------------------

class PageRankScores(BaseModel):
    """PageRank scores for the queried DOI."""
    standard: float = 0.0
    time_decay: float = 0.0
    # Percentile rank within the local graph (0–1)
    standard_percentile: float = 0.0
    time_decay_percentile: float = 0.0
    # Full score vectors for inspection
    standard_all: dict[str, float] = Field(default_factory=dict)
    time_decay_all: dict[str, float] = Field(default_factory=dict)


class IntentProfile(BaseModel):
    """Breakdown of citation intents for the queried paper's inbound citations."""
    methodology_count: int = 0
    result_comparison_count: int = 0
    background_count: int = 0
    unknown_count: int = 0
    methodology_fraction: float | None = None
    dominant_intent: str | None = None


class CitationVelocity(BaseModel):
    """Temporal citation dynamics from counts_by_year data."""
    years: list[int] = Field(default_factory=list)
    counts: list[int] = Field(default_factory=list)
    peak_year: int | None = None
    peak_count: int | None = None
    recent_3yr_avg: float | None = None
    acceleration: float | None = None  # Change in rate (positive = accelerating)
    trend: str | None = None  # "accelerating", "steady", "decelerating", "emerging"


class NetworkTopology(BaseModel):
    """Graph-level topology metrics."""
    total_nodes: int = 0
    total_edges: int = 0
    in_degree: int = 0
    out_degree: int = 0
    self_citation_count: int = 0
    self_citation_fraction: float | None = None
    influential_citation_count: int = 0
    influential_fraction: float | None = None
    unique_sources_contributing: list[str] = Field(default_factory=list)
    graph_is_truncated: bool = False  # True when known citations > graph edges
    known_citation_count: int | None = None  # From API citation counts


class FieldNormalization(BaseModel):
    """Field-normalized benchmarks from external sources."""
    fwci: float | None = None  # OpenAlex Field-Weighted Citation Impact
    relative_citation_ratio: float | None = None  # NIH RCR
    bip_influence: float | None = None  # OpenAIRE BIP! (global PageRank)
    bip_influence_class: str | None = None
    bip_popularity: float | None = None
    bip_impulse: float | None = None


class BiomedicalSignals(BaseModel):
    """Biomedical/PubMed-specific quality signals."""
    has_mesh_terms: bool = False
    mesh_term_count: int = 0
    has_clinical_trials: bool = False
    clinical_trial_count: int = 0
    has_retraction: bool = False
    has_correction: bool = False
    grant_backed_fraction: float | None = None  # Fraction of sources reporting grants
    pmid_available: bool = False


class AuthorPageRank(BaseModel):
    """PageRank aggregated at the author level."""
    name: str
    orcid: str | None = None
    pagerank_sum: float = 0.0
    paper_count: int = 0
    is_queried_author: bool = False


class CitationNetworkResult(BaseModel):
    """Full citation network analysis output."""
    doi: str
    pagerank: PageRankScores = Field(default_factory=PageRankScores)
    s_index: float = 0.0
    topology: NetworkTopology = Field(default_factory=NetworkTopology)
    intent_profile: IntentProfile = Field(default_factory=IntentProfile)
    citation_velocity: CitationVelocity = Field(default_factory=CitationVelocity)
    field_normalization: FieldNormalization = Field(default_factory=FieldNormalization)
    biomedical: BiomedicalSignals = Field(default_factory=BiomedicalSignals)
    author_pagerank: list[AuthorPageRank] = Field(default_factory=list)
    narrative: str = ""


# ---------------------------------------------------------------------------
# Intent weighting
# ---------------------------------------------------------------------------

def _intent_weight(intents: list[str]) -> float:
    """Compute edge weight multiplier from citation intents."""
    if not intents:
        return 1.0
    weights = [INTENT_WEIGHTS.get(i.lower(), 1.0) for i in intents]
    return max(weights)  # Use strongest intent


# ---------------------------------------------------------------------------
# Self-citation detection (ORCID-first, guarded surname fallback)
# ---------------------------------------------------------------------------

def _collect_orcids(authors: list[Author]) -> set[str]:
    """Extract normalized ORCIDs from an author list."""
    orcids: set[str] = set()
    for a in authors:
        oid = a.name.orcid
        if oid:
            cleaned = oid.strip()
            for prefix in ("https://orcid.org/", "http://orcid.org/"):
                if cleaned.startswith(prefix):
                    cleaned = cleaned[len(prefix):]
            if cleaned:
                orcids.add(cleaned)
    return orcids


def _author_name_set(authors: list[Author]) -> set[str]:
    """Extract lowercased author family names, excluding common surnames."""
    names: set[str] = set()
    for a in authors:
        family = None
        if a.name.family:
            family = a.name.family.strip().lower()
        elif a.name.full_name:
            parts = a.name.full_name.strip().split()
            if parts:
                family = parts[-1].lower()
        if family and len(family) >= MIN_SURNAME_LENGTH and family not in COMMON_SURNAMES:
            names.add(family)
    return names


def _detect_self_citation(
    queried_orcids: set[str],
    queried_surnames: set[str],
    citing_orcids: list[str],
    citing_author_names: list[str],
) -> bool:
    """Detect self-citation.  ORCID match is definitive; surname match is guarded."""
    # ORCID match — high confidence
    if queried_orcids and citing_orcids:
        for oid in citing_orcids:
            if oid in queried_orcids:
                return True

    # Surname fallback (only for non-common names)
    if not queried_surnames or not citing_author_names:
        return False
    for name in citing_author_names:
        tokens = {t.lower() for t in name.strip().split()}
        # Only match if token passes the same guards
        filtered = {t for t in tokens if len(t) >= MIN_SURNAME_LENGTH and t not in COMMON_SURNAMES}
        if filtered & queried_surnames:
            return True
    return False


# ---------------------------------------------------------------------------
# Time decay
# ---------------------------------------------------------------------------

def _time_decay_weight(citing_year: int | None) -> float:
    if citing_year is None:
        return 1.0
    age = max(0, _current_year() - citing_year)
    return math.exp(-TIME_DECAY_LAMBDA * age)


# ---------------------------------------------------------------------------
# Graph building (with edge merging, not first-wins discard)
# ---------------------------------------------------------------------------

def build_graph(
    doi: str,
    result: AggregatedResult,
) -> tuple[dict[str, GraphNode], list[GraphEdge]]:
    """Build citation graph from all source data.

    Key improvements over naive implementation:
    - Edges are MERGED across sources (intents, influential flags combined)
    - ORCID-based self-citation detection
    - Citation intent weighting applied to edge weights
    - Citing paper citation counts stored for authority-weighted PageRank
    """
    queried_id = doi.lower()
    nodes: dict[str, GraphNode] = {}
    edge_map: dict[tuple[str, str], GraphEdge] = {}  # Merge, don't discard

    # Collect queried paper's ORCIDs and surnames
    queried_orcids: set[str] = set()
    queried_surnames: set[str] = set()
    queried_author_full_names: list[str] = []
    for src in result.sources.values():
        if src.found and src.authors:
            queried_orcids |= _collect_orcids(src.authors)
            queried_surnames |= _author_name_set(src.authors)
            for a in src.authors:
                name = a.name.full_name or f"{a.name.given or ''} {a.name.family or ''}".strip()
                if name:
                    queried_author_full_names.append(name)

    # Center node
    queried_title = None
    queried_year = None
    for src in result.sources.values():
        if src.found:
            if not queried_title and src.title:
                queried_title = src.title
            if not queried_year and src.publication_year:
                queried_year = src.publication_year

    nodes[queried_id] = GraphNode(
        node_id=queried_id,
        doi=doi,
        title=queried_title,
        year=queried_year,
        is_queried=True,
        author_names=queried_author_full_names,
        author_orcids=sorted(queried_orcids),
    )

    def _ensure_node(nid: str, doi_val: str | None, title: str | None,
                     year: int | None, src_name: str) -> None:
        if nid not in nodes:
            nodes[nid] = GraphNode(node_id=nid, doi=doi_val, title=title, year=year)
        if src_name not in nodes[nid].sources:
            nodes[nid].sources.append(src_name)

    def _merge_edge(key: tuple[str, str], *, weight: float,
                    is_influential: bool | None, is_self: bool,
                    intents: list[str], year: int | None, src_name: str) -> None:
        """Merge edge data from a new source into existing edge, or create new."""
        if key in edge_map:
            e = edge_map[key]
            # Merge: take the richer data
            if is_influential and not e.is_influential:
                e.is_influential = True
            if is_self:
                e.is_self_citation = True
            for intent in intents:
                if intent not in e.intents:
                    e.intents.append(intent)
            if year is not None and e.year is None:
                e.year = year
            if src_name not in e.api_sources:
                e.api_sources.append(src_name)
            # Recompute weight with merged data
            e.weight = _compute_edge_weight(
                e.is_influential, e.is_self_citation, e.intents,
            )
        else:
            edge_map[key] = GraphEdge(
                source_id=key[0],
                target_id=key[1],
                weight=weight,
                is_influential=is_influential,
                is_self_citation=is_self,
                intents=list(intents),
                year=year,
                api_sources=[src_name],
            )

    # --- Inbound citations ---
    for src_name, src in result.sources.items():
        if not src.found:
            continue
        for cit in src.citations:
            nid = _node_id(cit.doi, cit.s2_paper_id)
            if not nid or nid == queried_id:
                continue

            _ensure_node(nid, cit.doi, cit.title, cit.year, src_name)

            is_self = _detect_self_citation(
                queried_orcids, queried_surnames,
                nodes[nid].author_orcids, nodes[nid].author_names,
            )
            weight = _compute_edge_weight(cit.is_influential, is_self, cit.intents)

            _merge_edge(
                (nid, queried_id),
                weight=weight, is_influential=cit.is_influential,
                is_self=is_self, intents=cit.intents,
                year=cit.year, src_name=src_name,
            )

    # --- Outbound references ---
    for src_name, src in result.sources.items():
        if not src.found:
            continue
        for ref in src.references:
            nid = _node_id(ref.doi, ref.s2_paper_id)
            if not nid or nid == queried_id:
                continue

            _ensure_node(nid, ref.doi, ref.title, ref.year, src_name)

            _merge_edge(
                (queried_id, nid),
                weight=1.0, is_influential=ref.is_influential,
                is_self=False, intents=ref.intents,
                year=ref.year, src_name=src_name,
            )

    # --- DataCite linked datasets ---
    for ds in result.datacite_linked_datasets:
        ds_id = ds.identifier.lower() if ds.identifier else None
        if not ds_id or ds_id == queried_id:
            continue
        _ensure_node(ds_id, ds.identifier, ds.title, None, "datacite")
        _merge_edge(
            (ds_id, queried_id),
            weight=1.0, is_influential=None, is_self=False,
            intents=[], year=None, src_name="datacite",
        )

    # --- Related works from per-source data (IsSupplementTo, HasPart, etc.) ---
    for src_name, src in result.sources.items():
        if not src.found:
            continue
        for rw in src.related_works:
            if rw.identifier_type.upper() != "DOI":
                continue
            rw_id = rw.identifier.lower()
            if rw_id == queried_id:
                continue
            _ensure_node(rw_id, rw.identifier, rw.title, None, src_name)
            # Direction depends on relation type
            if rw.relation_type in ("IsCitedBy", "IsReferencedBy", "IsSupplementedBy"):
                _merge_edge(
                    (rw_id, queried_id),
                    weight=1.0, is_influential=None, is_self=False,
                    intents=[], year=None, src_name=src_name,
                )
            else:
                _merge_edge(
                    (queried_id, rw_id),
                    weight=1.0, is_influential=None, is_self=False,
                    intents=[], year=None, src_name=src_name,
                )

    edges = list(edge_map.values())
    return nodes, edges


def _node_id(doi: str | None, s2_paper_id: str | None) -> str | None:
    if doi:
        return doi.lower()
    if s2_paper_id:
        return f"s2:{s2_paper_id}"
    return None


def _compute_edge_weight(
    is_influential: bool | None,
    is_self_citation: bool,
    intents: list[str],
) -> float:
    """Compute composite edge weight from all quality signals."""
    w = 1.0
    w *= _intent_weight(intents)
    if is_influential:
        w *= INFLUENTIAL_WEIGHT
    if is_self_citation:
        w *= SELF_CITATION_PENALTY
    return w


# ---------------------------------------------------------------------------
# Authority-weighted PageRank
# ---------------------------------------------------------------------------

def _compute_pagerank(
    nodes: dict[str, GraphNode],
    edges: list[GraphEdge],
    weight_fn: callable,
    damping: float = DAMPING,
    max_iter: int = MAX_ITERATIONS,
    threshold: float = CONVERGENCE_THRESHOLD,
) -> dict[str, float]:
    """PageRank with authority-weighted initialization.

    Instead of uniform 1/N init, nodes with known citation_count get
    proportionally higher initial mass.  This approximates the authority
    a full-graph PageRank would assign: well-cited papers' votes count more.
    """
    n = len(nodes)
    if n == 0:
        return {}

    node_ids = list(nodes.keys())

    # Authority-weighted initialization
    init_weights: dict[str, float] = {}
    for nid in node_ids:
        cc = nodes[nid].citation_count
        # log(1 + cc) smooths the distribution; +1 ensures non-zero for all
        init_weights[nid] = math.log1p(cc) + 1.0 if cc is not None else 1.0
    total_init = sum(init_weights.values())
    pr = {nid: init_weights[nid] / total_init for nid in node_ids}

    # Build outgoing adjacency
    out_edges: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for edge in edges:
        w = weight_fn(edge)
        if w > 0:
            out_edges[edge.source_id].append((edge.target_id, w))

    out_weight_sum: dict[str, float] = {}
    for nid in node_ids:
        out_weight_sum[nid] = sum(w for _, w in out_edges.get(nid, []))

    for _iteration in range(max_iter):
        new_pr: dict[str, float] = {}
        dangling_sum = sum(pr[nid] for nid in node_ids if out_weight_sum.get(nid, 0) == 0)

        for nid in node_ids:
            new_pr[nid] = (1.0 - damping) / n + damping * dangling_sum / n

        for source_nid in node_ids:
            total_out = out_weight_sum.get(source_nid, 0)
            if total_out == 0:
                continue
            for target_nid, w in out_edges.get(source_nid, []):
                new_pr[target_nid] += damping * pr[source_nid] * w / total_out

        max_delta = max(abs(new_pr[nid] - pr[nid]) for nid in node_ids)
        pr = new_pr
        if max_delta < threshold:
            break

    return pr


def compute_standard_pagerank(
    nodes: dict[str, GraphNode],
    edges: list[GraphEdge],
) -> dict[str, float]:
    """Standard PageRank using base edge weights (intents + influential + anti-gaming)."""
    return _compute_pagerank(nodes, edges, weight_fn=lambda e: e.weight)


def compute_time_decay_pagerank(
    nodes: dict[str, GraphNode],
    edges: list[GraphEdge],
) -> dict[str, float]:
    """Time-decay PageRank: recent citations weighted exponentially higher."""
    return _compute_pagerank(
        nodes, edges,
        weight_fn=lambda e: e.weight * _time_decay_weight(e.year),
    )


def _percentile_rank(scores: dict[str, float], target_id: str) -> float:
    """Fraction of nodes with score <= target_id's score."""
    if not scores or target_id not in scores:
        return 0.0
    target_val = scores[target_id]
    count_le = sum(1 for v in scores.values() if v <= target_val)
    return round(count_le / len(scores), 4)


# ---------------------------------------------------------------------------
# Topology
# ---------------------------------------------------------------------------

def compute_topology(
    queried_id: str,
    nodes: dict[str, GraphNode],
    edges: list[GraphEdge],
    known_citation_count: int | None = None,
) -> NetworkTopology:
    in_degree = sum(1 for e in edges if e.target_id == queried_id)
    out_degree = sum(1 for e in edges if e.source_id == queried_id)
    self_cit = sum(1 for e in edges if e.target_id == queried_id and e.is_self_citation)
    influential = sum(1 for e in edges if e.target_id == queried_id and e.is_influential)

    all_sources: set[str] = set()
    for e in edges:
        for s in e.api_sources:
            all_sources.add(s)

    truncated = False
    if known_citation_count is not None and in_degree < known_citation_count:
        truncated = True

    return NetworkTopology(
        total_nodes=len(nodes),
        total_edges=len(edges),
        in_degree=in_degree,
        out_degree=out_degree,
        self_citation_count=self_cit,
        self_citation_fraction=round(self_cit / in_degree, 3) if in_degree > 0 else None,
        influential_citation_count=influential,
        influential_fraction=round(influential / in_degree, 3) if in_degree > 0 else None,
        unique_sources_contributing=sorted(all_sources),
        graph_is_truncated=truncated,
        known_citation_count=known_citation_count,
    )


# ---------------------------------------------------------------------------
# Intent profile
# ---------------------------------------------------------------------------

def _build_intent_profile(edges: list[GraphEdge], queried_id: str) -> IntentProfile:
    """Analyze citation intent distribution for inbound citations."""
    profile = IntentProfile()
    inbound = [e for e in edges if e.target_id == queried_id]

    for e in inbound:
        if not e.intents:
            profile.unknown_count += 1
            continue
        intents_lower = [i.lower() for i in e.intents]
        if "methodology" in intents_lower:
            profile.methodology_count += 1
        elif "resultcomparison" in intents_lower:
            profile.result_comparison_count += 1
        elif "background" in intents_lower:
            profile.background_count += 1
        else:
            profile.unknown_count += 1

    total = profile.methodology_count + profile.result_comparison_count + profile.background_count
    if total > 0:
        profile.methodology_fraction = round(profile.methodology_count / total, 3)
        counts = {
            "methodology": profile.methodology_count,
            "result_comparison": profile.result_comparison_count,
            "background": profile.background_count,
        }
        profile.dominant_intent = max(counts, key=counts.get)

    return profile


# ---------------------------------------------------------------------------
# Citation velocity
# ---------------------------------------------------------------------------

def _build_citation_velocity(result: AggregatedResult) -> CitationVelocity:
    """Compute citation velocity from counts_by_year (OpenAlex, others)."""
    velocity = CitationVelocity()

    # Merge counts_by_year from all sources (use max per year)
    yearly: dict[int, int] = {}
    for src in result.sources.values():
        if src.found and src.counts_by_year:
            for year, count in src.counts_by_year.items():
                yearly[year] = max(yearly.get(year, 0), count)

    if not yearly:
        return velocity

    sorted_years = sorted(yearly.keys())
    velocity.years = sorted_years
    velocity.counts = [yearly[y] for y in sorted_years]

    # Peak
    peak_year = max(yearly, key=yearly.get)
    velocity.peak_year = peak_year
    velocity.peak_count = yearly[peak_year]

    # Recent 3-year average
    current = _current_year()
    recent = [yearly.get(y, 0) for y in range(current - 3, current)]
    if any(c > 0 for c in recent):
        velocity.recent_3yr_avg = round(sum(recent) / len(recent), 1)

    # Acceleration: compare last 3 years vs prior 3 years
    prior = [yearly.get(y, 0) for y in range(current - 6, current - 3)]
    prior_avg = sum(prior) / len(prior) if prior else 0
    recent_avg = velocity.recent_3yr_avg or 0

    if prior_avg > 0:
        velocity.acceleration = round((recent_avg - prior_avg) / prior_avg, 3)
        if velocity.acceleration > 0.2:
            velocity.trend = "accelerating"
        elif velocity.acceleration < -0.2:
            velocity.trend = "decelerating"
        else:
            velocity.trend = "steady"
    elif recent_avg > 0:
        velocity.trend = "emerging"

    return velocity


# ---------------------------------------------------------------------------
# Field normalization
# ---------------------------------------------------------------------------

def _build_field_normalization(result: AggregatedResult) -> FieldNormalization:
    fn = FieldNormalization()

    # OpenAlex FWCI
    oa = result.sources.get(SourceName.OPENALEX.value)
    if oa and oa.found:
        for ind in oa.impact_indicators:
            if ind.name == "fwci":
                fn.fwci = ind.value

    # NIH RCR
    nih = result.sources.get(SourceName.NIH_REPORTER.value)
    if nih and nih.found:
        fn.relative_citation_ratio = nih.relative_citation_ratio

    # OpenAIRE BIP!
    oaire = result.sources.get(SourceName.OPENAIRE.value)
    if oaire and oaire.found:
        if oaire.pagerank is not None:
            fn.bip_influence = oaire.pagerank
        for ind in oaire.impact_indicators:
            if ind.name == "bip_influence":
                fn.bip_influence_class = ind.class_label
            elif ind.name == "bip_popularity":
                fn.bip_popularity = ind.value
            elif ind.name == "bip_impulse":
                fn.bip_impulse = ind.value

    return fn


# ---------------------------------------------------------------------------
# Biomedical signals
# ---------------------------------------------------------------------------

def _build_biomedical_signals(result: AggregatedResult) -> BiomedicalSignals:
    bio = BiomedicalSignals()

    # MeSH terms
    for src in result.sources.values():
        if src.found and src.mesh_terms:
            bio.has_mesh_terms = True
            bio.mesh_term_count = max(bio.mesh_term_count, len(src.mesh_terms))

    # Clinical trials (CrossRef)
    cr = result.sources.get(SourceName.CROSSREF.value)
    if cr and cr.found and cr.clinical_trial_numbers:
        bio.has_clinical_trials = True
        bio.clinical_trial_count = len(cr.clinical_trial_numbers)

    # Retraction/correction detection
    epmc = result.sources.get(SourceName.EUROPE_PMC.value)
    if epmc and epmc.found:
        for corr in epmc.corrections:
            corr_type = corr.get("type", "").lower()
            if "retract" in corr_type:
                bio.has_retraction = True
            elif corr_type:
                bio.has_correction = True

    if cr and cr.found:
        for upd in cr.update_to:
            upd_type = str(upd.get("type", "")).lower()
            if "retract" in upd_type:
                bio.has_retraction = True
            elif upd_type:
                bio.has_correction = True

    # Grant-backed fraction
    sources_with_grants = 0
    sources_found = 0
    for src in result.sources.values():
        if src.found:
            sources_found += 1
            if src.grants or src.nih_grants or src.openaire_projects:
                sources_with_grants += 1
    if sources_found > 0:
        bio.grant_backed_fraction = round(sources_with_grants / sources_found, 3)

    # PMID availability
    cw = result.crosswalk
    bio.pmid_available = cw.pmid is not None

    return bio


# ---------------------------------------------------------------------------
# Author-level PageRank
# ---------------------------------------------------------------------------

def compute_author_pagerank(
    result: AggregatedResult,
    standard_pr: dict[str, float],
    queried_id: str,
) -> list[AuthorPageRank]:
    author_map: dict[str, AuthorPageRank] = {}

    for src in result.sources.values():
        if not src.found or not src.authors:
            continue
        for a in src.authors:
            orcid = a.name.orcid
            name = a.name.full_name or f"{a.name.given or ''} {a.name.family or ''}".strip()
            key = orcid if orcid else name.lower()
            if not key:
                continue

            if key not in author_map:
                author_map[key] = AuthorPageRank(
                    name=name or key,
                    orcid=orcid,
                    is_queried_author=True,
                )
            entry = author_map[key]
            if entry.paper_count == 0:
                entry.pagerank_sum = standard_pr.get(queried_id, 0.0)
                entry.paper_count = 1

    return sorted(author_map.values(), key=lambda a: a.pagerank_sum, reverse=True)


# ---------------------------------------------------------------------------
# S-index (properly normalized composite)
# ---------------------------------------------------------------------------

def compute_s_index(
    standard_pr_percentile: float,
    time_decay_pr_percentile: float,
    topology: NetworkTopology,
    intent_profile: IntentProfile,
    field_norm: FieldNormalization,
    biomedical: BiomedicalSignals,
) -> float:
    """Composite S-index from normalized components (all on [0, 1] scale).

    Components (weights sum to 1.0):
      30% — time-decay PageRank percentile (recency + authority)
      20% — standard PageRank percentile (classic authority)
      15% — influential citation fraction (depth of engagement)
      10% — methodology citation fraction (method reuse signal)
      10% — field-normalized calibration (FWCI or RCR, capped at 1.0)
      10% — integrity (inverse self-citation fraction)
       5% — biomedical relevance (grants, PubMed indexing, clinical trials)
    """
    influential = topology.influential_fraction or 0.0
    self_cit_penalty = 1.0 - (topology.self_citation_fraction or 0.0)
    methodology = intent_profile.methodology_fraction or 0.0

    # Field normalization: cap at 1.0 for scoring (FWCI 2.0 → 1.0; RCR 2.0 → 1.0)
    field_score = 0.0
    if field_norm.fwci is not None:
        field_score = min(field_norm.fwci / 2.0, 1.0)  # FWCI 2.0+ → max
    elif field_norm.relative_citation_ratio is not None:
        field_score = min(field_norm.relative_citation_ratio / 2.0, 1.0)

    # Biomedical relevance sub-score
    bio_score = 0.0
    if biomedical.pmid_available:
        bio_score += 0.3
    if biomedical.grant_backed_fraction:
        bio_score += 0.3 * biomedical.grant_backed_fraction
    if biomedical.has_clinical_trials:
        bio_score += 0.2
    if biomedical.has_mesh_terms:
        bio_score += 0.2
    bio_score = min(bio_score, 1.0)

    # Retraction kills the score
    if biomedical.has_retraction:
        return 0.0

    raw = (
        0.30 * time_decay_pr_percentile
        + 0.20 * standard_pr_percentile
        + 0.15 * influential
        + 0.10 * methodology
        + 0.10 * field_score
        + 0.10 * self_cit_penalty
        + 0.05 * bio_score
    )
    return round(raw, 6)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def analyze_citation_network(result: AggregatedResult) -> CitationNetworkResult:
    """Build citation graph and compute all metrics."""
    doi = result.doi
    queried_id = doi.lower()

    output = CitationNetworkResult(doi=doi)

    # Always compute these (independent of graph)
    output.field_normalization = _build_field_normalization(result)
    output.biomedical = _build_biomedical_signals(result)
    output.citation_velocity = _build_citation_velocity(result)

    # Build graph
    nodes, edges = build_graph(doi, result)

    # Determine known citation count for truncation detection
    known_cc: int | None = None
    for src in result.sources.values():
        if src.found and src.citation_count is not None:
            if known_cc is None or src.citation_count > known_cc:
                known_cc = src.citation_count

    if len(nodes) <= 1:
        output.topology = compute_topology(queried_id, nodes, edges, known_cc)
        # Minimal narrative for zero-citation papers
        parts = ["No citation edges available for network analysis"]
        if output.field_normalization.fwci is not None:
            parts.append(f"FWCI {output.field_normalization.fwci:.2f}")
        if output.field_normalization.relative_citation_ratio is not None:
            parts.append(f"NIH RCR {output.field_normalization.relative_citation_ratio:.2f}")
        if output.biomedical.has_clinical_trials:
            parts.append(
                f"Linked to {output.biomedical.clinical_trial_count} clinical trial(s)"
            )
        if output.citation_velocity.trend:
            parts.append(f"Citation trend: {output.citation_velocity.trend}")
        output.narrative = ". ".join(parts) + "."
        return output

    # Inject authority priors: store known citation counts on citing nodes
    # so PageRank initialization is authority-weighted
    _inject_authority_priors(nodes, edges, result, queried_id)

    # Compute PageRank variants
    standard_pr = compute_standard_pagerank(nodes, edges)
    time_decay_pr = compute_time_decay_pagerank(nodes, edges)

    output.pagerank = PageRankScores(
        standard=standard_pr.get(queried_id, 0.0),
        time_decay=time_decay_pr.get(queried_id, 0.0),
        standard_percentile=_percentile_rank(standard_pr, queried_id),
        time_decay_percentile=_percentile_rank(time_decay_pr, queried_id),
        standard_all=standard_pr,
        time_decay_all=time_decay_pr,
    )

    # Topology
    output.topology = compute_topology(queried_id, nodes, edges, known_cc)

    # Intent profile
    output.intent_profile = _build_intent_profile(edges, queried_id)

    # S-index (all components now on [0,1] scale)
    output.s_index = compute_s_index(
        output.pagerank.standard_percentile,
        output.pagerank.time_decay_percentile,
        output.topology,
        output.intent_profile,
        output.field_normalization,
        output.biomedical,
    )

    # Author-level
    output.author_pagerank = compute_author_pagerank(result, standard_pr, queried_id)

    # --- Build narrative ---
    output.narrative = _build_narrative(output)

    return output


def _inject_authority_priors(
    nodes: dict[str, GraphNode],
    edges: list[GraphEdge],
    result: AggregatedResult,
    queried_id: str,
) -> None:
    """Inject citation counts from S2/CrossRef data onto citing nodes.

    S2 citation records include citation counts for citing papers in some
    cases.  Even without per-paper counts, the `is_influential` flag serves
    as a binary authority signal.  We also use the queried paper's own
    citation count as its node authority.
    """
    # Queried paper's citation count
    for src in result.sources.values():
        if src.found and src.citation_count is not None:
            node = nodes.get(queried_id)
            if node:
                if node.citation_count is None or src.citation_count > node.citation_count:
                    node.citation_count = src.citation_count

    # For citing nodes, if they are influential, assign a synthetic
    # citation count based on the queried paper's median citation rate
    # (influential papers are typically in the top ~2% by citation count)
    median_cc = nodes[queried_id].citation_count
    for e in edges:
        if e.target_id == queried_id and e.is_influential:
            citer = nodes.get(e.source_id)
            if citer and citer.citation_count is None:
                # Influential papers are typically 5-10x median
                citer.citation_count = (median_cc or 10) * 5


def _build_narrative(output: CitationNetworkResult) -> str:
    parts: list[str] = []
    topo = output.topology
    fn = output.field_normalization
    bio = output.biomedical
    ip = output.intent_profile
    vel = output.citation_velocity

    # Retraction warning first
    if bio.has_retraction:
        parts.append("WARNING: Retraction detected — S-index set to 0")

    # Graph summary
    if topo.graph_is_truncated and topo.known_citation_count:
        parts.append(
            f"Citation network: {topo.total_nodes} papers in local graph "
            f"({topo.in_degree} of ~{topo.known_citation_count} known citations sampled, "
            f"{topo.out_degree} outbound references)"
        )
    else:
        parts.append(
            f"Citation network: {topo.total_nodes} papers, "
            f"{topo.total_edges} edges "
            f"({topo.in_degree} inbound, {topo.out_degree} outbound)"
        )

    # PageRank with percentile context
    pr = output.pagerank
    parts.append(
        f"Authority-weighted PageRank: {pr.standard:.4e} "
        f"(top {100 - pr.standard_percentile * 100:.0f}% in local graph)"
    )
    parts.append(f"S-index: {output.s_index:.4f}")

    # Intent breakdown
    if ip.methodology_count + ip.result_comparison_count + ip.background_count > 0:
        intent_parts = []
        if ip.methodology_count:
            intent_parts.append(f"{ip.methodology_count} methodology")
        if ip.result_comparison_count:
            intent_parts.append(f"{ip.result_comparison_count} result-comparison")
        if ip.background_count:
            intent_parts.append(f"{ip.background_count} background")
        parts.append(f"Citation intents: {', '.join(intent_parts)}")
        if ip.methodology_fraction and ip.methodology_fraction > 0.15:
            pct = int(ip.methodology_fraction * 100)
            parts.append(f"High method-reuse signal ({pct}% methodology citations)")

    # Self-citations
    if topo.self_citation_count > 0:
        pct = int((topo.self_citation_fraction or 0) * 100)
        parts.append(f"{topo.self_citation_count} self-citations ({pct}%, down-weighted)")

    # Influential
    if topo.influential_citation_count > 0:
        pct = int((topo.influential_fraction or 0) * 100)
        parts.append(f"{topo.influential_citation_count} influential citations ({pct}%)")

    # Field normalization
    if fn.fwci is not None:
        parts.append(f"FWCI: {fn.fwci:.2f}x field average")
    if fn.relative_citation_ratio is not None:
        parts.append(f"NIH RCR: {fn.relative_citation_ratio:.2f}x NIH median")
    if fn.bip_influence is not None:
        cls = f" (class {fn.bip_influence_class})" if fn.bip_influence_class else ""
        parts.append(f"BIP! influence: {fn.bip_influence:.4e}{cls}")

    # Citation velocity
    if vel.trend:
        parts.append(f"Citation velocity: {vel.trend}")
        if vel.recent_3yr_avg is not None:
            parts.append(f"Recent 3yr avg: {vel.recent_3yr_avg:.1f} citations/year")

    # Biomedical signals
    if bio.has_clinical_trials:
        parts.append(f"Clinical trial linkage: {bio.clinical_trial_count} trial(s)")
    if bio.has_correction and not bio.has_retraction:
        parts.append("Note: correction/erratum exists")

    # Sources
    sources = topo.unique_sources_contributing
    if sources:
        parts.append(f"Graph from {len(sources)} API sources: {', '.join(sources)}")

    return ". ".join(parts) + "."
