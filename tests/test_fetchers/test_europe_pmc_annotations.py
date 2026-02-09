"""Tests for Europe PMC Annotations fetcher."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from doi_metadata.fetchers.europe_pmc_annotations import (
    _parse_annotation,
    fetch_europe_pmc_annotations,
)
from doi_metadata.models import SourceName

# --- Unit tests for _parse_annotation ---


def test_parse_annotation_full():
    raw = {
        "type": "Gene_Proteins",
        "exact": "BRCA1",
        "prefix": "mutations in ",
        "postfix": " are linked to",
        "section": "Abstract",
        "tags": [{"name": "BRCA1", "uri": "https://identifiers.org/uniprot:P38398"}],
        "provider": "Europe PMC",
    }
    ann = _parse_annotation(raw)
    assert ann.annotation_type == "Gene_Proteins"
    assert ann.exact_text == "BRCA1"
    assert ann.prefix == "mutations in "
    assert ann.postfix == " are linked to"
    assert ann.section == "Abstract"
    assert len(ann.tags) == 1
    assert ann.tags[0]["name"] == "BRCA1"
    assert ann.provider == "Europe PMC"
    assert ann.source == SourceName.EUROPE_PMC_ANNOTATIONS


def test_parse_annotation_minimal():
    raw = {"type": "Diseases", "exact": "cancer"}
    ann = _parse_annotation(raw)
    assert ann.annotation_type == "Diseases"
    assert ann.exact_text == "cancer"
    assert ann.tags == []
    assert ann.section is None


def test_parse_annotation_unknown_type():
    raw = {}
    ann = _parse_annotation(raw)
    assert ann.annotation_type == "unknown"
    assert ann.exact_text is None


# --- Integration tests for fetch_europe_pmc_annotations ---


@pytest.mark.asyncio
async def test_fetch_annotations_empty_pmcid():
    result = await fetch_europe_pmc_annotations("")
    assert not result.found
    assert result.annotations == []


@pytest.mark.asyncio
async def test_fetch_annotations_not_found():
    with patch(
        "doi_metadata.fetchers.europe_pmc_annotations.fetch_json",
        new_callable=AsyncMock,
        return_value=None,
    ):
        result = await fetch_europe_pmc_annotations("PMC0000000")
        assert not result.found
        assert result.annotations == []


@pytest.mark.asyncio
async def test_fetch_annotations_success():
    mock_response = [
        {
            "source": "PMC",
            "pmcid": "PMC7116644",
            "annotations": [
                {
                    "type": "Gene_Proteins",
                    "exact": "SARS-CoV-2",
                    "section": "Title",
                    "tags": [{"name": "SARS-CoV-2", "uri": "https://identifiers.org/taxonomy:2697049"}],
                    "provider": "Europe PMC",
                },
                {
                    "type": "Diseases",
                    "exact": "COVID-19",
                    "section": "Abstract",
                    "tags": [{"name": "COVID-19", "uri": "https://identifiers.org/EFO:0700003"}],
                    "provider": "Europe PMC",
                },
                {
                    "type": "Organisms",
                    "exact": "human",
                    "section": "Body",
                    "tags": [{"name": "Homo sapiens", "uri": "https://identifiers.org/taxonomy:9606"}],
                    "provider": "Europe PMC",
                },
            ],
        }
    ]
    with patch(
        "doi_metadata.fetchers.europe_pmc_annotations.fetch_json",
        new_callable=AsyncMock,
        return_value=mock_response,
    ):
        result = await fetch_europe_pmc_annotations("PMC7116644")
        assert result.found
        assert len(result.annotations) == 3
        assert result.annotations[0].annotation_type == "Gene_Proteins"
        assert result.annotations[0].exact_text == "SARS-CoV-2"
        assert result.annotations[1].annotation_type == "Diseases"
        assert result.annotations[2].annotation_type == "Organisms"
        assert result.source == SourceName.EUROPE_PMC_ANNOTATIONS


@pytest.mark.asyncio
async def test_fetch_annotations_normalizes_pmcid():
    """Ensure PMCID without PMC prefix gets normalized."""
    mock_response = [{"annotations": [{"type": "Chemicals", "exact": "aspirin"}]}]
    with patch(
        "doi_metadata.fetchers.europe_pmc_annotations.fetch_json",
        new_callable=AsyncMock,
        return_value=mock_response,
    ) as mock_fetch:
        result = await fetch_europe_pmc_annotations("7116644")
        assert result.found
        # Verify the API was called with correct PMC format
        call_params = mock_fetch.call_args[1]["params"]
        assert call_params["articleIds"] == "PMC:7116644"


@pytest.mark.asyncio
async def test_fetch_annotations_error_handling():
    with patch(
        "doi_metadata.fetchers.europe_pmc_annotations.fetch_json",
        new_callable=AsyncMock,
        side_effect=Exception("Connection timeout"),
    ):
        result = await fetch_europe_pmc_annotations("PMC7116644")
        assert not result.found
        assert result.error == "Connection timeout"
