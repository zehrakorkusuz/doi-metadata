"""ORCID fetcher — author disambiguation, institution history."""

from __future__ import annotations

import logging

from doi_metadata.fetchers.base import fetch_json
from doi_metadata.models import (
    Author,
    PersonName,
    SourceName,
    SourceResult,
)

logger = logging.getLogger(__name__)
SOURCE = SourceName.ORCID


async def fetch_orcid(doi: str) -> SourceResult:
    result = SourceResult(source=SOURCE, doi=doi)

    headers = {
        "Accept": "application/json",
    }

    try:
        data = await fetch_json(
            "https://pub.orcid.org/v3.0/expanded-search",
            params={"q": f"doi-self:{doi}", "rows": "50"},
            headers=headers,
            source_name="ORCID",
        )
    except Exception as exc:
        result.error = str(exc)
        return result

    if not data:
        return result

    expanded = data.get("expanded-result", [])
    if not expanded:
        return result

    result.found = True
    result.raw = data

    for person in expanded:
        orcid_id = person.get("orcid-id", "")
        institutions = person.get("institution-name", []) or []

        result.authors.append(
            Author(
                name=PersonName(
                    given=person.get("given-names"),
                    family=person.get("family-names"),
                    full_name=person.get("credit-name")
                    or f"{person.get('given-names', '')} {person.get('family-names', '')}".strip(),
                    orcid=orcid_id,
                    source=SOURCE,
                ),
                sources=[SOURCE],
            )
        )

        # Store full ORCID record for later use
        result.orcid_records.append(
            {
                "orcid_id": orcid_id,
                "given_names": person.get("given-names"),
                "family_names": person.get("family-names"),
                "credit_name": person.get("credit-name"),
                "other_names": person.get("other-name", []),
                "institutions": institutions,
                "emails": person.get("email", []),
            }
        )

    return result
