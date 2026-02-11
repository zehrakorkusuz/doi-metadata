"""Benchmark pipeline runner for the DOI metadata aggregation system.

Continuously fetches DOIs through the full lookup pipeline, stores results
as JSON files, and periodically runs expander modules that discover new
DOIs to feed back into the queue.

All state lives in a SQLite database (``queue.db``), so the pipeline is
safe to kill and restart at any time.

Usage::

    python -m benchmark.pipeline --max-total 100 --concurrency 3
    python -m benchmark.pipeline --dry-run
    python -m benchmark.pipeline --status
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Ensure the project root is on sys.path so ``doi_metadata`` is importable
# regardless of how this module is invoked.
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DB_PATH = Path(__file__).resolve().parent / "queue.db"
CORPUS_PATH = Path(__file__).resolve().parent / "corpus.yaml"
DEFAULT_RESULTS_DIR = Path(__file__).resolve().parent / "results"

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("benchmark")


# ===================================================================
# Database helpers
# ===================================================================

def init_db() -> None:
    """Create tables and indices if they do not already exist."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS doi_queue (
                doi            TEXT PRIMARY KEY,
                tier           INTEGER NOT NULL,
                category       TEXT,
                priority       INTEGER DEFAULT 5,
                status         TEXT DEFAULT 'pending',
                source_doi     TEXT,
                source_expander TEXT,
                result_path    TEXT,
                fetched_at     TEXT,
                error          TEXT,
                retry_count    INTEGER DEFAULT 0,
                created_at     TEXT DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_status_priority
                ON doi_queue(status, priority, created_at);

            CREATE TABLE IF NOT EXISTS expander_state (
                expander_name TEXT PRIMARY KEY,
                last_page     INTEGER DEFAULT 0,
                last_run      TEXT,
                extra_json    TEXT
            );

            CREATE TABLE IF NOT EXISTS researchers (
                orcid       TEXT PRIMARY KEY,
                name        TEXT,
                institution TEXT,
                openalex_id TEXT,
                expanded    INTEGER DEFAULT 0
            );
            """
        )


def get_queue_stats() -> dict:
    """Return a nested dict of counts by status and tier."""
    stats: dict = {"by_tier": {}, "total": {}}
    with sqlite3.connect(DB_PATH) as conn:
        # Per-tier breakdown
        rows = conn.execute(
            """SELECT tier, status, COUNT(*) FROM doi_queue
               GROUP BY tier, status ORDER BY tier, status"""
        ).fetchall()
        for tier, status, count in rows:
            stats["by_tier"].setdefault(tier, {})[status] = count

        # Totals
        for status in ("pending", "in_progress", "done", "failed"):
            row = conn.execute(
                "SELECT COUNT(*) FROM doi_queue WHERE status = ?", (status,)
            ).fetchone()
            stats["total"][status] = row[0] if row else 0

        stats["total"]["all"] = sum(stats["total"].values())

        # Researchers
        r_row = conn.execute("SELECT COUNT(*), SUM(expanded) FROM researchers").fetchone()
        stats["researchers_total"] = r_row[0] if r_row and r_row[0] else 0
        stats["researchers_expanded"] = int(r_row[1]) if r_row and r_row[1] else 0

    return stats


def claim_batch(n: int) -> list[str]:
    """Atomically claim up to *n* pending DOIs for processing.

    Sets their status to ``in_progress`` and returns the DOI strings.
    """
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            """SELECT doi FROM doi_queue
               WHERE status = 'pending'
               ORDER BY priority ASC, created_at ASC
               LIMIT ?""",
            (n,),
        ).fetchall()
        dois = [r[0] for r in rows]
        if dois:
            placeholders = ",".join("?" for _ in dois)
            conn.execute(
                f"UPDATE doi_queue SET status = 'in_progress' WHERE doi IN ({placeholders})",
                dois,
            )
        return dois


def mark_done(doi: str, result_path: str) -> None:
    """Mark a DOI as successfully fetched."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """UPDATE doi_queue
               SET status = 'done',
                   result_path = ?,
                   fetched_at = ?,
                   error = NULL
               WHERE doi = ?""",
            (result_path, datetime.now(timezone.utc).isoformat(), doi),
        )


def mark_failed(doi: str, error: str) -> None:
    """Mark a DOI as failed.  Retries up to 3 times by resetting to pending."""
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            "SELECT retry_count FROM doi_queue WHERE doi = ?", (doi,)
        ).fetchone()
        retry_count = (row[0] if row else 0) + 1

        if retry_count < 3:
            new_status = "pending"
        else:
            new_status = "failed"

        conn.execute(
            """UPDATE doi_queue
               SET status = ?,
                   error = ?,
                   retry_count = ?
               WHERE doi = ?""",
            (new_status, error, retry_count, doi),
        )


def enqueue_doi(
    doi: str,
    tier: int,
    category: str | None = None,
    priority: int = 5,
    source_doi: str | None = None,
    source_expander: str | None = None,
) -> bool:
    """Insert a DOI into the queue.  Returns True if newly inserted."""
    with sqlite3.connect(DB_PATH) as conn:
        try:
            conn.execute(
                """INSERT OR IGNORE INTO doi_queue
                   (doi, tier, category, priority, status, source_doi, source_expander, created_at)
                   VALUES (?, ?, ?, ?, 'pending', ?, ?, datetime('now'))""",
                (doi.lower(), tier, category, priority, source_doi, source_expander),
            )
            return conn.total_changes > 0
        except sqlite3.IntegrityError:
            return False


def has_pending() -> bool:
    """Check whether there are any pending DOIs in the queue."""
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM doi_queue WHERE status = 'pending'"
        ).fetchone()
        return (row[0] if row else 0) > 0


def total_done() -> int:
    """Return the number of completed DOIs."""
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM doi_queue WHERE status = 'done'"
        ).fetchone()
        return row[0] if row else 0


def _reset_stale_in_progress() -> int:
    """Reset any DOIs stuck in 'in_progress' back to 'pending'.

    This handles the case where the pipeline was killed mid-batch.
    """
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "UPDATE doi_queue SET status = 'pending' WHERE status = 'in_progress'"
        )
        return conn.total_changes


# ===================================================================
# Corpus / seed loading
# ===================================================================

def load_seeds(tiers: str) -> None:
    """Parse corpus.yaml and INSERT OR IGNORE seed DOIs into the queue.

    *tiers* is a comma-separated string like ``"1,2,3"``.
    """
    if not CORPUS_PATH.exists():
        logger.warning("Corpus file not found at %s -- proceeding with existing queue", CORPUS_PATH)
        return

    try:
        import yaml
    except ImportError:
        logger.error("PyYAML is required to load the corpus.  Install with: pip install pyyaml")
        return

    with open(CORPUS_PATH) as fh:
        corpus = yaml.safe_load(fh)

    if not corpus:
        logger.warning("Corpus file is empty")
        return

    tier_set = {int(t.strip()) for t in tiers.split(",")}
    loaded = 0

    # ---- Tier 1: edge cases ----
    if 1 in tier_set:
        for item in corpus.get("tier1_edge_cases", []):
            doi = item.get("doi", "").strip()
            if doi:
                if enqueue_doi(doi, tier=1, category=item.get("category", "edge_case"), priority=1):
                    loaded += 1

    # ---- Tier 2: landmark papers ----
    if 2 in tier_set:
        tier2 = corpus.get("tier2_landmark_papers", {})
        for _category_key, papers in tier2.items():
            if not isinstance(papers, list):
                continue
            for item in papers:
                doi = item.get("doi", "").strip()
                if doi:
                    if enqueue_doi(doi, tier=2, category=item.get("category", _category_key), priority=3):
                        loaded += 1

    # ---- Tier 3: researchers ----
    if 3 in tier_set:
        for researcher in corpus.get("tier3_researchers", []):
            orcid = (researcher.get("orcid") or "").strip()
            name = (researcher.get("name") or "").strip()
            institution = (researcher.get("institution") or "").strip()

            # Insert into researchers table
            if orcid:
                with sqlite3.connect(DB_PATH) as conn:
                    conn.execute(
                        """INSERT OR IGNORE INTO researchers (orcid, name, institution)
                           VALUES (?, ?, ?)""",
                        (orcid, name, institution),
                    )

            # Enqueue their key DOIs
            for doi in researcher.get("key_dois", []):
                doi = doi.strip()
                if doi:
                    if enqueue_doi(doi, tier=3, category="researcher_key", priority=2):
                        loaded += 1

    logger.info("Loaded %d new seed DOIs from corpus.yaml (tiers: %s)", loaded, tiers)


# ===================================================================
# Status display
# ===================================================================

TIER_LABELS = {
    1: "Edge Cases",
    2: "Landmark",
    3: "Researchers",
    4: "Top Cited",
    5: "Author Works",
}


def show_status() -> None:
    """Print a summary table of the queue state."""
    if not DB_PATH.exists():
        print("No queue database found at", DB_PATH)
        return

    stats = get_queue_stats()
    by_tier = stats["by_tier"]

    print("\nQueue Status:")
    header = f"  {'Tier':<30s} {'total':>7s} | {'pending':>7s} | {'done':>7s} | {'failed':>7s}"
    print(header)
    print("  " + "-" * (len(header) - 2))

    grand_total = grand_pending = grand_done = grand_failed = 0

    for tier_num in sorted(set(list(by_tier.keys()) + [1, 2, 3, 4, 5])):
        tier_data = by_tier.get(tier_num, {})
        pending = tier_data.get("pending", 0) + tier_data.get("in_progress", 0)
        done = tier_data.get("done", 0)
        failed = tier_data.get("failed", 0)
        tier_total = pending + done + failed

        label = TIER_LABELS.get(tier_num, f"Tier {tier_num}")
        print(f"  Tier {tier_num} ({label:<16s}) {tier_total:>7d} | {pending:>7d} | {done:>7d} | {failed:>7d}")

        grand_total += tier_total
        grand_pending += pending
        grand_done += done
        grand_failed += failed

    print("  " + "-" * (len(header) - 2))
    print(f"  {'Total':<30s} {grand_total:>7d} | {grand_pending:>7d} | {grand_done:>7d} | {grand_failed:>7d}")

    # Results directory stats
    results_dir = DEFAULT_RESULTS_DIR
    if results_dir.exists():
        files = list(results_dir.glob("*.json"))
        total_size = sum(f.stat().st_size for f in files)
        size_mb = total_size / (1024 * 1024)
        print(f"\n  Results dir: {results_dir}/ ({len(files)} files, {size_mb:.1f} MB)")
    else:
        print(f"\n  Results dir: {results_dir}/ (not yet created)")

    # Researcher stats
    r_total = stats.get("researchers_total", 0)
    r_expanded = stats.get("researchers_expanded", 0)
    if r_total:
        print(f"  Researchers: {r_total} total | {r_expanded} expanded")

    print()


# ===================================================================
# Core processing
# ===================================================================

async def process_doi(
    doi: str,
    results_dir: Path,
    semaphore: asyncio.Semaphore,
    *,
    fast: bool = False,
    skip_sources: set[str] | None = None,
) -> tuple[str, str | None, str | None]:
    """Fetch a single DOI through the full pipeline.

    Returns ``(doi, result_path, error)``.  On success *error* is None;
    on failure *result_path* is None.  Never raises -- all exceptions are
    caught and returned as the *error* string.
    """
    async with semaphore:
        try:
            from doi_metadata.orchestrator import lookup

            result = await lookup(
                doi,
                include_raw=False,
                follow_links=not fast,
                run_analyses=not fast,
                skip_sources=skip_sources,
            )

            # Deterministic filename from DOI
            doi_hash = hashlib.sha256(doi.lower().encode()).hexdigest()[:16]
            result_path = results_dir / f"{doi_hash}.json"
            result_path.parent.mkdir(parents=True, exist_ok=True)

            # Serialize Pydantic model to JSON
            data = result.model_dump(mode="json", exclude_none=True)
            data["_benchmark"] = {
                "doi": doi,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            }
            result_path.write_text(json.dumps(data, indent=2, default=str))

            return (doi, str(result_path), None)

        except Exception as exc:
            logger.error("Failed to fetch %s: %s", doi, exc)
            return (doi, None, str(exc))


# ===================================================================
# Expander runner
# ===================================================================

async def run_expanders(results_dir: Path) -> None:
    """Run all expander modules and log results."""
    from benchmark.expanders.top_cited import expand_top_cited
    from benchmark.expanders.author_works import expand_author_works
    from benchmark.expanders.citation_graph import expand_citation_graph

    logger.info("Running expanders...")

    try:
        new_top = await expand_top_cited(DB_PATH)
        logger.info("  top_cited: %d new DOIs", new_top)
    except Exception as exc:
        logger.warning("  top_cited failed: %s", exc)

    try:
        new_author = await expand_author_works(DB_PATH)
        logger.info("  author_works: %d new DOIs", new_author)
    except Exception as exc:
        logger.warning("  author_works failed: %s", exc)

    try:
        new_cite = await expand_citation_graph(DB_PATH, results_dir)
        logger.info("  citation_graph: %d new DOIs", new_cite)
    except Exception as exc:
        logger.warning("  citation_graph failed: %s", exc)


# ===================================================================
# Main run loop
# ===================================================================

async def run(args: argparse.Namespace) -> None:
    """Main entry point.  Initialises the DB, loads seeds, then loops."""
    init_db()

    # --status: show stats and exit
    if args.status:
        show_status()
        return

    # Load seeds from corpus.yaml
    load_seeds(args.tiers)

    # --dry-run: show stats and exit
    if args.dry_run:
        show_status()
        return

    # Reset any DOIs left in_progress from a previous crash
    stale = _reset_stale_in_progress()
    if stale:
        logger.info("Reset %d stale in_progress DOIs back to pending", stale)

    results_dir = Path(args.results_dir)
    results_dir.mkdir(parents=True, exist_ok=True)

    # Concurrency limiter
    semaphore = asyncio.Semaphore(args.concurrency)

    start_time = time.time()
    done_count = 0
    expand_counter = 0

    logger.info(
        "Starting benchmark pipeline (concurrency=%d, max_total=%s, max_hours=%s, expand=%s)",
        args.concurrency,
        args.max_total or "unlimited",
        args.max_hours or "unlimited",
        args.expand,
    )

    skip = set(args.skip_sources.split(",")) if args.skip_sources else None

    # Worker-pool model: maintain up to `concurrency` in-flight tasks at all times.
    # As soon as one finishes, start the next — no waiting for a full batch.
    pending_tasks: dict[asyncio.Task, str] = {}  # task → doi
    last_log_time = start_time

    def _should_stop() -> bool:
        if args.max_total and done_count >= args.max_total:
            return True
        if args.max_hours and (time.time() - start_time) / 3600 >= args.max_hours:
            return True
        return False

    while True:
        # ---- Fill the pool up to concurrency ----
        while len(pending_tasks) < args.concurrency and not _should_stop():
            batch = claim_batch(min(args.concurrency - len(pending_tasks), 50))
            if not batch:
                break
            for doi in batch:
                task = asyncio.create_task(
                    process_doi(doi, results_dir, semaphore, fast=args.fast, skip_sources=skip)
                )
                pending_tasks[task] = doi

        if not pending_tasks:
            if _should_stop():
                break
            # Try expanders or exit
            if args.expand:
                await run_expanders(results_dir)
                if has_pending():
                    continue
            logger.info("Queue empty, stopping")
            break

        # ---- Wait for at least one task to complete ----
        finished, _ = await asyncio.wait(pending_tasks.keys(), return_when=asyncio.FIRST_COMPLETED)

        for task in finished:
            doi = pending_tasks.pop(task)
            try:
                result = task.result()
                _doi, result_path, error = result
                if error:
                    mark_failed(_doi, error)
                else:
                    mark_done(_doi, result_path)  # type: ignore[arg-type]
                    done_count += 1
                    expand_counter += 1
            except Exception as exc:
                logger.error("Unexpected task exception for %s: %s", doi, exc)
                mark_failed(doi, str(exc))

        # ---- Periodic logging ----
        now = time.time()
        if now - last_log_time >= 30:
            elapsed_min = (now - start_time) / 60
            rate = done_count / elapsed_min if elapsed_min > 0 else 0
            logger.info(
                "Progress: %d done, %d in-flight, %.1f DOIs/min, %.1f min elapsed",
                done_count, len(pending_tasks), rate, elapsed_min,
            )
            last_log_time = now

        # ---- Periodic expansion ----
        if args.expand and expand_counter >= args.expand_interval:
            expand_counter = 0
            await run_expanders(results_dir)

        if _should_stop() and not pending_tasks:
            break

    # ---- Final report ----
    elapsed_min = (time.time() - start_time) / 60
    show_status()
    logger.info(
        "Pipeline complete. %d DOIs fetched in %.1f minutes (%.1f DOIs/min).",
        done_count,
        elapsed_min,
        done_count / elapsed_min if elapsed_min > 0 else 0,
    )


# ===================================================================
# CLI
# ===================================================================

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="benchmark.pipeline",
        description="Benchmark pipeline runner for the DOI metadata aggregation system.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
examples:
  python -m benchmark.pipeline --dry-run
  python -m benchmark.pipeline --max-total 50 --concurrency 5
  python -m benchmark.pipeline --status
  python -m benchmark.pipeline --no-expand --max-hours 2
  python -m benchmark.pipeline --tiers 1,2
""",
    )

    parser.add_argument(
        "--max-total",
        type=int,
        default=0,
        metavar="N",
        help="Stop after N total DOIs fetched (default: 0 = unlimited)",
    )
    parser.add_argument(
        "--max-hours",
        type=float,
        default=0,
        metavar="H",
        help="Stop after H hours (default: 0 = unlimited)",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=3,
        metavar="C",
        help="Number of parallel DOI fetches (default: 3)",
    )
    parser.add_argument(
        "--expand",
        action="store_true",
        default=True,
        dest="expand",
        help="Enable auto-expansion via expander modules (default)",
    )
    parser.add_argument(
        "--no-expand",
        action="store_false",
        dest="expand",
        help="Disable auto-expansion",
    )
    parser.add_argument(
        "--expand-interval",
        type=int,
        default=50,
        metavar="N",
        help="Run expanders every N completed DOIs (default: 50)",
    )
    parser.add_argument(
        "--tiers",
        type=str,
        default="1,2,3",
        metavar="TIERS",
        help='Comma-separated tiers to load, e.g. "1,2,3" (default: "1,2,3")',
    )
    parser.add_argument(
        "--fast",
        action="store_true",
        default=False,
        help="Fast mode: skip Phase 3 (follow links), Phase 4 (analyses), Phase 5 (discrepancy report)",
    )
    parser.add_argument(
        "--skip-sources",
        type=str,
        default="",
        metavar="SRC",
        help='Comma-separated sources to skip, e.g. "zenodo,dryad,openaire"',
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Load seeds, show queue stats, do not fetch",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Show current queue.db stats and exit",
    )
    parser.add_argument(
        "--results-dir",
        type=str,
        default=str(DEFAULT_RESULTS_DIR),
        metavar="DIR",
        help=f"Where to write JSON results (default: {DEFAULT_RESULTS_DIR})",
    )

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        logger.info("Interrupted by user, shutting down gracefully...")
        # Reset any in_progress back to pending so they are retried on next run
        try:
            stale = _reset_stale_in_progress()
            if stale:
                logger.info("Reset %d in-progress DOIs back to pending", stale)
        except Exception:
            pass
        sys.exit(130)


if __name__ == "__main__":
    main()
