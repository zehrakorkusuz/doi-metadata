# API Test Results Analysis

**Date:** 2026-02-08  
**Endpoint:** `GET /v1/lookup/{doi}`  
**Papers tested:** 9  

## Summary Table

| Paper | Category | Agency | Sources | Zen | OAI | Unp | Conflicts | Datasets |
|-------|----------|--------|---------|-----|-----|-----|-----------|----------|
| [FAIR Guiding Principles](fair_principles.md) | Edge case | crossref | 8/11 | - | Y | Y | 6 | 25 |
| [ENCODE Consortium](encode.md) | Consortium/Nature | crossref | 8/11 | - | Y | Y | 7 | 25 |
| [pandas (Zenodo)](pandas_zenodo.md) | Software/Zenodo | datacite | 4/10 | Y | - | - | 3 | 25 |
| [MIMIC-CXR](mimic_cxr.md) | Data paper/Sci Data | crossref | 8/11 | - | Y | Y | 6 | 7 |
| [Dryad Dataset](dryad_dataset.md) | Dataset/Dryad | datacite | 1/11 | - | - | - | 0 | 0 |
| [AlphaFold](alphafold.md) | Methods/Nature | crossref | 7/10 | - | - | Y | 5 | 25 |
| [arXiv Preprint](arxiv_preprint.md) | Preprint/DataCite | datacite | 2/11 | - | - | - | 0 | 1 |
| [GigaScience](gigascience.md) | Data paper/GigaSci | crossref | 7/10 | - | - | Y | 6 | 1 |
| [UK Biobank](uk_biobank.md) | Resource/Nature | crossref | 8/11 | - | Y | Y | 5 | 25 |

## Key Findings

### Source Coverage

- **CrossRef articles** (7 DOIs): Consistently hit 7-8/11 sources (CrossRef, OpenAlex, Semantic Scholar, Europe PMC, NIH Reporter, ORCID, Unpaywall, OpenAIRE)
- **DataCite DOIs** (Zenodo, Dryad, arXiv): Much sparser — 1-4 sources. DataCite and the native repository (Zenodo) are the primary sources
- **Zenodo**: Now works via direct record ID lookup (InvenioRDM migration fixed)
- **OpenAIRE**: Now works via `pid=` param for exact DOI match (was doing full-text search)
- **Unpaywall**: Works for all CrossRef DOIs after configuring email

### Citation Count Divergence

Citation counts across sources diverge significantly:

- **FAIR Guiding Principles**: 6,148–16,440 (167% spread)
- **ENCODE Consortium**: 13,957–18,811 (35% spread)
- **pandas (Zenodo)**: 44–1,668 (3691% spread)
- **MIMIC-CXR**: 536–1,693 (216% spread)
- **AlphaFold**: 29,132–41,472 (42% spread)
- **GigaScience**: 3–6 (100% spread)
- **UK Biobank**: 6,979–9,125 (31% spread)

OpenAlex consistently reports the highest counts; Europe PMC the lowest.

### Source Availability by Registration Agency

| Source | CrossRef DOIs (7) | DataCite DOIs (2) |
|--------|-------------------|-------------------|
| crossref | 6/7 | 0/2 |
| datacite | 0/7 | 2/2 |
| europe_pmc | 6/7 | 0/2 |
| nih_reporter | 6/7 | 3/2 |
| openaire | 4/7 | 0/2 |
| openalex | 6/7 | 1/2 |
| orcid | 6/7 | 0/2 |
| semantic_scholar | 6/7 | 0/2 |
| unpaywall | 6/7 | 0/2 |
| zenodo | 0/7 | 1/2 |

### Bugs Fixed During Testing

1. **`AnalysesResult.keys()`** (orchestrator.py:88): Pydantic model doesn't have `.keys()` — changed to `.model_fields.keys()`
2. **Zenodo search API** (fetchers/zenodo.py): InvenioRDM migration broke `q=doi:"..."` search. Fixed to use direct `/api/records/{id}` for Zenodo DOIs
3. **OpenAIRE search vs pid** (fetchers/openaire.py): `search=` param did full-text search returning irrelevant results. Fixed to use `pid=` for exact DOI match
4. **OpenAIRE expired JWT** (fetchers/openaire.py): Expired Bearer token caused 403. Added fallback to retry without auth
5. **OpenAIRE v2 schema changes** (fetchers/openaire.py): `funder` is now a string (was dict), `subjects` nested under `subject` key, author PIDs nested under `pid.id`

### Remaining Gaps

- **Dryad dataset** (`10.5061/dryad.8sf3tx0h5`): Only 1/11 sources found. Neither Dryad's own API nor DataCite returned data — may be an access/encoding issue
- **arXiv preprint** (`10.48550/arXiv.1803.09010`): Only 2/11 sources — DataCite and NIH Reporter. Semantic Scholar didn't find it (may need different query format)
- **Zenodo search for non-Zenodo DOIs**: The `pids.doi.identifier` query returns 0 hits — only direct record lookup works
- **OpenAIRE for DataCite DOIs**: Not finding Zenodo or arXiv records via `pid=` param

## Per-Paper Reports

- [FAIR Guiding Principles](fair_principles.md) — `10.1038/sdata.2016.18`
- [ENCODE Consortium](encode.md) — `10.1038/nature11247`
- [pandas (Zenodo)](pandas_zenodo.md) — `10.5281/zenodo.3509134`
- [MIMIC-CXR](mimic_cxr.md) — `10.1038/s41597-019-0322-0`
- [Dryad Dataset](dryad_dataset.md) — `10.5061/dryad.8sf3tx0h5`
- [AlphaFold](alphafold.md) — `10.1038/s41586-021-03819-2`
- [arXiv Preprint](arxiv_preprint.md) — `10.48550/arXiv.1803.09010`
- [GigaScience](gigascience.md) — `10.1093/gigascience/giac044`
- [UK Biobank](uk_biobank.md) — `10.1038/s41586-018-0579-z`
