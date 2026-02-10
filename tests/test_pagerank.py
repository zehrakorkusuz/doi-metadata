"""Tests for the pagerank field across the pipeline."""

from __future__ import annotations

from doi_metadata.models import (
    AggregatedResult,
    ConflictReport,
    IdentifierCrosswalk,
    SourceName,
    SourceResult,
)
from doi_metadata.reconciliation.engine import reconcile


def _make_source(source: SourceName, pagerank: float | None = None, found: bool = True) -> SourceResult:
    return SourceResult(source=source, found=found, pagerank=pagerank)


class TestPagerankModel:
    def test_default_is_none(self):
        r = SourceResult(source=SourceName.OPENAIRE)
        assert r.pagerank is None

    def test_set_pagerank(self):
        r = SourceResult(source=SourceName.OPENAIRE, pagerank=1.23e-6)
        assert r.pagerank == 1.23e-6

    def test_serializes_when_set(self):
        r = SourceResult(source=SourceName.OPENAIRE, pagerank=4.5e-5)
        data = r.model_dump(exclude_none=True)
        assert data["pagerank"] == 4.5e-5

    def test_excluded_when_none(self):
        r = SourceResult(source=SourceName.OPENAIRE)
        data = r.model_dump(exclude_none=True)
        assert "pagerank" not in data


class TestPagerankReconciliation:
    def test_no_conflict_single_source(self):
        results = {
            "openaire": _make_source(SourceName.OPENAIRE, pagerank=1.5e-6),
            "crossref": _make_source(SourceName.CROSSREF, pagerank=None),
        }
        report = reconcile("10.1234/test", results)
        pr_conflicts = [c for c in report.conflicts if c.field == "pagerank"]
        assert len(pr_conflicts) == 0

    def test_conflict_when_sources_disagree(self):
        results = {
            "openaire": _make_source(SourceName.OPENAIRE, pagerank=1.5e-6),
            "openalex": _make_source(SourceName.OPENALEX, pagerank=2.3e-6),
        }
        report = reconcile("10.1234/test", results)
        pr_conflicts = [c for c in report.conflicts if c.field == "pagerank"]
        assert len(pr_conflicts) == 1
        assert pr_conflicts[0].risk == "medium"
        assert pr_conflicts[0].values["openaire"] == 1.5e-6
        assert pr_conflicts[0].values["openalex"] == 2.3e-6

    def test_no_conflict_when_sources_agree(self):
        results = {
            "openaire": _make_source(SourceName.OPENAIRE, pagerank=1.5e-6),
            "openalex": _make_source(SourceName.OPENALEX, pagerank=1.5e-6),
        }
        report = reconcile("10.1234/test", results)
        pr_conflicts = [c for c in report.conflicts if c.field == "pagerank"]
        assert len(pr_conflicts) == 0


class TestPagerankImpactProfile:
    def test_pagerank_collected_in_profile(self):
        from datetime import datetime, timezone

        from doi_metadata.analyses.impact_profile import analyze_impact

        results = {
            "openaire": _make_source(SourceName.OPENAIRE, pagerank=3.2e-6),
        }
        agg = AggregatedResult(
            doi="10.1234/test",
            retrieved_at=datetime.now(timezone.utc),
            sources=results,
            crosswalk=IdentifierCrosswalk(doi="10.1234/test"),
            conflicts=ConflictReport(doi="10.1234/test"),
        )
        profile = analyze_impact(agg)
        assert profile.pagerank == {"openaire": 3.2e-6}

    def test_pagerank_in_narrative(self):
        from datetime import datetime, timezone

        from doi_metadata.analyses.impact_profile import analyze_impact

        results = {
            "openaire": _make_source(SourceName.OPENAIRE, pagerank=3.2e-6),
        }
        agg = AggregatedResult(
            doi="10.1234/test",
            retrieved_at=datetime.now(timezone.utc),
            sources=results,
            crosswalk=IdentifierCrosswalk(doi="10.1234/test"),
            conflicts=ConflictReport(doi="10.1234/test"),
        )
        profile = analyze_impact(agg)
        assert "PageRank" in profile.narrative


class TestPagerankOutput:
    def test_pagerank_in_summary(self):
        from datetime import datetime, timezone

        from doi_metadata.output import to_summary

        results = {
            "openaire": _make_source(SourceName.OPENAIRE, pagerank=3.2e-6),
        }
        agg = AggregatedResult(
            doi="10.1234/test",
            retrieved_at=datetime.now(timezone.utc),
            sources=results,
            crosswalk=IdentifierCrosswalk(doi="10.1234/test"),
            conflicts=ConflictReport(doi="10.1234/test"),
        )
        summary = to_summary(agg)
        assert "pagerank=" in summary
