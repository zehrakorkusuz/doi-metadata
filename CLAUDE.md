# DOI Metadata Aggregator

## Project Purpose

Given a DOI, retrieve, reconcile, and unify metadata from every relevant scholarly infrastructure source — exposing agreements, conflicts, and gaps across providers.

## Architecture

```
DOI (input)
 │
 ├─► Phase 1: Fetch Everything (parallel, all 11 APIs)
 │   404s are expected and fine — not every DOI exists in every source
 │   ├── crossref.py       Journal articles, references, funders, licenses
 │   ├── datacite.py       Datasets, software, versioning, relatedIdentifiers
 │   ├── openalex.py       Merged scholarly graph, concepts, institutions, citations
 │   ├── semantic_scholar.py  Citation intents, influential citations, TLDR
 │   ├── unpaywall.py      Open access status and best OA location
 │   ├── europe_pmc.py     Full-text mined entities, grants, citation counts
 │   ├── openaire.py       EU funding, BIP! indicators, related software
 │   ├── nih_reporter.py   NIH grant → publication linkages (many-to-many)
 │   ├── zenodo.py         Repository files, communities, version chains
 │   ├── dryad.py          Dataset files, related works, usage stats
 │   └── orcid.py          Author disambiguation, affiliation history
 │
 ├─► Phase 2: Build Identifier Crosswalk
 │   Harvest PMID, PMCID, arXiv, ORCIDs, ROR IDs, grant numbers,
 │   related DOIs, handles from ALL responses. OpenAIRE alternate_ids
 │   is a goldmine (DOI + PMID + PMC + MAG + handles in one field).
 │
 ├─► Phase 3: Follow Discovered Links (selective)
 │   ├── DataCite reverse search: find datasets citing this article
 │   │   (ENCODE→1158 datasets, TCGA→327, GTEx→927)
 │   ├── NIH grant → sibling publications (all papers under same grant)
 │   ├── DataCite relatedIdentifiers → linked articles/software/versions
 │   └── Zenodo conceptdoi → full version chain
 │
 ├─► Normalization Layer   Map each source's schema → unified internal model
 │
 ├─► Reconciliation Layer  Detect and report conflicts across sources
 │   ├── citations         Compare counts (can diverge 100x for arXiv preprints)
 │   ├── authors           Match author lists (ORCID linking, name variants)
 │   ├── references        Union/intersect of cited-by and references graphs
 │   ├── oa_status          Cross-check Unpaywall vs OpenAlex vs OpenAIRE vs Europe PMC
 │   ├── funding           Merge NIH Reporter + Europe PMC + OpenAIRE + CrossRef + Zenodo
 │   └── related_works     Merge DataCite relatedIdentifier, Dryad relatedWorks, OpenAIRE
 │
 └─► Output Layer          Unified JSON, per-source raw responses, conflict report
```

### Documentation

- **[docs/api-reference.md](docs/api-reference.md)** — Full JSON schemas for all 11 APIs
- **[docs/source-connections.md](docs/source-connections.md)** — How sources connect, real-data patterns, identifier crosswalk

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

## Data Sources (11 APIs)

Full response schemas, nested objects, and call examples: **[docs/api-reference.md](docs/api-reference.md)**

| Source | Call Pattern | Auth | Unique Data |
|---|---|---|---|
| CrossRef | `GET api.crossref.org/works/{doi}?mailto=` | None (mailto for polite pool) | Crossmark, corrections, clinical trials, funder registry |
| DataCite | `GET api.datacite.org/dois/{doi}` | None | Version chains, geolocations, resource type taxonomy |
| OpenAlex | `GET api.openalex.org/works/doi:{doi}?mailto=` | **API key required after Feb 13, 2026** | FWCI, concept hierarchy, citation percentiles |
| Semantic Scholar | `GET api.semanticscholar.org/graph/v1/paper/DOI:{doi}?fields=` | x-api-key header (optional) | Citation intents, TLDR, influential citations, SPECTER2 |
| Unpaywall | `GET api.unpaywall.org/v2/{doi}?email=` | Email required | Per-location OA version tracking, DOAJ, evidence |
| Europe PMC | `GET ebi.ac.uk/.../rest/search?query=DOI:{doi}&resultType=core` | None | MeSH headings, chemicals, text-mined accessions, grants |
| OpenAIRE | `GET api.openaire.eu/graph/v2/researchProducts?search={doi}` | Bearer token (optional) | EU project linkages, BIP! indicators, FOS/SDG with trust |
| NIH Reporter | `POST api.reporter.nih.gov/v2/publications/search` | None | NIH award linkages, relative citation ratio |
| Zenodo | `GET zenodo.org/api/records?q=doi:{doi}` | Bearer token (optional) | Files with checksums, download stats, communities |
| Dryad | `GET datadryad.org/api/v2/datasets/doi%3A{encoded_doi}` | None | Methods, usage notes, ROR-linked affiliations |
| ORCID | `GET pub.orcid.org/v3.0/expanded-search?q=doi-self:{doi}` | OAuth2 /read-public | Employment/education history, peer reviews, funding |

### Cross-Source Conflict Points
| Data Point | Sources That Disagree | Risk |
|---|---|---|
| Citation count | CrossRef, OpenAlex, S2, Europe PMC, DataCite, OpenAIRE, NIH | HIGH |
| OA status | Unpaywall, OpenAlex, OpenAIRE, Europe PMC | MEDIUM |
| Author names | CrossRef, DataCite, OpenAlex, S2, Europe PMC, ORCID, Dryad | HIGH |
| Affiliations | CrossRef, OpenAlex, ORCID, Europe PMC, Dryad, NIH | HIGH |
| References | CrossRef, OpenAlex, S2, DataCite | MEDIUM |
| Funding | CrossRef, Europe PMC, OpenAIRE, NIH, Zenodo, Dryad, DataCite | MEDIUM |

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

## Example Workflows

### Article DOI: `10.1038/nature11247` (ENCODE)
1. Phase 1: Hit all 11 APIs in parallel
   - CrossRef: full article metadata, 84 references, funders ✓
   - DataCite: 404 (not a DataCite DOI) — expected
   - OpenAlex: 18,767 citations, concepts, institutions ✓
   - Semantic Scholar: citation intents, TLDR ✓
   - Unpaywall: OA status (bronze) ✓
   - Europe PMC: PMID 22955616, grants, MeSH ✓
   - OpenAIRE: alternate_ids (handles, PMC, MAG), 5 related GitHub repos, EU funding links ✓
   - NIH Reporter: 5 grants (U01HG004695, U54HG004592, ...), each with 20-724 sibling publications ✓
   - Zenodo/Dryad: 404 — expected
   - ORCID: author ORCIDs ✓
2. Phase 2: Build crosswalk — PMID, PMC, MAG, handles, ORCIDs, grant numbers
3. Phase 3: DataCite reverse search → 1,158 linked datasets (figshare, Zenodo)
4. Reconcile: citation counts diverge (OpenAlex 18,767 vs OpenAIRE 15,938)
5. Output: unified record + per-source raw + conflict report

### Dataset DOI: `10.5061/dryad.8sf3tx0h5` (Dryad)
1. Phase 1: Hit all 11 APIs in parallel
   - DataCite: full metadata, relatedIdentifiers (IsSupplementTo → article DOI) ✓
   - Dryad: dataset details, files, relatedWorks, ROR-linked affiliations ✓
   - OpenAlex: merged record ✓
   - CrossRef: 404 — expected
   - Others: varying coverage
2. Phase 2: Follow DataCite `IsSupplementTo` → fetch the linked article
3. Output: dataset record + linked article metadata + version chain

## Non-Goals (for now)

- Building a persistent database or search index
- Web UI (CLI-first)
- Batch processing thousands of DOIs (optimize for single-DOI deep lookup first)
- Resolving which citation count is "correct" — surface all, let user decide
