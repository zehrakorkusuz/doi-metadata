"""ClinicalTrials.gov fetcher — clinical trial details by NCT ID.

Links papers to trial registrations using NCT IDs discovered from CrossRef
(clinical-trial-number field) or Europe PMC text-mined accessions.

Uses the ClinicalTrials.gov v2 API (no auth required).

API docs: https://clinicaltrials.gov/data-api/api
"""

from __future__ import annotations

import logging
from typing import Any

from doi_metadata.fetchers.base import fetch_json
from doi_metadata.models import (
    ClinicalTrial,
    SourceName,
    SourceResult,
)

logger = logging.getLogger(__name__)
SOURCE = SourceName.CLINICAL_TRIALS


def _parse_study(study: dict[str, Any]) -> ClinicalTrial:
    """Parse a single study from the ClinicalTrials.gov v2 API response."""
    protocol = study.get("protocolSection", {})
    id_module = protocol.get("identificationModule", {})
    status_module = protocol.get("statusModule", {})
    design_module = protocol.get("designModule", {})
    desc_module = protocol.get("descriptionModule", {})
    conditions_module = protocol.get("conditionsModule", {})
    interventions_module = protocol.get("armsInterventionsModule", {})
    sponsor_module = protocol.get("sponsorCollaboratorsModule", {})
    outcomes_module = protocol.get("outcomesModule", {})
    eligibility_module = protocol.get("eligibilityModule", {})

    # Interventions
    interventions = []
    for interv in interventions_module.get("interventions", []):
        entry: dict[str, str] = {}
        if interv.get("type"):
            entry["type"] = interv["type"]
        if interv.get("name"):
            entry["name"] = interv["name"]
        if interv.get("description"):
            entry["description"] = interv["description"]
        if entry:
            interventions.append(entry)

    # Collaborators
    collaborators = []
    for collab in sponsor_module.get("collaborators", []):
        name = collab.get("name")
        if name:
            collaborators.append(name)

    # Primary outcomes
    primary_outcomes = []
    for outcome in outcomes_module.get("primaryOutcomes", []):
        entry = {}
        if outcome.get("measure"):
            entry["measure"] = outcome["measure"]
        if outcome.get("timeFrame"):
            entry["timeFrame"] = outcome["timeFrame"]
        if entry:
            primary_outcomes.append(entry)

    # Secondary outcomes
    secondary_outcomes = []
    for outcome in outcomes_module.get("secondaryOutcomes", []):
        entry = {}
        if outcome.get("measure"):
            entry["measure"] = outcome["measure"]
        if outcome.get("timeFrame"):
            entry["timeFrame"] = outcome["timeFrame"]
        if entry:
            secondary_outcomes.append(entry)

    # Enrollment
    enrollment = None
    enroll_info = eligibility_module.get("maximumAge") and design_module.get("enrollmentInfo", {})
    if not enroll_info:
        enroll_info = design_module.get("enrollmentInfo", {})
    if enroll_info:
        enrollment = enroll_info.get("count")

    # Dates
    start_date = status_module.get("startDateStruct", {}).get("date")
    completion_date = (
        status_module.get("completionDateStruct", {}).get("date")
        or status_module.get("primaryCompletionDateStruct", {}).get("date")
    )

    # Phase
    phases = design_module.get("phases", [])
    phase = ", ".join(phases) if phases else None

    return ClinicalTrial(
        nct_id=id_module.get("nctId", ""),
        title=id_module.get("officialTitle") or id_module.get("briefTitle"),
        brief_summary=desc_module.get("briefSummary"),
        overall_status=status_module.get("overallStatus"),
        phase=phase,
        study_type=design_module.get("studyType"),
        conditions=conditions_module.get("conditions", []),
        interventions=interventions,
        sponsor=sponsor_module.get("leadSponsor", {}).get("name"),
        collaborators=collaborators,
        enrollment=enrollment,
        start_date=start_date,
        completion_date=completion_date,
        primary_outcomes=primary_outcomes,
        secondary_outcomes=secondary_outcomes,
        source=SOURCE,
    )


async def fetch_clinical_trial(nct_id: str) -> ClinicalTrial | None:
    """Fetch a single clinical trial by NCT ID.

    Args:
        nct_id: ClinicalTrials.gov identifier, e.g. "NCT02793414".

    Returns:
        ClinicalTrial model or None if not found.
    """
    try:
        data = await fetch_json(
            f"https://clinicaltrials.gov/api/v2/studies/{nct_id}",
            source_name="ClinicalTrials.gov",
        )
    except Exception as exc:
        logger.warning("ClinicalTrials.gov: error fetching %s: %s", nct_id, exc)
        return None

    if not data:
        return None

    return _parse_study(data)


async def fetch_clinical_trials(nct_ids: list[str]) -> SourceResult:
    """Fetch clinical trial details for a list of NCT IDs.

    NCT IDs typically come from CrossRef clinical-trial-number field
    or from text-mined accessions in Europe PMC.

    Args:
        nct_ids: List of NCT identifiers.

    Returns:
        SourceResult with clinical_trials and nct_ids populated.
    """
    result = SourceResult(source=SOURCE, doi="")

    if not nct_ids:
        return result

    result.nct_ids = list(nct_ids)

    for nct_id in nct_ids:
        nct_id = nct_id.strip()
        if not nct_id:
            continue

        trial = await fetch_clinical_trial(nct_id)
        if trial:
            result.clinical_trials.append(trial)
            result.found = True

    if result.found:
        logger.info(
            "ClinicalTrials.gov: fetched %d/%d trials",
            len(result.clinical_trials),
            len(nct_ids),
        )

    return result
