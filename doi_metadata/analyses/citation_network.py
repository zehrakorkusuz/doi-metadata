"""Citation network analysis — build citation graph, compute PageRank variants, author-level metrics.

Builds a directed citation graph from all source data (S2 citations/references,
CrossRef references, OpenAlex referenced_works, etc.), then computes:

- Standard PageRank (classic importance via link analysis)
- Time-Decay PageRank (recent citations weighted exponentially higher)
- Self-citation detection and down-weighting (anti-gaming)
- Network topology metrics (in-degree, out-degree, clustering)
- Author-level aggregated PageRank scores
- Composite S-index score

The graph is a local ego network centered on the queried DOI.  Citing papers
and referenced papers form the 1-hop neighborhood.  Edge weights encode
quality signals: S2 influential flag, citation intent, self-citation penalty,
and time-decay factor.
"""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timezone

from pydantic import BaseModel, Field

from doi_metadata.models import AggregatedResult, Author, Citation, Reference, SourceName

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DAMPING = 0.85  # Standard PageRank damping factor
MAX_ITERATIONS = 100  # Power iteration cap
CONVERGENCE_THRESHOLD = 1e-8  # Stop when max delta < this
TIME_DECAY_LAMBDA = 0.15  # Exponential decay rate per year
INFLUENTIAL_WEIGHT = 3.0  # Weight multiplier for influential citations
SELF_CITATION_PENALTY = 0.1  # Multiplicative penalty (10% of normal weight)
CURRENT_YEAR = datetime.now(timezone.utc).year


# ---------------------------------------------------------------------------
# Graph data structures
# ---------------------------------------------------------------------------

class GraphNode(BaseModel):
    """A paper in the citation graph."""
    node_id: str  # DOI preferred, S2 paper ID as fallback
    doi: str | None = None
    title: str | None = None
    year: int | None = None
    is_queried: bool = False  # True for the paper being looked up
    author_names: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)  # Which APIs mentioned this paper


class GraphEdge(BaseModel):
    """A directed citation edge: source_id cites target_id."""
    source_id: str  # Citing paper
    target_id: str  # Cited paper
    weight: float = 1.0  # Base weight before PageRank
    is_influential: bool | None = None
    is_self_citation: bool = False
    intents: list[str] = Field(default_factory=list)
    year: int | None = None  # Year of the citing paper
    api_source: str | None = None  # Which API provided this edge


# ---------------------------------------------------------------------------
# PageRank result models
# ---------------------------------------------------------------------------

class PageRankScores(BaseModel):
    """PageRank scores for the queried DOI."""
    standard: float = 0.0
    time_decay: float = 0.0
    # Full score vectors (DOI/ID → score) for inspection
    standard_all: dict[str, float] = Field(default_factory=dict)
    time_decay_all: dict[str, float] = Field(default_factory=dict)


class NetworkTopology(BaseModel):
    """Graph-level topology metrics for the queried DOI."""
    total_nodes: int = 0
    total_edges: int = 0
    in_degree: int = 0  # Number of papers citing the queried DOI
    out_degree: int = 0  # Number of papers the queried DOI cites
    self_citation_count: int = 0
    self_citation_fraction: float | None = None
    influential_citation_count: int = 0
    influential_fraction: float | None = None
    unique_sources_contributing: list[str] = Field(default_factory=list)


class AuthorPageRank(BaseModel):
    """PageRank aggregated at the author level."""
    name: str
    orcid: str | None = None
    pagerank_sum: float = 0.0  # Sum of PageRank across their papers in graph
    paper_count: int = 0  # How many papers in the graph they appear on
    is_queried_author: bool = False  # Are they an author of the queried DOI?


class CitationNetworkResult(BaseModel):
    """Full citation network analysis output."""
    doi: str
    pagerank: PageRankScores = Field(default_factory=PageRankScores)
    s_index: float = 0.0  # Composite score
    topology: NetworkTopology = Field(default_factory=NetworkTopology)
    author_pagerank: list[AuthorPageRank] = Field(default_factory=list)
    # BIP! influence from OpenAIRE (external PageRank, for comparison)
    bip_influence: float | None = None
    bip_influence_class: str | None = None
    narrative: str = ""


# ---------------------------------------------------------------------------
# Graph building
# ---------------------------------------------------------------------------

def _node_id_for_citation(c: Citation) -> str | None:
    """Best identifier for a citing paper."""
    if c.doi:
        return c.doi.lower()
    if c.s2_paper_id:
        return f"s2:{c.s2_paper_id}"
    return None


def _node_id_for_reference(r: Reference) -> str | None:
    """Best identifier for a referenced paper."""
    if r.doi:
        return r.doi.lower()
    if r.s2_paper_id:
        return f"s2:{r.s2_paper_id}"
    return None


def _author_name_set(authors: list[Author]) -> set[str]:
    """Extract a set of lowercased author family names for self-citation detection."""
    names: set[str] = set()
    for a in authors:
        if a.name.family:
            names.add(a.name.family.strip().lower())
        elif a.name.full_name:
            # Use last token as family name approximation
            parts = a.name.full_name.strip().split()
            if parts:
                names.add(parts[-1].lower())
    return names


def _detect_self_citation(queried_authors: set[str], citing_author_names: list[str]) -> bool:
    """Check if a citing paper shares authors with the queried paper."""
    if not queried_authors or not citing_author_names:
        return False
    for name in citing_author_names:
        # Check if any token in the citing author name matches a queried author family name
        tokens = {t.lower() for t in name.strip().split()}
        if tokens & queried_authors:
            return True
    return False


def _time_decay_weight(citing_year: int | None, decay_lambda: float = TIME_DECAY_LAMBDA) -> float:
    """Exponential time decay: recent citations weighted higher."""
    if citing_year is None:
        return 1.0  # Unknown year → neutral weight
    age = max(0, CURRENT_YEAR - citing_year)
    return math.exp(-decay_lambda * age)


def build_graph(
    doi: str,
    result: AggregatedResult,
) -> tuple[dict[str, GraphNode], list[GraphEdge]]:
    """Build citation graph from all source data.

    Returns (nodes, edges) where nodes is a dict of node_id → GraphNode
    and edges is a list of directed GraphEdge objects.
    """
    queried_id = doi.lower()
    nodes: dict[str, GraphNode] = {}
    edges: list[GraphEdge] = []
    seen_edges: set[tuple[str, str]] = set()  # Deduplicate edges

    # Collect queried paper's author names for self-citation detection
    queried_authors: set[str] = set()
    queried_author_full_names: list[str] = []
    for src in result.sources.values():
        if src.found and src.authors:
            queried_authors |= _author_name_set(src.authors)
            for a in src.authors:
                name = a.name.full_name or f"{a.name.given or ''} {a.name.family or ''}".strip()
                if name:
                    queried_author_full_names.append(name)

    # Add queried paper as center node
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
    )

    # --- Inbound citations (papers that cite the queried DOI) ---
    for src_name, src in result.sources.items():
        if not src.found:
            continue
        for cit in src.citations:
            nid = _node_id_for_citation(cit)
            if not nid or nid == queried_id:
                continue

            # Add or update node
            if nid not in nodes:
                citing_author_names: list[str] = []
                # S2 citation data doesn't include author names directly,
                # so we only have what's available
                nodes[nid] = GraphNode(
                    node_id=nid,
                    doi=cit.doi,
                    title=cit.title,
                    year=cit.year,
                    author_names=citing_author_names,
                )
            if src_name not in nodes[nid].sources:
                nodes[nid].sources.append(src_name)

            # Add edge: citing paper → queried DOI
            edge_key = (nid, queried_id)
            if edge_key not in seen_edges:
                is_self = _detect_self_citation(queried_authors, nodes[nid].author_names)
                weight = 1.0
                if cit.is_influential:
                    weight *= INFLUENTIAL_WEIGHT
                if is_self:
                    weight *= SELF_CITATION_PENALTY

                edges.append(GraphEdge(
                    source_id=nid,
                    target_id=queried_id,
                    weight=weight,
                    is_influential=cit.is_influential,
                    is_self_citation=is_self,
                    intents=cit.intents,
                    year=cit.year,
                    api_source=src_name,
                ))
                seen_edges.add(edge_key)

    # --- Outbound references (papers the queried DOI cites) ---
    for src_name, src in result.sources.items():
        if not src.found:
            continue
        for ref in src.references:
            nid = _node_id_for_reference(ref)
            if not nid or nid == queried_id:
                continue

            # Add or update node
            if nid not in nodes:
                nodes[nid] = GraphNode(
                    node_id=nid,
                    doi=ref.doi,
                    title=ref.title,
                    year=ref.year,
                )
            if src_name not in nodes[nid].sources:
                nodes[nid].sources.append(src_name)

            # Add edge: queried DOI → referenced paper
            edge_key = (queried_id, nid)
            if edge_key not in seen_edges:
                edges.append(GraphEdge(
                    source_id=queried_id,
                    target_id=nid,
                    weight=1.0,
                    is_influential=ref.is_influential,
                    intents=ref.intents,
                    year=ref.year,
                    api_source=src_name,
                ))
                seen_edges.add(edge_key)

    # --- DataCite linked datasets (dataset → article citations) ---
    for ds in result.datacite_linked_datasets:
        ds_id = ds.identifier.lower() if ds.identifier else None
        if not ds_id or ds_id == queried_id:
            continue
        if ds_id not in nodes:
            nodes[ds_id] = GraphNode(
                node_id=ds_id,
                doi=ds.identifier,
                title=ds.title,
                sources=["datacite"],
            )
        edge_key = (ds_id, queried_id)
        if edge_key not in seen_edges:
            edges.append(GraphEdge(
                source_id=ds_id,
                target_id=queried_id,
                weight=1.0,
                api_source="datacite",
            ))
            seen_edges.add(edge_key)

    return nodes, edges


# ---------------------------------------------------------------------------
# PageRank computation (power iteration)
# ---------------------------------------------------------------------------

def _compute_pagerank(
    nodes: dict[str, GraphNode],
    edges: list[GraphEdge],
    weight_fn: callable,
    damping: float = DAMPING,
    max_iter: int = MAX_ITERATIONS,
    threshold: float = CONVERGENCE_THRESHOLD,
) -> dict[str, float]:
    """Compute PageRank via power iteration with custom edge weight function.

    Args:
        nodes: All graph nodes.
        edges: All directed edges.
        weight_fn: Function(GraphEdge) → float, returns final edge weight.
        damping: PageRank damping factor.
        max_iter: Maximum iterations.
        threshold: Convergence threshold.

    Returns:
        Dict of node_id → PageRank score.
    """
    n = len(nodes)
    if n == 0:
        return {}

    node_ids = list(nodes.keys())
    # Initialize uniformly
    pr = {nid: 1.0 / n for nid in node_ids}

    # Build adjacency: for each node, outgoing weighted edges
    # out_edges[source] = [(target, weight), ...]
    out_edges: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for edge in edges:
        w = weight_fn(edge)
        if w > 0:
            out_edges[edge.source_id].append((edge.target_id, w))

    # Precompute total outgoing weight per node
    out_weight_sum: dict[str, float] = {}
    for nid in node_ids:
        out_weight_sum[nid] = sum(w for _, w in out_edges.get(nid, []))

    for _iteration in range(max_iter):
        new_pr: dict[str, float] = {}
        # Collect dangling node mass (nodes with no outgoing edges)
        dangling_sum = sum(pr[nid] for nid in node_ids if out_weight_sum.get(nid, 0) == 0)

        for nid in node_ids:
            # Base: teleportation + dangling redistribution
            rank = (1.0 - damping) / n + damping * dangling_sum / n

            # Contribution from incoming edges
            # We need to iterate over edges where target == nid
            # For efficiency, build in_edges on first use
            new_pr[nid] = rank

        # Now add edge contributions
        for source_nid in node_ids:
            total_out = out_weight_sum.get(source_nid, 0)
            if total_out == 0:
                continue
            for target_nid, w in out_edges.get(source_nid, []):
                new_pr[target_nid] += damping * pr[source_nid] * w / total_out

        # Check convergence
        max_delta = max(abs(new_pr[nid] - pr[nid]) for nid in node_ids)
        pr = new_pr
        if max_delta < threshold:
            break

    return pr


def compute_standard_pagerank(
    nodes: dict[str, GraphNode],
    edges: list[GraphEdge],
) -> dict[str, float]:
    """Standard PageRank using base edge weights (influential + anti-gaming)."""
    return _compute_pagerank(
        nodes,
        edges,
        weight_fn=lambda e: e.weight,
    )


def compute_time_decay_pagerank(
    nodes: dict[str, GraphNode],
    edges: list[GraphEdge],
) -> dict[str, float]:
    """Time-decay PageRank: recent citations weighted exponentially higher."""
    def weight_fn(edge: GraphEdge) -> float:
        return edge.weight * _time_decay_weight(edge.year)

    return _compute_pagerank(nodes, edges, weight_fn=weight_fn)


# ---------------------------------------------------------------------------
# Network topology metrics
# ---------------------------------------------------------------------------

def compute_topology(
    queried_id: str,
    nodes: dict[str, GraphNode],
    edges: list[GraphEdge],
) -> NetworkTopology:
    """Compute topology metrics for the citation network."""
    in_degree = sum(1 for e in edges if e.target_id == queried_id)
    out_degree = sum(1 for e in edges if e.source_id == queried_id)
    self_cit = sum(1 for e in edges if e.target_id == queried_id and e.is_self_citation)
    influential = sum(1 for e in edges if e.target_id == queried_id and e.is_influential)

    all_sources: set[str] = set()
    for e in edges:
        if e.api_source:
            all_sources.add(e.api_source)

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
    )


# ---------------------------------------------------------------------------
# Author-level PageRank
# ---------------------------------------------------------------------------

def compute_author_pagerank(
    result: AggregatedResult,
    standard_pr: dict[str, float],
    queried_id: str,
) -> list[AuthorPageRank]:
    """Aggregate PageRank scores at the author level.

    For each disambiguated author on the queried paper, report their
    PageRank contribution.  If the same author appears on citing papers,
    their score is augmented.
    """
    # Collect authors from the queried paper across all sources
    author_map: dict[str, AuthorPageRank] = {}  # key: orcid or normalized name

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
            # Each author on the queried paper gets the queried DOI's PageRank
            if entry.paper_count == 0:
                entry.pagerank_sum = standard_pr.get(queried_id, 0.0)
                entry.paper_count = 1

    return sorted(author_map.values(), key=lambda a: a.pagerank_sum, reverse=True)


# ---------------------------------------------------------------------------
# S-index composite score
# ---------------------------------------------------------------------------

def compute_s_index(
    standard_pr: float,
    time_decay_pr: float,
    topology: NetworkTopology,
) -> float:
    """Compute composite S-index from PageRank variants and topology signals.

    S-index = weighted combination:
      - 40% time-decay PageRank (favors sustained + recent impact)
      - 30% standard PageRank (classic importance)
      - 20% influential citation fraction (quality signal)
      - 10% inverse self-citation fraction (anti-gaming)

    Normalized to [0, 1] range relative to the local graph.
    """
    influential_score = topology.influential_fraction or 0.0
    self_cit_penalty = 1.0 - (topology.self_citation_fraction or 0.0)

    raw = (
        0.4 * time_decay_pr
        + 0.3 * standard_pr
        + 0.2 * influential_score
        + 0.1 * self_cit_penalty
    )
    return round(raw, 8)


# ---------------------------------------------------------------------------
# Main analysis entry point
# ---------------------------------------------------------------------------

def analyze_citation_network(result: AggregatedResult) -> CitationNetworkResult:
    """Build citation graph and compute all PageRank variants + metrics."""
    doi = result.doi
    queried_id = doi.lower()

    # Build graph
    nodes, edges = build_graph(doi, result)

    output = CitationNetworkResult(doi=doi)

    if len(nodes) <= 1:
        # No citation data available — just report BIP! if present
        oaire = result.sources.get(SourceName.OPENAIRE.value)
        if oaire and oaire.found and oaire.pagerank is not None:
            output.bip_influence = oaire.pagerank
        output.narrative = "Insufficient citation data to build network graph."
        return output

    # Compute PageRank variants
    standard_pr = compute_standard_pagerank(nodes, edges)
    time_decay_pr = compute_time_decay_pagerank(nodes, edges)

    output.pagerank = PageRankScores(
        standard=standard_pr.get(queried_id, 0.0),
        time_decay=time_decay_pr.get(queried_id, 0.0),
        standard_all=standard_pr,
        time_decay_all=time_decay_pr,
    )

    # Topology
    output.topology = compute_topology(queried_id, nodes, edges)

    # S-index
    output.s_index = compute_s_index(
        output.pagerank.standard,
        output.pagerank.time_decay,
        output.topology,
    )

    # Author-level
    output.author_pagerank = compute_author_pagerank(result, standard_pr, queried_id)

    # BIP! influence for comparison
    oaire = result.sources.get(SourceName.OPENAIRE.value)
    if oaire and oaire.found:
        if oaire.pagerank is not None:
            output.bip_influence = oaire.pagerank
        for ind in oaire.impact_indicators:
            if ind.name == "bip_influence":
                output.bip_influence_class = ind.class_label

    # --- Build narrative ---
    parts: list[str] = []

    parts.append(
        f"Citation network: {output.topology.total_nodes} papers, "
        f"{output.topology.total_edges} edges "
        f"({output.topology.in_degree} inbound, {output.topology.out_degree} outbound)"
    )

    parts.append(f"Standard PageRank: {output.pagerank.standard:.4e}")
    parts.append(f"Time-Decay PageRank: {output.pagerank.time_decay:.4e}")
    parts.append(f"S-index: {output.s_index:.6f}")

    if output.topology.self_citation_count > 0:
        pct = int((output.topology.self_citation_fraction or 0) * 100)
        parts.append(
            f"{output.topology.self_citation_count} self-citations detected "
            f"({pct}%, down-weighted in scoring)"
        )

    if output.topology.influential_citation_count > 0:
        pct = int((output.topology.influential_fraction or 0) * 100)
        parts.append(f"{output.topology.influential_citation_count} influential citations ({pct}%)")

    if output.bip_influence is not None:
        cls = f" (class {output.bip_influence_class})" if output.bip_influence_class else ""
        parts.append(f"BIP! influence (external PageRank): {output.bip_influence:.4e}{cls}")

    if output.author_pagerank:
        top = output.author_pagerank[0]
        parts.append(f"Top author by PageRank: {top.name} ({top.pagerank_sum:.4e})")

    parts.append(
        f"Graph built from {len(output.topology.unique_sources_contributing)} API sources: "
        f"{', '.join(output.topology.unique_sources_contributing)}"
    )

    output.narrative = ". ".join(parts) + "."

    return output
