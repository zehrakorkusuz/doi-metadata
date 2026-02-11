"""Expander: discover top-cited papers via OpenAlex and enqueue them.

Pages through OpenAlex works sorted by citation count descending,
filtering for articles with >1000 citations.  Each invocation fetches
the *next* page (tracked in ``expander_state``) so the corpus grows
monotonically across pipeline restarts.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import httpx

logger = logging.getLogger("benchmark.expanders.top_cited")

OPENALEX_WORKS_URL = "https://api.openalex.org/works"
PER_PAGE = 200


def _get_openalex_email() -> str:
    """Best-effort import of the configured polite-pool email."""
    try:
        from doi_metadata.config import settings
        return settings.openalex_email or ""
    except Exception:
        return ""


def _read_state(conn: sqlite3.Connection) -> tuple[int, dict]:
    """Return (last_page, extra) from expander_state."""
    row = conn.execute(
        "SELECT last_page, extra_json FROM expander_state WHERE expander_name = 'top_cited'"
    ).fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO expander_state (expander_name, last_page, extra_json) VALUES ('top_cited', 0, '{}')"
        )
        conn.commit()
        return 0, {}
    extra = json.loads(row[1]) if row[1] else {}
    return row[0], extra


def _write_state(conn: sqlite3.Connection, page: int, extra: dict) -> None:
    conn.execute(
        "UPDATE expander_state SET last_page = ?, last_run = ?, extra_json = ? WHERE expander_name = 'top_cited'",
        (page, datetime.now(timezone.utc).isoformat(), json.dumps(extra)),
    )
    conn.commit()


async def expand_top_cited(db_path: Path, batch_size: int = 200) -> int:
    """Fetch the next page of top-cited papers from OpenAlex and enqueue.

    Returns the number of *new* DOIs enqueued (INSERT OR IGNORE means
    duplicates are silently skipped).
    """
    conn = sqlite3.connect(db_path)
    try:
        last_page, extra = _read_state(conn)
        next_page = last_page + 1

        # OpenAlex caps cursor-based pagination at page 10000/per_page.
        # For safety, stop at page 50 (10 000 DOIs).
        if next_page > 50:
            logger.info("top_cited: reached page limit (50), skipping")
            return 0

        email = _get_openalex_email()
        params: dict[str, str] = {
            "filter": "cited_by_count:>1000,type:article",
            "sort": "cited_by_count:desc",
            "per_page": str(batch_size),
            "page": str(next_page),
        }
        if email:
            params["mailto"] = email

        logger.info("top_cited: fetching page %d from OpenAlex (per_page=%d)", next_page, batch_size)

        enqueued = 0
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            resp = await client.get(OPENALEX_WORKS_URL, params=params)
            if resp.status_code != 200:
                logger.warning("top_cited: OpenAlex returned %d", resp.status_code)
                return 0

            data = resp.json()
            results = data.get("results", [])
            if not results:
                logger.info("top_cited: no more results on page %d", next_page)
                return 0

            for work in results:
                doi_url: str = work.get("doi", "") or ""
                if not doi_url:
                    continue
                # OpenAlex returns DOIs as full URLs: https://doi.org/10.xxx
                doi = doi_url.replace("https://doi.org/", "").replace("http://doi.org/", "")
                if not doi:
                    continue

                # Extract a category from primary_topic
                primary_topic = work.get("primary_topic") or {}
                category = (primary_topic.get("subfield", {}) or {}).get("display_name", "top_cited")

                try:
                    cursor = conn.execute(
                        """INSERT OR IGNORE INTO doi_queue
                           (doi, tier, category, priority, status, source_expander, created_at)
                           VALUES (?, 4, ?, 8, 'pending', 'top_cited', datetime('now'))""",
                        (doi.lower(), category),
                    )
                    if cursor.rowcount > 0:
                        enqueued += 1
                except sqlite3.IntegrityError:
                    pass  # already in queue

            conn.commit()

        _write_state(conn, next_page, extra)
        logger.info("top_cited: enqueued %d new DOIs from page %d (%d results)", enqueued, next_page, len(results))
        return enqueued

    finally:
        conn.close()
