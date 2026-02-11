"""Fetch citation neighbourhood from OpenAlex for DataRank 1-hop expansion.

For a seed paper we need:
1. Its OpenAlex ID (to query citers)
2. The list of papers that cite it, with enough metadata to compute E(q)

We use OpenAlex filters and the select parameter to keep responses small and fast.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from doi_metadata.config import settings

logger = logging.getLogger(__name__)

# Lightweight fields needed for citer endowment estimation
_CITER_SELECT = ",".join([
    "id", "doi", "type", "publication_year",
    "referenced_works_count", "cited_by_count",
    "open_access", "datasets",
])

# Max citers to fetch per paper (OpenAlex cursor paging)
MAX_CITERS = 500

# Polite delay between requests (seconds)
_POLITE_DELAY = 0.12  # ~8 req/s, well within polite pool


async def _openalex_get(
    client: httpx.AsyncClient,
    url: str,
    params: dict[str, str] | None = None,
) -> dict[str, Any] | None:
    """GET with retry for OpenAlex."""
    params = dict(params or {})
    if settings.openalex_api_key:
        params["api_key"] = settings.openalex_api_key
    elif settings.openalex_email:
        params["mailto"] = settings.openalex_email

    for attempt in range(3):
        try:
            resp = await client.get(url, params=params)
            if resp.status_code == 404:
                return None
            if resp.status_code == 429:
                wait = float(resp.headers.get("Retry-After", 2 ** (attempt + 1)))
                logger.debug("OpenAlex rate-limited, waiting %.1fs", wait)
                await asyncio.sleep(wait)
                continue
            if resp.status_code >= 500:
                await asyncio.sleep(2 ** (attempt + 1))
                continue
            resp.raise_for_status()
            return resp.json()
        except (httpx.TimeoutException, httpx.ConnectError):
            if attempt < 2:
                await asyncio.sleep(2 ** (attempt + 1))
            else:
                return None
    return None


async def resolve_openalex_id(
    client: httpx.AsyncClient,
    doi: str,
) -> str | None:
    """Resolve a DOI to its OpenAlex Work ID (e.g. 'W2100837269')."""
    data = await _openalex_get(
        client,
        f"https://api.openalex.org/works/doi:{doi}",
        params={"select": "id"},
    )
    if data and data.get("id"):
        # "https://openalex.org/W2100837269" -> "W2100837269"
        oa_id = data["id"]
        return oa_id.split("/")[-1] if "/" in oa_id else oa_id
    return None


async def fetch_citers(
    client: httpx.AsyncClient,
    openalex_id: str,
    max_citers: int = MAX_CITERS,
) -> list[dict]:
    """Fetch papers that cite the given OpenAlex work.

    Returns a list of lightweight work dicts with fields from _CITER_SELECT.
    Uses cursor paging to get up to *max_citers* results.
    """
    citers: list[dict] = []
    cursor = "*"
    base_url = "https://api.openalex.org/works"

    while len(citers) < max_citers:
        per_page = min(200, max_citers - len(citers))
        params = {
            "filter": f"cites:{openalex_id}",
            "select": _CITER_SELECT,
            "per_page": str(per_page),
            "cursor": cursor,
        }
        data = await _openalex_get(client, base_url, params=params)
        await asyncio.sleep(_POLITE_DELAY)

        if not data:
            break

        results = data.get("results", [])
        if not results:
            break

        citers.extend(results)

        # Advance cursor
        meta = data.get("meta", {})
        next_cursor = meta.get("next_cursor")
        if not next_cursor or next_cursor == cursor:
            break
        cursor = next_cursor

    return citers[:max_citers]


def citer_endowment_estimate(citer: dict) -> float:
    """Estimate a lightweight endowment for a citer work from OpenAlex fields.

    We don't have the full 14-source data for citers, so we use what OpenAlex
    gives us: work type, open access status, and dataset relations.
    """
    import math

    score = 0.0

    # Is this citer itself a dataset?
    if citer.get("type") == "dataset":
        score += 3.0

    # Is it open access?
    oa = citer.get("open_access", {})
    if isinstance(oa, dict) and oa.get("is_oa"):
        score += 1.0

    # Does it have dataset relations? (OpenAlex 'datasets' field)
    datasets = citer.get("datasets") or []
    if datasets:
        score += 5.0 * math.log1p(len(datasets))

    return score


async def fetch_citer_neighbourhood(
    doi: str,
    max_citers: int = MAX_CITERS,
    timeout: float = 30.0,
) -> tuple[list[dict], str | None]:
    """Fetch the 1-hop citer neighbourhood for a DOI.

    Returns (list_of_citer_dicts, openalex_id).
    Creates and closes its own HTTP client.
    """
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(timeout),
        headers={"User-Agent": "doi-metadata-sindex/1.0 (DataRank computation)"},
        follow_redirects=True,
    ) as client:
        oa_id = await resolve_openalex_id(client, doi)
        if not oa_id:
            logger.debug("Could not resolve OpenAlex ID for %s", doi)
            return [], None

        await asyncio.sleep(_POLITE_DELAY)
        citers = await fetch_citers(client, oa_id, max_citers=max_citers)
        logger.debug("Fetched %d citers for %s (%s)", len(citers), doi, oa_id)
        return citers, oa_id
