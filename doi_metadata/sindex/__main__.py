"""CLI entry point for DataRank computation.

Usage:
    # Offline mode (no API calls, endowment-only ranking):
    python -m doi_metadata.sindex --results-dir benchmark/results --offline

    # Full mode with 1-hop OpenAlex expansion:
    python -m doi_metadata.sindex --results-dir benchmark/results

    # JSON output:
    python -m doi_metadata.sindex --results-dir benchmark/results --format json --output datarank.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

from doi_metadata.sindex.datarank import compute_datarank_corpus
from doi_metadata.sindex.report import generate_json_report, generate_text_report

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Compute DataRank (s-index) for benchmark corpus")
    parser.add_argument(
        "--results-dir",
        type=str,
        default="benchmark/results",
        help="Path to benchmark results directory (default: benchmark/results)",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Offline mode: endowment-only ranking, no OpenAlex API calls",
    )
    parser.add_argument(
        "--max-citers",
        type=int,
        default=200,
        help="Max citers to fetch per paper (default: 200)",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=5,
        help="Concurrent OpenAlex requests (default: 5)",
    )
    parser.add_argument(
        "--max-papers",
        type=int,
        default=0,
        help="Limit to first N papers, 0 = all (default: 0)",
    )
    parser.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output file path (default: stdout)",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=50,
        help="Number of top papers to show (default: 50)",
    )
    args = parser.parse_args()

    results_dir = Path(args.results_dir)
    if not results_dir.exists():
        print(f"Error: results directory not found: {results_dir}", file=sys.stderr)
        sys.exit(1)

    corpus = asyncio.run(
        compute_datarank_corpus(
            results_dir=results_dir,
            max_citers=args.max_citers,
            concurrency=args.concurrency,
            offline=args.offline,
            max_papers=args.max_papers,
        )
    )

    if args.format == "json":
        report = json.dumps(generate_json_report(corpus, top_n=args.top), indent=2)
    else:
        report = generate_text_report(corpus, top_n=args.top)

    if args.output:
        Path(args.output).write_text(report)
        logging.getLogger(__name__).info("Report written to %s", args.output)
    else:
        print(report)


if __name__ == "__main__":
    main()
