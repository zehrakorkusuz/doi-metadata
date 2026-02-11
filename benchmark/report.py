"""Generate corpus-wide summary statistics from benchmark results.

Reads all completed JSON results and produces a comprehensive report
covering source coverage, citation divergence, OA status, conflicts,
and per-tier summaries.

Usage::

    python -m benchmark.report
    python -m benchmark.report --results-dir benchmark/results --format markdown
"""

from __future__ import annotations

import json
import logging
import sqlite3
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger("benchmark.report")

DEFAULT_RESULTS_DIR = Path(__file__).resolve().parent / "results"
DB_PATH = Path(__file__).resolve().parent / "queue.db"

ALL_SOURCES = [
    "crossref", "datacite", "openalex", "semantic_scholar", "unpaywall",
    "europe_pmc", "openaire", "nih_reporter", "zenodo", "dryad", "orcid", "entrez",
]


def load_results(results_dir: Path) -> list[dict]:
    """Load all JSON result files."""
    files = sorted(results_dir.glob("*.json"))
    results = []
    for f in files:
        try:
            data = json.loads(f.read_text())
            results.append(data)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Skipping %s: %s", f.name, exc)
    return results


def get_queue_stats() -> dict | None:
    """Read queue.db stats if available."""
    if not DB_PATH.exists():
        return None
    try:
        conn = sqlite3.connect(DB_PATH)
        stats = {}
        for status in ("pending", "in_progress", "done", "failed"):
            row = conn.execute("SELECT COUNT(*) FROM doi_queue WHERE status = ?", (status,)).fetchone()
            stats[status] = row[0] if row else 0
        stats["total"] = sum(stats.values())

        # Per-tier
        rows = conn.execute("SELECT tier, status, COUNT(*) FROM doi_queue GROUP BY tier, status").fetchall()
        by_tier: dict = {}
        for tier, status, count in rows:
            by_tier.setdefault(tier, {})[status] = count
        stats["by_tier"] = by_tier

        conn.close()
        return stats
    except Exception:
        return None


def analyze_source_coverage(results: list[dict]) -> dict:
    """Compute source coverage heatmap data."""
    coverage: dict[str, dict[str, int]] = {}  # source -> {found, total}
    agency_coverage: dict[str, dict[str, dict[str, int]]] = {}  # agency -> source -> {found, total}

    for r in results:
        agency = r.get("registration_agency", "unknown")
        sources = r.get("sources", {})

        for source_name in ALL_SOURCES:
            # Global
            coverage.setdefault(source_name, {"found": 0, "total": 0})
            coverage[source_name]["total"] += 1

            # Per agency
            agency_coverage.setdefault(agency, {})
            agency_coverage[agency].setdefault(source_name, {"found": 0, "total": 0})
            agency_coverage[agency][source_name]["total"] += 1

            src_data = sources.get(source_name, {})
            if isinstance(src_data, dict) and src_data.get("found"):
                coverage[source_name]["found"] += 1
                agency_coverage[agency][source_name]["found"] += 1

    return {"global": coverage, "by_agency": agency_coverage}


def analyze_citation_divergence(results: list[dict]) -> list[dict]:
    """Extract citation count divergence across sources."""
    divergences = []
    for r in results:
        doi = r.get("doi", "?")
        sources = r.get("sources", {})
        counts: dict[str, int] = {}

        for src_name, src_data in sources.items():
            if not isinstance(src_data, dict) or not src_data.get("found"):
                continue
            cc = src_data.get("citation_count")
            if cc is not None and isinstance(cc, (int, float)) and cc >= 0:
                counts[src_name] = int(cc)

        if len(counts) >= 2:
            min_c = min(counts.values())
            max_c = max(counts.values())
            spread = ((max_c - min_c) / min_c * 100) if min_c > 0 else float("inf")
            divergences.append({
                "doi": doi,
                "counts": counts,
                "min": min_c,
                "max": max_c,
                "spread_pct": spread,
            })

    return sorted(divergences, key=lambda x: x["spread_pct"], reverse=True)


def analyze_oa_status(results: list[dict]) -> dict:
    """Aggregate OA status information."""
    oa_counts: Counter = Counter()
    for r in results:
        sources = r.get("sources", {})
        # Prefer Unpaywall for OA classification
        unpaywall = sources.get("unpaywall", {})
        if isinstance(unpaywall, dict) and unpaywall.get("found"):
            oa_status = unpaywall.get("oa_status", "unknown")
            oa_counts[oa_status] += 1
        else:
            # Fallback to OpenAlex
            openalex = sources.get("openalex", {})
            if isinstance(openalex, dict) and openalex.get("found"):
                oa_status = openalex.get("oa_status", "unknown")
                oa_counts[oa_status] += 1
            else:
                oa_counts["no_data"] += 1
    return dict(oa_counts.most_common())


def analyze_conflicts(results: list[dict]) -> dict:
    """Aggregate conflict statistics."""
    total_conflicts = 0
    total_agreements = 0
    conflict_types: Counter = Counter()

    for r in results:
        conflicts = r.get("conflicts", {})
        if isinstance(conflicts, dict):
            total_conflicts += conflicts.get("conflict_count", 0)
            total_agreements += conflicts.get("agreement_count", 0)
            for detail in conflicts.get("details", []):
                if isinstance(detail, dict):
                    conflict_types[detail.get("field", "unknown")] += 1

    return {
        "total_conflicts": total_conflicts,
        "total_agreements": total_agreements,
        "avg_conflicts_per_doi": total_conflicts / len(results) if results else 0,
        "conflict_types": dict(conflict_types.most_common()),
    }


def generate_text_report(results: list[dict]) -> str:
    """Generate a plain-text summary report."""
    lines = []
    lines.append("=" * 70)
    lines.append("  DOI Metadata Benchmark — Corpus Report")
    lines.append("=" * 70)
    lines.append(f"\n  Total results analyzed: {len(results)}")

    # Queue stats
    queue_stats = get_queue_stats()
    if queue_stats:
        lines.append(f"\n  Queue stats:")
        lines.append(f"    Total:   {queue_stats['total']:>6d}")
        lines.append(f"    Done:    {queue_stats['done']:>6d}")
        lines.append(f"    Pending: {queue_stats['pending']:>6d}")
        lines.append(f"    Failed:  {queue_stats['failed']:>6d}")

    # Source coverage
    lines.append(f"\n{'—'*70}")
    lines.append("  Source Coverage")
    lines.append(f"{'—'*70}")

    coverage = analyze_source_coverage(results)
    lines.append(f"\n  {'Source':<20s} {'Found':>6s} / {'Total':>5s}   {'Rate':>5s}")
    lines.append(f"  {'-'*42}")
    for src in ALL_SOURCES:
        c = coverage["global"].get(src, {"found": 0, "total": 0})
        rate = f"{100 * c['found'] / c['total']:.0f}%" if c["total"] > 0 else "N/A"
        lines.append(f"  {src:<20s} {c['found']:>6d} / {c['total']:>5d}   {rate:>5s}")

    # Per-agency coverage
    for agency, src_map in coverage["by_agency"].items():
        total_for_agency = next(iter(src_map.values()), {}).get("total", 0) if src_map else 0
        lines.append(f"\n  {agency} DOIs ({total_for_agency}):")
        for src in ALL_SOURCES:
            c = src_map.get(src, {"found": 0, "total": 0})
            if c["total"] > 0:
                rate = f"{100 * c['found'] / c['total']:.0f}%"
                lines.append(f"    {src:<20s} {c['found']:>4d} / {c['total']:>4d}  {rate}")

    # Citation divergence
    lines.append(f"\n{'—'*70}")
    lines.append("  Citation Count Divergence (top 20)")
    lines.append(f"{'—'*70}")

    divergences = analyze_citation_divergence(results)
    for d in divergences[:20]:
        spread = f"{d['spread_pct']:.0f}%" if d["spread_pct"] != float("inf") else "inf"
        lines.append(f"  {d['doi'][:50]:<50s}  {d['min']:>8,d} — {d['max']:>8,d}  ({spread})")

    if divergences:
        spreads = [d["spread_pct"] for d in divergences if d["spread_pct"] != float("inf")]
        if spreads:
            lines.append(f"\n  Median spread: {statistics.median(spreads):.0f}%")
            lines.append(f"  Mean spread:   {statistics.mean(spreads):.0f}%")

    # OA status
    lines.append(f"\n{'—'*70}")
    lines.append("  Open Access Status")
    lines.append(f"{'—'*70}")

    oa = analyze_oa_status(results)
    for status, count in oa.items():
        pct = f"{100 * count / len(results):.0f}%" if results else "N/A"
        lines.append(f"  {status:<20s} {count:>5d}  ({pct})")

    # Conflicts
    lines.append(f"\n{'—'*70}")
    lines.append("  Conflict Summary")
    lines.append(f"{'—'*70}")

    conflict_stats = analyze_conflicts(results)
    lines.append(f"  Total conflicts:   {conflict_stats['total_conflicts']:>6d}")
    lines.append(f"  Total agreements:  {conflict_stats['total_agreements']:>6d}")
    lines.append(f"  Avg per DOI:       {conflict_stats['avg_conflicts_per_doi']:>6.1f}")
    if conflict_stats["conflict_types"]:
        lines.append(f"\n  Conflict types:")
        for ctype, count in conflict_stats["conflict_types"].items():
            lines.append(f"    {ctype:<30s} {count:>5d}")

    # Registration agency distribution
    lines.append(f"\n{'—'*70}")
    lines.append("  Registration Agency Distribution")
    lines.append(f"{'—'*70}")

    agency_counts = Counter(r.get("registration_agency", "unknown") for r in results)
    for agency, count in agency_counts.most_common():
        pct = f"{100 * count / len(results):.0f}%" if results else "N/A"
        lines.append(f"  {agency or 'unknown':<20s} {count:>5d}  ({pct})")

    lines.append(f"\n{'='*70}")
    return "\n".join(lines)


def generate_markdown_report(results: list[dict]) -> str:
    """Generate a Markdown-formatted report."""
    lines = []
    lines.append("# DOI Metadata Benchmark Report")
    lines.append(f"\n**Total results:** {len(results)}")

    # Source coverage table
    lines.append("\n## Source Coverage\n")
    coverage = analyze_source_coverage(results)
    lines.append("| Source | Found | Total | Rate |")
    lines.append("|--------|------:|------:|-----:|")
    for src in ALL_SOURCES:
        c = coverage["global"].get(src, {"found": 0, "total": 0})
        rate = f"{100 * c['found'] / c['total']:.0f}%" if c["total"] > 0 else "N/A"
        lines.append(f"| {src} | {c['found']} | {c['total']} | {rate} |")

    # OA
    lines.append("\n## Open Access Status\n")
    oa = analyze_oa_status(results)
    lines.append("| Status | Count | Pct |")
    lines.append("|--------|------:|----:|")
    for status, count in oa.items():
        pct = f"{100 * count / len(results):.0f}%" if results else "N/A"
        lines.append(f"| {status} | {count} | {pct} |")

    # Top citation divergences
    lines.append("\n## Top Citation Divergences\n")
    divergences = analyze_citation_divergence(results)
    lines.append("| DOI | Min | Max | Spread |")
    lines.append("|-----|----:|----:|-------:|")
    for d in divergences[:15]:
        spread = f"{d['spread_pct']:.0f}%" if d["spread_pct"] != float("inf") else "inf"
        lines.append(f"| `{d['doi'][:45]}` | {d['min']:,d} | {d['max']:,d} | {spread} |")

    # Conflicts
    lines.append("\n## Conflicts\n")
    cs = analyze_conflicts(results)
    lines.append(f"- Total conflicts: **{cs['total_conflicts']}**")
    lines.append(f"- Total agreements: **{cs['total_agreements']}**")
    lines.append(f"- Avg conflicts per DOI: **{cs['avg_conflicts_per_doi']:.1f}**")

    return "\n".join(lines)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Generate benchmark corpus report")
    parser.add_argument(
        "--results-dir",
        type=str,
        default=str(DEFAULT_RESULTS_DIR),
        help=f"Results directory (default: {DEFAULT_RESULTS_DIR})",
    )
    parser.add_argument(
        "--format",
        choices=["text", "markdown"],
        default="text",
        help="Output format (default: text)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output file path (default: stdout)",
    )
    args = parser.parse_args()

    results_dir = Path(args.results_dir)
    results = load_results(results_dir)

    if not results:
        print(f"No results found in {results_dir}")
        sys.exit(1)

    if args.format == "markdown":
        report = generate_markdown_report(results)
    else:
        report = generate_text_report(results)

    if args.output:
        Path(args.output).write_text(report)
        logger.info("Report written to %s", args.output)
    else:
        print(report)


if __name__ == "__main__":
    main()
