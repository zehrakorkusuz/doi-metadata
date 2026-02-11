"""Generate DataRank leaderboard and summary report."""

from __future__ import annotations

from doi_metadata.sindex.models import DataRankCorpus


def generate_text_report(corpus: DataRankCorpus, top_n: int = 50) -> str:
    """Generate a plain-text DataRank leaderboard."""
    lines: list[str] = []
    lines.append("=" * 80)
    lines.append("  DataRank — Data-Sharing Influence Ranking")
    lines.append("=" * 80)
    lines.append(f"\n  Corpus: {corpus.total_papers} papers")
    lines.append(f"  Damping factor: {corpus.damping_factor}")
    lines.append(f"  Mean DataRank:   {corpus.mean_datarank:.6f}")
    lines.append(f"  Median DataRank: {corpus.median_datarank:.6f}")
    lines.append(f"  Max DataRank:    {corpus.max_datarank:.6f}")
    lines.append("\n  Quantile thresholds:")
    lines.append(f"    S1 (top 0.01%): {corpus.s1_threshold:.6f}")
    lines.append(f"    S2 (top 0.1%):  {corpus.s2_threshold:.6f}")
    lines.append(f"    S3 (top 1%):    {corpus.s3_threshold:.6f}")
    lines.append(f"    S4 (top 10%):   {corpus.s4_threshold:.6f}")

    # Class distribution
    class_counts: dict[str, int] = {}
    for p in corpus.papers:
        cls = p.quantile_class or "?"
        class_counts[cls] = class_counts.get(cls, 0) + 1
    lines.append("\n  Class distribution:")
    for cls in ("S1", "S2", "S3", "S4", "S5"):
        c = class_counts.get(cls, 0)
        lines.append(f"    {cls}: {c}")

    lines.append(f"\n{'—' * 80}")
    lines.append(f"  Top {top_n} Papers by DataRank")
    lines.append(f"{'—' * 80}\n")

    header = f"  {'Rank':>4s}  {'Class':>5s}  {'DataRank':>10s}  {'Endow':>8s}  {'Citers':>6s}  {'D.Cite':>6s}  DOI"
    lines.append(header)
    lines.append(f"  {'-' * 74}")

    for p in corpus.papers[:top_n]:
        e = p.endowment
        lines.append(
            f"  {p.corpus_rank:>4d}  {p.quantile_class or '?':>5s}"
            f"  {p.datarank:>10.6f}  {e.endowment:>8.2f}"
            f"  {p.citer_count:>6d}  {e.datacite_reuse_total:>6d}"
            f"  {p.doi}"
        )

    # Papers with highest endowment (direct data sharing evidence)
    by_endowment = sorted(corpus.papers, key=lambda p: p.endowment.endowment, reverse=True)
    lines.append(f"\n{'—' * 80}")
    lines.append(f"  Top {top_n} Papers by Direct Data-Sharing Evidence (Endowment)")
    lines.append(f"{'—' * 80}\n")

    hdr = "  {:>4s}  {:>8s}  {:>6s}  {:>5s}  {:>8s}  {:>5s}  {:>5s}  DOI"
    lines.append(hdr.format("Rank", "Endow", "D.Cite", "Files", "DLs", "VerCh", "isDat"))
    lines.append(f"  {'-' * 74}")

    for i, p in enumerate(by_endowment[:top_n]):
        e = p.endowment
        lines.append(
            f"  {i+1:>4d}  {e.endowment:>8.2f}"
            f"  {e.datacite_reuse_total:>6d}"
            f"  {e.file_count:>5d}"
            f"  {e.downloads:>8d}"
            f"  {'Y' if e.has_version_chain else 'N':>5s}"
            f"  {'Y' if e.is_dataset else 'N':>5s}"
            f"  {p.doi}"
        )

    lines.append(f"\n{'=' * 80}")
    return "\n".join(lines)


def generate_json_report(corpus: DataRankCorpus, top_n: int = 100) -> dict:
    """Generate a JSON-serializable report."""
    return {
        "total_papers": corpus.total_papers,
        "damping_factor": corpus.damping_factor,
        "stats": {
            "mean_datarank": corpus.mean_datarank,
            "median_datarank": corpus.median_datarank,
            "max_datarank": corpus.max_datarank,
        },
        "thresholds": {
            "S1": corpus.s1_threshold,
            "S2": corpus.s2_threshold,
            "S3": corpus.s3_threshold,
            "S4": corpus.s4_threshold,
        },
        "leaderboard": [
            {
                "rank": p.corpus_rank,
                "doi": p.doi,
                "datarank": p.datarank,
                "quantile_class": p.quantile_class,
                "endowment": p.endowment.endowment,
                "datacite_reuse_total": p.endowment.datacite_reuse_total,
                "citer_count": p.citer_count,
                "citers_with_endowment": p.citers_with_endowment,
                "is_dataset": p.endowment.is_dataset,
                "is_oa": p.endowment.is_oa,
                "downloads": p.endowment.downloads,
                "file_count": p.endowment.file_count,
            }
            for p in corpus.papers[:top_n]
        ],
    }
