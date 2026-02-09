# API Reference: All Data Sources

Complete reference for every API the DOI metadata aggregator calls. Each section covers: how to call it, authentication, rate limits, the full response JSON key hierarchy, and what unique data it provides.

Test DOIs used throughout:
- **Article:** `10.1038/s41586-020-2649-2` (NumPy paper, Nature 2020)
- **Dataset:** `10.5061/dryad.8sf3tx0h5` (Dryad dataset)
- **Zenodo:** `10.5281/zenodo.3509134` (Zenodo record)

---

## 1. CrossRef

### Call Pattern
```
GET https://api.crossref.org/works/{doi}?mailto={email}
```

**Headers:** `User-Agent: DOIMetadataAggregator/1.0 (mailto:{email})`

**Auth:** None. `mailto` param routes to polite pool (better rate limits).

**Rate Limits:** ~50 req/s (polite pool). Headers: `X-Rate-Limit-Limit`, `X-Rate-Limit-Interval`.

**Errors:** 404 for non-CrossRef DOIs (DataCite DOIs). Catch gracefully.

### Response Envelope
```json
{
  "status": "ok",
  "message-type": "work",
  "message-version": "1.0.0",
  "message": { /* work object */ }
}
```

### Work Object — Full Key Hierarchy

#### Always Present
| Key | Type | Example |
|-----|------|---------|
| `DOI` | String | `"10.1038/s41586-020-2649-2"` |
| `URL` | String | `"http://dx.doi.org/10.1038/..."` |
| `title` | [String] | `["Array programming with NumPy"]` |
| `publisher` | String | `"Springer Science and Business Media LLC"` |
| `type` | String | `"journal-article"` |
| `source` | String | `"Crossref"` |
| `prefix` | String | `"10.1038"` |
| `member` | String | `"297"` |
| `references-count` | Number | Count of outbound references |
| `is-referenced-by-count` | Number | Inbound citation count |
| `created` | FullDate | DOI first registered |
| `deposited` | FullDate | Metadata last updated |
| `indexed` | FullDate | Last indexed |
| `issued` | PartialDate | Earliest publication date |
| `content-domain` | Object | `{domain: [], crossmark-restriction: false}` |
| `score` | Number | 0 for direct lookup |

#### Optional
| Key | Type | Notes |
|-----|------|-------|
| `abstract` | String | Often JATS XML |
| `subtitle` | [String] | |
| `container-title` | [String] | Journal name, e.g. `["Nature"]` |
| `short-container-title` | [String] | Abbreviated |
| `volume` | String | |
| `issue` | String | |
| `page` | String | `"357-362"` |
| `article-number` | String | When no page |
| `published-print` | PartialDate | |
| `published-online` | PartialDate | |
| `published` | PartialDate | |
| `language` | String | ISO code |
| `subject` | [String] | ASJC categories |
| `ISSN` | [String] | |
| `issn-type` | [{value, type}] | type: `print`/`electronic`/`link` |
| `ISBN` | [String] | |
| `archive` | [String] | e.g. `["Portico", "CLOCKSS"]` |
| `alternative-id` | [String] | Publisher-assigned IDs |
| `author` | [Contributor] | See below |
| `editor` | [Contributor] | |
| `funder` | [Funder] | See below |
| `license` | [License] | See below |
| `link` | [ResourceLink] | Full-text links |
| `reference` | [Reference] | Outbound references |
| `assertion` | [Assertion] | Crossmark assertions |
| `relation` | Object | Relations to other works |
| `update-to` | [Update] | Corrections/retractions |
| `clinical-trial-number` | [CTN] | |

### Nested Objects

**FullDate** (`created`, `deposited`, `indexed`):
```json
{"date-parts": [[2020, 9, 16]], "date-time": "2020-09-16T00:00:00Z", "timestamp": 1600214400000}
```

**PartialDate** (`issued`, `published-*`):
```json
{"date-parts": [[2020, 9]]}  // only year guaranteed; month/day optional
```

**Contributor** (`author[]`, `editor[]`):
```json
{
  "given": "Charles R.", "family": "Harris", "sequence": "first",
  "affiliation": [{"name": "Independent researcher"}],
  "ORCID": "http://orcid.org/0000-0002-7833-8590",
  "authenticated-orcid": true
}
```

**Funder** (`funder[]`):
```json
{
  "name": "National Science Foundation", "DOI": "10.13039/100000001",
  "award": ["1447153"], "doi-asserted-by": "publisher"
}
```

**License** (`license[]`):
```json
{
  "URL": "http://creativecommons.org/licenses/by/4.0/",
  "start": {"date-parts": [[2020, 9, 16]]},
  "delay-in-days": 0,
  "content-version": "vor"  // vor | am | tdm | unspecified
}
```

**Reference** (`reference[]`):
```json
{
  "key": "2649_CR1", "DOI": "10.1109/MCSE.2007.58",
  "doi-asserted-by": "publisher", "author": "J. D. Hunter",
  "year": "2007", "journal-title": "Comput. Sci. Eng.",
  "first-page": "10", "unstructured": "Hunter, J. D. Matplotlib: ..."
}
```
Note: Most references only have `key` + `unstructured`. `DOI` is sparse.

### Useful Auxiliary Endpoints
| Endpoint | Use |
|----------|-----|
| `GET /works/{doi}/agency` | Determine registration agency (CrossRef vs DataCite) |
| `GET /funders/{id}` | Funder details from Open Funder Registry |
| `GET /journals/{issn}/works` | All works in a journal |

---

## 2. DataCite

### Call Pattern
```
GET https://api.datacite.org/dois/{doi}
```

**Auth:** None required. Fully public.

**Headers:** `Accept: application/json`

**Query params:** `?affiliation=true` (structured affiliations with ROR), `?publisher=true` (structured publisher)

### Response Structure (JSON:API)
```json
{
  "data": {
    "id": "10.5061/dryad.8sf3tx0h5",
    "type": "dois",
    "attributes": { /* ... */ },
    "relationships": { /* ... */ }
  }
}
```

### `data.attributes` — Full Key Hierarchy

| Key | Type | Notes |
|-----|------|-------|
| `doi` | String | |
| `prefix` | String | |
| `suffix` | String | |
| `identifiers` | [{identifier, identifierType}] | |
| `alternateIdentifiers` | [{alternateIdentifier, alternateIdentifierType}] | |
| `creators` | [Creator] | See below |
| `titles` | [{title, titleType, lang}] | |
| `publisher` | String | (or Object with `?publisher=true`) |
| `publicationYear` | Integer | |
| `subjects` | [{subject, subjectScheme, schemeUri, valueUri, classificationCode}] | |
| `contributors` | [Creator + contributorType] | |
| `dates` | [{date, dateType, dateInformation}] | dateType: Issued, Created, Updated, Available |
| `language` | String | ISO 639-1 |
| `types` | Object | `{resourceTypeGeneral, resourceType, schemaOrg, citeproc, bibtex, ris}` |
| `relatedIdentifiers` | [RelatedId] | See below — critical for versioning |
| `relatedItems` | [Object] | Full bibliographic detail (Schema 4.3+) |
| `sizes` | [String] | |
| `formats` | [String] | |
| `version` | String | Resource version |
| `rightsList` | [{rights, rightsUri, rightsIdentifier, ...}] | |
| `descriptions` | [{description, descriptionType}] | descriptionType: Abstract, Methods, TechnicalInfo |
| `geoLocations` | [{geoLocationPlace, geoLocationPoint, geoLocationBox, geoLocationPolygon}] | |
| `fundingReferences` | [{funderName, funderIdentifier, funderIdentifierType, awardNumber, ...}] | |
| `container` | Object | `{type, identifier, identifierType, title, volume, issue, firstPage, lastPage}` |
| `xml` | String | Base64-encoded DataCite XML |
| `url` | String | Landing page URL |
| `metadataVersion` | Integer | |
| `schemaVersion` | String | |
| `state` | String | |
| `isActive` | Boolean | |
| `viewCount` | Integer | |
| `downloadCount` | Integer | |
| `citationCount` | Integer | |
| `referenceCount` | Integer | |
| `partCount` | Integer | |
| `partOfCount` | Integer | |
| `versionCount` | Integer | |
| `versionOfCount` | Integer | |
| `created` | String | ISO timestamp |
| `registered` | String | |
| `published` | String | |
| `updated` | String | |

**Creator**:
```json
{
  "name": "Harris, Charles R.", "nameType": "Personal",
  "givenName": "Charles R.", "familyName": "Harris",
  "affiliation": [{"name": "...", "affiliationIdentifier": "https://ror.org/..."}],
  "nameIdentifiers": [{"nameIdentifier": "0000-...", "nameIdentifierScheme": "ORCID"}]
}
```

**RelatedIdentifier** (critical for version chains):
```json
{
  "relatedIdentifier": "10.5061/dryad.8sf3tx0h5/1",
  "relatedIdentifierType": "DOI",
  "relationType": "HasVersion",
  "resourceTypeGeneral": "Dataset"
}
```

### `data.relationships` — Pre-computed Links
```json
{
  "client": {"data": {"id": "...", "type": "clients"}},
  "provider": {"data": {"id": "...", "type": "providers"}},
  "references": {"data": [{"id": "...", "type": "dois"}]},
  "citations": {"data": [{"id": "...", "type": "dois"}]},
  "versions": {"data": [{"id": "...", "type": "dois"}]},
  "versionOf": {"data": [{"id": "...", "type": "dois"}]},
  "parts": {"data": []},
  "partOf": {"data": []}
}
```

### Key Controlled Vocabularies
- **resourceTypeGeneral** (32): Dataset, Software, Text, Collection, JournalArticle, ...
- **relationType** (38): HasVersion, IsVersionOf, IsCitedBy, IsSupplementTo, IsNewVersionOf, IsPreviousVersionOf, ...
- **relatedIdentifierType** (21): DOI, URL, arXiv, PMID, Handle, ...

### Versioning Pattern
- **Dryad:** `10.5061/dryad.xxx` → HasVersion → `10.5061/dryad.xxx/1`, `/2`
- **Zenodo:** Concept DOI → HasVersion → version DOIs. Version DOIs → IsVersionOf → concept DOI.
- Both use `relatedIdentifiers` in attributes AND `relationships.versions`/`relationships.versionOf`.

---

## 3. OpenAlex

### Call Pattern
```
GET https://api.openalex.org/works/doi:{doi}?mailto={email}
```

**Auth transition (CRITICAL):** Polite pool (`?mailto=`) deprecated **February 13, 2026**. After that, use `?api_key=YOUR_KEY`. Free keys at `https://openalex.org/settings/api`. Singleton lookups cost 0 credits (unlimited).

**Env vars:** `OPENALEX_EMAIL` (current), `OPENALEX_API_KEY` (add when available).

### Response — Full Key Hierarchy (48 fields)

#### Core Identification
| Key | Type | Notes |
|-----|------|-------|
| `id` | String | `"https://openalex.org/W2741809807"` |
| `doi` | String | `"https://doi.org/10.1038/..."` |
| `title` | String | |
| `display_name` | String | Same as title |
| `ids` | Object | `{openalex, doi, mag, pmid, pmcid}` |

#### Type & Publication
| Key | Type |
|-----|------|
| `type` | String | `"article"`, `"preprint"`, `"book"`, ... |
| `publication_year` | Integer |
| `publication_date` | String | ISO 8601 |
| `language` | String | ISO 639-1 |

#### Citations & Impact
| Key | Type | Notes |
|-----|------|-------|
| `cited_by_count` | Integer | |
| `cited_by_percentile_year` | Object | `{min, max}` |
| `citation_normalized_percentile` | Object | `{value, is_in_top_1_percent, is_in_top_10_percent}` |
| `fwci` | Float | Field-weighted citation impact |
| `counts_by_year` | [{year, cited_by_count}] | Last 10 years |
| `cited_by_api_url` | String | URL to fetch all citing works |

#### Authorships (max 100)
```json
{
  "author_position": "first",
  "author": {"id": "...", "display_name": "...", "orcid": "..."},
  "institutions": [{"id": "...", "display_name": "...", "ror": "...", "country_code": "...", "type": "...", "lineage": [...]}],
  "affiliations": [{"raw_affiliation_string": "...", "institution_ids": [...]}],
  "countries": ["US"],
  "is_corresponding": true,
  "raw_author_name": "..."
}
```

#### Locations & Open Access
```json
{
  "primary_location": {
    "is_oa": true, "is_published": true, "is_accepted": false,
    "landing_page_url": "...", "pdf_url": "...",
    "version": "publishedVersion",
    "license": "cc-by",
    "source": {"id": "...", "display_name": "Nature", "issn_l": "...", "issn": [...], "host_organization": "...", "type": "journal"}
  },
  "best_oa_location": { /* same structure */ },
  "locations": [ /* array of same */ ],
  "locations_count": 5,
  "open_access": {
    "is_oa": true,
    "oa_status": "gold",  // gold | green | hybrid | bronze | diamond | closed
    "oa_url": "...",
    "any_repository_has_fulltext": true
  }
}
```

#### Topics, Concepts, Keywords
| Key | Type |
|-----|------|
| `primary_topic` | Object | `{id, display_name, score, subfield:{}, field:{}, domain:{}}` |
| `topics` | [Object] | Up to 3 |
| `concepts` | [{id, wikidata, display_name, level, score}] | |
| `keywords` | [{id, display_name, score}] | Up to 5 |
| `sustainable_development_goals` | [{id, display_name, score}] | |

#### References & Related Works
| Key | Type | Notes |
|-----|------|-------|
| `referenced_works` | [String] | OpenAlex IDs of outgoing citations |
| `related_works` | [String] | Algorithmically computed (concept similarity) |

#### Other Fields
| Key | Type | Notes |
|-----|------|-------|
| `abstract_inverted_index` | Object | `{"word": [positions]}` — needs reconstruction |
| `grants` | [{funder, funder_display_name, award_id}] | |
| `mesh` | [{descriptor_ui, descriptor_name, qualifier_ui, qualifier_name, is_major_topic}] | |
| `biblio` | Object | `{volume, issue, first_page, last_page}` |
| `apc_list` | Object | `{value, currency, provenance, value_usd}` |
| `apc_paid` | Object | Same structure |
| `has_fulltext` | Boolean | |
| `indexed_in` | [String] | `["arxiv", "crossref", "doaj", "pubmed"]` |
| `is_paratext` | Boolean | |
| `is_retracted` | Boolean | |
| `created_date` | String | ISO 8601 |
| `updated_date` | String | ISO 8601 |

### Abstract Reconstruction
```python
def abstract_from_inverted_index(inv_index: dict) -> str:
    if not inv_index:
        return ""
    length = max(pos for positions in inv_index.values() for pos in positions) + 1
    words = [""] * length
    for word, positions in inv_index.items():
        for pos in positions:
            words[pos] = word
    return " ".join(words)
```

---

## 4. Semantic Scholar

### Call Pattern
```
GET https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}?fields={comma-separated-fields}
```

**Paper ID formats:** `DOI:`, `ARXIV:`, `PMID:`, `PMCID:`, `MAG:`, `ACL:`, `CorpusId:`, `URL:`, or raw S2 ID.

**Auth:** `x-api-key: {key}` header. Optional but recommended.

**Rate limits:** Unauthenticated: shared ~1000 req/s pool (unstable). Authenticated: dedicated 1 req/s (increasable).

### Available Fields (use in `?fields=`)

| Field | Type | Notes |
|-------|------|-------|
| `paperId` | String | Always returned (40-char hex) |
| `corpusId` | String | |
| `title` | String | Default |
| `abstract` | String | |
| `year` | Integer | |
| `venue` | String | Short name |
| `publicationVenue` | Object | `{id, name, type, alternate_names, issn, url}` |
| `publicationDate` | String | ISO YYYY-MM-DD |
| `publicationTypes` | [String] | `["JournalArticle"]` |
| `url` | String | S2 page URL |
| `externalIds` | Object | `{DOI, ArXiv, PubMed, MAG, CorpusId, DBLP, PubMedCentral}` |
| `authors` | [Author] | `{authorId, name}` |
| `journal` | Object | `{name, pages, volume}` |
| `citationCount` | Integer | |
| `referenceCount` | Integer | |
| `influentialCitationCount` | Integer | |
| `isOpenAccess` | Boolean | |
| `openAccessPdf` | Object/null | `{url, status}` status: GOLD/GREEN/HYBRID |
| `fieldsOfStudy` | [String] | |
| `s2FieldsOfStudy` | [{category, source}] | source: `"external"` or `"s2-fos-model"` |
| `tldr` | Object | `{model, text}` — AI-generated summary |
| `embedding` | Object | SPECTER2 vector |
| `citations` | [Paper] | Citing papers |
| `references` | [Paper] | Referenced papers |
| `citationStyles` | Object | `{bibtex: "..."}` |

### Dot Notation for Nested Fields
Request sub-fields on citations/references/authors:
```
?fields=citations.title,citations.intents,citations.isInfluential,references.title
```

### Citation Intent (unique to S2)
Available on citations/references via dot notation:
| Field | Type | Notes |
|-------|------|-------|
| `contexts` | [String] | Text snippets around citation |
| `intents` | [String] | `"Background"`, `"Methodology"`, `"ResultComparison"` |
| `isInfluential` | Boolean | |
| `contextsWithIntent` | [{context, intents}] | Combined |

### Pagination Endpoints (for large citation lists)
```
GET /graph/v1/paper/{id}/citations?offset=0&limit=100&fields=title,intents,isInfluential
GET /graph/v1/paper/{id}/references?offset=0&limit=100&fields=title,intents,isInfluential
```
Use these instead of embedding `citations`/`references` in the paper detail call (10MB response limit).

### Recommended Fetcher Call
```
GET /graph/v1/paper/DOI:{doi}?fields=title,abstract,year,authors,citationCount,referenceCount,influentialCitationCount,tldr,externalIds,publicationTypes,journal,openAccessPdf,citationStyles,s2FieldsOfStudy,publicationDate,publicationVenue
```

---

## 5. Unpaywall

### Call Pattern
```
GET https://api.unpaywall.org/v2/{doi}?email={email}
```

**Auth:** Email required (query param). No API key.

**Rate Limits:** 100,000 requests/day.

### Response — Full Key Hierarchy

#### DOI Object (top-level)
| Key | Type | Notes |
|-----|------|-------|
| `doi` | String | Lowercase |
| `doi_url` | String | `"https://doi.org/..."` |
| `title` | String | |
| `genre` | String | `"journal-article"` |
| `is_oa` | Boolean | Any OA copy exists |
| `is_paratext` | Boolean | Editorial/TOC/etc |
| `oa_status` | String | `gold`/`green`/`hybrid`/`bronze`/`closed` |
| `has_repository_copy` | Boolean | |
| `journal_is_oa` | Boolean | |
| `journal_is_in_doaj` | Boolean | |
| `journal_issns` | String | Comma-separated |
| `journal_issn_l` | String | Linking ISSN |
| `journal_name` | String | |
| `publisher` | String | |
| `published_date` | String | YYYY-MM-DD |
| `year` | Integer | |
| `updated` | String | ISO timestamp |
| `data_standard` | Integer | 1 or 2 |
| `best_oa_location` | OALocation/null | Best available |
| `first_oa_location` | OALocation/null | First found |
| `oa_locations` | [OALocation] | All OA copies |
| `oa_locations_embargoed` | [OALocation] | Under embargo |
| `z_authors` | [Author] | From CrossRef: `{given, family, sequence, ORCID, authenticated-orcid, affiliation}` |

#### OA Location Object
```json
{
  "url": "...",
  "url_for_pdf": "...",
  "url_for_landing_page": "...",
  "host_type": "publisher",        // "publisher" | "repository"
  "version": "publishedVersion",   // publishedVersion | acceptedVersion | submittedVersion
  "license": "cc-by",
  "evidence": "open (via page says license)",
  "is_best": true,
  "oa_date": "2020-09-16",
  "endpoint_id": "...",
  "pmh_id": "...",
  "repository_institution": "...",
  "updated": "..."
}
```

#### `best_oa_location` Ranking Logic
1. `version`: publishedVersion > acceptedVersion > submittedVersion
2. `url_for_pdf`: having PDF preferred
3. Repository reputation: PMC and arXiv rank higher

### Unique Data
- Granular OA status taxonomy (gold/green/hybrid/bronze/closed)
- Per-location version tracking
- Per-location license
- DOAJ membership
- Discovery method (`evidence`)
- Embargoed locations

---

## 6. Europe PMC

### Call Pattern
```
GET https://www.ebi.ac.uk/europepmc/webservices/rest/search?query=DOI:{doi}&format=json&resultType=core
```

**Auth:** None required.

**Params:** `resultType=core` for full metadata (vs `lite` default).

### Response Envelope
```json
{
  "version": "...",
  "hitCount": 1,
  "request": {"queryString": "...", "resultType": "core", "pageSize": 25},
  "resultList": {"result": [ /* ... */ ]}
}
```

### Result Object — Key Fields

#### Identifiers & Basic Metadata
| Key | Type | Notes |
|-----|------|-------|
| `id` | String | PMID |
| `pmid` | String | |
| `pmcid` | String | `"PMC7116644"` |
| `doi` | String | |
| `title` | String | |
| `authorString` | String | Formatted author list |
| `journalTitle` | String | |
| `journalVolume` | String | |
| `issue` | String | |
| `pubYear` | String | |
| `pubType` | String | |
| `isOpenAccess` | String | `"Y"` or `"N"` |
| `citedByCount` | Integer | Europe PMC citation count |
| `pageInfo` | String | `"357-362"` |
| `language` | String | `"eng"` |

#### CORE-only Fields
| Key | Type | Notes |
|-----|------|-------|
| `abstractText` | String | Full abstract |
| `authorList.author[]` | Array | Structured: `{fullName, firstName, lastName, initials, authorId:{type,value}, authorAffiliationDetailsList}` |
| `journalInfo` | Object | `{issue, volume, yearOfPublication, journal:{title, ISOAbbreviation, NLMid, ISSN, ESSN}}` |
| `grantsList.grant[]` | Array | **`{grantId, agency, acronym, orderIn}`** |
| `meshHeadingList.meshHeading[]` | Array | `{majorTopic_YN, descriptorName, meshQualifierList}` |
| `keywordList.keyword[]` | [String] | |
| `chemicalList.chemical[]` | Array | `{name, registryNumber}` |
| `fullTextUrlList.fullTextUrl[]` | Array | `{availability, availabilityCode, documentStyle, site, url}` |
| `commentCorrectionList.commentCorrection[]` | Array | Errata/corrections/retractions |
| `investigatorList.investigator[]` | Array | Named investigators |
| `tmAccessionTypeList.accessionType[]` | [String] | Text-mined accession types (gen, pdb) |
| `dataLinksTagsList.dataLinksTag[]` | Array | Altmetrics/supporting data links |
| `publicationStatus` | String | `ppublish`/`epublish`/`aheadofprint` |
| `dateOfCreation` | String | |
| `dateOfRevision` | String | |

### Unique Data
- **Grants** with structured grantId/agency/acronym
- **MeSH headings** (medical subject headings)
- **Chemical substances**
- **Text-mined accession numbers** (GenBank, PDB, etc.)
- **Corrections/retractions** linked to article
- **NLM/MEDLINE identifiers** for journals
- Coverage: ~40M+ articles (life sciences focus)

---

## 7. OpenAIRE

### Call Pattern
```
GET https://api.openaire.eu/graph/v2/researchProducts?search={doi}&pageSize=1
```

Or direct by constructed ID:
```
GET https://api.openaire.eu/graph/v2/researchProducts/doi_dedup___::{md5(lowercase_doi)}
```

Or legacy:
```
GET https://api.openaire.eu/search/researchProducts?doi={doi}&format=json
```

**Auth:** `Authorization: Bearer {ACCESS_TOKEN}` header. Optional (unauthenticated works but rate-limited).

**Token refresh:** POST to `https://aai.openaire.eu/oidc/token` with refresh_token grant.

### Response Envelope
```json
{
  "header": {"numFound": 1, "maxScore": 1.0, "queryTime": 21, "page": 1, "pageSize": 10},
  "results": [ /* ResearchProduct objects */ ]
}
```

### ResearchProduct — Full Key Hierarchy

#### Core
| Key | Type |
|-----|------|
| `id` | String | `"doi_dedup___::80f29c8c..."` |
| `type` | String | `publication`/`dataset`/`software`/`other` |
| `originalIds` | [String] |
| `mainTitle` | String |
| `subTitle` | String |
| `publicationDate` | String | YYYY-MM-DD |
| `publisher` | String |
| `descriptions` | [String] |
| `language` | Object | `{code: "eng", label: "English"}` |
| `sources` | [String] |
| `formats` | [String] |
| `embargoEndDate` | String |
| `lastUpdateTimeStamp` | Long |

#### Authors
```json
{
  "fullName": "...", "givenName": "...", "familyName": "...",
  "rank": 1,
  "pid": {"scheme": "orcid", "value": "0000-..."}
}
```

#### PIDs
```json
{"scheme": "doi", "value": "10.1038/..."}  // also: pmid, arxiv, handle
```

#### Access & OA
| Key | Type | Notes |
|-----|------|-------|
| `bestAccessRight` | Object | `{code, label, scheme}` — OPEN/CLOSED/RESTRICTED/EMBARGO |
| `isGreen` | Boolean | Green OA |
| `openAccessColor` | String | `bronze`/`gold`/`hybrid` |
| `isInDiamondJournal` | Boolean | |
| `publiclyFunded` | Boolean | |

#### Instances (per-repository copies)
```json
{
  "accessRight": {"code": "...", "label": "...", "openAccessRoute": "gold"},
  "alternateIdentifiers": [{"scheme": "...", "value": "..."}],
  "articleProcessingCharge": {"amount": "...", "currency": "EUR"},
  "license": "http://creativecommons.org/licenses/by/4.0",
  "pids": [{"scheme": "doi", "value": "..."}],
  "type": "Article",
  "urls": ["..."],
  "hostedby": {"id": "...", "name": "..."},
  "collectedfrom": {"id": "...", "name": "..."}
}
```

#### Impact Indicators (BIP!)
```json
{
  "indicators": {
    "citationImpact": {
      "citationCount": 142.0, "citationClass": "C1",
      "influence": 0.85, "influenceClass": "C1",
      "popularity": 0.92, "popularityClass": "C1",
      "impulse": 0.75, "impulseClass": "C1"
    },
    "usageCounts": {"downloads": 5432, "views": 12345}
  }
}
```

#### Projects & Funding (UNIQUE TO OPENAIRE)
```json
{
  "projects": [{
    "id": "corda__h2020::94c4a066...",
    "code": "727929",
    "acronym": "TomRes",
    "title": "Full project title...",
    "funder": {
      "shortName": "EC",
      "name": "European Commission",
      "jurisdiction": "EU",
      "fundingStream": "H2020"
    },
    "provenance": {"provenance": "Harvested", "trust": "0.9"},
    "validated": {"validationDate": "...", "validatedByFunder": true}
  }]
}
```

#### Subjects with Provenance
```json
{
  "subjects": [{
    "scheme": "FOS",  // or "SDG"
    "value": "Computer Science",
    "provenance": {"provenance": "Inferred by OpenAIRE", "trust": "0.85"}
  }]
}
```

#### Type-specific Extensions
- **Publication:** adds `container` (journal: name, vol, iss, pages, ISSN)
- **Dataset:** adds `size`, `version`, `geolocations`
- **Software:** adds `documentationUrls`, `codeRepositoryUrl`, `programmingLanguage`

### Unique Data
- **EU/international funding linkages** with funder validation
- **BIP! citation impact indicators** (influence, popularity, impulse)
- **Usage counts** (downloads, views)
- **OA mandate compliance** fields
- **Research community** connections
- **FOS and SDG classifications** with trust scores
- **APC data** per instance

---

## 8. NIH Reporter

### Call Patterns

**Publications by DOI:**
```
POST https://api.reporter.nih.gov/v2/publications/search
Content-Type: application/json

{"criteria": {"doi": "10.1038/s41586-020-2649-2"}, "offset": 0, "limit": 50}
```

**Projects by project number (follow-up):**
```
POST https://api.reporter.nih.gov/v2/projects/search
Content-Type: application/json

{"criteria": {"project_nums": ["U01HG004695"]}, "offset": 0, "limit": 10}
```

**Auth:** None required.

### Critical Design Insight: Many-to-Many Linkage

A single publication often links to **multiple grants** (5+ is common for consortium papers like ENCODE, TCGA, GTEx, TOPMed). Each grant carries its own project details, PIs, funding breakdowns.

The response is structured as `{coreProjectNum → {project_details, publications[]}}` where publications is a list of `{coreproject, pmid, applid}` tuples.

### Response — Per-Grant Object

```json
{
  "U01HG004695": {
    "total_project_records": 2913550,
    "total_publications": 46,
    "latest_project": { /* Project object */ },
    "publications": [
      {"coreproject": "U01HG004695", "pmid": 25164755, "applid": 8494858},
      {"coreproject": "U01HG004695", "pmid": 25504731, "applid": 8494858}
    ]
  },
  "R01HL120393": {
    "total_publications": 545,
    "latest_project": { /* ... */ },
    "publications": [ /* ... */ ]
  }
}
```

### Project Object (`latest_project`)
| Key | Type | Notes |
|-----|------|-------|
| `appl_id` | Integer | NIH application ID |
| `subproject_id` | Integer/null | |
| `fiscal_year` | Integer | |
| `project_num` | String | Full project number, e.g. `"1R01NR014792-01"` |
| `project_serial_num` | String | e.g. `"NR014792"` |
| `award_type` | String | `"1"` (new), `"4N"` (non-competing renewal) |
| `activity_code` | String | `"R01"`, `"U01"`, `"U54"`, `"P41"`, `"U24"` |
| `award_amount` | Integer | Total award in USD |
| `project_start_date` | String | ISO datetime |
| `project_end_date` | String | |
| `project_title` | String | |
| `abstract_text` | String | Full project abstract |
| `phr_text` | String | Public health relevance statement |
| `spending_categories_desc` | String | Semicolon-separated RCDC categories |
| `cong_dist` | String | Congressional district, e.g. `"TX-09"` |

**Organization:**
```json
{
  "org_name": "BAYLOR COLLEGE OF MEDICINE",
  "org_city": "HOUSTON", "org_state": "TX", "org_country": "UNITED STATES",
  "dept_type": "OBSTETRICS & GYNECOLOGY",
  "org_duns": ["051113330"], "org_ueis": ["FXKMA43NTV21"],
  "primary_duns": "051113330", "primary_uei": "FXKMA43NTV21",
  "org_fips": "US", "org_ipf_code": "481201", "org_zipcode": "770303411"
}
```

**Principal Investigators:**
```json
[{
  "profile_id": 8196581, "first_name": "Kjersti", "middle_name": "Marie",
  "last_name": "Aagaard", "full_name": "Kjersti Marie Aagaard",
  "is_contact_pi": true, "title": "PROFESSOR"
}]
```

**Program Officers:**
```json
[{"first_name": "LOIS", "middle_name": "", "last_name": "TULLY", "full_name": "LOIS  TULLY"}]
```

**Agency/IC Funding Breakdown:**
```json
[{
  "fy": 2013, "code": "NR",
  "name": "National Institute of Nursing Research", "abbreviation": "NINR",
  "total_cost": 560670.0, "direct_cost_ic": 382840.0, "indirect_cost_ic": 177830.0
}]
```

### Publication Linkage Tuple
```json
{"coreproject": "U01HG004695", "pmid": 25164755, "applid": 8494858}
```
- `coreproject`: the grant that funded this publication
- `pmid`: PubMed ID → **bridges to Europe PMC, OpenAlex, Semantic Scholar**
- `applid`: links back to the specific application/award year

### Unique Data
- **Many-to-many grant↔publication linkage** (one paper → multiple grants, one grant → hundreds of papers)
- **Full project metadata:** abstract, public health relevance, spending categories
- **Institutional detail:** UEI/DUNS identifiers, department, congressional district
- **PI profiles** with profile_id for cross-referencing
- **IC-level funding breakdown** (which NIH institute, direct vs indirect costs)
- **Activity code taxonomy** (R01, U01, P41, etc.) indicating grant mechanism
- **Relative Citation Ratio** (NIH's own impact metric, on publications endpoint)

### Connection Strategy
1. Query publications by DOI → get list of `coreProjectNum` values
2. For each project number → query projects endpoint for full grant details
3. Each grant's `publications[]` gives **PMIDs** of all sibling publications
4. These PMIDs bridge to Europe PMC, OpenAlex, S2 for full metadata on each

---

## 9. Zenodo

### Call Patterns
```
GET https://zenodo.org/api/records?q=doi:{doi}          # Search
GET https://zenodo.org/api/records/{record_id}           # Direct by numeric ID
```

**Auth:** Optional. `Authorization: Bearer {token}` for access to restricted records.

### Response — Search Envelope
```json
{
  "hits": {"hits": [ /* Record objects */ ], "total": 1},
  "aggregations": {},
  "links": {"self": "...", "next": "..."}
}
```

### Record Object — Full Key Hierarchy

#### Top-level
| Key | Type | Notes |
|-----|------|-------|
| `id` | Integer | Record ID |
| `conceptrecid` | String | **Shared across all versions** |
| `doi` | String | This version's DOI |
| `conceptdoi` | String | **Version-independent DOI** (redirects to latest) |
| `created` | String | ISO timestamp |
| `updated` | String | |
| `revision` | Integer | |
| `owners` | [Integer] | |

#### Files
```json
{
  "files": [{
    "id": "...", "key": "dataset.csv", "filename": "dataset.csv",
    "size": 12345, "filesize": 12345,
    "checksum": "md5:abc123...",
    "bucket": "...", "type": "csv",
    "links": {"self": "...", "download": "..."}
  }]
}
```

#### Links
```json
{
  "links": {
    "self": "...", "html": "...", "doi": "...",
    "badge": "...", "bucket": "...",
    "latest": "...", "latest_html": "...", "versions": "..."
  }
}
```

#### Stats
```json
{
  "stats": {
    "downloads": 1234, "unique_downloads": 567,
    "views": 8901, "unique_views": 2345,
    "version_downloads": 100, "version_unique_downloads": 50,
    "version_views": 200, "version_unique_views": 100
  }
}
```

#### Metadata
| Key | Type | Notes |
|-----|------|-------|
| `metadata.title` | String | |
| `metadata.description` | String | HTML allowed |
| `metadata.publication_date` | String | YYYY-MM-DD |
| `metadata.creators[]` | Array | `{name, affiliation, orcid, gnd, type}` |
| `metadata.access_right` | String | `open`/`embargoed`/`restricted`/`closed` |
| `metadata.resource_type` | Object | `{type, subtype, title}` |
| `metadata.doi` | String | |
| `metadata.license` | Object | `{id: "cc-by-4.0"}` |
| `metadata.related_identifiers[]` | Array | `{identifier, relation, resource_type, scheme}` |
| `metadata.relations.version[]` | Array | `{index, is_last, parent:{pid_type, pid_value}, count, last_child:{pid_type, pid_value}}` |
| `metadata.contributors[]` | Array | Same as creators + `type` (ContactPerson, etc.) |
| `metadata.keywords[]` | [String] | |
| `metadata.subjects[]` | [{term, identifier, scheme}] | |
| `metadata.notes` | String | |
| `metadata.version` | String | |
| `metadata.language` | String | ISO 639 |
| `metadata.method` | String | |
| `metadata.dates[]` | [{start, end, type, description}] | |
| `metadata.locations[]` | [{lat, lon, place, description}] | |
| `metadata.grants[]` | Array | `{funder:{doi, name, acronyms}, code, title, url, program}` |
| `metadata.communities[]` | [{id}] | Zenodo communities |
| `metadata.journal` | Object | `{title, volume, issue, pages}` |
| `metadata.meeting` | Object | `{title, acronym, dates, place, url, session, session_part}` |
| `metadata.imprint` | Object | `{publisher, isbn, place}` |
| `metadata.part_of` | Object | `{title, pages}` |
| `metadata.thesis` | Object | `{supervisors[], university}` |

### Version Chain Navigation
- `conceptrecid` is the permanent parent ID (shared across all versions)
- `conceptdoi` always redirects to the latest version
- `metadata.relations.version[].index` gives version position
- `metadata.relations.version[].is_last` indicates if this is the latest

---

## 10. Dryad

### Call Pattern
```
GET https://datadryad.org/api/v2/datasets/doi%3A{url_encoded_doi}
```
DOI must be URL-encoded: `10.5061/dryad.8sf3tx0h5` → `doi%3A10.5061%2Fdryad.8sf3tx0h5`

**Auth:** None for public datasets.

### Response — Full Key Hierarchy

| Key | Type | Notes |
|-----|------|-------|
| `identifier` | String | DOI |
| `id` | Integer | Internal ID |
| `versionStatus` | String | |
| `versionNumber` | Integer | |
| `curationStatus` | String | |
| `title` | String | |
| `abstract` | String | |
| `methods` | String | |
| `usageNotes` | String | |
| `keywords[]` | [String] | |
| `fieldOfScience` | String | |
| `publicationDate` | String | |
| `lastModificationDate` | String | |
| `storageSize` | Integer | bytes |
| `visibility` | String | |
| `license` | String | |
| `sharingLink` | String | |
| `publicationISSN` | String | |
| `publicationName` | String | |
| `manuscriptNumber` | String | |
| `versionChanges` | String | |

**Authors:**
```json
{
  "authors": [{
    "firstName": "...", "lastName": "...", "email": "...",
    "affiliation": "...", "affiliationROR": "https://ror.org/...",
    "affiliationISNI": "...", "orcid": "0000-...", "order": 1
  }]
}
```

**Funders:**
```json
{
  "funders": [{
    "organization": "NSF", "identifier": "...",
    "identifierType": "crossref_funder_id", "awardNumber": "12345"
  }]
}
```

**Related Works (links to articles, software):**
```json
{
  "relatedWorks": [{
    "relationship": "IsCitedBy",
    "identifierType": "DOI",
    "identifier": "10.1038/..."
  }]
}
```

**Geolocation:**
```json
{
  "locations": [{"place": "...", "point": {"latitude": 0.0, "longitude": 0.0}}]
}
```

**HATEOAS Links:**
```json
{
  "_links": {
    "self": {"href": "..."},
    "stash:version": {"href": "..."},
    "stash:versions": {"href": "..."},
    "stash:download": {"href": "..."}
  }
}
```

### Getting Files
Requires following HATEOAS links: `_links.stash:version.href` → then `_links.stash:files.href` (2-3 sequential requests).

### Versioning Note
Unlike Zenodo, Dryad does NOT use separate DOIs per version. All versions share one DOI, differentiated by `versionNumber`.

---

## 11. ORCID

### Call Patterns

**Search by DOI (find ORCIDs for a paper):**
```
GET https://pub.orcid.org/v3.0/expanded-search?q=doi-self:{doi}
Accept: application/json
Authorization: Bearer {token}
```

**Full record:**
```
GET https://pub.orcid.org/v3.0/{orcid}/record
```

**Works:**
```
GET https://pub.orcid.org/v3.0/{orcid}/works
```

**Auth:** OAuth2 client_credentials with `/read-public` scope.
```
POST https://orcid.org/oauth/token
client_id={id}&client_secret={secret}&grant_type=client_credentials&scope=/read-public
```
Token is long-lived (~20 years). Public data may work without token (unofficial).

**Rate limits:** 24 req/s, burst queue of 40. HTTP 503 on exceeded.

### Expanded Search Response
```json
{
  "num-found": 5,
  "expanded-result": [{
    "orcid-id": "0000-0001-2345-6789",
    "given-names": "Charles",
    "family-names": "Harris",
    "credit-name": "C.R. Harris",
    "other-name": ["C Harris"],
    "email": [],
    "institution-name": ["MIT", "Harvard University"]
  }]
}
```

### Works Response Structure (grouped)
```json
{
  "group": [{
    "external-ids": {
      "external-id": [{
        "external-id-type": "doi",
        "external-id-value": "10.1038/...",
        "external-id-normalized": {"value": "..."},
        "external-id-url": {"value": "..."},
        "external-id-relationship": "self"
      }]
    },
    "work-summary": [{
      "put-code": 12345,
      "title": {"title": {"value": "Array programming with NumPy"}},
      "type": "journal-article",
      "publication-date": {"year": {"value": "2020"}, "month": {"value": "09"}},
      "journal-title": {"value": "Nature"},
      "source": {"source-name": {"value": "Crossref"}},
      "visibility": "public",
      "external-ids": {"external-id": []}
    }]
  }]
}
```

### Full Work (by put-code) — Additional Fields
```json
{
  "contributors": {"contributor": [{
    "contributor-orcid": {"path": "0000-...", "uri": "..."},
    "credit-name": {"value": "..."},
    "contributor-attributes": {
      "contributor-sequence": "first",
      "contributor-role": "author"
    }
  }]},
  "citation": {"citation-type": "bibtex", "citation-value": "..."},
  "short-description": "...",
  "language-code": "en",
  "country": {"value": "US"}
}
```

### Full Record Sections
The `/record` endpoint returns everything:
- `person`: name, other-names, biography, emails, addresses, keywords, external-identifiers, researcher-urls
- `activities-summary`: educations, employments, distinctions, fundings, works, peer-reviews, research-resources

Each affiliation includes `organization.disambiguated-organization` with ROR/RINGGOLD/GRID IDs.

### Search Query Fields
| Field | Example |
|-------|---------|
| `doi-self` | Exact DOI match |
| `family-name` | Last name |
| `affiliation-org-name` | Institution |
| `ror-org-id` | ROR organization ID |
| `keyword` | Profile keywords |
| `grant-numbers` | Grant numbers |

Solr/Lucene syntax: `q=family-name:Einstein+AND+keyword:Relativity`

### Recommended Fetcher Strategy
1. `GET /v3.0/expanded-search?q=doi-self:{doi}` → get all ORCIDs + names + institutions
2. Optionally `GET /v3.0/{orcid}/person` for richer affiliation history
3. Optionally `GET /v3.0/{orcid}/work/{put-code}` for contributors

---

## 12. Entrez/PubMed (NCBI E-utilities)

### Call Pattern

Two-step pipeline: **esearch** (find PMID by DOI) → **efetch** (get full PubMed XML).

**Step 1 — Search for PMID:**
```
GET https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=pubmed&term={doi}[doi]&retmode=json&email={email}&api_key={key}
```

**Step 2 — Fetch full record:**
```
GET https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pubmed&id={pmid}&rettype=xml&email={email}&api_key={key}
```

**Auth:** Optional. `email` recommended (NCBI contact). `api_key` increases rate limit from 3 req/s to 10 req/s. Register at https://www.ncbi.nlm.nih.gov/account/.

**Rate Limits:** 3 req/s without key, 10 req/s with key. HTTP 429 on exceeded.

**Errors:** esearch returns `{"esearchresult": {"count": "0"}}` when no PMID found for the DOI.

### esearch Response (JSON)
```json
{
  "header": {"type": "esearch", "version": "0.3"},
  "esearchresult": {
    "count": "1",
    "retmax": "1",
    "retstart": "0",
    "idlist": ["32939066"],
    "translationset": [],
    "querytranslation": "10.1038/s41586-020-2649-2[doi]"
  }
}
```

### efetch Response (PubMed XML) — Full Key Hierarchy

The PubMed XML response wraps in `<PubmedArticleSet><PubmedArticle>` with two main sections:

#### MedlineCitation
| Path | Type | Notes |
|------|------|-------|
| `PMID` | String | Authoritative PubMed ID (with `@Version` attribute) |
| `DateCompleted` | Date | Year/Month/Day |
| `DateRevised` | Date | Year/Month/Day |
| `Article/Journal/ISSN` | String | With `@IssnType` (Print/Electronic) |
| `Article/Journal/JournalIssue/Volume` | String | |
| `Article/Journal/JournalIssue/Issue` | String | |
| `Article/Journal/JournalIssue/PubDate` | Date | Year + Month or MedlineDate |
| `Article/Journal/Title` | String | Full journal name |
| `Article/Journal/ISOAbbreviation` | String | ISO-abbreviated title |
| `Article/ArticleTitle` | String | Full article title |
| `Article/Pagination/StartPage` | String | First page |
| `Article/Pagination/EndPage` | String | Last page |
| `Article/Pagination/MedlinePgn` | String | e.g. `"357-362"` |
| `Article/ELocationID` | String | DOI and/or PII (with `@EIdType`, `@ValidYN`) |
| `Article/Abstract/AbstractText` | [String] | Labeled sections (`@Label`: BACKGROUND, METHODS, etc.) |
| `Article/AuthorList/Author` | [Author] | See below |
| `Article/Language` | String | e.g. `"eng"` |
| `Article/PublicationTypeList/PublicationType` | [String] | NLM controlled vocabulary with `@UI` |
| `Article/ArticleDate` | Date | `@DateType="Electronic"` |
| `Article/GrantList/Grant` | [Grant] | See below |
| `Article/DataBankList/DataBank` | [DataBank] | See below |
| `Article/VernacularTitle` | String | Title in original language |
| `MeshHeadingList/MeshHeading` | [MeSH] | See below |
| `SupplMeshList/SupplMeshName` | [String] | With `@Type` (Disease/Protocol/Organism) and `@UI` |
| `KeywordList/Keyword` | [String] | With `@MajorTopicYN` flag |
| `ChemicalList/Chemical` | [Chemical] | See below |
| `GeneSymbolList/GeneSymbol` | [String] | HUGO gene symbols |
| `CoiStatement` | String | Conflict of interest disclosure |
| `CommentsCorrectionsList/CommentsCorrections` | [CC] | See below |
| `InvestigatorList/Investigator` | [Person] | Consortium/collaborative group members |
| `PersonalNameSubjectList/PersonalNameSubject` | [Person] | Biography subjects |
| `SpaceFlightMission` | String | (rare, space medicine papers) |
| `MedlineJournalInfo/Country` | String | Country of publication |
| `MedlineJournalInfo/MedlineTA` | String | Abbreviated journal title |
| `MedlineJournalInfo/NlmUniqueID` | String | NLM catalog ID |
| `MedlineJournalInfo/ISSNLinking` | String | Linking ISSN |
| `CitationSubset` | [String] | e.g. `"IM"` (Index Medicus) |
| `OtherAbstract` | [Abstract] | Abstracts in other languages with `@Type` and `@Language` |
| `ObjectList/Object` | [Object] | With `@Type` (keyword, grant link, etc.) |

#### PubmedData
| Path | Type | Notes |
|------|------|-------|
| `PublicationStatus` | String | `"ppublish"`, `"epublish"`, `"aheadofprint"` |
| `ArticleIdList/ArticleId` | [String] | With `@IdType`: `pubmed`, `pmc`, `doi`, `pii`, `mid` |
| `History/PubMedPubDate` | [Date] | With `@PubStatus`: `received`, `accepted`, `revised`, `pubmed`, `medline`, `entrez` |
| `ReferenceList/Reference` | [Ref] | See below |

### Nested Objects

**Author:**
```xml
<Author ValidYN="Y">
  <LastName>Harris</LastName>
  <ForeName>Charles R</ForeName>
  <Initials>CR</Initials>
  <Identifier Source="ORCID">0000-0002-7833-3745</Identifier>
  <AffiliationInfo>
    <Affiliation>Stony Brook University, Stony Brook, NY, USA</Affiliation>
  </AffiliationInfo>
  <!-- or CollectiveName for groups -->
  <CollectiveName>NumPy Contributors</CollectiveName>
</Author>
```

**Grant:**
```xml
<Grant>
  <GrantID>U01 HG004695</GrantID>
  <Acronym>HG</Acronym>
  <Agency>NHGRI NIH HHS</Agency>
  <Country>United States</Country>
</Grant>
```

**MeSH Heading:**
```xml
<MeshHeading>
  <DescriptorName UI="D000465" MajorTopicYN="N">Algorithms</DescriptorName>
  <QualifierName UI="Q000379" MajorTopicYN="Y">methods</QualifierName>
</MeshHeading>
```

**Chemical:**
```xml
<Chemical>
  <RegistryNumber>EC 2.7.11.24</RegistryNumber>
  <NameOfSubstance UI="D048051">p38 Mitogen-Activated Protein Kinases</NameOfSubstance>
</Chemical>
```

**DataBank:**
```xml
<DataBank>
  <DataBankName>ClinicalTrials.gov</DataBankName>
  <AccessionNumberList>
    <AccessionNumber>NCT01234567</AccessionNumber>
  </AccessionNumberList>
</DataBank>
```

**CommentsCorrections:**
```xml
<CommentsCorrections RefType="ErratumFor">
  <RefSource>Nature. 2020;585(7824):E3</RefSource>
  <PMID Version="1">32939086</PMID>
</CommentsCorrections>
```
RefTypes include: `ErratumFor`, `ErratumIn`, `RetractionOf`, `RetractionIn`, `CommentOn`, `CommentIn`, `RepublishedFrom`, `RepublishedIn`, `ExpressionOfConcernFor`, `ExpressionOfConcernIn`, `UpdateOf`, `UpdateIn`, `CitesMethods`, `OriginalReportIn`.

**Reference:**
```xml
<Reference>
  <Citation>van der Walt S, et al. The NumPy array. Comput Sci Eng. 2011;13:22-30.</Citation>
  <ArticleIdList>
    <ArticleId IdType="pubmed">21977015</ArticleId>
    <ArticleId IdType="doi">10.1109/MCSE.2011.37</ArticleId>
  </ArticleIdList>
</Reference>
```

### Publication Types (NLM Controlled Vocabulary)
Common values:
| UI | Value |
|----|-------|
| `D016428` | Journal Article |
| `D016454` | Review |
| `D016449` | Randomized Controlled Trial |
| `D017418` | Meta-Analysis |
| `D016422` | Letter |
| `D016420` | Comment |
| `D016421` | Editorial |
| `D016427` | Case Reports |
| `D013485` | Research Support, Non-U.S. Gov't |
| `D052061` | Research Support, N.I.H., Extramural |

### Recommended Fetcher Strategy
1. `esearch.fcgi?db=pubmed&term={doi}[doi]&retmode=json` → get PMID
2. `efetch.fcgi?db=pubmed&id={pmid}&rettype=xml` → parse full PubmedArticle XML
3. Extract all identifiers from `ArticleIdList` (PMID, PMCID, PII, DOI, MID)
4. Parse MeSH, chemicals, grants, gene symbols, databank accessions
5. Parse CommentsCorrectionsList for errata/retractions

---

## Cross-Source Conflict Matrix

This table shows where the same data exists in multiple sources and may conflict:

| Data Point | Sources | Conflict Risk |
|------------|---------|---------------|
| **Citation count** | CrossRef, OpenAlex, S2, Europe PMC, DataCite, OpenAIRE, NIH Reporter | HIGH — each counts differently |
| **OA status** | Unpaywall, OpenAlex, OpenAIRE, Europe PMC | MEDIUM — different taxonomies |
| **Author names** | CrossRef, DataCite, OpenAlex, S2, Europe PMC, ORCID, Dryad, Entrez | HIGH — spelling/ordering varies |
| **Author ORCIDs** | CrossRef, DataCite, OpenAlex, ORCID, Dryad, NIH Reporter, Entrez | LOW — but coverage varies widely |
| **Affiliations** | CrossRef, OpenAlex, ORCID, Europe PMC, Dryad, NIH Reporter, Entrez | HIGH — different granularity, time |
| **Abstract** | CrossRef (XML), OpenAlex (inverted index), S2, Europe PMC, Entrez (structured) | LOW — usually same content, different format |
| **References** | CrossRef, OpenAlex, S2, DataCite, Entrez | MEDIUM — different completeness |
| **Funding** | CrossRef, Europe PMC, OpenAIRE, NIH Reporter, Zenodo, Dryad, DataCite, Entrez | MEDIUM — different coverage |
| **License** | CrossRef, Unpaywall, OpenAlex, DataCite, Zenodo, Dryad | LOW — usually agree |
| **Publication date** | All sources | LOW — but format/precision varies |
| **Related works** | DataCite, Dryad, Zenodo, OpenAlex | MEDIUM — different relationship types |
| **MeSH terms** | Europe PMC, OpenAlex, Entrez | LOW — same vocabulary |
| **Version info** | DataCite, Zenodo, Dryad | LOW within source, HIGH across |

### Data Unique to Single Sources
| Source | Unique Data |
|--------|-------------|
| **Semantic Scholar** | Citation intents, influential citations, TLDR, SPECTER2 embeddings |
| **OpenAIRE** | EU project linkages, BIP! indicators, FOS/SDG with trust, usage counts |
| **NIH Reporter** | NIH award linkages, activity codes, relative citation ratio |
| **Unpaywall** | Per-location OA version tracking, evidence/discovery method, DOAJ membership |
| **Europe PMC** | MeSH headings, chemicals, text-mined accessions, corrections/errata |
| **Zenodo** | Files with checksums, download stats, community membership |
| **Dryad** | Dataset methods, usage notes, ROR-linked author affiliations |
| **ORCID** | Author employment/education history, peer reviews, funding records |
| **OpenAlex** | FWCI, concept hierarchy, citation percentiles, abstract inverted index |
| **DataCite** | Full version chains, geolocations, resource type taxonomy |
| **Entrez/PubMed** | Publication types (NLM vocabulary), gene symbols, databank accessions, conflict of interest statements, comments/corrections with RefType, supplementary MeSH, investigators, personal name subjects, NLM journal info, citation subsets |
| **CrossRef** | Crossmark assertions, update-to (corrections), clinical trial numbers |
