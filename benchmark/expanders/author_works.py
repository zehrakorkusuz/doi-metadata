"""Expander: discover all publications by Tier 3 researchers via OpenAlex.

For each researcher whose ``expanded`` flag is 0, we look up their
OpenAlex author ID by ORCID, then page through all of their works and
enqueue every DOI as Tier 5.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import httpx

logger = logging.getLogger("benchmark.expanders.author_works")

OPENALEX_AUTHORS_URL = "https://api.openalex.org/authors/orcid:{orcid}"
OPENALEX_WORKS_URL = "https://api.openalex.org/works"
PER_PAGE = 200


def _get_openalex_email() -> str:
    try:
        from doi_metadata.config import settings
        return settings.openalex_email or ""
    except Exception:
        return ""


async def expand_author_works(db_path: Path) -> int:
    """For each un-expanded researcher, fetch all their DOIs via OpenAlex.

    Returns total number of new DOIs enqueued across all researchers.
    """
    conn = sqlite3.connect(db_path)
    total_enqueued = 0

    try:
        rows = conn.execute(
            "SELECT orcid, name FROM researchers WHERE expanded = 0 AND orcid != ''"
        ).fetchall()

        if not rows:
            logger.debug("author_works: no un-expanded researchers")
            return 0

        email = _get_openalex_email()

        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            for orcid, name in rows:
                enqueued = await _expand_single_author(conn, client, orcid, name, email)
                total_enqueued += enqueued

        # Update expander_state
        _update_state(conn)
        return total_enqueued

    finally:
        conn.close()


async def _expand_single_author(
    conn: sqlite3.Connection,
    client: httpx.AsyncClient,
    orcid: str,
    name: str,
    email: str,
) -> int:
    """Resolve one researcher and enqueue their works.  Returns count of new DOIs."""
    logger.info("author_works: expanding %s (ORCID %s)", name, orcid)

    # Step 1: resolve ORCID -> OpenAlex author ID
    author_url = OPENALEX_AUTHORS_URL.format(orcid=orcid)
    params: dict[str, str] = {}
    if email:
        params["mailto"] = email

    try:
        resp = await client.get(author_url, params=params)
    except httpx.HTTPError as exc:
        logger.warning("author_works: failed to resolve ORCID %s: %s", orcid, exc)
        return 0

    if resp.status_code != 200:
        logger.warning("author_works: OpenAlex returned %d for ORCID %s", resp.status_code, orcid)
        return 0

    author_data = resp.json()
    openalex_id: str = author_data.get("id", "")
    if not openalex_id:
        logger.warning("author_works: no OpenAlex ID for ORCID %s", orcid)
        return 0

    # Store the openalex_id
    conn.execute(
        "UPDATE researchers SET openalex_id = ? WHERE orcid = ?",
        (openalex_id, orcid),
    )
    conn.commit()

    # Step 2: page through all works
    # OpenAlex author IDs look like https://openalex.org/A1234567890
    enqueued = 0
    page = 1

    while True:
        works_params: dict[str, str] = {
            "filter": f"authorships.author.id:{openalex_id}",
            "per_page": str(PER_PAGE),
            "page": str(page),
            "select": "doi",
        }
        if email:
            works_params["mailto"] = email

        try:
            resp = await client.get(OPENALEX_WORKS_URL, params=works_params)
        except httpx.HTTPError as exc:
            logger.warning("author_works: works request failed for %s page %d: %s", name, page, exc)
            break

        if resp.status_code != 200:
            logger.warning("author_works: works returned %d for %s page %d", resp.status_code, name, page)
            break

        data = resp.json()
        results = data.get("results", [])
        if not results:
            break

        for work in results:
            doi_url: str = work.get("doi", "") or ""
            if not doi_url:
                continue
            doi = doi_url.replace("https://doi.org/", "").replace("http://doi.org/", "")
            if not doi:
                continue

            try:
                cursor = conn.execute(
                    """INSERT OR IGNORE INTO doi_queue
                       (doi, tier, category, priority, status, source_expander, created_at)
                       VALUES (?, 5, 'author_works', 9, 'pending', 'author_works', datetime('now'))""",
                    (doi.lower(),),
                )
                if cursor.rowcount > 0:
                    enqueued += 1
            except sqlite3.IntegrityError:
                pass

        conn.commit()

        # If we got fewer than PER_PAGE results, this was the last page
        if len(results) < PER_PAGE:
            break
        page += 1

        # Safety: cap at 50 pages (10 000 works per author)
        if page > 50:
            logger.info("author_works: reached page limit for %s", name)
            break

    # Mark researcher as expanded
    conn.execute("UPDATE researchers SET expanded = 1 WHERE orcid = ?", (orcid,))
    conn.commit()

    logger.info("author_works: enqueued works for %s (%s)", name, openalex_id)
    return enqueued


def _update_state(conn: sqlite3.Connection) -> None:
    """Update the expander_state table."""
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT INTO expander_state (expander_name, last_run)
           VALUES ('author_works', ?)
           ON CONFLICT(expander_name) DO UPDATE SET last_run = excluded.last_run""",
        (now,),
    )
    conn.commit()
