# DOI Metadata Aggregator

## Project Purpose

Given a DOI, retrieve, reconcile, and unify metadata from every relevant scholarly infrastructure source — exposing agreements, conflicts, and gaps across providers.

## Architecture

```
DOI (input)
 │
 ├─► Resolver Layer        Classify DOI (article vs dataset vs preprint vs software)
 │                         via DOI prefix → registration agency (CrossRef / DataCite)
 │
 ├─► Fetcher Layer         Parallel async calls to all relevant APIs
 │   ├── crossref.py       Journal articles, references, funders, licenses
 │   ├── datacite.py       Datasets, software, versioning, relatedIdentifiers
 │   ├── openalex.py       Merged scholarly graph, concepts, institutions, citations
 │   ├── semantic_scholar.py  Citation intents, influential citations, TLDR
 │   ├── unpaywall.py      Open access status and best OA location
 │   ├── europe_pmc.py     Full-text mined entities, grants, citation counts
 │   ├── nih_reporter.py   NIH grant → publication linkages
 │   ├── zenodo.py         Repository files, communities, version chains
 │   ├── dryad.py          Dataset files, related works, usage stats
 │   ├── orcid.py          Author disambiguation, affiliation history
 │   └── dimensions.py     Patents, clinical trials, policy documents (optional, key required)
 │
 ├─► Normalization Layer   Map each source's schema → unified internal model
 │
 ├─► Reconciliation Layer  Detect and report conflicts across sources
 │   ├── citations         Compare citation counts (OpenAlex vs S2 vs CrossRef vs Dimensions)
 │   ├── authors           Match author lists across sources (name variants, ORCID linking)
 │   ├── references        Union/intersect of cited-by and references graphs
 │   ├── oa_status          Cross-check Unpaywall vs OpenAlex vs Europe PMC
 │   └── related_works     Merge DataCite relatedIdentifier, CrossRef references, OpenAlex concepts
 │
 └─► Output Layer          Unified JSON, per-source raw responses, conflict report
```

## Tech Stack

- **Language:** Python 3.11+
- **HTTP:** `httpx` with async support for parallel API calls
- **CLI:** `click` or `typer` for command-line interface
- **Data models:** `pydantic` for validation and serialization
- **Testing:** `pytest` with `pytest-asyncio`, VCR cassettes for API replay
- **Packaging:** `pyproject.toml` (PEP 621)

## Key Design Decisions

### DOI Classification
DOI prefixes map to registration agencies. Use the DOI Foundation's `doi.org/api/handles/` or `registration-agency` endpoint to determine if a DOI is CrossRef (typically articles) or DataCite (typically datasets/software). This determines which fetchers are primary vs supplementary.

### Conflict Handling
Do NOT silently pick a "winner" when sources disagree. Instead, preserve all values with provenance:
```python
{
  "citation_count": {
    "openalex": 142,
    "semantic_scholar": 138,
    "crossref": 127,
    "europe_pmc": 145,
    "consensus": null,  # let the consumer decide
    "retrieved_at": "2025-01-15T10:30:00Z"
  }
}
```

### Version Chains (Zenodo/DataCite)
Zenodo uses "concept DOIs" (parent) → version DOIs (children). DataCite's `relatedIdentifier` with `relationType=IsVersionOf` encodes this. Always resolve the full version chain and indicate which version the user queried.

### Rate Limiting & Politeness
- All APIs have rate limits. Use `httpx` with retry + exponential backoff.
- OpenAlex: polite pool requires `mailto` parameter.
- Semantic Scholar: 100 req/5min without key, higher with key.
- Unpaywall: requires email in query param.
- Store API keys in environment variables, never in code.

## Data Source Details

### Free, No Key Required
| Source | Endpoint Pattern | Returns |
|---|---|---|
| CrossRef | `api.crossref.org/works/{doi}` | Full article metadata, references, funders |
| DataCite | `api.datacite.org/dois/{doi}` | Dataset/software metadata, related identifiers |
| OpenAlex | `api.openalex.org/works/doi:{doi}` | Merged record, concepts, institutions, cited_by_count |
| Semantic Scholar | `api.semanticscholar.org/graph/v1/paper/DOI:{doi}` | Citations, references, TLDR, citation intents |
| Unpaywall | `api.unpaywall.org/v2/{doi}?email=` | OA status, best OA URL |
| Europe PMC | `www.ebi.ac.uk/europepmc/webservices/rest/search?query=DOI:{doi}` | PMC metadata, grants, full-text links |
| Zenodo | `zenodo.org/api/records?q=doi:{doi}` | Files, communities, version info |
| Dryad | `datadryad.org/api/v2/datasets/doi:{doi}` | Dataset files, related works |

### Key Required (Optional)
| Source | Notes |
|---|---|
| NIH Reporter | `api.reporter.nih.gov/v2/publications/search` — search by DOI |
| Dimensions | Requires API key; provides patents, clinical trials, policy docs |
| ORCID | Public API free; member API for richer data |

## Project Layout

```
doi_metadata/
├── __init__.py
├── cli.py              # CLI entry point
├── resolver.py         # DOI classification (CrossRef vs DataCite vs unknown)
├── models.py           # Pydantic models for unified metadata
├── fetchers/
│   ├── __init__.py
│   ├── base.py         # Abstract fetcher with retry/rate-limit logic
│   ├── crossref.py
│   ├── datacite.py
│   ├── openalex.py
│   ├── semantic_scholar.py
│   ├── unpaywall.py
│   ├── europe_pmc.py
│   ├── nih_reporter.py
│   ├── zenodo.py
│   ├── dryad.py
│   └── orcid.py
├── reconciliation/
│   ├── __init__.py
│   ├── citations.py    # Compare citation counts across sources
│   ├── authors.py      # Author name matching and ORCID linking
│   ├── references.py   # Union/intersect reference graphs
│   └── oa_status.py    # Cross-check OA information
├── output.py           # Formatters (JSON, summary, conflict report)
└── config.py           # API keys, timeouts, polite-pool emails
tests/
├── conftest.py
├── cassettes/          # VCR cassettes for API response replay
├── test_resolver.py
├── test_fetchers/
├── test_reconciliation/
└── test_output.py
pyproject.toml
```

## Development Commands

```bash
# Install in dev mode
pip install -e ".[dev]"

# Run tests
pytest

# Run linter
ruff check .

# Type check
mypy doi_metadata/

# Run CLI
doi-metadata lookup 10.5061/dryad.8sf3tx0h5
doi-metadata lookup 10.1038/s41586-023-06647-8 --format json --include-raw
```

## Example Workflow

1. User provides DOI: `10.5061/dryad.8sf3tx0h5`
2. Resolver hits `doi.org` → determines this is a DataCite DOI (Dryad dataset)
3. Fetchers fire in parallel: DataCite (primary), Dryad, OpenAlex, Semantic Scholar, Europe PMC, CrossRef (may 404 — that's fine)
4. Normalization maps each response to unified model
5. Reconciliation compares overlapping fields, flags conflicts
6. Output renders unified record + conflict report

## Non-Goals (for now)

- Building a persistent database or search index
- Web UI (CLI-first)
- Batch processing thousands of DOIs (optimize for single-DOI deep lookup first)
- Resolving which citation count is "correct" — surface all, let user decide
