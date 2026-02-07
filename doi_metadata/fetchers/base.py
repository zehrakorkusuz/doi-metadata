"""Shared HTTP client with retry, backoff, and rate-limit handling."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from doi_metadata.config import settings

logger = logging.getLogger(__name__)

# Shared client — created once, reused across fetchers
_client: httpx.AsyncClient | None = None


async def get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            timeout=httpx.Timeout(settings.http_timeout),
            headers={"User-Agent": settings.user_agent},
            follow_redirects=True,
        )
    return _client


async def close_client() -> None:
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
        _client = None


async def fetch_json(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    params: dict[str, str] | None = None,
    json_body: dict[str, Any] | None = None,
    max_retries: int | None = None,
    source_name: str = "",
) -> dict[str, Any] | None:
    """Fetch JSON with retry + exponential backoff. Returns None on 404/not-found."""
    retries = max_retries if max_retries is not None else settings.http_max_retries
    client = await get_client()

    for attempt in range(retries + 1):
        try:
            if method == "POST":
                resp = await client.post(url, headers=headers, params=params, json=json_body)
            else:
                resp = await client.get(url, headers=headers, params=params)

            if resp.status_code == 404:
                logger.debug("%s: 404 for %s — expected for some DOI types", source_name, url)
                return None

            if resp.status_code == 429:
                retry_after = float(resp.headers.get("Retry-After", 2 ** (attempt + 1)))
                logger.warning("%s: rate-limited, waiting %.1fs", source_name, retry_after)
                await asyncio.sleep(retry_after)
                continue

            if resp.status_code >= 500:
                wait = 2 ** (attempt + 1)
                logger.warning("%s: server error %d, retrying in %ds", source_name, resp.status_code, wait)
                await asyncio.sleep(wait)
                continue

            resp.raise_for_status()
            return resp.json()

        except httpx.HTTPStatusError as exc:
            logger.warning("%s: HTTP %d for %s", source_name, exc.response.status_code, url)
            raise
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            if attempt < retries:
                wait = 2 ** (attempt + 1)
                logger.warning("%s: %s, retrying in %ds", source_name, exc, wait)
                await asyncio.sleep(wait)
            else:
                logger.error("%s: failed after %d retries: %s", source_name, retries, exc)
                raise

    return None
