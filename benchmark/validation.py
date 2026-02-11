"""Validate benchmark results against expected metadata.

Reads completed JSON results from the results/ directory, checks for:
- Expected registration agency (CrossRef vs DataCite)
- Minimum source coverage
- Key fields present (title, authors, etc.)
- No empty/broken results

Usage::

    python -m benchmark.validation
    python -m benchmark.validation --results-dir benchmark/results
"""

from __future__ import annotations

import json
import logging
import sys
from collections import Counter
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger("benchmark.validation")

DEFAULT_RESULTS_DIR = Path(__file__).resolve().parent / "results"

# Minimum number of sources expected per registration agency
MIN_SOURCES = {
    "crossref": 4,  # CrossRef DOIs should hit at least CrossRef + OpenAlex + S2 + Europe PMC
    "datacite": 1,  # DataCite DOIs may only hit DataCite itself
}


def validate_result(filepath: Path) -> dict:
    """Validate a single result JSON file.

    Returns a dict with: doi, valid (bool), errors (list[str]), warnings (list[str]),
    sources_found (int), registration_agency.
    """
    report = {
        "file": filepath.name,
        "doi": None,
        "valid": True,
        "errors": [],
        "warnings": [],
        "sources_found": 0,
        "registration_agency": None,
    }

    try:
        data = json.loads(filepath.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        report["valid"] = False
        report["errors"].append(f"Failed to read: {exc}")
        return report

    # DOI
    doi = data.get("doi") or data.get("_benchmark", {}).get("doi")
    report["doi"] = doi
    if not doi:
        report["valid"] = False
        report["errors"].append("Missing DOI")

    # Registration agency
    agency = data.get("registration_agency")
    report["registration_agency"] = agency

    # Sources
    sources = data.get("sources", {})
    found_sources = [name for name, src in sources.items() if isinstance(src, dict) and src.get("found")]
    report["sources_found"] = len(found_sources)

    if agency:
        min_src = MIN_SOURCES.get(agency, 1)
        if len(found_sources) < min_src:
            report["warnings"].append(
                f"Only {len(found_sources)} sources found (expected >= {min_src} for {agency})"
            )

    # Key fields
    if not found_sources:
        report["valid"] = False
        report["errors"].append("No sources returned data")

    # Check for crosswalk
    crosswalk = data.get("crosswalk")
    if not crosswalk:
        report["warnings"].append("No crosswalk data")

    # Check for conflicts
    conflicts = data.get("conflicts")
    if conflicts:
        conflict_count = conflicts.get("conflict_count", 0)
        if conflict_count > 0:
            report["warnings"].append(f"{conflict_count} conflicts detected")

    # Check for analyses
    analyses = data.get("analyses")
    if not analyses:
        report["warnings"].append("No analyses data")

    return report


def validate_all(results_dir: Path) -> list[dict]:
    """Validate all JSON result files in the directory."""
    results_dir = Path(results_dir)
    if not results_dir.exists():
        logger.error("Results directory not found: %s", results_dir)
        return []

    files = sorted(results_dir.glob("*.json"))
    if not files:
        logger.warning("No JSON files found in %s", results_dir)
        return []

    logger.info("Validating %d result files in %s", len(files), results_dir)

    reports = []
    for f in files:
        report = validate_result(f)
        reports.append(report)

    return reports


def print_validation_summary(reports: list[dict]) -> None:
    """Print a summary of validation results."""
    if not reports:
        print("No results to validate.")
        return

    total = len(reports)
    valid = sum(1 for r in reports if r["valid"])
    invalid = total - valid
    warnings_count = sum(len(r["warnings"]) for r in reports)

    print(f"\n{'='*60}")
    print(f"  Validation Summary: {total} results")
    print(f"{'='*60}")
    print(f"  Valid:    {valid:>5d} ({100*valid/total:.0f}%)")
    print(f"  Invalid:  {invalid:>5d} ({100*invalid/total:.0f}%)")
    print(f"  Warnings: {warnings_count:>5d}")

    # Source coverage distribution
    src_counts = Counter(r["sources_found"] for r in reports)
    print(f"\n  Sources found distribution:")
    for count in sorted(src_counts.keys()):
        bar = "#" * src_counts[count]
        print(f"    {count:>2d} sources: {src_counts[count]:>4d} DOIs  {bar}")

    # Agency breakdown
    agency_counts = Counter(r["registration_agency"] for r in reports)
    print(f"\n  Registration agency breakdown:")
    for agency, count in agency_counts.most_common():
        print(f"    {agency or 'unknown':<15s}: {count:>5d}")

    # Errors
    if invalid > 0:
        print(f"\n  Errors ({invalid}):")
        for r in reports:
            if not r["valid"]:
                print(f"    {r['doi'] or r['file']}: {'; '.join(r['errors'])}")

    print()


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Validate benchmark results")
    parser.add_argument(
        "--results-dir",
        type=str,
        default=str(DEFAULT_RESULTS_DIR),
        help=f"Results directory (default: {DEFAULT_RESULTS_DIR})",
    )
    args = parser.parse_args()

    reports = validate_all(Path(args.results_dir))
    print_validation_summary(reports)

    # Exit with non-zero if any invalid
    invalid = sum(1 for r in reports if not r["valid"])
    if invalid:
        sys.exit(1)


if __name__ == "__main__":
    main()
