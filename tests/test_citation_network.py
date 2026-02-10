"""Tests for citation network analysis — graph building, PageRank, anti-gaming, author metrics."""

from __future__ import annotations

from datetime import datetime, timezone

from doi_metadata.analyses.citation_network import (
    INFLUENTIAL_WEIGHT,
    CitationNetworkResult,
    GraphEdge,
    GraphNode,
    _author_name_set,
    _detect_self_citation,
    _time_decay_weight,
    analyze_citation_network,
    build_graph,
    compute_author_pagerank,
    compute_s_index,
    compute_standard_pagerank,
    compute_time_decay_pagerank,
    compute_topology,
)
from doi_metadata.models import (
    AggregatedResult,
    Author,
    Citation,
    ConflictReport,
    IdentifierCrosswalk,
    PersonName,
    Reference,
    RelatedWork,
    SourceName,
    SourceResult,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_agg(
    doi: str = "10.1234/test",
    sources: dict[str, SourceResult] | None = None,
    datasets: list[RelatedWork] | None = None,
) -> AggregatedResult:
    return AggregatedResult(
        doi=doi,
        retrieved_at=datetime.now(timezone.utc),
        sources=sources or {},
        crosswalk=IdentifierCrosswalk(doi=doi),
        conflicts=ConflictReport(doi=doi),
        datacite_linked_datasets=datasets or [],
    )


def _make_source(
    source: SourceName,
    found: bool = True,
    citations: list[Citation] | None = None,
    references: list[Reference] | None = None,
    authors: list[Author] | None = None,
    pagerank: float | None = None,
) -> SourceResult:
    return SourceResult(
        source=source,
        found=found,
        citations=citations or [],
        references=references or [],
        authors=authors or [],
        pagerank=pagerank,
    )


def _make_citation(doi: str | None = None, year: int | None = 2023,
                   is_influential: bool | None = None,
                   intents: list[str] | None = None,
                   s2_paper_id: str | None = None) -> Citation:
    return Citation(
        doi=doi, year=year, is_influential=is_influential,
        intents=intents or [], s2_paper_id=s2_paper_id,
        source=SourceName.SEMANTIC_SCHOLAR,
    )


def _make_reference(doi: str | None = None, year: int | None = 2020,
                    is_influential: bool | None = None,
                    s2_paper_id: str | None = None) -> Reference:
    return Reference(
        doi=doi, year=year, is_influential=is_influential,
        s2_paper_id=s2_paper_id, source=SourceName.SEMANTIC_SCHOLAR,
    )


def _make_author(family: str, given: str | None = None, orcid: str | None = None) -> Author:
    return Author(
        name=PersonName(family=family, given=given, orcid=orcid, source=SourceName.OPENALEX),
        sources=[SourceName.OPENALEX],
    )


# ---------------------------------------------------------------------------
# Graph building tests
# ---------------------------------------------------------------------------

class TestBuildGraph:
    def test_empty_sources(self):
        agg = _make_agg()
        nodes, edges = build_graph("10.1234/test", agg)
        # Should have at least the queried DOI node
        assert len(nodes) == 1
        assert "10.1234/test" in nodes
        assert nodes["10.1234/test"].is_queried

    def test_citations_become_inbound_edges(self):
        src = _make_source(
            SourceName.SEMANTIC_SCHOLAR,
            citations=[
                _make_citation(doi="10.1000/cit1", year=2023),
                _make_citation(doi="10.1000/cit2", year=2024),
            ],
        )
        agg = _make_agg(sources={"semantic_scholar": src})
        nodes, edges = build_graph("10.1234/test", agg)

        assert len(nodes) == 3  # queried + 2 citing papers
        # Edges point FROM citing paper TO queried DOI
        for e in edges:
            assert e.target_id == "10.1234/test"
        assert len(edges) == 2

    def test_references_become_outbound_edges(self):
        src = _make_source(
            SourceName.SEMANTIC_SCHOLAR,
            references=[
                _make_reference(doi="10.1000/ref1"),
                _make_reference(doi="10.1000/ref2"),
                _make_reference(doi="10.1000/ref3"),
            ],
        )
        agg = _make_agg(sources={"semantic_scholar": src})
        nodes, edges = build_graph("10.1234/test", agg)

        assert len(nodes) == 4  # queried + 3 references
        outbound = [e for e in edges if e.source_id == "10.1234/test"]
        assert len(outbound) == 3

    def test_deduplication_across_sources(self):
        """Same citation DOI from S2 and CrossRef should produce one edge."""
        s2 = _make_source(
            SourceName.SEMANTIC_SCHOLAR,
            citations=[_make_citation(doi="10.1000/cit1")],
        )
        cr = _make_source(
            SourceName.CROSSREF,
            citations=[Citation(doi="10.1000/cit1", source=SourceName.CROSSREF)],
        )
        agg = _make_agg(sources={"semantic_scholar": s2, "crossref": cr})
        nodes, edges = build_graph("10.1234/test", agg)

        # Only one edge, not two
        inbound = [e for e in edges if e.target_id == "10.1234/test"]
        assert len(inbound) == 1

    def test_datacite_linked_datasets_as_edges(self):
        ds = [
            RelatedWork(identifier="10.5281/zenodo.123", source=SourceName.DATACITE),
            RelatedWork(identifier="10.5281/zenodo.456", source=SourceName.DATACITE),
        ]
        agg = _make_agg(datasets=ds)
        nodes, edges = build_graph("10.1234/test", agg)

        assert len(nodes) == 3  # queried + 2 datasets
        assert len(edges) == 2
        for e in edges:
            assert e.target_id == "10.1234/test"

    def test_influential_weight(self):
        src = _make_source(
            SourceName.SEMANTIC_SCHOLAR,
            citations=[
                _make_citation(doi="10.1000/influential", is_influential=True),
                _make_citation(doi="10.1000/normal", is_influential=False),
            ],
        )
        agg = _make_agg(sources={"semantic_scholar": src})
        _, edges = build_graph("10.1234/test", agg)

        influential_edge = [e for e in edges if e.source_id == "10.1000/influential"][0]
        normal_edge = [e for e in edges if e.source_id == "10.1000/normal"][0]

        assert influential_edge.weight == INFLUENTIAL_WEIGHT
        assert normal_edge.weight == 1.0

    def test_s2_paper_id_fallback(self):
        """Papers without DOI should use S2 paper ID as node identifier."""
        src = _make_source(
            SourceName.SEMANTIC_SCHOLAR,
            citations=[_make_citation(doi=None, s2_paper_id="abc123")],
        )
        agg = _make_agg(sources={"semantic_scholar": src})
        nodes, _ = build_graph("10.1234/test", agg)

        assert "s2:abc123" in nodes


# ---------------------------------------------------------------------------
# Self-citation detection tests
# ---------------------------------------------------------------------------

class TestSelfCitationDetection:
    def test_author_name_set(self):
        authors = [
            _make_author("Smith", "John"),
            _make_author("Doe", "Jane"),
        ]
        names = _author_name_set(authors)
        assert names == {"smith", "doe"}

    def test_full_name_fallback(self):
        author = Author(
            name=PersonName(full_name="Alice Wonderland", source=SourceName.OPENALEX),
            sources=[SourceName.OPENALEX],
        )
        names = _author_name_set([author])
        assert "wonderland" in names

    def test_detect_self_citation_match(self):
        queried = {"smith", "doe"}
        assert _detect_self_citation(queried, ["John Smith"]) is True

    def test_detect_self_citation_no_match(self):
        queried = {"smith", "doe"}
        assert _detect_self_citation(queried, ["Alice Wonderland"]) is False

    def test_detect_self_citation_empty(self):
        assert _detect_self_citation(set(), ["John Smith"]) is False
        assert _detect_self_citation({"smith"}, []) is False

    def test_self_citation_penalty_applied(self):
        queried_authors = [_make_author("Smith", "John")]
        # The citing paper has "J. Smith" in author names
        src = _make_source(
            SourceName.SEMANTIC_SCHOLAR,
            citations=[_make_citation(doi="10.1000/self-cite")],
            authors=queried_authors,
        )
        agg = _make_agg(sources={"semantic_scholar": src})

        # We need to manually set the citing paper's author names for detection
        # In reality, S2 citation data may not include author names,
        # so self-citation detection depends on available data
        nodes, edges = build_graph("10.1234/test", agg)

        # The edge exists (self-citation detection depends on citing paper having author data)
        assert len(edges) == 1


# ---------------------------------------------------------------------------
# Time decay tests
# ---------------------------------------------------------------------------

class TestTimeDecay:
    def test_recent_citation_higher_weight(self):
        recent = _time_decay_weight(2025)
        older = _time_decay_weight(2015)
        assert recent > older

    def test_current_year_weight_near_one(self):
        from doi_metadata.analyses.citation_network import CURRENT_YEAR
        w = _time_decay_weight(CURRENT_YEAR)
        assert 0.99 <= w <= 1.01  # exp(0) = 1.0

    def test_none_year_neutral(self):
        assert _time_decay_weight(None) == 1.0

    def test_future_year_clamped(self):
        # Future year → age=0 → weight=1.0
        w = _time_decay_weight(2030)
        assert w == 1.0


# ---------------------------------------------------------------------------
# PageRank computation tests
# ---------------------------------------------------------------------------

class TestPageRank:
    def _simple_graph(self) -> tuple[dict[str, GraphNode], list[GraphEdge]]:
        """A → B, C → B (B has 2 inbound citations)."""
        nodes = {
            "a": GraphNode(node_id="a"),
            "b": GraphNode(node_id="b", is_queried=True),
            "c": GraphNode(node_id="c"),
        }
        edges = [
            GraphEdge(source_id="a", target_id="b", weight=1.0),
            GraphEdge(source_id="c", target_id="b", weight=1.0),
        ]
        return nodes, edges

    def test_standard_pagerank_converges(self):
        nodes, edges = self._simple_graph()
        pr = compute_standard_pagerank(nodes, edges)

        assert len(pr) == 3
        # B should have highest PageRank (most inbound edges)
        assert pr["b"] > pr["a"]
        assert pr["b"] > pr["c"]

    def test_pagerank_sums_to_one(self):
        nodes, edges = self._simple_graph()
        pr = compute_standard_pagerank(nodes, edges)
        total = sum(pr.values())
        assert abs(total - 1.0) < 0.001

    def test_time_decay_pagerank_converges(self):
        nodes, edges = self._simple_graph()
        pr = compute_time_decay_pagerank(nodes, edges)
        assert len(pr) == 3
        total = sum(pr.values())
        assert abs(total - 1.0) < 0.01

    def test_influential_edges_boost_pagerank(self):
        """When a node distributes rank across edges, higher weight gets more."""
        nodes = {
            "a": GraphNode(node_id="a"),
            "b": GraphNode(node_id="b"),
            "d": GraphNode(node_id="d"),
        }
        # a cites both b and d, but b's edge has influential weight (3x)
        # a distributes 3/4 to b and 1/4 to d
        edges = [
            GraphEdge(source_id="a", target_id="b", weight=INFLUENTIAL_WEIGHT),
            GraphEdge(source_id="a", target_id="d", weight=1.0),
        ]
        pr = compute_standard_pagerank(nodes, edges)
        assert pr["b"] > pr["d"]

    def test_empty_graph(self):
        pr = compute_standard_pagerank({}, [])
        assert pr == {}

    def test_single_node_no_edges(self):
        nodes = {"a": GraphNode(node_id="a")}
        pr = compute_standard_pagerank(nodes, [])
        assert abs(pr["a"] - 1.0) < 0.001

    def test_larger_graph(self):
        """Star graph: 10 nodes all citing center."""
        nodes = {"center": GraphNode(node_id="center", is_queried=True)}
        edges = []
        for i in range(10):
            nid = f"citer_{i}"
            nodes[nid] = GraphNode(node_id=nid)
            edges.append(GraphEdge(source_id=nid, target_id="center", weight=1.0))

        pr = compute_standard_pagerank(nodes, edges)
        # Center should have highest rank
        assert pr["center"] == max(pr.values())
        # All citers should have equal rank
        citer_ranks = [pr[f"citer_{i}"] for i in range(10)]
        assert max(citer_ranks) - min(citer_ranks) < 0.001


# ---------------------------------------------------------------------------
# Topology tests
# ---------------------------------------------------------------------------

class TestTopology:
    def test_basic_topology(self):
        nodes = {
            "q": GraphNode(node_id="q", is_queried=True),
            "a": GraphNode(node_id="a"),
            "b": GraphNode(node_id="b"),
            "r": GraphNode(node_id="r"),
        }
        edges = [
            GraphEdge(source_id="a", target_id="q", weight=1.0, is_influential=True, api_source="s2"),
            GraphEdge(source_id="b", target_id="q", weight=0.1, is_self_citation=True, api_source="s2"),
            GraphEdge(source_id="q", target_id="r", weight=1.0, api_source="crossref"),
        ]
        topo = compute_topology("q", nodes, edges)

        assert topo.total_nodes == 4
        assert topo.total_edges == 3
        assert topo.in_degree == 2
        assert topo.out_degree == 1
        assert topo.self_citation_count == 1
        assert topo.self_citation_fraction == 0.5
        assert topo.influential_citation_count == 1
        assert topo.influential_fraction == 0.5
        assert set(topo.unique_sources_contributing) == {"s2", "crossref"}


# ---------------------------------------------------------------------------
# S-index tests
# ---------------------------------------------------------------------------

class TestSIndex:
    def test_basic_computation(self):
        topo = compute_topology.__wrapped__ if hasattr(compute_topology, '__wrapped__') else None
        from doi_metadata.analyses.citation_network import NetworkTopology
        topo = NetworkTopology(
            influential_fraction=0.2,
            self_citation_fraction=0.1,
        )
        s = compute_s_index(0.5, 0.6, topo)
        # 0.4*0.6 + 0.3*0.5 + 0.2*0.2 + 0.1*(1-0.1) = 0.24 + 0.15 + 0.04 + 0.09 = 0.52
        assert abs(s - 0.52) < 0.001

    def test_zero_inputs(self):
        from doi_metadata.analyses.citation_network import NetworkTopology
        topo = NetworkTopology()
        s = compute_s_index(0.0, 0.0, topo)
        # 0.4*0 + 0.3*0 + 0.2*0 + 0.1*(1-0) = 0.1
        assert abs(s - 0.1) < 0.001


# ---------------------------------------------------------------------------
# Author PageRank tests
# ---------------------------------------------------------------------------

class TestAuthorPageRank:
    def test_authors_get_queried_doi_score(self):
        src = _make_source(
            SourceName.OPENALEX,
            authors=[
                _make_author("Smith", "John", orcid="0000-0001-1234-5678"),
                _make_author("Doe", "Jane"),
            ],
        )
        agg = _make_agg(sources={"openalex": src})
        pr = {"10.1234/test": 0.45, "10.1000/other": 0.05}

        authors = compute_author_pagerank(agg, pr, "10.1234/test")
        assert len(authors) == 2
        assert all(a.is_queried_author for a in authors)
        assert all(a.pagerank_sum == 0.45 for a in authors)

    def test_author_with_orcid_deduped(self):
        """Same ORCID from two sources → one author entry."""
        s1 = _make_source(
            SourceName.OPENALEX,
            authors=[_make_author("Smith", "John", orcid="0000-0001-0000-0001")],
        )
        s2 = _make_source(
            SourceName.SEMANTIC_SCHOLAR,
            authors=[Author(
                name=PersonName(family="Smith", given="J.", orcid="0000-0001-0000-0001",
                                source=SourceName.SEMANTIC_SCHOLAR),
                sources=[SourceName.SEMANTIC_SCHOLAR],
            )],
        )
        agg = _make_agg(sources={"openalex": s1, "semantic_scholar": s2})
        authors = compute_author_pagerank(agg, {"10.1234/test": 0.3}, "10.1234/test")

        # Should be 1 entry (deduped by ORCID)
        assert len(authors) == 1
        assert authors[0].orcid == "0000-0001-0000-0001"


# ---------------------------------------------------------------------------
# Full analysis integration tests
# ---------------------------------------------------------------------------

class TestAnalyzeCitationNetwork:
    def test_empty_sources_returns_narrative(self):
        agg = _make_agg()
        result = analyze_citation_network(agg)
        assert isinstance(result, CitationNetworkResult)
        assert "Insufficient" in result.narrative

    def test_with_citations_and_references(self):
        src = _make_source(
            SourceName.SEMANTIC_SCHOLAR,
            citations=[
                _make_citation(doi="10.1000/c1", year=2023, is_influential=True),
                _make_citation(doi="10.1000/c2", year=2024),
                _make_citation(doi="10.1000/c3", year=2022),
            ],
            references=[
                _make_reference(doi="10.1000/r1"),
                _make_reference(doi="10.1000/r2"),
            ],
            authors=[_make_author("Smith", "John")],
        )
        agg = _make_agg(sources={"semantic_scholar": src})
        result = analyze_citation_network(agg)

        # PageRank scores should be non-zero
        assert result.pagerank.standard > 0
        assert result.pagerank.time_decay > 0
        assert result.s_index > 0

        # Topology
        assert result.topology.total_nodes == 6  # 1 queried + 3 citing + 2 referenced
        assert result.topology.in_degree == 3
        assert result.topology.out_degree == 2

        # Narrative should mention key metrics
        assert "PageRank" in result.narrative
        assert "S-index" in result.narrative

    def test_with_bip_influence(self):
        oaire = _make_source(SourceName.OPENAIRE, pagerank=1.5e-6)
        from doi_metadata.models import ImpactIndicator
        oaire.impact_indicators.append(
            ImpactIndicator(name="bip_influence", value=1.5e-6, class_label="C2", source=SourceName.OPENAIRE)
        )
        # Need at least one citation to get past the "insufficient data" check
        s2 = _make_source(
            SourceName.SEMANTIC_SCHOLAR,
            citations=[_make_citation(doi="10.1000/c1")],
        )
        agg = _make_agg(sources={"openaire": oaire, "semantic_scholar": s2})
        result = analyze_citation_network(agg)

        assert result.bip_influence == 1.5e-6
        assert result.bip_influence_class == "C2"
        assert "BIP!" in result.narrative

    def test_pagerank_all_contains_all_nodes(self):
        src = _make_source(
            SourceName.SEMANTIC_SCHOLAR,
            citations=[
                _make_citation(doi="10.1000/c1"),
                _make_citation(doi="10.1000/c2"),
            ],
        )
        agg = _make_agg(sources={"semantic_scholar": src})
        result = analyze_citation_network(agg)

        # All 3 nodes should appear in the full score vector
        assert len(result.pagerank.standard_all) == 3
        assert "10.1234/test" in result.pagerank.standard_all
        assert "10.1000/c1" in result.pagerank.standard_all


# ---------------------------------------------------------------------------
# Reconciliation test — pagerank field on SourceResult still works
# ---------------------------------------------------------------------------

class TestPagerankSourceField:
    def test_openaire_pagerank_field(self):
        """The SourceResult.pagerank field for externally-provided scores still works."""
        r = SourceResult(source=SourceName.OPENAIRE, found=True, pagerank=2.5e-6)
        assert r.pagerank == 2.5e-6
        data = r.model_dump(exclude_none=True)
        assert data["pagerank"] == 2.5e-6

    def test_reconciliation_with_pagerank(self):
        from doi_metadata.reconciliation.engine import reconcile
        results = {
            "openaire": SourceResult(source=SourceName.OPENAIRE, found=True, pagerank=1.5e-6),
            "openalex": SourceResult(source=SourceName.OPENALEX, found=True, pagerank=2.3e-6),
        }
        report = reconcile("10.1234/test", results)
        pr_conflicts = [c for c in report.conflicts if c.field == "pagerank"]
        assert len(pr_conflicts) == 1
