# Citation Network Analysis & PageRank Scoring

## Overview

The citation network module builds a directed citation graph from all 11 API sources and computes multi-dimensional authority scores for the queried DOI. Rather than relying on a single source's citation count, it reconstructs a local ego network, runs authority-weighted PageRank with anti-gaming mechanisms, and produces a composite **S-index** that integrates structural, temporal, semantic, and biomedical signals.

**Entry point:** `doi_metadata.analyses.citation_network.analyze_citation_network(result)`

**Output:** `CitationNetworkResult` — contains PageRank scores, S-index, network topology, citation intent profile, citation velocity, field normalization, biomedical signals, author-level metrics, and a narrative summary.

---

## Architecture

```
AggregatedResult (all 11 sources fetched)
 │
 ├─► Graph Building
 │    ├── Inbound citations (papers citing the queried DOI)
 │    ├── Outbound references (papers the queried DOI cites)
 │    ├── DataCite linked datasets
 │    ├── Related works (IsSupplementTo, HasPart, IsCitedBy, etc.)
 │    ├── Edge merging across sources (not first-wins discard)
 │    ├── Self-citation detection (ORCID-first, guarded surname fallback)
 │    └── Citation intent weighting (Methodology, ResultComparison, Background)
 │
 ├─► PageRank Computation
 │    ├── Authority-weighted initialization (citing paper importance → init mass)
 │    ├── Standard PageRank (weighted edges: intent × influential × anti-gaming)
 │    ├── Time-Decay PageRank (exponential recency weighting)
 │    └── Percentile ranking within local graph
 │
 ├─► Supplementary Analyses
 │    ├── Network topology (degree, self-citation fraction, truncation detection)
 │    ├── Citation intent profile (methodology vs background vs result-comparison)
 │    ├── Citation velocity (acceleration/deceleration from counts_by_year)
 │    ├── Field normalization (FWCI from OpenAlex, RCR from NIH, BIP! from OpenAIRE)
 │    ├── Biomedical signals (MeSH, clinical trials, retractions, grants, PMID)
 │    └── Author-level PageRank aggregation
 │
 └─► S-index Computation
      └── Weighted composite of all normalized [0,1] components
```

---

## Data Sources for Graph Construction

The citation graph merges data from every available API source. Each source contributes different types of edges and metadata:

### Source Contributions

| Source | Inbound Citations | Outbound References | Intents | Influential | Citation Count | Additional |
|--------|:-:|:-:|:-:|:-:|:-:|---|
| **Semantic Scholar** | Yes (paginated, ~100) | Yes (with intents) | Yes | Yes | Yes | TLDR, s2_paper_id fallback |
| **CrossRef** | — | Yes (with key, DOI) | — | — | Yes (`is-referenced-by-count`) | `update-to` (retractions), `clinical-trial-number` |
| **OpenAlex** | — | Yes (OpenAlex IDs) | — | — | Yes (`cited_by_count`) | `counts_by_year`, FWCI, `citation_normalized_percentile` |
| **Europe PMC** | — | — | — | — | Yes (`citedByCount`) | MeSH terms, `commentCorrectionList` (retractions/errata) |
| **OpenAIRE** | — | — | — | — | Yes (BIP! `citationCount`) | BIP! influence (global PageRank), popularity, impulse |
| **NIH Reporter** | — | — | — | — | Yes | Relative Citation Ratio (RCR), grant linkages |
| **DataCite** | Yes (reverse search) | — | — | — | — | `relatedIdentifiers` (IsSupplementTo, HasVersion, etc.) |
| **Zenodo** | — | — | — | — | — | Version chains via concept DOI, related works |
| **Dryad** | — | — | — | — | — | Related works |
| **ORCID** | — | — | — | — | — | Author ORCIDs for self-citation detection |
| **Unpaywall** | — | — | — | — | — | OA status (used in other analyses) |

### How Edges Are Created

**Inbound citations** (other papers cite the queried DOI):
- Semantic Scholar provides the richest citation data: DOI, year, `intents` (Background/Methodology/ResultComparison), `isInfluential` flag, and citation `contexts`
- DataCite reverse search discovers datasets that cite the article (e.g., ENCODE → 1,158 datasets)
- Related works with `IsCitedBy` or `IsReferencedBy` relations create inbound edges

**Outbound references** (papers the queried DOI cites):
- CrossRef provides structured references with DOIs (when available) and unstructured strings
- Semantic Scholar provides references with intents and influential flags
- OpenAlex provides `referenced_works` as OpenAlex IDs

**Related works** (non-citation relationships):
- DataCite `relatedIdentifiers` with relation types: `IsSupplementTo`, `HasPart`, `IsNewVersionOf`, etc.
- Dryad `relatedWorks`
- Zenodo version chains
- Direction depends on relation type: `IsCitedBy` → inbound, `Cites`/`IsSupplementTo` → outbound

### Node Identifiers

Each paper in the graph needs a unique identifier:

```
Priority: DOI (lowercased) → s2:{paperId}
```

- DOIs are normalized to lowercase for deduplication
- When only a Semantic Scholar paper ID is available (no DOI), the node uses `s2:{paperId}` as its identifier
- Papers with neither DOI nor S2 ID are skipped (cannot be placed in the graph)

---

## Edge Merging (Not First-Wins Discard)

A critical design decision: the same citation edge can appear from multiple sources (e.g., CrossRef reports "paper A cites paper B" and Semantic Scholar reports the same edge with additional intent data). Rather than discarding duplicate edges, we **merge** them:

```python
edge_map: dict[tuple[str, str], GraphEdge]  # keyed by (source_id, target_id)
```

When the same `(source, target)` pair is seen from a second API:
1. **Intents** are unioned (CrossRef has none → S2 adds "Methodology")
2. **Influential flag** is upgraded (False → True if S2 says influential)
3. **Self-citation flag** is set if either source detects it
4. **Year** is filled from whichever source provides it
5. **API sources** list tracks provenance
6. **Weight is recomputed** from the merged data

This prevents a common bug: CrossRef often provides citation edges first (during parallel fetch) with no intent data, and S2 provides the same edges with rich intent/influential metadata. Without merging, the S2 data would be silently discarded.

### Example

```
CrossRef reports: 10.1000/citer → 10.1234/target (no intents, no influential flag)
S2 reports:       10.1000/citer → 10.1234/target (intent=Methodology, influential=True)

Merged edge:
  source_id: "10.1000/citer"
  target_id: "10.1234/target"
  intents: ["Methodology"]
  is_influential: True
  api_sources: ["crossref", "semantic_scholar"]
  weight: 2.5 × 3.0 = 7.5  (methodology × influential)
```

---

## Edge Weighting

Each edge carries a composite weight computed from three multiplicative signals:

```python
weight = intent_weight × influential_weight × self_citation_penalty
```

### Citation Intent Weighting

Semantic Scholar classifies citation intents into three categories. The intuition: a paper that reuses your method is a stronger endorsement than one that mentions you in the background.

| Intent | Multiplier | Reasoning |
|--------|--------:|---|
| **Methodology** | 2.5x | The citing paper reused or extended the method — strongest signal of influence |
| **ResultComparison** | 1.8x | The citing paper compared results against this work — active engagement |
| **Background** | 0.7x | Perfunctory context citation — weakest signal |
| *(no intent / unknown)* | 1.0x | Neutral weight when intent data is unavailable |

When multiple intents are present, the **maximum** weight is used (a paper cited for both methodology and background gets 2.5x, not an average).

### Influential Citation Boost

Semantic Scholar's `isInfluential` flag identifies citations where the cited paper plays a central role (roughly the top ~2% of citations). These receive a **3.0x multiplier**.

### Self-Citation Penalty

Self-citations (where an author of the queried paper is also an author of the citing paper) receive a **0.1x multiplier** (90% reduction). This is a standard anti-gaming mechanism.

### Combined Weight Examples

| Scenario | Intent | Influential | Self-cite | Weight |
|----------|--------|:-:|:-:|------:|
| S2 methodology citation, influential | Methodology (2.5x) | Yes (3.0x) | No | **7.50** |
| S2 methodology citation, not influential | Methodology (2.5x) | No | No | **2.50** |
| S2 background citation | Background (0.7x) | No | No | **0.70** |
| CrossRef citation (no S2 data) | None (1.0x) | No | No | **1.00** |
| Self-citation, influential, methodology | Methodology (2.5x) | Yes (3.0x) | Yes (0.1x) | **0.75** |
| Self-citation, background | Background (0.7x) | No | Yes (0.1x) | **0.07** |

---

## Self-Citation Detection

Self-citations are detected in two ways, prioritizing precision over recall:

### 1. ORCID Matching (High Confidence)

ORCIDs are collected from the queried paper's author lists across all sources (CrossRef, OpenAlex, S2, Europe PMC, ORCID). Each citing paper's author ORCIDs (when available) are checked against this set. An ORCID match is definitive — it means the same person authored both papers.

```python
# ORCID URLs are normalized: "https://orcid.org/0000-0001-..." → "0000-0001-..."
queried_orcids = {collect from all sources}
if any citing_orcid in queried_orcids:
    → self_citation = True
```

### 2. Surname Fallback (Guarded)

When ORCIDs are unavailable (common for S2 citations, which often lack author names entirely), we fall back to surname matching with two safeguards:

**Common surname exclusion.** 60+ surnames that are too frequent for reliable matching are excluded:

- East Asian: Wang, Li, Zhang, Liu, Chen, Yang, Huang, Zhao, Wu, Zhou, Kim, Lee, Park, Choi, Jung, Kang, Cho, Yoon, Tanaka, Suzuki, Watanabe, Sato, Takahashi, Ito
- Western: Smith, Johnson, Williams, Brown, Jones, Garcia, Miller, Davis
- South Asian: Kumar, Singh, Sharma, Patel
- European: Muller, Schmidt, Schneider, Fischer, Weber, Meyer, Martin, Bernard, Dubois, Petit, Moreau, Rossi, Russo, Ferrari, Esposito, Bianchi, Silva, Santos, Oliveira

**Minimum length.** Surnames shorter than 3 characters are skipped (catches initials and data entry errors).

### Why Not Full Author Name Matching?

Full name matching produces unacceptable false-positive rates in scholarly data:
- Name ordering varies by culture and source (family-first vs given-first)
- Transliteration differences ("Müller" vs "Mueller" vs "Muller")
- Name changes (marriage, legal changes)
- S2 citation records often lack author names entirely, making the comparison moot

ORCID matching is strictly preferred; surname matching is a best-effort fallback.

---

## PageRank Computation

### The Star Graph Problem

The citation graph for a single DOI is a **1-hop ego network**: the queried paper at the center, with citing papers (inbound) and referenced papers (outbound) as leaf nodes. This forms a star topology where standard PageRank degenerates to weighted in-degree — every leaf node has the same (uniform) initial mass, so the center simply accumulates proportional to edge count.

### Authority-Weighted Initialization

We address this by injecting **authority priors**: instead of uniform `1/N` initialization, each node's initial PageRank mass is proportional to its known authority:

```python
init_weight[node] = log(1 + citation_count) + 1.0  # if citation_count known
init_weight[node] = 1.0                             # otherwise
```

This approximates what a 2-hop graph walk would compute: a citation from a paper with 10,000 citations carries more weight than one from a paper with 5 citations, because the well-cited paper would itself receive more PageRank from its own citers.

**Where citation counts come from:** The queried paper's citation count is taken from the maximum across all sources (CrossRef, OpenAlex, S2, Europe PMC, OpenAIRE, NIH). For citing papers, S2's `isInfluential` flag is used as a proxy — influential citers are assigned `5 × median_citation_count` as their authority prior.

### Algorithm

Standard power iteration with damping factor `d = 0.85`:

```
PR(v) = (1 - d) / N + d × Σ [PR(u) × w(u→v) / Σ w(u→*)]
                         u→v
```

Where:
- `N` = total nodes in graph
- `w(u→v)` = edge weight (intent × influential × self-citation)
- Dangling nodes (no outgoing edges) distribute their rank uniformly

**Parameters:**
| Parameter | Value | Reasoning |
|-----------|------:|---|
| Damping factor | 0.85 | Standard value from Brin & Page (1998) |
| Max iterations | 100 | Sufficient for convergence on small ego networks |
| Convergence threshold | 1e-8 | Tight convergence for reproducibility |

### Time-Decay PageRank

A second PageRank variant applies **exponential time decay** to edge weights:

```
time_weight(edge) = edge.weight × exp(-λ × age_years)
```

Where `λ = 0.15` — a citation from 2024 is approximately 3x more valuable than one from 2014. This surfaces papers with growing recent influence rather than accumulated historical citations.

| Citation Age | Decay Factor |
|-------------|------------:|
| 0 years (current) | 1.000 |
| 1 year | 0.861 |
| 2 years | 0.741 |
| 5 years | 0.472 |
| 10 years | 0.223 |
| 20 years | 0.050 |

### Percentile Ranking

Raw PageRank scores are hard to interpret (they depend on graph size). We compute **percentile rank** within the local graph: what fraction of nodes have a score ≤ the queried paper's score.

```python
percentile = count(scores where score ≤ target_score) / total_nodes
```

A percentile of 0.95 means the queried paper has higher PageRank than 95% of the nodes in its local citation graph.

---

## Network Topology

Topology metrics characterize the structure of the citation graph:

| Metric | Description |
|--------|---|
| `total_nodes` | Papers in graph (queried + citing + referenced + datasets) |
| `total_edges` | Directed citation relationships |
| `in_degree` | Number of inbound citations in the graph |
| `out_degree` | Number of outbound references in the graph |
| `self_citation_count` | Inbound edges flagged as self-citations |
| `self_citation_fraction` | `self_citation_count / in_degree` |
| `influential_citation_count` | Inbound edges with S2 influential flag |
| `influential_fraction` | `influential_citation_count / in_degree` |
| `unique_sources_contributing` | Which APIs provided edges (e.g., `["crossref", "semantic_scholar"]`) |
| `graph_is_truncated` | True when known citation count > graph edges |
| `known_citation_count` | Maximum citation count reported by any API |

### Graph Truncation Detection

APIs paginate their results. Semantic Scholar returns at most ~100 citations per request. If OpenAlex reports 18,767 citations but the graph only contains 100 inbound edges, the graph is **truncated** and the narrative warns about it:

```
"Citation network: 103 papers in local graph (100 of ~18767 known citations sampled, 2 outbound references)"
```

This is critical for honest reporting: PageRank on a truncated sample may not represent the full network.

---

## Citation Intent Profile

For papers with Semantic Scholar coverage, we break down inbound citations by their intent:

| Intent | Description |
|--------|---|
| **Methodology** | The citing paper reused, extended, or built upon the method |
| **ResultComparison** | The citing paper compared its results against this work |
| **Background** | The citing paper mentioned this work as context |
| **Unknown** | No intent data available (non-S2 citations) |

Output includes:
- Counts per intent category
- `methodology_fraction` — fraction of classified citations that are methodology
- `dominant_intent` — the most frequent intent category

A high methodology fraction (>15%) is flagged in the narrative as a "method-reuse signal," indicating the paper's primary influence is through its methodology rather than its conclusions.

---

## Citation Velocity

Citation velocity analyzes temporal dynamics using `counts_by_year` data (primarily from OpenAlex):

### Computation

1. **Merge yearly counts** across sources (take max per year to avoid double-counting)
2. **Peak detection:** year with highest citation count
3. **Recent 3-year average:** mean citations/year for the last 3 years
4. **Acceleration:** `(recent_3yr_avg - prior_3yr_avg) / prior_3yr_avg`

### Trend Classification

| Trend | Condition |
|-------|---|
| **Accelerating** | Acceleration > +20% (citations growing faster) |
| **Decelerating** | Acceleration < -20% (citations slowing down) |
| **Steady** | Acceleration between -20% and +20% |
| **Emerging** | No prior period data, but recent citations exist |

### Example

```
Year:  2018  2019  2020  2021  2022  2023  2024  2025
Count:   10    15    20    25    30    35    40    45

Prior 3yr avg (2020-2022): (20+25+30)/3 = 25.0
Recent 3yr avg (2023-2025): (35+40+45)/3 = 40.0
Acceleration: (40.0 - 25.0) / 25.0 = 0.60 → "accelerating"
```

---

## Field Normalization

Raw citation counts and PageRank scores are field-dependent — a paper in particle physics will have very different citation dynamics than one in nursing. Field normalization provides cross-disciplinary calibration:

| Metric | Source | Description |
|--------|--------|---|
| **FWCI** | OpenAlex | Field-Weighted Citation Impact. 1.0 = field average. A paper with FWCI 2.5 is cited 2.5x more than the average paper in its field and year. |
| **RCR** | NIH Reporter | Relative Citation Ratio. 1.0 = NIH median. Benchmarked against NIH-funded papers. Only available for PubMed-indexed papers. |
| **BIP! Influence** | OpenAIRE | Global PageRank score from the OpenAIRE BIP! indicators service. Computed over the entire OpenAIRE graph (not just the ego network). |
| **BIP! Popularity** | OpenAIRE | Attention-based metric from BIP!. |
| **BIP! Impulse** | OpenAIRE | Recency-weighted influence from BIP!. |

These are collected and reported as-is (not recomputed). FWCI and RCR are also used as components in the S-index.

---

## Biomedical Signals

For papers in biomedical/healthcare domains, additional quality signals are extracted:

| Signal | Source(s) | Description |
|--------|-----------|---|
| **MeSH Terms** | Europe PMC | Medical Subject Headings indicating the paper is PubMed-indexed and topically categorized |
| **Clinical Trials** | CrossRef (`clinical-trial-number`) | Linked clinical trial registry numbers (e.g., NCT12345678) |
| **Retraction** | CrossRef (`update-to` type "retraction"), Europe PMC (`commentCorrectionList` type "Retraction") | Whether the paper has been retracted |
| **Correction** | Same sources, non-retraction types | Whether an erratum/correction exists |
| **Grant-Backed Fraction** | All sources | Fraction of sources that report grant/funding data |
| **PMID Available** | Identifier crosswalk | Whether a PubMed ID was found (indicates biomedical indexing) |

### Retraction Detection

Retractions are detected from two independent sources:

1. **CrossRef `update-to` field:** When a publisher issues a retraction notice, CrossRef records it as an `update-to` entry with type containing "retract"
2. **Europe PMC `commentCorrectionList`:** PubMed/PMC tracks retractions as comment-correction links with type containing "Retract"

**Impact:** A detected retraction sets the S-index to **0.0** regardless of all other signals. This is a hard kill switch — retracted papers should not score well on any impact metric.

---

## S-index: Composite Score

The S-index is a single [0, 1] composite score that integrates all available signals. All components are normalized to the [0, 1] range before weighting.

### Component Weights

| Component | Weight | Source | Normalization |
|-----------|-------:|--------|---|
| Time-Decay PageRank Percentile | 30% | Local graph computation | Percentile rank [0, 1] |
| Standard PageRank Percentile | 20% | Local graph computation | Percentile rank [0, 1] |
| Influential Citation Fraction | 15% | S2 `isInfluential` flags | Fraction [0, 1] |
| Methodology Citation Fraction | 10% | S2 citation intents | Fraction [0, 1] |
| Field-Normalized Calibration | 10% | OpenAlex FWCI or NIH RCR | `min(value / 2.0, 1.0)` — FWCI 2.0+ or RCR 2.0+ maps to 1.0 |
| Integrity (inverse self-citation) | 10% | Self-citation detection | `1.0 - self_citation_fraction` |
| Biomedical Relevance | 5% | MeSH, clinical trials, grants, PMID | Sub-score capped at 1.0 |

### Biomedical Relevance Sub-Score

```
bio_score = 0.0
if pmid_available:           bio_score += 0.3
if grant_backed_fraction:    bio_score += 0.3 × grant_backed_fraction
if has_clinical_trials:      bio_score += 0.2
if has_mesh_terms:           bio_score += 0.2
bio_score = min(bio_score, 1.0)
```

### Formula

```
S-index = 0.30 × time_decay_percentile
        + 0.20 × standard_percentile
        + 0.15 × influential_fraction
        + 0.10 × methodology_fraction
        + 0.10 × field_score
        + 0.10 × (1.0 - self_citation_fraction)
        + 0.05 × bio_score
```

### Retraction Kill Switch

```python
if biomedical.has_retraction:
    return 0.0
```

### Why Percentile Ranks, Not Raw PageRank

Previous versions mixed raw PageRank scores (which scale as O(1/N) with graph size) with fractions (which are O(1)). This made PageRank terms negligible — a raw score of 0.0008 contributes almost nothing next to a fraction of 0.06. Using percentile ranks puts all components on the same [0, 1] scale, giving each component its intended influence on the final score.

### Example Scores

| Paper Profile | Expected S-index | Key Drivers |
|---------------|:----------------:|---|
| Highly cited, influential, methodology-driven, well-indexed | 0.75–0.95 | High PageRank percentiles, influential fraction, methodology fraction, field normalization |
| Moderately cited, mostly background citations | 0.35–0.50 | Moderate PageRank, low influential fraction, low methodology |
| New paper, few citations, no S2 data | 0.10–0.20 | Only integrity (1.0) and biomedical sub-scores contribute |
| Zero citations | 0.10 | Only integrity term (no self-citations = 1.0 × 0.10) |
| Retracted paper with 10,000 citations | 0.00 | Retraction kill switch |

---

## Edge Cases

### Zero Citations

When no citation edges exist (only the queried paper's node), the module:
- Reports topology with zero degree
- Skips PageRank computation (returns 0.0)
- Still computes field normalization, biomedical signals, and citation velocity
- Generates a minimal narrative: "No citation edges available for network analysis"

### Single Node

A graph with only 1 node (the queried DOI, no neighbors) gets PageRank = 1.0 for that node, but since there's nothing to compare against, the percentile is meaningless. The S-index falls back to non-PageRank components only.

### Large Graphs (Truncation)

Highly-cited papers (e.g., ENCODE with 18,767 citations) will have truncated graphs because APIs paginate results. The system:
- Detects truncation by comparing `max(citation_count)` across sources against actual inbound edge count
- Sets `graph_is_truncated = True`
- Reports both the sampled count and the known total in the narrative
- PageRank is still computed on the available sample (biased toward the first page of results)

### No Semantic Scholar Coverage

Many papers (especially datasets, non-English publications, or very recent preprints) have no S2 coverage:
- No citation intents → all intent weights default to 1.0x
- No influential flags → influential fraction = 0
- No S2 citations → graph relies on CrossRef references, DataCite links, and related works
- Methodology and influential components of S-index contribute 0

### S2 Citations Without Author Names

Semantic Scholar citation records typically lack author name data for citing papers. This means:
- Surname-based self-citation detection is inactive for S2-sourced edges
- ORCID matching still works if the citing paper has known ORCIDs (rare for S2 citation records)
- Self-citation detection is most effective for CrossRef/OpenAlex-sourced edges where author data is richer

### Papers Without DOI (S2 Paper ID Fallback)

Some Semantic Scholar citations reference papers that lack DOIs but have S2 paper IDs. These are included in the graph with node ID `s2:{paperId}`. They participate in PageRank normally but cannot be cross-referenced with other sources.

### Common Surname Collisions

If the queried paper's only author has the surname "Wang" (a common surname), surname-based self-citation detection is entirely disabled for that paper. ORCID matching remains active. This is by design — a false self-citation detection would incorrectly penalize genuine citations.

### Retracted Papers

Retraction detection fires from either CrossRef or Europe PMC. When a retraction is detected:
- `BiomedicalSignals.has_retraction = True`
- S-index = 0.0 (hard kill switch)
- Narrative leads with "WARNING: Retraction detected"
- All other metrics are still computed for transparency

### Missing Field Normalization

When neither OpenAlex (FWCI) nor NIH Reporter (RCR) data is available, the field normalization component of S-index contributes 0. This occurs for papers not indexed in OpenAlex or NIH (e.g., some dataset DOIs, non-PubMed papers).

### DataCite Datasets with Massive Citation Graphs

Dataset DOIs (e.g., ENCODE `10.1038/nature11247`) can discover 1,000+ linked datasets via DataCite reverse search. Each dataset creates an inbound edge. The graph can grow large, but PageRank power iteration is O(|V| + |E|) per iteration and converges quickly on these sparse graphs.

---

## Integration with Impact Profile

The citation network analysis is also invoked by the **Impact Profile** analysis (`doi_metadata.analyses.impact_profile`):

```python
from doi_metadata.analyses.citation_network import analyze_citation_network

cn = analyze_citation_network(result)
profile.computed_pagerank = cn.pagerank.standard
profile.computed_pagerank_time_decay = cn.pagerank.time_decay
profile.s_index = cn.s_index
```

This cross-reference means the impact profile includes both:
- **External PageRank** — per-source scores from APIs (e.g., OpenAIRE BIP! influence)
- **Computed PageRank** — locally computed from the citation graph

The impact profile wraps this in a best-effort `try/except` block, so citation network failures don't break the impact analysis.

---

## Output Schema

### CitationNetworkResult

```python
class CitationNetworkResult(BaseModel):
    doi: str
    pagerank: PageRankScores          # Standard + time-decay + percentiles
    s_index: float                    # Composite score [0, 1]
    topology: NetworkTopology         # Graph structure metrics
    intent_profile: IntentProfile     # Citation intent breakdown
    citation_velocity: CitationVelocity  # Temporal dynamics
    field_normalization: FieldNormalization  # FWCI, RCR, BIP!
    biomedical: BiomedicalSignals     # MeSH, clinical trials, retractions
    author_pagerank: list[AuthorPageRank]  # Per-author aggregation
    narrative: str                    # Human-readable summary
```

### PageRankScores

```python
class PageRankScores(BaseModel):
    standard: float              # Authority-weighted PageRank
    time_decay: float            # Time-decay PageRank
    standard_percentile: float   # Percentile rank [0, 1]
    time_decay_percentile: float
    standard_all: dict[str, float]    # Full score vector (all nodes)
    time_decay_all: dict[str, float]
```

### NetworkTopology

```python
class NetworkTopology(BaseModel):
    total_nodes: int
    total_edges: int
    in_degree: int
    out_degree: int
    self_citation_count: int
    self_citation_fraction: float | None
    influential_citation_count: int
    influential_fraction: float | None
    unique_sources_contributing: list[str]
    graph_is_truncated: bool
    known_citation_count: int | None
```

---

## Narrative Example

For a well-cited biomedical paper with S2 coverage:

```
Citation network: 156 papers, 203 edges (105 inbound, 98 outbound).
Authority-weighted PageRank: 2.3481e-01 (top 1% in local graph).
S-index: 0.7234.
Citation intents: 12 methodology, 8 result-comparison, 42 background.
High method-reuse signal (19% methodology citations).
3 self-citations (3%, down-weighted).
8 influential citations (8%).
FWCI: 3.45x field average.
NIH RCR: 4.20x NIH median.
BIP! influence: 1.2300e-06 (class C2).
Citation velocity: accelerating.
Recent 3yr avg: 42.3 citations/year.
Clinical trial linkage: 2 trial(s).
Graph from 4 API sources: crossref, europe_pmc, openalex, semantic_scholar.
```

For a zero-citation dataset DOI:

```
No citation edges available for network analysis.
```

For a retracted paper:

```
WARNING: Retraction detected — S-index set to 0.
Citation network: 89 papers, 112 edges (67 inbound, 45 outbound).
Authority-weighted PageRank: 1.8923e-01 (top 2% in local graph).
S-index: 0.0000.
...
```

---

## Configuration Constants

All tunable parameters are defined at the top of `doi_metadata/analyses/citation_network.py`:

| Constant | Value | Purpose |
|----------|------:|---|
| `DAMPING` | 0.85 | PageRank damping factor |
| `MAX_ITERATIONS` | 100 | PageRank convergence limit |
| `CONVERGENCE_THRESHOLD` | 1e-8 | PageRank convergence precision |
| `TIME_DECAY_LAMBDA` | 0.15 | Exponential decay rate for time-weighted PageRank |
| `INFLUENTIAL_WEIGHT` | 3.0 | Edge weight multiplier for S2 influential citations |
| `SELF_CITATION_PENALTY` | 0.1 | Edge weight multiplier for self-citations (90% reduction) |
| `INTENT_WEIGHTS` | `{"methodology": 2.5, "resultcomparison": 1.8, "background": 0.7}` | Citation intent multipliers |
| `COMMON_SURNAMES` | 60+ entries | Surnames excluded from self-citation surname matching |
| `MIN_SURNAME_LENGTH` | 3 | Minimum surname length for surname matching |

---

## Testing

The test suite (`tests/test_citation_network.py`) covers 52 test cases across 12 test classes:

| Test Class | # Tests | What It Validates |
|------------|:-------:|---|
| `TestIntentWeighting` | 8 | Intent weight lookup, edge weight composition, self-citation penalty |
| `TestSelfCitationORCID` | 7 | ORCID matching, common surname exclusion, URL stripping, guarded fallback |
| `TestEdgeMerging` | 1 | CrossRef + S2 edge merging preserves intents and influential flags |
| `TestBuildGraph` | 5 | Empty sources, citations → inbound, references → outbound, related works, S2 fallback |
| `TestPageRank` | 9 | Convergence, sum-to-one, time decay, weighted distribution, authority init, empty/single/star graphs, percentile |
| `TestTopology` | 2 | Degree counting, truncation detection |
| `TestIntentProfile` | 2 | Intent counting, dominant intent selection |
| `TestCitationVelocity` | 2 | Trend computation from counts_by_year, empty input |
| `TestBiomedicalSignals` | 5 | MeSH detection, clinical trials, retraction (CrossRef + Europe PMC), PMID |
| `TestSIndex` | 4 | Component normalization, retraction kill, zero inputs, field norm capping |
| `TestAnalyzeCitationNetwork` | 5 | Full integration: empty, with data, retraction, truncation, field norm |
| `TestPagerankSourceField` | 2 | OpenAIRE pagerank field, reconciliation conflict detection |

Run tests:
```bash
pytest tests/test_citation_network.py -v
```

---

## Limitations and Honest Framing

1. **1-hop ego network.** The graph captures only direct citations and references. Multi-hop PageRank would require fetching the entire citation graph, which is infeasible via API calls. Authority-weighted initialization partially compensates.

2. **API pagination bias.** Semantic Scholar returns at most ~100 citations. For highly-cited papers, the sample is biased toward whatever ordering the API uses (typically recency). Truncation is detected and reported.

3. **Intent coverage.** Citation intents are only available from Semantic Scholar, which doesn't cover all papers. For papers without S2 coverage, all intent-dependent signals contribute 0.

4. **Self-citation detection is conservative.** The ORCID-first, guarded-surname approach prioritizes precision (few false positives) over recall (may miss some self-citations, especially when ORCIDs are unavailable and surnames are common).

5. **Time-decay assumes recency = relevance.** The exponential decay model (λ=0.15) is a heuristic. Some citation patterns (e.g., classic methods papers) maintain influence across decades. Time-decay PageRank may undervalue these.

6. **S-index weights are domain-informed heuristics.** The component weights (30% time-decay PR, 20% standard PR, etc.) are not empirically optimized against ground truth. They represent informed judgment about relative importance.

7. **Field normalization is sparse.** FWCI requires OpenAlex coverage; RCR requires NIH/PubMed indexing. Many papers (datasets, software, non-English) have neither, leaving the field normalization component at 0.
