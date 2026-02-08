"""Fetcher modules — one per data source."""

from doi_metadata.fetchers.crossref import fetch_crossref
from doi_metadata.fetchers.datacite import fetch_datacite
from doi_metadata.fetchers.dryad import fetch_dryad
from doi_metadata.fetchers.entrez import fetch_entrez
from doi_metadata.fetchers.europe_pmc import fetch_europe_pmc
from doi_metadata.fetchers.nih_reporter import fetch_nih_reporter
from doi_metadata.fetchers.openaire import fetch_openaire
from doi_metadata.fetchers.openalex import fetch_openalex
from doi_metadata.fetchers.orcid import fetch_orcid
from doi_metadata.fetchers.semantic_scholar import fetch_semantic_scholar
from doi_metadata.fetchers.unpaywall import fetch_unpaywall
from doi_metadata.fetchers.zenodo import fetch_zenodo

ALL_FETCHERS = [
    fetch_crossref,
    fetch_datacite,
    fetch_openalex,
    fetch_semantic_scholar,
    fetch_unpaywall,
    fetch_europe_pmc,
    fetch_openaire,
    fetch_nih_reporter,
    fetch_zenodo,
    fetch_dryad,
    fetch_orcid,
    fetch_entrez,
]

__all__ = [
    "ALL_FETCHERS",
    "fetch_crossref",
    "fetch_datacite",
    "fetch_openalex",
    "fetch_semantic_scholar",
    "fetch_unpaywall",
    "fetch_europe_pmc",
    "fetch_openaire",
    "fetch_nih_reporter",
    "fetch_zenodo",
    "fetch_dryad",
    "fetch_orcid",
    "fetch_entrez",
]
