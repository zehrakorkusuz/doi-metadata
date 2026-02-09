# Citation Count Discrepancies: Deep Investigation

**Date:** 2026-02-09
**DOIs analyzed:** 9 (from `tests/api_results/`)
**Sources reporting citations:** CrossRef, OpenAlex, Semantic Scholar, Europe PMC, OpenAIRE (5 of 11)

---

## 1. The Problem

Citation counts for the same DOI differ dramatically across sources — both between APIs and between what APIs return vs. what the corresponding websites display.

### Observed Divergence Across 9 Test DOIs

| Paper | Min | Max | Spread | Sources |
|-------|-----|-----|--------|---------|
| FAIR Guiding Principles | 6,148 (Europe PMC) | 16,440 (OpenAlex) | **167%** | 5 |
| pandas (Zenodo) | 44 (DataCite) | 1,668 (OpenAlex) | **3,691%** | 2 |
| MIMIC-CXR | 536 (Europe PMC) | 1,693 (S2) | **216%** | 5 |
| GigaScience | 3 (S2) | 6 (CrossRef/OpenAlex) | **100%** | 4 |
| AlphaFold | 29,132 (Europe PMC) | 41,472 (OpenAlex) | **42%** | 4 |
| ENCODE Consortium | 13,957 (Europe PMC) | 18,811 (OpenAlex) | **35%** | 5 |
| UK Biobank | 6,979 (Europe PMC) | 9,125 (OpenAlex) | **31%** | 5 |

**Consistent pattern:** OpenAlex highest, Europe PMC lowest, with 30-167% spreads on well-cited articles.

---

## 2. Why Each Source Counts Differently (Root Causes)

### 2.1 CrossRef — `is-referenced-by-count`

**What it counts:** Only citations from Crossref-registered works whose publishers deposited reference metadata.

**Why it's often lower than OpenAlex:**
- **Opt-in reference deposits:** Not all publishers deposit reference lists. Some publishers (notably Wiley historically) do not grant permission to release citation data via the API, causing `is-referenced-by-count` to show `0` even when citations exist.
- **Only CrossRef-to-CrossRef links:** It cannot count citations from DataCite-registered works (datasets, software), non-DOI content, or sources outside the CrossRef ecosystem.
- **Matching failures:** If a citing work's reference list doesn't include the DOI and the metadata is insufficient for matching, the citation is missed.
- **Processing delay:** Updates to `is-referenced-by-count` happen asynchronously and can lag behind reality.

**API vs. website discrepancy:** CrossRef's REST API JSON and XML endpoints can return different values for the same DOI ([Issue #211](https://github.com/CrossRef/rest-api-doc/issues/211)). The `is-referenced-by-count` is updated in batch for performance reasons, so the API value may lag behind what the Cited-by service shows.

**Code:** `fetchers/crossref.py:171` — `result.citation_count = msg.get("is-referenced-by-count")`

### 2.2 OpenAlex — `cited_by_count`

**What it counts:** Citations from the merged OpenAlex scholarly graph, which integrates CrossRef, PubMed, the former Microsoft Academic Graph (MAG), and other sources.

**Why it's consistently the highest:**
- **Broadest corpus:** Inherits MAG's web-crawled data plus CrossRef publisher deposits and PubMed records. This means it counts citations from sources that CrossRef alone cannot see.
- **Includes preprints and less-established venues:** MAG crawled broadly, indexing works that other databases skip.
- **Deduplication challenges:** While OpenAlex deduplicates works, the broad ingestion means it may occasionally count citations from sources that other databases would not consider "scholarly."

**API vs. website discrepancy:** OpenAlex has a known timing lag — the pre-computed `cited_by_count` stored on the work object is not always in sync with the live search index. The `counts_by_year` field is pre-calculated and updated infrequently (every few months), so:
- Summing `counts_by_year` can be **lower** than `cited_by_count` (only covers last 10 years)
- Paradoxically, `counts_by_year` sums can also be **higher** than `cited_by_count` due to a known aggregation bug
- The web UI may show a different count than the API because it queries the live index

**Code:** `fetchers/openalex.py:154` — `result.citation_count = data.get("cited_by_count")`

### 2.3 Semantic Scholar — `citationCount`

**What it counts:** Citations from S2's own corpus of academic papers and preprints, built through publisher partnerships and PDF extraction.

**Why it's typically 5-25% lower than OpenAlex:**
- **Narrower scope:** Focuses on academic articles and preprints. Book coverage is very limited, patents are excluded entirely.
- **Reference extraction issues:** Has known problems extracting references from certain PDF formats and external web versions.
- **No conference proceedings bias:** While strong in CS/AI conference papers, it may miss citations from journals outside its core coverage areas.

**API vs. website discrepancy:** S2 adds new content daily. The API returns the current computed count, but there can be delays between when a citing paper is ingested and when its citation links are resolved. The website may show slightly different counts due to caching.

**Code:** `fetchers/semantic_scholar.py:88` — `result.citation_count = data.get("citationCount")`

### 2.4 Europe PMC — `citedByCount`

**What it counts:** Citations from open citation data, scoped to the life sciences literature.

**Why it's consistently the lowest (often 50%+ below OpenAlex):**
- **Open citation data only:** Relies on open citation datasets, which are significantly smaller than proprietary indexes (Web of Science, Scopus). Europe PMC explicitly states this: "The citation dataset available to Europe PMC is based on open citation data and is smaller than those held by subscription-based services."
- **Life sciences focus:** Primarily indexes PubMed, PMC, and Agricola records. A paper cited heavily by computer science or engineering works will have those citations missing from Europe PMC.
- **Requires PubMed ID resolution:** Citation matching depends on resolving references to PubMed IDs. References that can't be matched to a PMID are missed.

**API vs. website discrepancy:** The `citedByCount` field in the API search response should match what the website shows for the same record, since both query the same underlying index. However, Europe PMC updates its citation links periodically (not real-time), so there can be a lag after a new citing paper is published.

**Code:** `fetchers/europe_pmc.py:78-80` — `result.citation_count = rec.get("citedByCount")`

### 2.5 OpenAIRE — BIP! `citationCount`

**What it counts:** Citations computed by the BIP! framework using data from OpenCitations COCI dataset and other open citation sources, over a deduplicated citation network.

**Why it varies (sometimes close to CrossRef, sometimes divergent):**
- **OpenCitations-based:** Uses the COCI (CrossRef Open Citation Index) and POCI (PubMed Open Citation Index) datasets. These are subsets of CrossRef and PubMed citation data that publishers have made openly available.
- **Deduplication effect:** Since v10, BIP! deduplicates citation network nodes using OpenAIRE's algorithm, which avoids double-counting citations from multiple versions of the same work. This can make its count lower than raw CrossRef counts.
- **Periodic computation:** BIP! indicators are computed periodically (not real-time), so they reflect a snapshot that may lag behind other sources.

**API vs. website discrepancy:** The OpenAIRE API returns BIP! indicators that were computed in batch. The OpenAIRE Explore website may show different numbers if it's querying a more recently computed batch.

**Code:** `fetchers/openaire.py:169-171` — `result.citation_count = int(citation_impact.get("citationCount"))`

---

## 3. Why API Values Differ From What Websites Show

There are two distinct discrepancy types:

### 3.1 Cross-Source Discrepancies (API-to-API)

These are **expected and inherent** — each source uses different:

| Factor | Effect |
|--------|--------|
| **Corpus scope** | OpenAlex (broadest, MAG + CrossRef + PubMed) > CrossRef (publisher deposits only) > S2 (articles/preprints) > Europe PMC (life sciences open citations) |
| **Citation matching method** | CrossRef: DOI matching from deposited refs. OpenAlex: inherited MAG matching + CrossRef. S2: PDF extraction + NLP. Europe PMC: PubMed ID resolution |
| **What counts as a "work"** | OpenAlex includes preprints, blog posts crawled by MAG. CrossRef only counts DOI-registered works. S2 excludes books/patents |
| **Deduplication** | A preprint and its published version may be separate works in one system but merged in another, affecting citation attribution |
| **Update frequency** | Real-time (CrossRef, on deposit) vs. periodic batch (OpenAIRE BIP!, every few months) vs. daily (OpenAlex, S2) |

### 3.2 Same-Source API vs. Website Discrepancies

These happen because:

1. **Pre-computed vs. live counts:** APIs often return pre-computed/cached `citation_count` values, while websites may query the live search index. OpenAlex explicitly documents this timing lag.

2. **Batch update schedules:** OpenAIRE BIP! indicators are computed in periodic batches. The API and website may be serving different batch versions.

3. **API versioning:** CrossRef's JSON API (`is-referenced-by-count`) and XML API (`citedby-count`) can return different values ([GitHub Issue #211](https://github.com/CrossRef/rest-api-doc/issues/211)).

4. **Publisher permissions:** Some publishers don't allow CrossRef to expose citation data via the public API, causing `is-referenced-by-count = 0` even when citations exist. The Cited-by member service may show the actual count.

5. **Caching layers:** CDNs and API gateway caches can serve stale data for minutes to hours after updates.

---

## 4. Extreme Cases Explained

### pandas on Zenodo: 44 (DataCite) vs. 1,668 (OpenAlex) — 3,691% spread

DataCite's `citationCount` for Zenodo records only counts citations from other DataCite-registered works (mostly datasets). OpenAlex indexes the published paper version and counts all citations from its merged graph. This is a **corpus scope mismatch**, not a bug.

### FAIR Principles: 6,148 (Europe PMC) vs. 16,440 (OpenAlex) — 167% spread

Europe PMC only has open citation data from life sciences. The FAIR paper is heavily cited by computer science, library science, and policy works — most of which are outside Europe PMC's scope. OpenAlex sees all of these.

### GTEx: 265 (OpenAlex) vs. 7,734 (OpenAIRE) — documented in source-connections.md

OpenAlex resolved to a **different version** of the work (the pilot paper vs. the consortium paper). This is a **DOI-to-record mapping error**, not a counting methodology difference. Title verification is essential.

### fastMRI arXiv: 569 (OpenAlex) vs. 9 (OpenAIRE)

arXiv preprints have **fragmented identity** — the arXiv ID, the DataCite DOI (`10.48550/arxiv.*`), and the published version DOI all exist independently. Citations may be split across these identities differently in each system.

---

## 5. How the Codebase Handles This

The system correctly follows the design principle: **"Do NOT silently pick a winner."**

### Fetching (Phase 1)
Each fetcher extracts the native citation count field:
- `crossref.py:171` → `is-referenced-by-count`
- `openalex.py:154` → `cited_by_count`
- `semantic_scholar.py:88` → `citationCount`
- `europe_pmc.py:78` → `citedByCount`
- `openaire.py:169-171` → BIP! `citationCount`
- `datacite.py:149` → `citationCount`
- `nih_reporter.py:66-67` → `citationCount`

### Reconciliation (Phase 4)
`reconciliation/engine.py:34` flags citation count conflicts as **HIGH risk** when any two sources disagree.

### Analysis (Phase 4)
`analyses/impact_profile.py:79-92` computes min/max/median/spread across all reporting sources. The narrative flags "significant cross-source divergence" when spread > 30% of median (line 170).

### What's NOT done (by design)
- No averaging or consensus computation
- No "authoritative source" selection
- All values preserved with provenance
- Consumer decides which to trust

---

## 6. Recommendations

### For consumers of this data

1. **Use OpenAlex for broadest coverage** — it consistently captures the most citations due to its merged corpus.
2. **Use CrossRef for publisher-verified counts** — lower but backed by formal reference deposits.
3. **Use Europe PMC only for biomedical scope** — it undercounts by design for non-life-science papers.
4. **Compare median across sources** as a reasonable estimate, but know it has a downward bias (Europe PMC pulls it down).
5. **Always check that titles match** across sources to catch DOI-to-record mapping errors (GTEx case).

### For this codebase

1. **Add `retrieved_at` timestamps per source** — to help diagnose whether API-to-website differences are timing-related.
2. **Consider adding a `citation_count_notes` field** — to flag known issues like "Europe PMC undercount expected for non-biomedical DOIs."
3. **Log OpenAlex `updated_date`** — this field from the API response indicates when the record was last refreshed.
4. **Consider querying OpenAlex `cites` filter** for a live count instead of relying solely on the pre-computed `cited_by_count`, to reduce API-to-website discrepancies for OpenAlex specifically.
5. **Add title-match verification** — compare titles across sources and warn when a source may have resolved to a different work (prevents GTEx-type errors).

---

## Sources

- [CrossRef Cited-by Service](https://www.crossref.org/services/cited-by/)
- [CrossRef REST API Issue #199 — Incorrect Citation Count](https://github.com/CrossRef/rest-api-doc/issues/199)
- [CrossRef REST API Issue #211 — is-referenced-by-count vs citedby-count differ](https://github.com/CrossRef/rest-api-doc/issues/211)
- [OpenAlex FAQ](https://docs.openalex.org/additional-help/faq)
- [OpenAlex counts_by_year discrepancy](https://groups.google.com/g/openalex-community/c/1gUorSyDGT8)
- [openalexR Issue #115 — cited_by_count discrepancy](https://github.com/ropensci/openalexR/issues/115)
- [Semantic Scholar FAQ](https://www.semanticscholar.org/faq)
- [Europe PMC Help — Citation Data](https://europepmc.org/help)
- [OpenAIRE Graph — BIP! Impact Indicators](https://graph.openaire.eu/docs/graph-production-workflow/indicators-ingestion/impact-indicators/)
- [OpenCitations Service Guide](https://www.openaire.eu/opencitations-guide)
- [Citation counts across databases — comparative analysis](https://www.sciencedirect.com/science/article/abs/pii/S1751157724001305)
- [ResearchGate discussion: Why do citation counts vary across sources?](https://www.researchgate.net/post/Why_do_citation_counts_vary_across_OpenAlex_Web_of_Science_Scopus_and_Google_Scholar)
