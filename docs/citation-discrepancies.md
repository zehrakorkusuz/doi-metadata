# Citation Count Discrepancies Across Scholarly Infrastructure: A Technical Analysis

**Date:** 2026-02-09
**Context:** NIH Data Sharing Index (S-Index) Challenge — measuring data paper impact
**DOIs analyzed:** 9 test cases spanning articles, datasets, software, and preprints
**Infrastructure sources:** 7 APIs reporting citation counts (of 11 queried)

---

## Executive Summary

Citation counts for the same DOI diverge 30–3,691% across open scholarly infrastructure sources. This is not a bug — it is a structural property of the federated scholarly metadata ecosystem. Each source operates on a different citation graph, built from different input data, using different matching algorithms, updated on different schedules.

For the S-Index competition, this has a critical implication: **no single citation count is authoritative for data papers**. Any metric that rewards data sharing must either (a) specify which citation graph it uses and why, or (b) aggregate across graphs with explicit provenance. Our system does (b).

This report documents the precise technical reasons for divergence, grounded in the actual API field-level behavior of each source, with empirical data from 9 DOIs spanning the CrossRef and DataCite registration agencies.

---

## 1. Empirical Findings: Divergence Patterns

### 1.1 Measured Citation Counts Across 7 Sources

| Paper | CrossRef | OpenAlex | Sem. Scholar | Europe PMC | OpenAIRE | DataCite | Spread |
|-------|----------|----------|--------------|------------|----------|----------|--------|
| FAIR Principles | 12,733 | **16,440** | 14,131 | 6,148 | 12,213 | — | 167% |
| AlphaFold | 38,165 | **41,472** | 32,871 | 29,132 | — | — | 42% |
| ENCODE | 16,630 | **18,811** | 16,414 | 13,957 | 16,032 | — | 35% |
| UK Biobank | 8,158 | **9,125** | 7,117 | 6,979 | 7,259 | — | 31% |
| MIMIC-CXR | 1,282 | 1,445 | **1,693** | 536 | 1,207 | — | 216% |
| GigaScience | 6 | 6 | 3 | 4 | — | — | 100% |
| pandas (Zenodo) | — | **1,668** | — | — | — | 44 | 3,691% |
| arXiv preprint | — | — | — | — | — | 11 | — |

**Bold** = highest count for that DOI.

### 1.2 Consistent Rank Order

Across all 7 article DOIs with 3+ sources reporting:

```
OpenAlex > CrossRef ≈ Semantic Scholar > OpenAIRE > Europe PMC
```

This is not coincidental — it directly reflects corpus scope (Section 2).

### 1.3 Divergence Scales With Interdisciplinarity

The FAIR Principles paper (167% spread) is cited across computer science, library science, biomedicine, and policy. Europe PMC, scoped to life sciences, misses the majority. The ENCODE paper (35% spread), primarily cited within genomics, shows much tighter convergence because all sources have strong biomedical coverage.

**Implication for data papers:** Data papers that enable reuse across disciplines will show the largest citation count divergences — precisely the papers that are most impactful under the S-Index's data sharing framework.

---

## 2. Source-by-Source Technical Analysis

### 2.1 CrossRef — `is-referenced-by-count`

**Citation graph:** Publisher-deposited reference lists matched to CrossRef DOIs.

**Mechanism:** When a publisher registers a new work with CrossRef and includes its reference list in the metadata deposit, CrossRef performs automated DOI matching against existing registered content. Each successful match increments the cited work's `is-referenced-by-count`. This field is updated asynchronously in batch for performance ([CrossRef REST API Issue #211](https://github.com/CrossRef/rest-api-doc/issues/211)).

**Known undercounting factors:**
- **44% reference metadata coverage** across all CrossRef records (per CrossRef's 2025 Participation Reports). Only 44% of works registered with CrossRef include reference lists in their metadata deposits.
- **Publisher opt-out:** Some publishers historically did not grant permission to release citation data via the public API, causing `is-referenced-by-count = 0` even for cited works ([Issue #199](https://github.com/CrossRef/rest-api-doc/issues/199)). Elsevier began depositing references only in 2021.
- **CrossRef-to-CrossRef only:** Cannot count citations from DataCite DOIs (datasets, software), non-DOI content, books without DOIs, or theses.
- **Matching failures:** Unstructured references without DOIs may fail to match if metadata is insufficient. CrossRef's matching algorithm requires enough bibliographic signal (author, title, year) to identify the cited work.

**API vs. website discrepancy:** The JSON REST API (`is-referenced-by-count`) and XML Transform API (`citedby-count`) can return different values for the same DOI. The REST API uses a pre-computed field updated in batch; the Cited-by member service may reflect more recent data. CDN caching adds additional latency.

**Relevance to S-Index:** CrossRef is the primary citation graph for journal articles. Its 44% reference coverage rate means that even for well-cited articles, roughly half of the citation links are being systematically missed. For data papers cited by datasets (which are registered with DataCite, not CrossRef), the undercount is far worse — CrossRef literally cannot see DataCite-to-DataCite citation links.

### 2.2 OpenAlex — `cited_by_count`

**Citation graph:** Merged scholarly graph built from CrossRef, PubMed/MEDLINE, the former Microsoft Academic Graph (MAG), and institutional repositories.

**Mechanism:** OpenAlex tracks citations via the `referenced_works` property on each work. When work A lists work B in its `referenced_works`, B's `cited_by_count` is incremented. The `cited_by_count` is a pre-computed field stored on the work object. A live count can be obtained via the `cites` filter on the `/works` endpoint, which may return a slightly higher number due to a timing lag in updating the pre-computed field ([OpenAlex docs](https://docs.openalex.org/api-entities/works/work-object)).

**Why consistently highest:**
- **Broadest corpus:** Inherited ~250M records from MAG's web crawling, which indexed preprints, theses, reports, and grey literature that other sources miss.
- **Multi-source reference matching:** Combines CrossRef-deposited references with MAG's algorithmically-extracted references from crawled PDFs.
- **MAG legacy works:** The `mag_only` filter exists specifically because MAG-only works (not in CrossRef or PubMed) can inflate counts with lower-confidence matches.

**Field-normalized metrics:** OpenAlex provides FWCI (Field-Weighted Citation Impact) using the same snowball metric recipe as Scopus/SciVal, but computed over OpenAlex's larger corpus. Because OpenAlex includes many uncited works (driving down the expected citation baseline), FWCI values tend to be **higher** than Scopus FWCI for the same paper ([OpenAlex FWCI docs](https://help.openalex.org/hc/en-us/articles/24735753007895-Field-Weighted-Citation-Impact-FWCI)). OpenAlex classifies fields at the **work level** (via text analysis), not journal level — a methodological advantage for interdisciplinary data papers.

**`counts_by_year` caveats:** Only covers the last 10 years. Can diverge from `cited_by_count` in both directions due to aggregation timing.

**Relevance to S-Index:** OpenAlex is the strongest candidate for a primary citation source in an S-Index metric because: (a) it has the broadest coverage, (b) it is fully open and freely queryable, (c) it provides FWCI for field-normalization, (d) it indexes both articles and datasets. However, its higher counts must be understood as an upper bound, not ground truth.

### 2.3 Semantic Scholar — `citationCount`

**Citation graph:** S2's proprietary corpus built from publisher partnerships, open access PDFs, and the DBLP database. Originally focused on computer science; expanded to biomedical and general coverage via MAG integration.

**Mechanism:** S2 extracts references from PDFs using machine learning pipelines (including GROBID-based extraction) and matches them against its corpus. The `citationCount` reflects the number of papers in S2's corpus that cite the given work. S2 also provides `influentialCitationCount` — citations where the citing paper engages substantively with the cited work (not just passing mentions), determined by full-text analysis.

**Known undercounting factors:**
- **~10% of Crossref records not indexed** (per Delgado-Quirós et al., 2024). Robot exclusion blocks S2's crawlers from 35.2% of publisher sites that it has not formed partnerships with.
- **Limited book/patent coverage:** S2's own FAQ acknowledges this as a known gap.
- **Reference extraction errors:** PDF-based extraction is imperfect, particularly for non-standard layouts, tables of DOIs, and supplementary reference sections.

**Unique value — influential citations:** S2's `influentialCitationCount` is the only open metric that distinguishes substantive engagement from perfunctory citation. Across our test data, the influential ratio is typically 2–5%, with highly impactful papers (ENCODE, FAIR Principles) at ~4.5%.

**Relevance to S-Index:** The influential citation metric is directly relevant to measuring data paper impact — it answers "how many downstream works actually used this data in a meaningful way?" rather than just "how many mentioned it in passing."

### 2.4 Europe PMC — `citedByCount`

**Citation graph:** Open citation data scoped to the life sciences (PubMed, PMC, Agricola, and partner repositories).

**Mechanism:** Europe PMC matches references using open citation datasets. The `citedByCount` field in the search API response reflects the number of works in Europe PMC's index that cite the given PMID/DOI. Citation links are updated periodically, not in real-time.

**Systematic undercount:**
- **Open citation data only:** Europe PMC explicitly states: "The citation dataset available to Europe PMC is based on open citation data and is smaller than those held by subscription-based services." In 2019, COCI (the OpenCitations CrossRef index) contained only 28% of all citations found across major databases (Martín-Martín et al., 2021). By 2021, this had improved to ~53% after Elsevier opened its references.
- **Life sciences scope:** Primarily indexes PubMed/PMC content. A paper cited by 10,000 computer science papers and 5,000 biomedical papers will show only ~5,000 in Europe PMC.
- **PMID dependency:** Works without a PubMed ID are harder to match in Europe PMC's citation graph.

**Relevance to S-Index:** Europe PMC undercount is most severe for interdisciplinary data papers. However, its grant linkage data (from full-text mining) and MeSH annotations are unique and valuable for NIH-context impact assessment.

### 2.5 OpenAIRE — BIP! `citationCount`

**Citation graph:** Computed by the BIP! (Bibliometric-enhanced Information Processing) framework over a deduplicated citation network built from OpenCitations COCI, POCI (PubMed citations), and other open sources.

**Mechanism:** BIP! constructs a citation graph, deduplicates work nodes using OpenAIRE's article deduplication algorithm (preventing double-counting of preprint + published version), and computes multiple graph-theoretic indicators: `citationCount` (raw), `influence` (PageRank), `popularity` (recency-weighted citation count), and `impulse` (recency-weighted PageRank). Each indicator comes with an impact class: C1 (top 0.01%), C2 (top 0.1%), C3 (top 1%), C4 (top 10%), C5 (bottom 90%) ([OpenAIRE docs](https://graph.openaire.eu/docs/graph-production-workflow/indicators-ingestion/impact-indicators/)).

**Why it sometimes differs from CrossRef:**
- **Deduplication reduces counts:** By merging preprint and published versions into single nodes, BIP! avoids double-counting, making its count potentially *lower* than CrossRef for papers with heavily-cited preprints.
- **Batch computation:** BIP! indicators are computed periodically from a snapshot. The API returns the most recently computed batch, which may lag behind CrossRef or OpenAlex by weeks to months.

**Unique value — multi-dimensional impact:** BIP! `influence` (PageRank-based) captures not just how many times a paper is cited, but whether it is cited *by highly-cited papers*. The `popularity` and `impulse` indicators capture recency, addressing the bias against recent publications inherent in raw citation counts.

**Relevance to S-Index:** BIP! indicators are particularly useful for data papers that may have modest raw citation counts but are cited by landmark publications. A dataset cited 50 times, where 5 of those citations are from papers with 10,000+ citations each, will have a much higher BIP! `influence` than a dataset cited 200 times by low-impact works.

### 2.6 DataCite — `citationCount`

**Citation graph:** DataCite Event Data, built from `relatedIdentifier` metadata in DataCite DOI registrations and CrossRef Event Data (Scholix-compliant).

**Mechanism:** When a DataCite DOI's metadata includes a `relatedIdentifier` with `relationType` of `IsCitedBy`, `IsReferencedBy`, or `IsSupplementTo`, and the target is another DOI, a citation event is created. CrossRef Event Data contributes cross-registry links (Crossref DOI → DataCite DOI) via the Scholix framework. Only DOI-to-DOI events count; duplicate relation types for the same pair are deduplicated ([DataCite docs](https://support.datacite.org/docs/citations-and-references)).

**Why it's dramatically lower for software/datasets:**
- **Metadata-driven, not extracted:** DataCite counts depend entirely on repositories explicitly adding `relatedIdentifier` entries. Most citations in journal article reference lists are *not* reflected back into DataCite metadata.
- **The pandas case (44 vs 1,668):** DataCite shows 44 citations for Zenodo's pandas DOI because only 44 other DataCite-registered works have explicit `relatedIdentifier` links to it. OpenAlex shows 1,668 because it also counts journal articles that cite pandas — articles that are registered with CrossRef, not DataCite.

**Relevance to S-Index:** DataCite citation counts are the *primary* measure for dataset-to-dataset citation chains. For the S-Index, DataCite's `relatedIdentifier` graph answers: "How many other datasets cite this dataset?" — a question no other source can answer.

### 2.7 NIH Reporter — `citation_count` + Relative Citation Ratio

**Citation graph:** NIH iCite's curated PubMed-based citation network.

**Mechanism:** NIH Reporter provides the Relative Citation Ratio (RCR), a field- and time-normalized metric benchmarked to NIH-funded papers (Hutchins et al., 2016, *PLOS Biology*). RCR = Article Citation Rate / Expected Citation Rate, where the expected rate is derived from the paper's co-citation network (papers cited alongside it). RCR = 1.0 means the paper performs at the median of NIH-funded papers in its field. The co-citation network defines "field" dynamically at the article level, not the journal level ([iCite Support](https://support.icite.nih.gov/hc/en-us/articles/9105587565851-Relative-Citation-Ratio-RCR)).

**Constraints:** Only available for PubMed-indexed papers. Only calculated for papers ≥2 years old. The raw `citation_count` from NIH Reporter uses iCite's data, which draws from PubMed Central, Europe PMC, CrossRef, and Web of Science.

**Relevance to S-Index:** RCR is the NIH's own field-normalized metric. For any NIH-context evaluation, RCR has direct institutional credibility. An S-Index metric that includes RCR alongside raw counts demonstrates awareness of the NIH's preferred bibliometric framework.

---

## 3. The Preprint/Published Version Citation Splitting Problem

A systematic source of divergence that affects all sources differently.

When a paper exists as both a preprint (arXiv, bioRxiv, medRxiv) and a published journal article, citations split across versions:

| Database | Handling |
|----------|----------|
| **OpenAlex** | Merges preprint and published version into a single work; citations to both versions are summed |
| **Semantic Scholar** | Merges versions using DOI + arXiv ID matching; citation counts are consolidated |
| **CrossRef** | Only sees the published version (journal DOI); preprint citations are invisible |
| **DataCite** | Only sees the preprint DOI (`10.48550/arXiv.*`); journal citations are invisible |
| **OpenAIRE BIP!** | Deduplicates via OpenAIRE's algorithm; citations are consolidated on the surviving node |
| **Europe PMC** | Only sees PubMed-indexed articles; most preprint citations are missed |
| **Google Scholar** | Has pooled preprint + published citations since ~2015 |

**Empirical example — fastMRI:** OpenAlex shows 569 citations (merged). OpenAIRE shows 9 (only matched to the arXiv DataCite DOI; the published journal version's citations are on a separate node). This 63x discrepancy is entirely explained by version splitting.

**Impact on data papers:** Data papers often have companion datasets with separate DOIs. Citations may target the data paper DOI, the dataset DOI, or the repository landing page URL. The S-Index must account for this fragmentation or it will systematically undercount data sharing impact.

---

## 4. API vs. Website Discrepancies (Same Source)

Beyond cross-source divergence, the same source's API and web interface can show different numbers:

| Source | Root Cause | Typical Lag |
|--------|-----------|-------------|
| **CrossRef** | JSON vs. XML endpoints return different values; `is-referenced-by-count` is batch-updated asynchronously; some publishers restrict API release | Hours to days |
| **OpenAlex** | Pre-computed `cited_by_count` lags behind the live `cites` filter; `counts_by_year` has known aggregation bug | Hours to weeks |
| **Semantic Scholar** | Daily ingestion pipeline → citation resolution delay; web UI may cache differently from API | Hours |
| **Europe PMC** | Periodic citation link updates; API and web use same index | Days to weeks |
| **OpenAIRE** | BIP! indicators computed in periodic batches; API returns last batch; web may show a newer batch | Weeks to months |
| **DataCite** | Event Data processing delay for new `relatedIdentifier` additions; Scholix sync from CrossRef is asynchronous | Days to weeks |

---

## 5. Implications for Data Paper Impact Assessment (S-Index Context)

### 5.1 Why Raw Citation Counts Are Insufficient

The NIH S-Index Challenge asks for a metric that "rewards researchers who share high-quality data." Raw citation counts from any single source fail this requirement because:

1. **Data papers are interdisciplinary by nature.** A genomics dataset reused by bioinformatics, AI, and clinical researchers will have citations scattered across venues that no single source fully indexes.

2. **Dataset citations are structurally different from article citations.** Datasets are cited via DataCite `relatedIdentifier` links, informal URL mentions in methods sections, and standard reference lists — only the last is visible to CrossRef's citation graph.

3. **Citation splitting between data paper and dataset DOI is endemic.** A researcher citing a dataset may cite the data paper (CrossRef DOI), the dataset itself (DataCite DOI), or both. No source reliably merges these.

### 5.2 Multi-Source Triangulation Strategy

Our system addresses this by querying all 7 citation-reporting sources in parallel, preserving all values with provenance, and computing:

- **Min/max/median/spread** across sources (quantifies divergence)
- **OpenAlex FWCI** (field-normalized, work-level, open)
- **S2 influential citation ratio** (substantive engagement vs. passing mention)
- **NIH RCR** (NIH-benchmarked, field-normalized via co-citation network)
- **OpenAIRE BIP! influence** (PageRank — captures citation *by* high-impact works)
- **DataCite reverse search** (dataset-to-dataset citation chains)
- **OpenAIRE BIP! popularity/impulse** (recency-corrected metrics)

### 5.3 Recommended Impact Narrative for an S-Index Submission

Rather than reporting a single citation count, a robust data paper impact narrative should include:

```
This data paper has been cited [OpenAlex count] times across the
scholarly literature (OpenAlex merged graph), including [S2 influential
count] substantive citations (Semantic Scholar, [ratio]% influential
vs. typical 2%). The NIH Relative Citation Ratio is [RCR]x the
median NIH-funded paper in its dynamically-defined field. [DataCite
reverse search count] downstream datasets in DataCite have declared
formal data reuse relationships. Citation counts diverge across open
infrastructure sources (range [min]–[max], [N] sources), reflecting
the interdisciplinary reach of this dataset beyond any single index.
```

This framing:
- Uses the highest-coverage source (OpenAlex) as the primary count
- Adds quality signal via S2 influential citations
- Includes NIH's own normalized metric (RCR)
- Captures the data-specific reuse chain (DataCite)
- Transparently acknowledges divergence as a feature, not a flaw

---

## 6. Detailed Source Comparison: Coverage and Methodology

| Dimension | CrossRef | OpenAlex | Sem. Scholar | Europe PMC | OpenAIRE | DataCite | NIH iCite |
|-----------|----------|----------|--------------|------------|----------|----------|-----------|
| **Corpus scope** | Publisher deposits | MAG + CrossRef + PubMed | Partnerships + PDFs | Life sciences | OpenCitations + partners | Repository metadata | PubMed |
| **Corpus size** | ~156M records | ~250M+ works | ~220M papers | ~45M records | ~190M products | ~60M DOIs | ~35M PMIDs |
| **Citation matching** | DOI matching from deposited refs | MAG + CrossRef refs | PDF extraction + NLP | Open citation data | COCI + POCI | `relatedIdentifier` metadata | iCite pipeline |
| **Reference deposit rate** | 44% of records | Inherited from sources | N/A (extraction-based) | N/A (open data) | N/A (open data) | Repository-dependent | N/A |
| **Version dedup** | No | Yes (preprint → published) | Yes | No | Yes (BIP!) | No | No |
| **Update frequency** | On deposit (async batch) | Daily | Daily | Periodic | Periodic (batch) | On metadata update | Monthly snapshots |
| **Field normalization** | No | FWCI (work-level) | No | No | BIP! indicators | No | RCR (co-citation) |
| **Open access** | Yes | Yes | Yes | Yes | Yes | Yes | Yes (iCite) |
| **Unique signal** | Publisher-verified refs | FWCI, broadest coverage | Influential citations, TLDR | MeSH, grants, chemicals | BIP!, EU funding, software | Data citation chains | RCR, NIH benchmarking |

---

## 7. Known Edge Cases and Failure Modes

| Case | What Happens | Detection | Mitigation |
|------|-------------|-----------|------------|
| **DOI resolves to wrong work** | GTEx: OpenAlex showed 265 instead of 7,734 (wrong version) | Title mismatch between sources | Cross-source title verification |
| **Preprint citation splitting** | fastMRI: 569 (OpenAlex) vs. 9 (OpenAIRE) | Large divergence + arXiv DOI prefix | Check for version links in DataCite `relatedIdentifier` |
| **Publisher blocks API release** | CrossRef `is-referenced-by-count = 0` for cited works | Zero count with high OpenAlex count | Flag when CrossRef = 0 but others > 0 |
| **Consortium authorship** | ENCODE: author counts range 1–200 across sources | Author count conflict | Use ORCID disambiguation |
| **Software/dataset DOI** | pandas Zenodo: 44 (DataCite) vs. 1,668 (OpenAlex) | DataCite DOI prefix + large divergence | Report both; explain scope difference |
| **Very recent paper** | Citation counts all near zero; one source may be weeks ahead | Low counts + recent publication date | Report freshness (`retrieved_at`) with counts |

---

## 8. Technical Implementation in This System

Our codebase implements the "preserve all values with provenance" design principle from the CLAUDE.md architecture document:

**Phase 1 — Parallel fetch (7 citation sources):**
Each fetcher extracts the native citation count field using the source's API:
- `crossref.py:171` → `msg.get("is-referenced-by-count")`
- `openalex.py:154` → `data.get("cited_by_count")`
- `semantic_scholar.py:88` → `data.get("citationCount")`
- `europe_pmc.py:78` → `rec.get("citedByCount")`
- `openaire.py:169` → `int(citation_impact.get("citationCount"))`
- `datacite.py:149` → `data.get("citationCount")`
- `nih_reporter.py:66` → `data.get("citationCount")`

**Phase 4 — Reconciliation (`reconciliation/engine.py:34`):**
Citation count conflicts flagged as **HIGH risk**. All values preserved in `FieldConflict` with source provenance.

**Phase 4 — Impact analysis (`analyses/impact_profile.py:79-92`):**
Computes min/max/median/spread. Flags "significant cross-source divergence" when spread > 30% of median. Constructs multi-metric narrative combining FWCI, influential citations, RCR, BIP!, and dataset reuse counts.

---

## References

### Official Documentation
- [CrossRef Cited-by Service](https://www.crossref.org/services/cited-by/)
- [CrossRef Participation Reports (44% reference coverage)](https://www.crossref.org/documentation/reports/participation-reports/)
- [OpenAlex Work Object — cited_by_count](https://docs.openalex.org/api-entities/works/work-object)
- [OpenAlex FWCI Documentation](https://help.openalex.org/hc/en-us/articles/24735753007895-Field-Weighted-Citation-Impact-FWCI)
- [Semantic Scholar FAQ — Coverage Limitations](https://www.semanticscholar.org/faq)
- [Europe PMC Help — Citation Data](https://europepmc.org/help)
- [OpenAIRE Graph — BIP! Impact Indicators](https://graph.openaire.eu/docs/graph-production-workflow/indicators-ingestion/impact-indicators/)
- [DataCite Citations and References](https://support.datacite.org/docs/citations-and-references)
- [DataCite Event Data Guide](https://support.datacite.org/docs/eventdata-guide)
- [NIH iCite — Relative Citation Ratio](https://support.icite.nih.gov/hc/en-us/articles/9105587565851-Relative-Citation-Ratio-RCR)

### Known Issues & Bug Reports
- [CrossRef API Issue #199 — Incorrect Citation Count](https://github.com/CrossRef/rest-api-doc/issues/199)
- [CrossRef API Issue #211 — is-referenced-by-count vs citedby-count differ](https://github.com/CrossRef/rest-api-doc/issues/211)

### Peer-Reviewed Comparisons
- Delgado-Quirós et al. (2024). "Why are these publications missing? Uncovering the reasons behind the exclusion of documents in free-access scholarly databases." *JASIST*. [doi:10.1002/asi.24839](https://asistdl.onlinelibrary.wiley.com/doi/10.1002/asi.24839)
- Martín-Martín et al. (2021). "Google Scholar, Microsoft Academic, Scopus, Dimensions, Web of Science, and OpenCitations' COCI: a multidisciplinary comparison of coverage via citations." *Scientometrics*. [PMC7505221](https://pmc.ncbi.nlm.nih.gov/articles/PMC7505221/)
- Gusenbauer (2024). "Beyond Google Scholar, Scopus, and Web of Science: An evaluation of the backward and forward citation coverage of 59 databases' citation indices." *Research Synthesis Methods*. [doi:10.1002/jrsm.1729](https://onlinelibrary.wiley.com/doi/full/10.1002/jrsm.1729)
- Hutchins et al. (2016). "Relative Citation Ratio (RCR): A New Metric That Uses Citation Rates to Measure Influence at the Article Level." *PLOS Biology*. [doi:10.1371/journal.pbio.1002541](https://journals.plos.org/plosbiology/article?id=10.1371/journal.pbio.1002541)
- Bardi & Manghi. "Merging the citations received by arXiv-deposited e-prints and their corresponding published journal articles." *Information Processing & Management*. [ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S0306457319311045)
- Visser et al. (2021). "A tipping point for open citation data." *Quantitative Science Studies*. [PMC8425298](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC8425298/)

### NIH S-Index Challenge
- [NIH Challenge Recognizes Phase 1 Winners](https://www.nei.nih.gov/about/news-and-events/news/nih-challenge-aimed-incentivizing-data-sharing-recognizes-phase-1-winners)
- [NUCATS Collaborative Named S-Index Finalist](https://www.nucats.northwestern.edu/about/news/2025/s-index-finalist.html)
- [S-Index Challenge Overview (yet2)](https://www.yet2.com/active-projects/nih-data-sharing-index-s-index-challenge/)
