# DOIphin 🐬

**DOI Metadata Aggregator**

Given a DOI, query 14 scholarly APIs in parallel (12 Phase 1 + 2 Phase 3), normalize the results, detect cross-source conflicts, and return unified metadata with derived analyses.

**Sources:** CrossRef, DataCite, OpenAlex, Semantic Scholar, Unpaywall, Europe PMC, OpenAIRE, NIH Reporter, Zenodo, Dryad, ORCID, Entrez/PubMed + Phase 3: Europe PMC Annotations, ClinicalTrials.gov

## Quick Start

**Requirements:** Python 3.11+

```bash
# Clone and install
git clone https://github.com/Kaimen-Inc/doi-metadata.git
cd doi-metadata
pip install -e ".[dev]"

# Configure API credentials
cp .env.example .env
# Edit .env with your email/keys (see Configuration below)

# CLI lookup
doi-metadata lookup 10.1038/sdata.2016.18
doi-metadata lookup 10.1038/nature11247 --format json --include-raw

# Start REST API
uvicorn doi_metadata.api:app --host 0.0.0.0 --port 8000

# Query the API
curl http://localhost:8000/v1/lookup/10.1038/sdata.2016.18
```

## Configuration

Copy `.env.example` to `.env` and fill in at minimum the three email fields — most APIs work without keys but require an email for polite/authenticated access:

```bash
# Required (email-based, no signup needed)
CROSSREF_EMAIL=your@email.com
UNPAYWALL_EMAIL=your@email.com
OPENALEX_EMAIL=your@email.com
```

Optional keys for higher rate limits or additional data:

| Variable | Where to get it | Why |
|---|---|---|
| `OPENALEX_API_KEY` | [openalex.org/settings/api](https://openalex.org/settings/api) | Required after Feb 13, 2026 |
| `SEMANTIC_SCHOLAR_API_KEY` | [semanticscholar.org/product/api](https://www.semanticscholar.org/product/api) | Dedicated 1 req/s pool |
| `OPENAIRE_API_KEY` | [aai.openaire.eu](https://aai.openaire.eu) | Higher rate limits |
| `ORCID_CLIENT_ID` / `ORCID_CLIENT_SECRET` | [orcid.org/developer-tools](https://orcid.org/developer-tools) | Author disambiguation |
| `ENTREZ_EMAIL` | Recommended for NCBI E-utilities | NCBI contact email |
| `ENTREZ_API_KEY` | [ncbi.nlm.nih.gov/account](https://www.ncbi.nlm.nih.gov/account/) | 10 req/s with key, 3 req/s without |

All other APIs (DataCite, Europe PMC, NIH Reporter, Zenodo, Dryad, ClinicalTrials.gov) are fully public and need no credentials.

## Usage

### CLI

```bash
# Human-readable summary
doi-metadata lookup 10.1038/nature11247

# Full JSON output
doi-metadata lookup 10.1038/nature11247 --format json

# Include raw API responses from each source
doi-metadata lookup 10.1038/nature11247 --format json --include-raw

# Skip link-following phase (faster, less data)
doi-metadata lookup 10.5061/dryad.8sf3tx0h5 --no-follow

# Debug logging
doi-metadata lookup 10.1038/nature11247 --verbose
```

### REST API

```bash
# Start the server
doi-metadata-api
# or: uvicorn doi_metadata.api:app --host 0.0.0.0 --port 8000

# Query
curl http://localhost:8000/v1/lookup/10.1038/s41586-023-06647-8

# Interactive docs
open http://localhost:8000/docs
```

### Python Library

```python
import asyncio
from doi_metadata import lookup

result = asyncio.run(lookup("10.1038/s41586-023-06647-8"))

# Per-source data
for name, src in result.sources.items():
    if src.found:
        print(f"{name}: {src.citation_count} citations, {len(src.authors)} authors")

# Identifier crosswalk (PMID, PMCID, ORCIDs, etc.)
print(result.crosswalk.pmid, result.crosswalk.pmcid)

# Derived analyses
print(result.analyses.impact)    # citation counts, FWCI, percentiles
print(result.analyses.funding)   # merged funding from all sources
print(result.analyses.oa_audit)  # cross-source OA verification
print(result.analyses.authors)   # disambiguated author network
print(result.analyses.topics)    # unified subject mapping

# Conflicts between sources
for c in result.conflicts.conflicts:
    print(f"{c.field}: {c.values}")
```

## How It Works

```
DOI (input)
 |
 +--> Phase 1: Fetch all 12 APIs in parallel
 |    CrossRef, DataCite, OpenAlex, Semantic Scholar, Unpaywall,
 |    Europe PMC, OpenAIRE, NIH Reporter, Zenodo, Dryad, ORCID,
 |    Entrez/PubMed
 |    (404s are expected -- not every DOI exists in every source)
 |
 +--> Phase 2: Build identifier crosswalk
 |    Harvest PMID, PMCID, arXiv, ORCIDs, ROR IDs, grant numbers, NCT IDs
 |
 +--> Phase 3: Follow discovered links
 |    DataCite reverse search for linked datasets
 |    Europe PMC Annotations (text-mined genes, diseases, organisms via PMCID)
 |    ClinicalTrials.gov (trial details via NCT IDs from CrossRef)
 |
 +--> Phase 4: Reconcile + Analyze
      Detect conflicts, run 7 derived analyses
```

When sources disagree (e.g., citation counts), all values are preserved with provenance rather than picking a winner.

### 14 Data Sources

| Source | Unique Value |
|--------|-------------|
| CrossRef | References, funders, clinical trials, Crossmark corrections |
| DataCite | Dataset version chains, geolocations, related identifiers |
| OpenAlex | FWCI, concept hierarchy, citation percentiles, institutional data |
| Semantic Scholar | Citation intents, TLDR summaries, influential citation flags |
| Unpaywall | OA status per location, version tracking (published/accepted/submitted) |
| Europe PMC | MeSH headings, chemicals, text-mined accessions, grants |
| OpenAIRE | EU project linkages, BIP! impact indicators, FOS/SDG classifications |
| NIH Reporter | NIH grant-publication linkages, relative citation ratio |
| Zenodo | Files with checksums, download stats, version chains, communities |
| Dryad | Dataset methods, usage notes, ROR-linked affiliations |
| ORCID | Author disambiguation, employment/education history |
| Entrez/PubMed | Authoritative PMID, publication types, gene symbols, databank accessions |
| Europe PMC Annotations | Text-mined gene/protein, disease, organism, chemical entities (Phase 3) |
| ClinicalTrials.gov | Full trial protocol, sponsor, enrollment, outcomes (Phase 3) |

### 7 Derived Analyses

Each lookup produces these cross-source analyses:

- **Impact Profile** -- FWCI, citation trends, influential citation ratio
- **Funding Landscape** -- Merged funders from CrossRef + Europe PMC + OpenAIRE + NIH + Zenodo + Entrez
- **Dataset Reuse** -- DataCite reverse search, related software/data counts
- **Author Network** -- ORCID coverage, institutional breakdown, country distribution
- **Grant Siblings** -- Other publications under the same NIH grants
- **OA Audit** -- Cross-check OA status across Unpaywall, OpenAlex, OpenAIRE, Europe PMC
- **Topic Profile** -- Fields of study, MeSH terms, SDG mappings, keywords

## API

### `GET /v1/lookup/{doi}`

Full metadata lookup. Returns unified JSON with all source results, crosswalk, conflicts, linked datasets, and analyses.

**Query params:**
- `include_raw=true` -- Include raw API responses per source
- `follow_links=false` -- Skip Phase 3 link following

**Example response structure:**
```json
{
  "doi": "10.1038/sdata.2016.18",
  "registration_agency": "crossref",
  "sources": {
    "crossref": {"found": true, "title": "...", "citation_count": 12733, "...": "..."},
    "openalex": {"found": true, "citation_count": 16440, "...": "..."},
    "openaire": {"found": true, "citation_count": 12213, "...": "..."}
  },
  "crosswalk": {
    "doi": "10.1038/sdata.2016.18",
    "pmid": "26978244",
    "pmcid": "PMC4792175",
    "orcids": ["0000-0001-6960-357x", "..."]
  },
  "conflicts": {
    "conflict_count": 6,
    "conflicts": [
      {"field": "citation_count", "risk": "high",
       "values": {"crossref": 12733, "openalex": 16440, "semantic_scholar": 14131}}
    ]
  },
  "datacite_linked_datasets": ["..."],
  "analyses": {
    "impact": {"fwci": 319.42, "citation_comparison": {"...": "..."}},
    "funding": {"total_funders": 5, "funding_agencies": ["..."]},
    "oa_audit": {"consensus_status": "gold", "consensus_is_oa": true}
  }
}
```

### `GET /health`

Health check. Returns `{"status": "ok"}`.

## Test Results

We tested with 9 DOIs spanning data papers, consortium papers, datasets, software, preprints, and regular research articles. See [tests/api_results/analysis.md](tests/api_results/analysis.md) for the full report.

| Paper | Type | Sources Found | Conflicts | Linked Datasets |
|-------|------|---------------|-----------|-----------------|
| FAIR Principles | Edge case | 8/11 | 6 | 25 |
| ENCODE (Nature) | Consortium | 8/11 | 7 | 25 |
| pandas (Zenodo) | Software | 4/10 | 3 | 25 |
| MIMIC-CXR | Data paper | 8/11 | 6 | 7 |
| AlphaFold | Methods | 7/10 | 5 | 25 |
| UK Biobank | Resource | 8/11 | 5 | 25 |

Key findings:
- CrossRef articles consistently hit 7-8 sources
- Citation counts diverge 30-170% across sources (OpenAlex highest, Europe PMC lowest)
- DataCite DOIs get sparser coverage (1-4 sources)

Per-paper reports: [tests/api_results/](tests/api_results/)

## Project Structure

```
doi_metadata/
├── api.py              # FastAPI REST API
├── cli.py              # Typer CLI
├── client.py           # Python client
├── config.py           # Settings from .env
├── models.py           # Pydantic models (50+ types)
├── orchestrator.py     # 4-phase pipeline
├── resolver.py         # DOI registration agency detection
├── crosswalk.py        # Identifier crosswalk builder
├── output.py           # Output formatters
├── fetchers/           # 14 API fetchers (12 Phase 1 + 2 Phase 3)
│   ├── base.py         # Shared HTTP client with retry/backoff
│   ├── crossref.py
│   ├── datacite.py
│   ├── openalex.py
│   ├── semantic_scholar.py
│   ├── unpaywall.py
│   ├── europe_pmc.py
│   ├── europe_pmc_annotations.py
│   ├── openaire.py
│   ├── nih_reporter.py
│   ├── zenodo.py
│   ├── dryad.py
│   ├── orcid.py
│   ├── entrez.py
│   └── clinical_trials.py
├── reconciliation/     # Cross-source conflict detection
│   └── engine.py
└── analyses/           # 7 derived analysis modules
    ├── impact_profile.py
    ├── funding_landscape.py
    ├── dataset_reuse.py
    ├── author_network.py
    ├── grant_siblings.py
    ├── oa_audit.py
    └── topic_profile.py
```

## Development

```bash
pip install -e ".[dev]"
pytest
ruff check .
mypy doi_metadata/
```

## Documentation

- [docs/api-reference.md](docs/api-reference.md) — full JSON schemas for all 14 APIs
- [docs/source-connections.md](docs/source-connections.md) — how sources connect and where they conflict

## Design Principles

- **Never pick a winner** -- When sources disagree, surface all values with provenance. Let the consumer decide.
- **404 is not an error** -- Not every DOI exists in every source. A DataCite 404 for a CrossRef article is expected.
- **Parallel everything** -- All 12 Phase 1 API calls run concurrently via `asyncio.gather`.
- **Schema-first** -- 50+ Pydantic models ensure type safety and serialization.

## License

See [LICENSE](LICENSE) for details.
