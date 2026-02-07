"""Python client for the DOI Metadata Aggregator API.

Usage as library (direct, no server needed):

    import asyncio
    from doi_metadata import lookup

    result = asyncio.run(lookup("10.1038/s41586-023-06647-8"))
    print(result.analyses.impact)
    print(result.crosswalk.pmid)

Usage via HTTP client (requires running API server):

    from doi_metadata.client import DOIMetadataClient

    # Synchronous
    client = DOIMetadataClient("http://localhost:8000")
    result = client.lookup("10.1038/s41586-023-06647-8")
    print(result["analyses"]["impact"]["narrative"])

    # Async
    import asyncio
    async def main():
        client = DOIMetadataClient("http://localhost:8000")
        result = await client.alookup("10.1038/s41586-023-06647-8")
        print(result["analyses"]["impact"]["narrative"])
        await client.aclose()
    asyncio.run(main())
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx


class DOIMetadataClient:
    """HTTP client for the DOI Metadata Aggregator REST API.

    Args:
        base_url: Base URL of the running API server (e.g. "http://localhost:8000").
        timeout: Request timeout in seconds. DOI lookups hit 11 APIs so allow plenty of time.
    """

    def __init__(self, base_url: str = "http://localhost:8000", timeout: float = 120.0) -> None:
        self.base_url = base_url.rstrip("/")
        self._sync = httpx.Client(base_url=self.base_url, timeout=timeout)
        self._async = httpx.AsyncClient(base_url=self.base_url, timeout=timeout)

    # ----- synchronous -----

    def lookup(
        self,
        doi: str,
        *,
        include_raw: bool = False,
        follow_links: bool = True,
    ) -> dict[str, Any]:
        """Look up a DOI synchronously. Returns the full aggregated result as a dict."""
        resp = self._sync.get(
            f"/v1/lookup/{quote(doi, safe='')}",
            params=_params(include_raw, follow_links),
        )
        resp.raise_for_status()
        return resp.json()

    def health(self) -> dict[str, str]:
        resp = self._sync.get("/health")
        resp.raise_for_status()
        return resp.json()

    def close(self) -> None:
        self._sync.close()

    # ----- async -----

    async def alookup(
        self,
        doi: str,
        *,
        include_raw: bool = False,
        follow_links: bool = True,
    ) -> dict[str, Any]:
        """Look up a DOI asynchronously. Returns the full aggregated result as a dict."""
        resp = await self._async.get(
            f"/v1/lookup/{quote(doi, safe='')}",
            params=_params(include_raw, follow_links),
        )
        resp.raise_for_status()
        return resp.json()

    async def ahealth(self) -> dict[str, str]:
        resp = await self._async.get("/health")
        resp.raise_for_status()
        return resp.json()

    async def aclose(self) -> None:
        await self._async.aclose()

    # ----- context managers -----

    def __enter__(self) -> DOIMetadataClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    async def __aenter__(self) -> DOIMetadataClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.aclose()


def _params(include_raw: bool, follow_links: bool) -> dict[str, str]:
    p: dict[str, str] = {}
    if include_raw:
        p["include_raw"] = "true"
    if not follow_links:
        p["follow_links"] = "false"
    return p
