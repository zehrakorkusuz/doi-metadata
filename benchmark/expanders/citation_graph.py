"""Expander: extract referenced DOIs from completed results and enqueue them.

To keep the queue from exploding, only references from Tier 1-3 results
are followed.  A ``citation_graph_processed`` table tracks which parent
DOIs have already been mined so work is not repeated across runs.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("benchmark.expanders.citation_graph")


def _ensure_processed_table(conn: sqlite3.Connection) -> None:
    """Create the tracking table on first use."""
    conn.execute(
        """CREATE TABLE IF NOT EXISTS citation_graph_processed (
               doi TEXT PRIMARY KEY,
               processed_at TEXT DEFAULT (datetime('now'))
           )"""
    )
    conn.commit()


async def expand_citation_graph(db_path: Path, results_dir: Path) -> int:
    """Extract reference DOIs from completed Tier 1-3 results and enqueue.

    Returns the number of new DOIs enqueued.
    """
    conn = sqlite3.connect(db_path)
    total_enqueued = 0

    try:
        _ensure_processed_table(conn)

        # Find completed Tier 1-3 results that have not been citation-graph processed
        rows = conn.execute(
            """SELECT dq.doi, dq.result_path
               FROM doi_queue dq
               LEFT JOIN citation_graph_processed cgp ON dq.doi = cgp.doi
               WHERE dq.status = 'done'
                 AND dq.result_path IS NOT NULL
                 AND dq.tier <= 3
                 AND cgp.doi IS NULL
               LIMIT 100"""
        ).fetchall()

        if not rows:
            logger.debug("citation_graph: no unprocessed Tier 1-3 results")
            return 0

        logger.info("citation_graph: processing %d completed results", len(rows))

        for parent_doi, result_path_str in rows:
            if not result_path_str:
                continue

            result_path = Path(result_path_str)
            if not result_path.exists():
                logger.debug("citation_graph: result file missing for %s", parent_doi)
                # Mark as processed anyway so we don't retry
                conn.execute(
                    "INSERT OR IGNORE INTO citation_graph_processed (doi) VALUES (?)",
                    (parent_doi,),
                )
                continue

            try:
                data = json.loads(result_path.read_text())
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("citation_graph: failed to read %s: %s", result_path, exc)
                conn.execute(
                    "INSERT OR IGNORE INTO citation_graph_processed (doi) VALUES (?)",
                    (parent_doi,),
                )
                continue

            # Extract reference DOIs from all sources
            ref_dois = _extract_reference_dois(data)
            new_count = 0

            for ref_doi in ref_dois:
                try:
                    cursor = conn.execute(
                        """INSERT OR IGNORE INTO doi_queue
                           (doi, tier, category, priority, status, source_doi, source_expander, created_at)
                           VALUES (?, 4, 'citation_graph', 9, 'pending', ?, 'citation_graph', datetime('now'))""",
                        (ref_doi.lower(), parent_doi),
                    )
                    if cursor.rowcount > 0:
                        new_count += 1
                except sqlite3.IntegrityError:
                    pass

            # Mark parent as processed
            conn.execute(
                "INSERT OR IGNORE INTO citation_graph_processed (doi) VALUES (?)",
                (parent_doi,),
            )
            conn.commit()

            if new_count > 0:
                logger.debug("citation_graph: %d new DOIs from %s", new_count, parent_doi)
            total_enqueued += new_count

        # Update expander_state
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """INSERT INTO expander_state (expander_name, last_run)
               VALUES ('citation_graph', ?)
               ON CONFLICT(expander_name) DO UPDATE SET last_run = excluded.last_run""",
            (now,),
        )
        conn.commit()

        logger.info("citation_graph: enqueued %d new DOIs from %d parents", total_enqueued, len(rows))
        return total_enqueued

    finally:
        conn.close()


def _extract_reference_dois(data: dict) -> set[str]:
    """Pull DOIs from references across all sources in a result JSON."""
    dois: set[str] = set()

    sources: dict = data.get("sources", {})
    for _source_name, source_data in sources.items():
        if not isinstance(source_data, dict):
            continue

        # References list
        for ref in source_data.get("references", []):
            if isinstance(ref, dict):
                ref_doi = ref.get("doi")
                if ref_doi and isinstance(ref_doi, str) and ref_doi.strip():
                    dois.add(_normalize_doi(ref_doi))

        # Citations list (inbound -- these are papers citing the parent)
        for cit in source_data.get("citations", []):
            if isinstance(cit, dict):
                cit_doi = cit.get("doi")
                if cit_doi and isinstance(cit_doi, str) and cit_doi.strip():
                    dois.add(_normalize_doi(cit_doi))

        # Related works (DataCite, Dryad, Zenodo, OpenAIRE)
        for rw in source_data.get("related_works", []):
            if isinstance(rw, dict):
                rw_id = rw.get("identifier", "")
                rw_type = rw.get("identifier_type", "")
                if rw_type.upper() == "DOI" and rw_id:
                    dois.add(_normalize_doi(rw_id))

    return dois


def _normalize_doi(doi: str) -> str:
    """Strip URL prefixes and lowercase."""
    doi = doi.strip()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if doi.lower().startswith(prefix.lower()):
            doi = doi[len(prefix):]
            break
    return doi.lower()
