# DOI Metadata Aggregator

Given a DOI, fetch and reconcile metadata from 11 scholarly APIs in parallel — exposing agreements, conflicts, and gaps across providers.

**Sources:** CrossRef, DataCite, OpenAlex, Semantic Scholar, Unpaywall, Europe PMC, OpenAIRE, NIH Reporter, Zenodo, Dryad, ORCID

## Quick Start

**Requirements:** Python 3.11+

```bash
# Clone and install
git clone https://github.com/zehrakorkusuz/doi-metadata.git
cd doi-metadata
pip install -e ".[dev]"

# Configure API credentials
cp .env.example .env
# Edit .env with your email/keys (see Configuration below)

# Look up a DOI
doi-metadata lookup 10.1038/s41586-023-06647-8
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

All other APIs (DataCite, Europe PMC, NIH Reporter, Zenodo, Dryad) are fully public and need no credentials.

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

1. **Classify DOI** — determine registration agency (CrossRef vs DataCite)
2. **Fetch** — query all 11 APIs in parallel (404s from irrelevant sources are expected)
3. **Crosswalk** — harvest PMID, PMCID, arXiv, ORCIDs, ROR IDs, grant numbers from all responses
4. **Follow links** — DataCite reverse search for citing datasets, NIH grant siblings, version chains
5. **Analyze** — run 7 derived analyses (impact, funding, OA, authors, grants, dataset reuse, topics)
6. **Output** — unified record with per-source provenance and conflict report

When sources disagree (e.g., citation counts), all values are preserved with provenance rather than picking a winner.

## Development

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Lint
ruff check .

# Type check
mypy doi_metadata/
```

## Project Structure

```
doi_metadata/
  cli.py              CLI entry point (typer)
  api.py              REST API (FastAPI)
  orchestrator.py     Pipeline coordination
  resolver.py         DOI classification
  models.py           Pydantic data models
  crosswalk.py        Identifier linking
  config.py           Settings from .env
  output.py           JSON and summary formatters
  fetchers/           One module per API source (11 total)
  reconciliation/     Cross-source conflict detection
  analyses/           7 derived analysis modules
```

## Documentation

- [docs/api-reference.md](docs/api-reference.md) — full JSON schemas for all 11 APIs
- [docs/source-connections.md](docs/source-connections.md) — how sources connect and where they conflict

## License

See [LICENSE](LICENSE) for details.
