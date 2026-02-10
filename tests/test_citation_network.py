"""Tests for citation network analysis — graph, PageRank, intents, anti-gaming, biomedical signals."""

from __future__ import annotations

from datetime import datetime, timezone

from doi_metadata.analyses.citation_network import (
    COMMON_SURNAMES,
    INFLUENTIAL_WEIGHT,
    INTENT_WEIGHTS,
    CitationNetworkResult,
    GraphEdge,
    GraphNode,
    _author_name_set,
    _build_biomedical_signals,
    _build_citation_velocity,
    _build_intent_profile,
    _collect_orcids,
    _compute_edge_weight,
    _detect_self_citation,
    _intent_weight,
    _percentile_rank,
    analyze_citation_network,
    build_graph,
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
    ImpactIndicator,
    MeSHTerm,
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
    citation_count: int | None = None,
    **kwargs,
) -> SourceResult:
    return SourceResult(
        source=source, found=found,
        citations=citations or [], references=references or [],
        authors=authors or [], pagerank=pagerank,
        citation_count=citation_count, **kwargs,
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
                    intents: list[str] | None = None,
                    s2_paper_id: str | None = None) -> Reference:
    return Reference(
        doi=doi, year=year, is_influential=is_influential,
        intents=intents or [], s2_paper_id=s2_paper_id,
        source=SourceName.SEMANTIC_SCHOLAR,
    )


def _make_author(family: str, given: str | None = None, orcid: str | None = None) -> Author:
    return Author(
        name=PersonName(family=family, given=given, orcid=orcid, source=SourceName.OPENALEX),
        sources=[SourceName.OPENALEX],
    )


# ---------------------------------------------------------------------------
# Intent weighting
# ---------------------------------------------------------------------------

class TestIntentWeighting:
    def test_methodology_highest(self):
        assert _intent_weight(["Methodology"]) == INTENT_WEIGHTS["methodology"]

    def test_result_comparison_mid(self):
        assert _intent_weight(["ResultComparison"]) == INTENT_WEIGHTS["resultcomparison"]

    def test_background_lowest(self):
        assert _intent_weight(["Background"]) < 1.0

    def test_multiple_intents_takes_max(self):
        w = _intent_weight(["Background", "Methodology"])
        assert w == INTENT_WEIGHTS["methodology"]

    def test_empty_intents_neutral(self):
        assert _intent_weight([]) == 1.0

    def test_unknown_intent_neutral(self):
        assert _intent_weight(["SomethingNew"]) == 1.0

    def test_edge_weight_combines_all_signals(self):
        # Influential + Methodology + not self-cite
        w = _compute_edge_weight(True, False, ["Methodology"])
        assert w == INTENT_WEIGHTS["methodology"] * INFLUENTIAL_WEIGHT

    def test_edge_weight_self_citation_penalty(self):
        w = _compute_edge_weight(False, True, [])
        assert w == 0.1


# ---------------------------------------------------------------------------
# Self-citation detection
# ---------------------------------------------------------------------------

class TestSelfCitationORCID:
    def test_orcid_match_detects_self_citation(self):
        assert _detect_self_citation(
            queried_orcids={"0000-0001-1234-5678"},
            queried_surnames=set(),
            citing_orcids=["0000-0001-1234-5678"],
            citing_author_names=[],
        ) is True

    def test_orcid_mismatch_no_detection(self):
        assert _detect_self_citation(
            queried_orcids={"0000-0001-1234-5678"},
            queried_surnames=set(),
            citing_orcids=["0000-0002-9999-9999"],
            citing_author_names=[],
        ) is False

    def test_common_surname_ignored(self):
        """'Wang' is in COMMON_SURNAMES — should not trigger self-citation."""
        assert "wang" in COMMON_SURNAMES
        # _author_name_set should exclude common surnames
        author = _make_author("Wang", "Wei")
        names = _author_name_set([author])
        assert "wang" not in names

    def test_uncommon_surname_detected(self):
        author = _make_author("Korkusuz", "Zehra")
        names = _author_name_set([author])
        assert "korkusuz" in names

    def test_short_surname_excluded(self):
        author = _make_author("Li", "Xin")
        names = _author_name_set([author])
        assert len(names) == 0  # "li" is both common AND short

    def test_surname_fallback_with_guards(self):
        assert _detect_self_citation(
            queried_orcids=set(),
            queried_surnames={"korkusuz"},
            citing_orcids=[],
            citing_author_names=["Zehra Korkusuz"],
        ) is True

    def test_collect_orcids_strips_url(self):
        author = Author(
            name=PersonName(orcid="https://orcid.org/0000-0001-0000-0001", source=SourceName.ORCID),
            sources=[SourceName.ORCID],
        )
        orcids = _collect_orcids([author])
        assert "0000-0001-0000-0001" in orcids


# ---------------------------------------------------------------------------
# Edge merging (not first-wins discard)
# ---------------------------------------------------------------------------

class TestEdgeMerging:
    def test_same_edge_from_two_sources_merges(self):
        """CrossRef provides edge first (no intent), S2 provides same edge with intent.
        The merged edge should have the S2 intent and influential flag."""
        cr = _make_source(
            SourceName.CROSSREF,
            citations=[Citation(doi="10.1000/cit1", source=SourceName.CROSSREF)],
        )
        s2 = _make_source(
            SourceName.SEMANTIC_SCHOLAR,
            citations=[_make_citation(doi="10.1000/cit1", is_influential=True,
                                      intents=["Methodology"])],
        )
        agg = _make_agg(sources={"crossref": cr, "semantic_scholar": s2})
        nodes, edges = build_graph("10.1234/test", agg)

        # Should be 1 merged edge, not 2
        inbound = [e for e in edges if e.target_id == "10.1234/test"]
        assert len(inbound) == 1
        edge = inbound[0]
        assert edge.is_influential is True
        assert "Methodology" in edge.intents
        assert len(edge.api_sources) == 2
        # Weight should reflect both influential AND methodology
        assert edge.weight == INTENT_WEIGHTS["methodology"] * INFLUENTIAL_WEIGHT


# ---------------------------------------------------------------------------
# Graph building
# ---------------------------------------------------------------------------

class TestBuildGraph:
    def test_empty_sources(self):
        agg = _make_agg()
        nodes, edges = build_graph("10.1234/test", agg)
        assert len(nodes) == 1
        assert nodes["10.1234/test"].is_queried

    def test_citations_become_inbound_edges(self):
        src = _make_source(
            SourceName.SEMANTIC_SCHOLAR,
            citations=[
                _make_citation(doi="10.1000/cit1"),
                _make_citation(doi="10.1000/cit2"),
            ],
        )
        agg = _make_agg(sources={"semantic_scholar": src})
        nodes, edges = build_graph("10.1234/test", agg)
        assert len(nodes) == 3
        for e in edges:
            assert e.target_id == "10.1234/test"

    def test_references_become_outbound_edges(self):
        src = _make_source(
            SourceName.SEMANTIC_SCHOLAR,
            references=[
                _make_reference(doi="10.1000/r1"),
                _make_reference(doi="10.1000/r2"),
            ],
        )
        agg = _make_agg(sources={"semantic_scholar": src})
        _, edges = build_graph("10.1234/test", agg)
        outbound = [e for e in edges if e.source_id == "10.1234/test"]
        assert len(outbound) == 2

    def test_related_works_with_doi(self):
        src = _make_source(
            SourceName.DATACITE,
            related_works=[
                RelatedWork(
                    identifier="10.1000/supplement",
                    identifier_type="DOI",
                    relation_type="IsCitedBy",
                    source=SourceName.DATACITE,
                ),
            ],
        )
        agg = _make_agg(sources={"datacite": src})
        nodes, edges = build_graph("10.1234/test", agg)
        assert "10.1000/supplement" in nodes
        inbound = [e for e in edges if e.target_id == "10.1234/test"]
        assert len(inbound) == 1

    def test_s2_paper_id_fallback(self):
        src = _make_source(
            SourceName.SEMANTIC_SCHOLAR,
            citations=[_make_citation(doi=None, s2_paper_id="abc123")],
        )
        agg = _make_agg(sources={"semantic_scholar": src})
        nodes, _ = build_graph("10.1234/test", agg)
        assert "s2:abc123" in nodes


# ---------------------------------------------------------------------------
# PageRank
# ---------------------------------------------------------------------------

class TestPageRank:
    def _simple_graph(self):
        """A → B, C → B (B has 2 inbound)."""
        nodes = {
            "a": GraphNode(node_id="a"),
            "b": GraphNode(node_id="b", is_queried=True),
            "c": GraphNode(node_id="c"),
        }
        edges = [
            GraphEdge(source_id="a", target_id="b", weight=1.0, api_sources=["s2"]),
            GraphEdge(source_id="c", target_id="b", weight=1.0, api_sources=["s2"]),
        ]
        return nodes, edges

    def test_converges(self):
        nodes, edges = self._simple_graph()
        pr = compute_standard_pagerank(nodes, edges)
        assert len(pr) == 3
        assert pr["b"] > pr["a"]

    def test_sums_to_one(self):
        nodes, edges = self._simple_graph()
        pr = compute_standard_pagerank(nodes, edges)
        assert abs(sum(pr.values()) - 1.0) < 0.001

    def test_time_decay_converges(self):
        nodes, edges = self._simple_graph()
        pr = compute_time_decay_pagerank(nodes, edges)
        assert abs(sum(pr.values()) - 1.0) < 0.01

    def test_weighted_distribution(self):
        """Higher edge weight gets proportionally more rank."""
        nodes = {
            "a": GraphNode(node_id="a"),
            "b": GraphNode(node_id="b"),
            "d": GraphNode(node_id="d"),
        }
        edges = [
            GraphEdge(source_id="a", target_id="b", weight=INFLUENTIAL_WEIGHT, api_sources=["s2"]),
            GraphEdge(source_id="a", target_id="d", weight=1.0, api_sources=["s2"]),
        ]
        pr = compute_standard_pagerank(nodes, edges)
        assert pr["b"] > pr["d"]

    def test_authority_weighted_init(self):
        """Node with known citation count gets higher initial authority."""
        nodes = {
            "citer_big": GraphNode(node_id="citer_big", citation_count=1000),
            "citer_small": GraphNode(node_id="citer_small", citation_count=1),
            "target": GraphNode(node_id="target", is_queried=True),
        }
        edges = [
            GraphEdge(source_id="citer_big", target_id="target", weight=1.0, api_sources=["s2"]),
            GraphEdge(source_id="citer_small", target_id="target", weight=1.0, api_sources=["s2"]),
        ]
        pr = compute_standard_pagerank(nodes, edges)
        # Target gets more from citer_big because big has higher init mass
        # But both converge — the key test is that it converges correctly
        assert pr["target"] > pr["citer_big"]
        assert pr["target"] > pr["citer_small"]

    def test_empty_graph(self):
        assert compute_standard_pagerank({}, []) == {}

    def test_single_node(self):
        nodes = {"a": GraphNode(node_id="a")}
        pr = compute_standard_pagerank(nodes, [])
        assert abs(pr["a"] - 1.0) < 0.001

    def test_star_graph(self):
        nodes = {"center": GraphNode(node_id="center", is_queried=True)}
        edges = []
        for i in range(10):
            nid = f"citer_{i}"
            nodes[nid] = GraphNode(node_id=nid)
            edges.append(GraphEdge(source_id=nid, target_id="center", weight=1.0, api_sources=["s2"]))
        pr = compute_standard_pagerank(nodes, edges)
        assert pr["center"] == max(pr.values())

    def test_percentile_rank(self):
        scores = {"a": 0.1, "b": 0.5, "c": 0.3}
        assert _percentile_rank(scores, "b") == 1.0  # b is the max
        assert _percentile_rank(scores, "a") < 1.0


# ---------------------------------------------------------------------------
# Topology
# ---------------------------------------------------------------------------

class TestTopology:
    def test_basic(self):
        nodes = {
            "q": GraphNode(node_id="q"),
            "a": GraphNode(node_id="a"),
            "b": GraphNode(node_id="b"),
        }
        edges = [
            GraphEdge(source_id="a", target_id="q", weight=1.0, is_influential=True, api_sources=["s2"]),
            GraphEdge(source_id="b", target_id="q", weight=0.1, is_self_citation=True, api_sources=["s2"]),
            GraphEdge(source_id="q", target_id="a", weight=1.0, api_sources=["cr"]),
        ]
        topo = compute_topology("q", nodes, edges)
        assert topo.in_degree == 2
        assert topo.out_degree == 1
        assert topo.self_citation_count == 1
        assert topo.influential_citation_count == 1

    def test_truncation_detection(self):
        nodes = {"q": GraphNode(node_id="q"), "a": GraphNode(node_id="a")}
        edges = [GraphEdge(source_id="a", target_id="q", weight=1.0, api_sources=["s2"])]
        topo = compute_topology("q", nodes, edges, known_citation_count=500)
        assert topo.graph_is_truncated is True
        assert topo.known_citation_count == 500


# ---------------------------------------------------------------------------
# Intent profile
# ---------------------------------------------------------------------------

class TestIntentProfile:
    def test_counts_intents(self):
        edges = [
            GraphEdge(source_id="a", target_id="q", intents=["Methodology"], api_sources=["s2"]),
            GraphEdge(source_id="b", target_id="q", intents=["Background"], api_sources=["s2"]),
            GraphEdge(source_id="c", target_id="q", intents=["ResultComparison"], api_sources=["s2"]),
            GraphEdge(source_id="d", target_id="q", intents=[], api_sources=["s2"]),
        ]
        ip = _build_intent_profile(edges, "q")
        assert ip.methodology_count == 1
        assert ip.background_count == 1
        assert ip.result_comparison_count == 1
        assert ip.unknown_count == 1
        assert ip.methodology_fraction is not None

    def test_dominant_intent(self):
        edges = [
            GraphEdge(source_id="a", target_id="q", intents=["Methodology"], api_sources=["s2"]),
            GraphEdge(source_id="b", target_id="q", intents=["Methodology"], api_sources=["s2"]),
            GraphEdge(source_id="c", target_id="q", intents=["Background"], api_sources=["s2"]),
        ]
        ip = _build_intent_profile(edges, "q")
        assert ip.dominant_intent == "methodology"


# ---------------------------------------------------------------------------
# Citation velocity
# ---------------------------------------------------------------------------

class TestCitationVelocity:
    def test_computes_trend(self):
        src = _make_source(SourceName.OPENALEX, counts_by_year={
            2018: 10, 2019: 15, 2020: 20, 2021: 25, 2022: 30, 2023: 35, 2024: 40, 2025: 45,
        })
        agg = _make_agg(sources={"openalex": src})
        vel = _build_citation_velocity(agg)
        assert vel.peak_year is not None
        assert vel.recent_3yr_avg is not None
        assert vel.trend is not None

    def test_empty_counts(self):
        agg = _make_agg()
        vel = _build_citation_velocity(agg)
        assert vel.years == []
        assert vel.trend is None


# ---------------------------------------------------------------------------
# Biomedical signals
# ---------------------------------------------------------------------------

class TestBiomedicalSignals:
    def test_mesh_terms_detected(self):
        src = _make_source(
            SourceName.EUROPE_PMC,
            mesh_terms=[MeSHTerm(descriptor_name="Genomics", source=SourceName.EUROPE_PMC)],
        )
        agg = _make_agg(sources={"europe_pmc": src})
        bio = _build_biomedical_signals(agg)
        assert bio.has_mesh_terms is True
        assert bio.mesh_term_count == 1

    def test_clinical_trials_detected(self):
        src = _make_source(
            SourceName.CROSSREF,
            clinical_trial_numbers=[{"number": "NCT12345678", "type": "results"}],
        )
        agg = _make_agg(sources={"crossref": src})
        bio = _build_biomedical_signals(agg)
        assert bio.has_clinical_trials is True
        assert bio.clinical_trial_count == 1

    def test_retraction_detected_from_europe_pmc(self):
        src = _make_source(
            SourceName.EUROPE_PMC,
            corrections=[{"type": "Retraction"}],
        )
        agg = _make_agg(sources={"europe_pmc": src})
        bio = _build_biomedical_signals(agg)
        assert bio.has_retraction is True

    def test_retraction_detected_from_crossref(self):
        src = _make_source(
            SourceName.CROSSREF,
            update_to=[{"type": "retraction", "DOI": "10.1234/retracted"}],
        )
        agg = _make_agg(sources={"crossref": src})
        bio = _build_biomedical_signals(agg)
        assert bio.has_retraction is True

    def test_pmid_availability(self):
        agg = _make_agg()
        agg.crosswalk.pmid = "12345678"
        bio = _build_biomedical_signals(agg)
        assert bio.pmid_available is True


# ---------------------------------------------------------------------------
# S-index
# ---------------------------------------------------------------------------

class TestSIndex:
    def _defaults(self):
        from doi_metadata.analyses.citation_network import (
            BiomedicalSignals,
            FieldNormalization,
            IntentProfile,
            NetworkTopology,
        )
        return (
            NetworkTopology(influential_fraction=0.2, self_citation_fraction=0.1),
            IntentProfile(methodology_fraction=0.3),
            FieldNormalization(fwci=1.5),
            BiomedicalSignals(pmid_available=True, has_mesh_terms=True),
        )

    def test_all_components_on_same_scale(self):
        topo, ip, fn, bio = self._defaults()
        s = compute_s_index(0.9, 0.95, topo, ip, fn, bio)
        # S-index should be in [0, 1]
        assert 0.0 <= s <= 1.0

    def test_retraction_kills_score(self):
        topo, ip, fn, bio = self._defaults()
        bio.has_retraction = True
        s = compute_s_index(1.0, 1.0, topo, ip, fn, bio)
        assert s == 0.0

    def test_zero_inputs(self):
        from doi_metadata.analyses.citation_network import (
            BiomedicalSignals,
            FieldNormalization,
            IntentProfile,
            NetworkTopology,
        )
        topo = NetworkTopology()
        ip = IntentProfile()
        fn = FieldNormalization()
        bio = BiomedicalSignals()
        s = compute_s_index(0.0, 0.0, topo, ip, fn, bio)
        # Only self_cit_penalty (1.0) contributes: 0.10 * 1.0 = 0.1
        assert abs(s - 0.1) < 0.001

    def test_field_norm_capped(self):
        """FWCI of 10.0 should not produce S-index > 1.0."""
        topo, ip, fn, bio = self._defaults()
        fn.fwci = 10.0  # Extreme
        s = compute_s_index(1.0, 1.0, topo, ip, fn, bio)
        assert s <= 1.0


# ---------------------------------------------------------------------------
# Full integration
# ---------------------------------------------------------------------------

class TestAnalyzeCitationNetwork:
    def test_empty_sources(self):
        agg = _make_agg()
        result = analyze_citation_network(agg)
        assert isinstance(result, CitationNetworkResult)
        assert "No citation edges" in result.narrative

    def test_with_citations_and_references(self):
        src = _make_source(
            SourceName.SEMANTIC_SCHOLAR,
            citations=[
                _make_citation(doi="10.1000/c1", year=2023, is_influential=True,
                               intents=["Methodology"]),
                _make_citation(doi="10.1000/c2", year=2024, intents=["Background"]),
                _make_citation(doi="10.1000/c3", year=2022, intents=["ResultComparison"]),
            ],
            references=[
                _make_reference(doi="10.1000/r1"),
                _make_reference(doi="10.1000/r2"),
            ],
            authors=[_make_author("Korkusuz", "Zehra")],
        )
        agg = _make_agg(sources={"semantic_scholar": src})
        result = analyze_citation_network(agg)

        assert result.pagerank.standard > 0
        assert result.pagerank.standard_percentile > 0
        assert result.s_index > 0
        assert result.topology.in_degree == 3
        assert result.topology.out_degree == 2

        # Intent profile populated
        assert result.intent_profile.methodology_count == 1
        assert result.intent_profile.background_count == 1

        # Narrative covers key metrics
        assert "PageRank" in result.narrative
        assert "S-index" in result.narrative
        assert "intent" in result.narrative.lower()

    def test_retraction_zeroes_s_index(self):
        """Retracted paper should get S-index = 0."""
        s2 = _make_source(
            SourceName.SEMANTIC_SCHOLAR,
            citations=[_make_citation(doi="10.1000/c1")],
        )
        epmc = _make_source(
            SourceName.EUROPE_PMC,
            corrections=[{"type": "Retraction"}],
        )
        agg = _make_agg(sources={"semantic_scholar": s2, "europe_pmc": epmc})
        result = analyze_citation_network(agg)
        assert result.s_index == 0.0
        assert "Retraction" in result.narrative

    def test_truncation_noted_in_narrative(self):
        """When citation_count >> graph edges, narrative should note truncation."""
        src = _make_source(
            SourceName.SEMANTIC_SCHOLAR,
            citations=[_make_citation(doi="10.1000/c1")],
            citation_count=5000,
        )
        agg = _make_agg(sources={"semantic_scholar": src})
        result = analyze_citation_network(agg)
        assert result.topology.graph_is_truncated is True
        assert "5000" in result.narrative

    def test_field_normalization_collected(self):
        oa = _make_source(SourceName.OPENALEX)
        oa.impact_indicators.append(
            ImpactIndicator(name="fwci", value=2.5, source=SourceName.OPENALEX)
        )
        nih = _make_source(SourceName.NIH_REPORTER, relative_citation_ratio=3.1)
        s2 = _make_source(
            SourceName.SEMANTIC_SCHOLAR,
            citations=[_make_citation(doi="10.1000/c1")],
        )
        agg = _make_agg(sources={"openalex": oa, "nih_reporter": nih, "semantic_scholar": s2})
        result = analyze_citation_network(agg)
        assert result.field_normalization.fwci == 2.5
        assert result.field_normalization.relative_citation_ratio == 3.1
        assert "FWCI" in result.narrative
        assert "RCR" in result.narrative


# ---------------------------------------------------------------------------
# SourceResult.pagerank field still works
# ---------------------------------------------------------------------------

class TestPagerankSourceField:
    def test_openaire_pagerank_field(self):
        r = SourceResult(source=SourceName.OPENAIRE, found=True, pagerank=2.5e-6)
        assert r.pagerank == 2.5e-6

    def test_reconciliation(self):
        from doi_metadata.reconciliation.engine import reconcile
        results = {
            "openaire": SourceResult(source=SourceName.OPENAIRE, found=True, pagerank=1.5e-6),
            "openalex": SourceResult(source=SourceName.OPENALEX, found=True, pagerank=2.3e-6),
        }
        report = reconcile("10.1234/test", results)
        pr_conflicts = [c for c in report.conflicts if c.field == "pagerank"]
        assert len(pr_conflicts) == 1
