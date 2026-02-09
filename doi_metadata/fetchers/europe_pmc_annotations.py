"""Europe PMC Annotations fetcher — text-mined entities from full text.

This fetcher uses the Europe PMC Annotations API to extract text-mined
entities from full-text articles: diseases, gene/protein mentions,
organisms, chemicals, GO terms, and accession numbers.

Requires a PMCID (e.g. "PMC7116644") — call after crosswalk identifies it.

API docs: https://europepmc.org/AnnotationsApi
"""

from __future__ import annotations

import logging
from typing import Any

from doi_metadata.fetchers.base import fetch_json
from doi_metadata.models import (
    SourceName,
    SourceResult,
    TextMinedAnnotation,
)

logger = logging.getLogger(__name__)
SOURCE = SourceName.EUROPE_PMC_ANNOTATIONS


def _parse_annotation(ann: dict[str, Any]) -> TextMinedAnnotation:
    """Parse a single annotation from the Annotations API response."""
    tags = []
    for tag in ann.get("tags", []):
        tag_entry: dict[str, str] = {}
        if tag.get("name"):
            tag_entry["name"] = tag["name"]
        if tag.get("uri"):
            tag_entry["uri"] = tag["uri"]
        if tag_entry:
            tags.append(tag_entry)

    return TextMinedAnnotation(
        annotation_type=ann.get("type", "unknown"),
        exact_text=ann.get("exact"),
        prefix=ann.get("prefix"),
        postfix=ann.get("postfix"),
        section=ann.get("section"),
        tags=tags,
        provider=ann.get("provider"),
        source=SOURCE,
    )


async def fetch_europe_pmc_annotations(pmcid: str) -> SourceResult:
    """Fetch text-mined annotations for a given PMCID.

    Args:
        pmcid: PubMed Central ID, e.g. "PMC7116644".
              The "PMC" prefix is required.

    Returns:
        SourceResult with annotations populated.
    """
    result = SourceResult(source=SOURCE, doi="")

    if not pmcid:
        return result

    # Normalize: ensure PMC prefix
    if not pmcid.upper().startswith("PMC"):
        pmcid = f"PMC{pmcid}"

    try:
        data = await fetch_json(
            "https://www.ebi.ac.uk/europepmc/annotations_api/annotationsByArticleIds",
            params={
                "articleIds": f"PMC:{pmcid.replace('PMC', '')}",
                "format": "JSON",
            },
            source_name="EuropePMC-Annotations",
        )
    except Exception as exc:
        result.error = str(exc)
        return result

    if not data:
        return result

    # Response is a list of article annotation sets
    if not isinstance(data, list) or not data:
        # Try treating it as a dict with results
        if isinstance(data, dict):
            data = [data]
        else:
            return result

    result.found = True
    result.raw = {"pmcid": pmcid, "annotations": data}

    # Parse annotations from the first (and usually only) article result
    for article_result in data:
        annotations_list = article_result.get("annotations", [])
        for ann in annotations_list:
            result.annotations.append(_parse_annotation(ann))

    if result.annotations:
        logger.info(
            "EuropePMC-Annotations: found %d annotations for %s",
            len(result.annotations),
            pmcid,
        )

    return result
