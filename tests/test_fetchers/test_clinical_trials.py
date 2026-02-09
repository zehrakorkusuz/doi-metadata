"""Tests for ClinicalTrials.gov fetcher."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from doi_metadata.fetchers.clinical_trials import (
    _parse_study,
    fetch_clinical_trial,
    fetch_clinical_trials,
)
from doi_metadata.models import SourceName

# --- Sample ClinicalTrials.gov v2 API response ---

SAMPLE_STUDY = {
    "protocolSection": {
        "identificationModule": {
            "nctId": "NCT02793414",
            "briefTitle": "Study of Drug X in Advanced Cancer",
            "officialTitle": "A Phase 3, Randomized Study of Drug X vs Placebo in Advanced Cancer",
        },
        "statusModule": {
            "overallStatus": "COMPLETED",
            "startDateStruct": {"date": "2016-06-01"},
            "completionDateStruct": {"date": "2020-12-31"},
            "primaryCompletionDateStruct": {"date": "2020-06-30"},
        },
        "descriptionModule": {
            "briefSummary": "This study evaluates Drug X in patients with advanced cancer.",
        },
        "designModule": {
            "studyType": "INTERVENTIONAL",
            "phases": ["PHASE3"],
            "enrollmentInfo": {"count": 500},
        },
        "conditionsModule": {
            "conditions": ["Advanced Cancer", "Solid Tumors"],
        },
        "armsInterventionsModule": {
            "interventions": [
                {"type": "DRUG", "name": "Drug X", "description": "Experimental drug"},
                {"type": "DRUG", "name": "Placebo", "description": "Placebo comparator"},
            ],
        },
        "sponsorCollaboratorsModule": {
            "leadSponsor": {"name": "Pharma Corp"},
            "collaborators": [
                {"name": "National Cancer Institute"},
                {"name": "University Hospital"},
            ],
        },
        "outcomesModule": {
            "primaryOutcomes": [
                {"measure": "Overall Survival", "timeFrame": "From randomization to death, up to 5 years"},
            ],
            "secondaryOutcomes": [
                {"measure": "Progression Free Survival", "timeFrame": "Up to 3 years"},
            ],
        },
        "eligibilityModule": {
            "maximumAge": "75 Years",
        },
    }
}


# --- Unit tests for _parse_study ---


def test_parse_study_full():
    trial = _parse_study(SAMPLE_STUDY)
    assert trial.nct_id == "NCT02793414"
    assert trial.title == "A Phase 3, Randomized Study of Drug X vs Placebo in Advanced Cancer"
    assert trial.brief_summary == "This study evaluates Drug X in patients with advanced cancer."
    assert trial.overall_status == "COMPLETED"
    assert trial.phase == "PHASE3"
    assert trial.study_type == "INTERVENTIONAL"
    assert trial.conditions == ["Advanced Cancer", "Solid Tumors"]
    assert len(trial.interventions) == 2
    assert trial.interventions[0]["name"] == "Drug X"
    assert trial.interventions[0]["type"] == "DRUG"
    assert trial.sponsor == "Pharma Corp"
    assert trial.collaborators == ["National Cancer Institute", "University Hospital"]
    assert trial.enrollment == 500
    assert trial.start_date == "2016-06-01"
    assert trial.completion_date == "2020-12-31"
    assert len(trial.primary_outcomes) == 1
    assert trial.primary_outcomes[0]["measure"] == "Overall Survival"
    assert len(trial.secondary_outcomes) == 1


def test_parse_study_minimal():
    minimal = {
        "protocolSection": {
            "identificationModule": {"nctId": "NCT00000001"},
            "statusModule": {},
            "designModule": {},
            "descriptionModule": {},
            "conditionsModule": {},
            "armsInterventionsModule": {},
            "sponsorCollaboratorsModule": {},
            "outcomesModule": {},
            "eligibilityModule": {},
        }
    }
    trial = _parse_study(minimal)
    assert trial.nct_id == "NCT00000001"
    assert trial.title is None
    assert trial.conditions == []
    assert trial.interventions == []
    assert trial.phase is None


def test_parse_study_falls_back_to_brief_title():
    study = {
        "protocolSection": {
            "identificationModule": {
                "nctId": "NCT12345678",
                "briefTitle": "Brief Title Only",
            },
            "statusModule": {},
            "designModule": {},
            "descriptionModule": {},
            "conditionsModule": {},
            "armsInterventionsModule": {},
            "sponsorCollaboratorsModule": {},
            "outcomesModule": {},
            "eligibilityModule": {},
        }
    }
    trial = _parse_study(study)
    assert trial.title == "Brief Title Only"


# --- Integration tests for fetch_clinical_trial ---


@pytest.mark.asyncio
async def test_fetch_clinical_trial_success():
    with patch(
        "doi_metadata.fetchers.clinical_trials.fetch_json",
        new_callable=AsyncMock,
        return_value=SAMPLE_STUDY,
    ):
        trial = await fetch_clinical_trial("NCT02793414")
        assert trial is not None
        assert trial.nct_id == "NCT02793414"
        assert trial.overall_status == "COMPLETED"


@pytest.mark.asyncio
async def test_fetch_clinical_trial_not_found():
    with patch(
        "doi_metadata.fetchers.clinical_trials.fetch_json",
        new_callable=AsyncMock,
        return_value=None,
    ):
        trial = await fetch_clinical_trial("NCT99999999")
        assert trial is None


@pytest.mark.asyncio
async def test_fetch_clinical_trial_error():
    with patch(
        "doi_metadata.fetchers.clinical_trials.fetch_json",
        new_callable=AsyncMock,
        side_effect=Exception("API error"),
    ):
        trial = await fetch_clinical_trial("NCT02793414")
        assert trial is None


# --- Integration tests for fetch_clinical_trials (batch) ---


@pytest.mark.asyncio
async def test_fetch_clinical_trials_empty_list():
    result = await fetch_clinical_trials([])
    assert not result.found
    assert result.clinical_trials == []
    assert result.source == SourceName.CLINICAL_TRIALS


@pytest.mark.asyncio
async def test_fetch_clinical_trials_success():
    with patch(
        "doi_metadata.fetchers.clinical_trials.fetch_json",
        new_callable=AsyncMock,
        return_value=SAMPLE_STUDY,
    ):
        result = await fetch_clinical_trials(["NCT02793414"])
        assert result.found
        assert len(result.clinical_trials) == 1
        assert result.clinical_trials[0].nct_id == "NCT02793414"
        assert result.nct_ids == ["NCT02793414"]


@pytest.mark.asyncio
async def test_fetch_clinical_trials_multiple():
    study2 = {
        "protocolSection": {
            "identificationModule": {"nctId": "NCT11111111", "briefTitle": "Another Trial"},
            "statusModule": {"overallStatus": "RECRUITING"},
            "designModule": {"studyType": "OBSERVATIONAL"},
            "descriptionModule": {},
            "conditionsModule": {"conditions": ["Diabetes"]},
            "armsInterventionsModule": {},
            "sponsorCollaboratorsModule": {},
            "outcomesModule": {},
            "eligibilityModule": {},
        }
    }

    call_count = 0

    async def mock_fetch(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if "NCT02793414" in args[0]:
            return SAMPLE_STUDY
        return study2

    with patch(
        "doi_metadata.fetchers.clinical_trials.fetch_json",
        new_callable=AsyncMock,
        side_effect=mock_fetch,
    ):
        result = await fetch_clinical_trials(["NCT02793414", "NCT11111111"])
        assert result.found
        assert len(result.clinical_trials) == 2


@pytest.mark.asyncio
async def test_fetch_clinical_trials_partial_failure():
    """One NCT ID found, one not — still returns found=True."""

    async def mock_fetch(*args, **kwargs):
        if "NCT02793414" in args[0]:
            return SAMPLE_STUDY
        return None

    with patch(
        "doi_metadata.fetchers.clinical_trials.fetch_json",
        new_callable=AsyncMock,
        side_effect=mock_fetch,
    ):
        result = await fetch_clinical_trials(["NCT02793414", "NCT99999999"])
        assert result.found
        assert len(result.clinical_trials) == 1
