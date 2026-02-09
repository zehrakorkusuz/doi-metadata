# Source Connections: How to Link Data Across APIs

## Philosophy: Fetch Everything First, Connect After

Don't try to be clever about which sources to query. **Hit all 12 APIs in parallel** for the input DOI. Many will return 404/empty — that's fine. Then use the identifiers and relationships discovered across all responses to build the connection graph.

## What Each Source Gives You (Identifier Harvest)

After fetching all sources for a single DOI, you'll have a pool of identifiers to work with:

### Identifiers Returned by Source

```
CrossRef works/{doi}
 ├─ author[].ORCID              → ORCID profiles
 ├─ funder[].DOI                → CrossRef Funder Registry / ROR
 ├─ reference[].DOI             → outbound citation DOIs (sparse)
 ├─ ISSN / issn-type            → journal identity
 ├─ alternative-id              → publisher-assigned IDs
 └─ clinical-trial-number       → clinical trial registries

DataCite dois/{doi}
 ├─ relatedIdentifiers[]        → OTHER DOIs (articles, software, versions)
 │   Types: DOI, URL, arXiv, PMID, Handle, URN
 │   Relations: IsSupplementTo, HasVersion, IsCitedBy, References, ...
 ├─ creators[].nameIdentifiers  → ORCIDs
 ├─ creators[].affiliation[].affiliationIdentifier → ROR IDs
 ├─ fundingReferences[].funderIdentifier → CrossRef Funder / ROR
 └─ relationships.versions/citations/references → pre-resolved DOI lists

OpenAlex works/doi:{doi}
 ├─ ids.pmid                    → PubMed ID
 ├─ ids.pmcid                   → PubMed Central ID
 ├─ ids.openalex                → OpenAlex entity ID
 ├─ ids.mag                     → Microsoft Academic Graph ID (legacy)
 ├─ authorships[].author.orcid  → ORCIDs
 ├─ authorships[].author.id     → OpenAlex author entity (disambiguated)
 ├─ authorships[].institutions[].ror → ROR IDs
 ├─ authorships[].institutions[].id  → OpenAlex institution entity
 ├─ referenced_works[]          → OpenAlex IDs of outgoing citations
 ├─ related_works[]             → conceptually similar (algorithmic)
 ├─ grants[].funder             → OpenAlex funder entity ID
 └─ primary_location.source.id  → OpenAlex source (journal/repo) entity

Semantic Scholar paper/DOI:{doi}
 ├─ externalIds.PubMed          → PMID
 ├─ externalIds.PubMedCentral   → PMC ID
 ├─ externalIds.ArXiv           → arXiv ID
 ├─ externalIds.DBLP            → DBLP key
 ├─ externalIds.MAG             → MAG ID
 ├─ externalIds.CorpusId        → S2 corpus ID
 ├─ authors[].authorId          → S2 author entity (disambiguated)
 ├─ citations[].externalIds     → DOIs of citing papers
 └─ references[].externalIds    → DOIs of referenced papers

Unpaywall v2/{doi}
 ├─ oa_locations[].pmh_id       → OAI-PMH identifier
 ├─ oa_locations[].endpoint_id  → repository identifier
 ├─ z_authors[].ORCID           → ORCIDs (from CrossRef data)
 └─ journal_issn_l              → linking ISSN

Europe PMC search?query=DOI:{doi}
 ├─ pmid                        → PubMed ID
 ├─ pmcid                       → PMC ID (e.g. "PMC7116644")
 ├─ grantsList[].grantId        → grant identifiers → NIH Reporter
 ├─ grantsList[].agency         → funding agency name
 ├─ authorList[].authorId       → {type: "ORCID", value: "0000-..."}
 ├─ chemicalList                → registry numbers
 ├─ tmAccessionTypeList         → text-mined accession types (GenBank, PDB)
 └─ commentCorrectionList       → linked corrections/errata DOIs

OpenAIRE researchProducts?search={doi}
 ├─ pids[]                      → DOI, PMID, arXiv, Handle
 ├─ authors[].pid               → ORCIDs
 ├─ instances[].alternateIdentifiers → additional IDs per repository copy
 ├─ projects[].id               → OpenAIRE project ID
 ├─ projects[].code             → grant number (e.g. "727929")
 ├─ projects[].funder           → {shortName, jurisdiction, fundingStream}
 └─ **alternate_ids[]**         → GOLDMINE: handle, pmc, mag_id, doi, pmid, arXiv

NIH Reporter publications/search
 ├─ pmid                        → PubMed ID
 ├─ pmcId                       → PMC ID
 ├─ coreProjectNum              → NIH grant number → projects endpoint
 ├─ applId                      → NIH application ID
 ├─ authorList[].orcid          → ORCIDs
 └─ publications[].pmid         → sibling PMIDs under same grant

Zenodo records?q=doi:{doi}
 ├─ conceptrecid / conceptdoi   → version-independent identifiers
 ├─ metadata.creators[].orcid   → ORCIDs
 ├─ metadata.related_identifiers[].identifier → linked DOIs
 ├─ metadata.grants[].funder.doi → funder DOIs
 └─ metadata.communities[].id   → community membership

Dryad datasets/doi:{doi}
 ├─ relatedWorks[].identifier   → linked article/software DOIs
 ├─ authors[].orcid             → ORCIDs
 ├─ authors[].affiliationROR    → ROR IDs
 ├─ funders[].identifier        → funder IDs (CrossRef type)
 └─ _links.stash:version/files  → HATEOAS navigation

ORCID expanded-search?q=doi-self:{doi}
 ├─ orcid-id                    → canonical ORCID
 ├─ institution-name[]          → current affiliations
 └─ (follow-up: /works, /employments, /fundings per ORCID)

Entrez/PubMed esearch→efetch pipeline
 ├─ PMID                        → authoritative PubMed ID (highest priority)
 ├─ ArticleIdList[pmc]          → PMC ID
 ├─ ArticleIdList[pii]          → Publisher Item Identifier
 ├─ ArticleIdList[mid]          → Manuscript ID
 ├─ Author[].Identifier[ORCID]  → ORCIDs
 ├─ Investigator[].Identifier[ORCID] → investigator ORCIDs
 ├─ GrantList[].GrantID         → grant identifiers → NIH Reporter
 ├─ MeshHeadingList             → MeSH descriptors with UIDs
 ├─ GeneSymbolList              → HUGO gene symbols
 ├─ DataBankList[].AccessionNumber → GenBank, ClinicalTrials.gov, PDB, GEO
 ├─ CommentsCorrectionsList     → linked errata/retractions (PMIDs)
 ├─ ReferenceList[].ArticleId   → cited PMIDs and DOIs
 ├─ MedlineJournalInfo.NlmUniqueID → NLM catalog ID
 └─ ChemicalList                → substance UIDs and registry numbers
```

## The Identifier Crosswalk

After Phase 1 (all parallel fetches complete), build this crosswalk from whatever came back:

```python
@dataclass
class IdentifierCrosswalk:
    doi: str                          # input
    pmid: str | None = None           # from Entrez, OpenAlex, S2, Europe PMC, NIH, OpenAIRE
    pmcid: str | None = None          # from Entrez, OpenAlex, S2, Europe PMC, NIH, OpenAIRE
    arxiv_id: str | None = None       # from S2, OpenAIRE, DataCite
    mag_id: str | None = None         # from OpenAlex (legacy), OpenAIRE
    openalex_id: str | None = None    # from OpenAlex
    s2_corpus_id: str | None = None   # from S2
    s2_paper_id: str | None = None    # from S2
    concept_doi: str | None = None    # from Zenodo (version-independent)
    concept_recid: str | None = None  # from Zenodo
    handles: list[str] = []           # from OpenAIRE, DataCite
    orcids: set[str] = set()          # union from ALL sources (incl. Entrez investigators)
    ror_ids: set[str] = set()         # from OpenAlex, DataCite, Dryad
    grant_ids: list[GrantId] = []     # from NIH, Europe PMC, OpenAIRE, CrossRef, Zenodo, Dryad, Entrez
    related_dois: list[RelatedDOI] = []  # from DataCite, Dryad, Zenodo, CrossRef refs
    pii: str | None = None            # from Entrez (Publisher Item Identifier)
    nlm_unique_id: str | None = None  # from Entrez (NLM catalog ID)
    registration_agency: str = ""     # "crossref" or "datacite"
```

### Priority Rules for Conflicting IDs

When multiple sources return the same identifier type, prefer:
- **PMID**: Entrez > Europe PMC > OpenAlex > S2 > NIH (Entrez is the authoritative PMID source from NCBI)
- **ORCID**: ORCID API > CrossRef (authenticated) > OpenAlex > DataCite > Entrez (ORCID API is ground truth)
- **DOI**: all sources agree (it's the input)
- **arXiv**: S2 > OpenAIRE (S2 has best arXiv coverage)

In practice, they almost always agree — the priority is for coverage (which source is most likely to have it), not conflict resolution.

## Connection Patterns from Real Data

### Pattern 1: Article DOI → Discover Associated Datasets

**Observed:** ENCODE paper (10.1038/nature11247) → DataCite finds 1,158 linked datasets via reverse lookup

```
Input: article DOI (CrossRef-registered)
 ↓
CrossRef:    Full article metadata (always works for articles)
DataCite:    404 (it's not a DataCite DOI) BUT...
  → DataCite search: query=relatedIdentifiers.relatedIdentifier:{doi}
  → Returns datasets that CITE this article (figshare, Zenodo, etc.)
  → ENCODE: 1158 datasets, TCGA: 327, GTEx: 927
OpenAlex:    Full record with referenced_works (filter for DataCite prefixes)
```

**Key insight:** Even when DataCite returns 404 for the DOI itself, DataCite's **reverse search** finds datasets that reference it. This is the primary way to discover dataset reuse.

### Pattern 2: Dataset DOI → Find the Article It Supports

**Observed:** Dryad dataset → relatedWorks[relationship=IsCitedBy] → article DOI

```
Input: dataset DOI (DataCite-registered)
 ↓
DataCite:    Full metadata + relatedIdentifiers[relationType=IsSupplementTo] → article DOI
Dryad:       relatedWorks[relationship=IsCitedBy] → same article DOI
CrossRef:    404 (it's not a CrossRef DOI)
 ↓
Follow the article DOI through CrossRef, OpenAlex, S2, Europe PMC...
```

### Pattern 3: PMID Bridge (article without explicit dataset link)

**Observed:** NIH Reporter returns PMIDs → these bridge to Europe PMC, OpenAlex, S2

```
Input: article DOI
 ↓
OpenAlex:    ids.pmid = "25164755"
 ↓
NIH Reporter: search by DOI → coreProjectNum = ["U01HG004695", "U54HG004592", ...]
 ↓
For each grant → publications[] gives ALL PMIDs under that grant
 ↓
Each sibling PMID → OpenAlex (to get its DOI) → full metadata
  = "all papers funded by the same grant as the input paper"
```

### Pattern 4: OpenAIRE as Universal Crosswalk

**Observed:** OpenAIRE alternate_ids contains handle, pmc, mag_id, doi, pmid, arXiv — all in one response

```
Input: any DOI
 ↓
OpenAIRE: alternate_ids = [
  "handle:1721.1/87013",        → institutional repository
  "pmc:PMC3439153",             → Europe PMC full text
  "mag_id:2259938310",          → legacy MAG
  "doi:10.1038/nature11247",    → canonical
  "handle:20.500.14038/49900",  → another repository
  "pmid:22955616",              → PubMed
  "handle:10230/23072"          → yet another
]
```

OpenAIRE also uniquely provides:
- `related_software` → GitHub repositories (observed for ENCODE, TOPMed)
- `related_data_openaire` → ENA/repository records (observed for ENCODE, GTEx)
- `funding` with direct links to OpenAIRE project pages

### Pattern 5: Funding Chain (Grant → All Its Papers → Their Datasets)

```
Input: article DOI
 ↓
Europe PMC:  grantsList[].grantId → ["U01HG004695"]
Entrez:      GrantList[].GrantID → ["U01 HG004695"] (with agency + country)
NIH Reporter: search by grant → 46 publications (PMIDs)
OpenAIRE:    projects[].code → "727929" (EU Horizon 2020)
CrossRef:    funder[].DOI → "10.13039/100000001" (NSF)
 ↓
For each grant:
  NIH Reporter → all PMIDs under that grant
  OpenAIRE → all publications under that project
  → For each sibling paper:
     DataCite reverse search → datasets that reference it
     = "all datasets produced under the same funding umbrella"
```

### Pattern 6: Citation Count Divergence (Reconciliation, Not Connection)

**Observed from real data:**
| Paper | OpenAlex | OpenAIRE | Gap |
|-------|----------|----------|-----|
| ENCODE | 18,767 | 15,938 | +18% |
| TCGA | 8,448 | 7,609 | +11% |
| GTEx (main) | 265 | 7,734 | -97% (!!) |
| fastMRI | 569 | 9 | +6222% |

GTEx shows OpenAlex returning 265 while OpenAIRE shows 7,734 — this likely means OpenAlex resolved to a different work (perhaps the pilot paper vs the consortium paper). **Always verify DOI-to-record mapping by checking titles match.**

fastMRI (arXiv preprint) shows OpenAlex at 569 vs OpenAIRE at 9 — arXiv papers have fragmented identity (the arXiv ID, the DataCite DOI `10.48550/arxiv.*`, and possibly a published version DOI).

### Pattern 7: Software Discovery (OpenAIRE unique)

**Observed:** TOPMed paper → OpenAIRE finds 5 related GitHub repositories

```
OpenAIRE related_software:
  - topmed_variant_calling (GitHub)
  - loftee (GitHub)
  - topmed_singleton_clusters (GitHub)
  - fusera (GitHub)
  - UKB_WES_vs_TOPMed_IMP (GitHub)
```

No other source provides this. OpenAIRE harvests GitHub-Zenodo integration and text-mining.

### Pattern 8: Version Chain Resolution

```
Input: Zenodo version DOI (e.g. 10.5281/zenodo.3509134)
 ↓
Zenodo:   conceptdoi = "10.5281/zenodo.3509133" (version-independent)
          metadata.relations.version[0].count = 5 (5 versions exist)
 ↓
DataCite: dois/10.5281/zenodo.3509134
          relatedIdentifiers: [
            {relationType: "IsVersionOf", relatedIdentifier: "10.5281/zenodo.3509133"},
            {relationType: "HasVersion", relatedIdentifier: "10.5281/zenodo.3509135"}
          ]
 ↓
Both sources agree on version chain structure

Input: Dryad DOI (e.g. 10.5061/dryad.8sf3tx0h5)
 ↓
Dryad:    versionNumber = 2, one DOI for all versions
DataCite: relatedIdentifiers with HasVersion pointing to /1, /2 suffixes
 ↓
Dryad uses single-DOI versioning; DataCite exposes the version sub-DOIs
```

## Fetcher Orchestration

### Phase 1: Parallel Fetch Everything
```python
results = await asyncio.gather(
    fetch_crossref(doi),           # 404 ok for dataset DOIs
    fetch_datacite(doi),           # 404 ok for article DOIs
    fetch_openalex(doi),           # almost always has data
    fetch_semantic_scholar(doi),   # almost always has data
    fetch_unpaywall(doi),          # only for articles
    fetch_europe_pmc(doi),         # only if PMID exists (DOI search)
    fetch_openaire(doi),           # broad coverage
    fetch_nih_reporter(doi),       # only US-funded works
    fetch_zenodo(doi),             # only Zenodo DOIs (usually 404)
    fetch_dryad(doi),              # only Dryad DOIs (usually 404)
    fetch_orcid_by_doi(doi),       # author lookup
    fetch_entrez(doi),             # PubMed — authoritative PMID, MeSH, pub types
    return_exceptions=True,        # don't fail on individual errors
)
```

### Phase 2: Build Crosswalk
```python
crosswalk = build_crosswalk(results)
# Merges all identifiers discovered across sources:
# - PMID from Entrez (highest priority) or OpenAlex or S2 or Europe PMC or OpenAIRE
# - PMCID from Entrez ArticleIdList or OpenAlex or Europe PMC
# - ORCIDs from all sources (incl. Entrez author + investigator ORCIDs)
# - Grant IDs from NIH, Europe PMC, OpenAIRE, CrossRef, Entrez
# - Related DOIs from DataCite, Dryad, Zenodo, CrossRef refs
# - OpenAIRE alternate_ids (handles, mag_id, etc.)
# - PII from Entrez (Publisher Item Identifier)
# - NLM Unique ID from Entrez (journal catalog)
```

### Phase 3: Follow Discovered Links (Selective)
```python
# Only if DataCite had relatedIdentifiers pointing to articles
for related in crosswalk.related_dois:
    if related.relation in ("IsSupplementTo", "IsPartOf", "IsCitedBy"):
        # Fetch the linked article from CrossRef + OpenAlex
        ...

# Only if NIH grants were found
for grant in crosswalk.grant_ids:
    if grant.source == "nih_reporter":
        # Get full project details + sibling publications
        project = await fetch_nih_project(grant.number)
        ...

# DataCite reverse search: find datasets that reference this DOI
datacite_reuse = await search_datacite_reverse(doi)
# This is how ENCODE→1158 datasets, TCGA→327, GTEx→927 were found
```

### Phase 4: Reconcile and Output
```python
# Compare overlapping fields, flag divergences
# Output unified record with provenance on every field
```

## DataCite Reverse Search (Dataset Discovery)

This is the key technique for finding datasets associated with an article:

```
GET https://api.datacite.org/dois?query=relatedIdentifiers.relatedIdentifier:{doi}&page[size]=25
```

This returns all DataCite DOIs (datasets, software, figures) that declare a relationship to the input DOI via `relatedIdentifiers`. The relationship types tell you the nature:
- `IsSupplementTo` → dataset supports this article
- `IsCitedBy` → this dataset is cited by the article
- `References` → this dataset references the article
- `IsNewVersionOf` → version chain
- `IsPartOf` → dataset is part of a collection
