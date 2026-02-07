"""FastAPI server — REST API for DOI metadata aggregation.

Usage:
    # Start server
    uvicorn doi_metadata.api:app --host 0.0.0.0 --port 8000

    # Or via CLI entry point
    doi-metadata-api

    # Query
    curl http://localhost:8000/v1/lookup/10.1038/s41586-023-06647-8
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse

from doi_metadata.models import AggregatedResult

logger = logging.getLogger(__name__)

app = FastAPI(
    title="DOI Metadata Aggregator",
    description=(
        "Given a DOI, query 11 scholarly APIs in parallel, normalize, reconcile conflicts, "
        "and return unified metadata with derived analyses."
    ),
    version="0.1.0",
)


@app.get("/health")
async def health() -> dict[str, str]:
    """Health check."""
    return {"status": "ok"}


@app.get(
    "/v1/lookup/{doi:path}",
    response_model=AggregatedResult,
    response_model_exclude_none=True,
    summary="Look up metadata for a DOI",
    description=(
        "Fetches metadata from 11 scholarly APIs (CrossRef, DataCite, OpenAlex, "
        "Semantic Scholar, Unpaywall, Europe PMC, OpenAIRE, NIH Reporter, Zenodo, "
        "Dryad, ORCID), builds identifier crosswalk, detects conflicts, and runs "
        "7 derived analyses (impact, funding, dataset reuse, authors, grant siblings, "
        "OA audit, topics)."
    ),
)
async def lookup_doi(
    doi: str,
    include_raw: Annotated[bool, Query(description="Include raw API responses per source")] = False,
    follow_links: Annotated[bool, Query(description="Follow discovered links (Phase 3)")] = True,
) -> AggregatedResult:
    """Full DOI metadata lookup across all sources."""
    from doi_metadata.orchestrator import lookup

    result = await lookup(doi, include_raw=include_raw, follow_links=follow_links)
    return result


@app.exception_handler(Exception)
async def global_exception_handler(request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error: %s", exc)
    return JSONResponse(
        status_code=500,
        content={"detail": str(exc)},
    )


def main() -> None:
    """Entry point for `doi-metadata-api` CLI command."""
    import uvicorn

    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)-8s %(name)s: %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    uvicorn.run(
        "doi_metadata.api:app",
        host="0.0.0.0",
        port=8000,
        log_level="info",
    )


if __name__ == "__main__":
    main()
