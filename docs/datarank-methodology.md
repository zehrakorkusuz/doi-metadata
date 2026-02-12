# DataRank: A Data-Sharing Influence Metric for Scholarly Works

## 1. The Problem

Citation counts measure *intellectual influence* — whether a paper's ideas propagated. But they are silent on **data sharing**. A landmark genomics paper (ENCODE, *Nature* 2012) has ~19,000 citations, but this number tells you nothing about the 1,158 downstream datasets deposited in Zenodo and Figshare that reuse its data. A carefully curated Dryad dataset with 6,830 downloads and active version maintenance scores zero in every existing bibliometric system.

We need a single number that captures a paper's **data-sharing influence**: both its direct data contributions (files deposited, datasets linked, downloads accumulated) and its indirect influence (did the research it enabled also share data?).

## 2. Design Requirements

1. **Heterogeneous signals.** Data sharing manifests differently across disciplines — genomics produces deposited sequences, climate science produces NetCDF archives, social science produces survey instruments. The metric must fuse signals from 14 different scholarly infrastructure APIs without privileging any single source.

2. **Direct + transitive influence.** A paper that itself deposits no data but catalyzes 500 datasets downstream (e.g., a methods paper) should score higher than a paper with one dataset and no downstream impact.

3. **Diminishing returns.** The 1,000th DataCite link should matter less than the 1st. A paper with 10 downloads and 5 files should not be trivialized next to one with 100,000 downloads.

4. **No false precision.** Sources disagree on citation counts by 100x for preprints. The metric should be robust to individual source failures and should not claim to resolve conflicts that the underlying infrastructure cannot.

5. **Quantile classification.** Absolute scores are meaningless in isolation. The output should be a corpus-relative class (S1–S5) analogous to BIP! impact classes, making it interpretable across corpora of different sizes.

## 3. Theoretical Foundation: Personalized PageRank

### 3.1 Why PageRank?

The citation graph is a directed graph where edges represent "paper A cites paper B." PageRank (Brin & Page, 1998) computes a stationary distribution over this graph: the probability that a random walker, following citation links, lands on a given node. It captures *transitive* influence — a paper cited by highly-cited papers scores higher than one cited by obscure ones.

But standard PageRank has a critical flaw for our purpose: **it treats all papers as equal in the teleportation step.** When the random walker "gets bored" and jumps to a random node (with probability 1−d), it jumps uniformly. This means a paper's baseline score is independent of whether it shares data.

### 3.2 Personalized PageRank (PPR)

Personalized PageRank (Haveliwala, 2002) replaces the uniform teleportation distribution with a **personalization vector** — a prior distribution that biases the random walk toward nodes of interest.

Standard PageRank:

```
PR(p) = (1-d)/N + d * Σ_{q→p} PR(q) / outdeg(q)
```

Personalized PageRank:

```
PPR(p) = (1-d) * π(p) + d * Σ_{q→p} PPR(q) / outdeg(q)
```

Where π(p) is the personalization vector (sums to 1).

**The key insight:** if we set π(p) proportional to a paper's *direct data-sharing evidence*, then the random walk is biased toward data-sharing nodes. Papers that share data get a direct boost. Papers *cited by* data-sharing papers get an indirect boost. The transitive credit flows through the citation graph, weighted by data-sharing activity at every hop.

### 3.3 DataRank = 1-Hop PPR Approximation

Full PPR requires iterating the power method to convergence over the entire citation graph — billions of nodes in OpenAlex. This is computationally prohibitive for a per-query tool.

Instead, we use a **1-hop approximation**: for each seed paper, we fetch its immediate citers and compute one step of the power iteration. This is equivalent to truncating the random walk after one hop:

```
DataRank(p) = (1-d) * E_norm(p) + d * Σ_{q cites p} E(q) / outdeg(q)
```

Where:
- **E(p)** = endowment score (direct data-sharing evidence, see Section 4)
- **E_norm(p)** = E(p) / Σ_i E(i), the normalized endowment (personalization vector)
- **E(q)** = lightweight endowment estimate for citer q (from OpenAlex metadata)
- **outdeg(q)** = number of references in citer q's reference list
- **d = 0.85** = damping factor (standard in PageRank literature)

**Why 1-hop is sufficient:** In practice, the majority of PageRank mass transfers happen in the first iteration. The 1-hop approximation captures the dominant effect (am I cited by data-sharing papers?) while avoiding the cost and complexity of full graph convergence. For a domain-specific metric where we care about *relative ranking* rather than absolute stationary probabilities, this is a well-justified tradeoff.

## 4. The Endowment Function E(p)

The endowment is the personalization vector — it encodes how much *direct* evidence exists that a paper involves data sharing. It is computed from the aggregated metadata of 14 scholarly APIs.

### 4.1 Signal Inventory

| Signal | Source APIs | Weight | Rationale |
|--------|-----------|--------|-----------|
| DataCite reverse search total | DataCite | 5.0 * log(1+n) | Strongest signal: actual count of downstream datasets that reference this DOI |
| DataCite relation type richness | DataCite, all sources | 1.5 per type | Structural diversity of data connections (IsSupplementTo, IsDerivedFrom, etc.) |
| File deposits | Zenodo, Dryad, DataCite | 3.0 + 1.0*log(1+n) | Tangible shared artifacts — someone uploaded actual files |
| File size | Zenodo, Dryad | 0.5 * log(1+MB) | Substantial data deposits (not just a README) |
| Downloads | Zenodo, Dryad | 2.0 * log(1+n) | Community reuse evidence |
| Views | Zenodo, Dryad | 0.5 * log(1+n) | Interest signal (weaker than downloads) |
| Version chain | Zenodo, DataCite | 2.0 + 0.5*log(1+versions) | Actively maintained data (not abandoned) |
| Dataset classification | OpenAlex | 3.0 (binary) | The work is itself classified as a dataset |
| Open access status | Unpaywall, OpenAlex | 1.0 (binary) | Necessary condition for data sharing |

### 4.2 Why log(1+x) Everywhere?

All count-based signals use logarithmic scaling (`log1p`) to achieve **diminishing returns**:

| Raw count | log(1+n) | Effective contribution (weight=5.0) |
|-----------|----------|-------------------------------------|
| 1         | 0.69     | 3.5 |
| 10        | 2.40     | 12.0 |
| 100       | 4.62     | 23.1 |
| 1,000     | 6.91     | 34.5 |
| 10,000    | 9.21     | 46.1 |

This prevents a single paper with 10,000 DataCite links from completely dominating the ranking. The ratio between 1 and 10,000 links is 10,000x in raw counts but only 13.3x in endowment contribution.

### 4.3 Endowment Distribution (Benchmark: 1,000 Papers)

From a run over 1,000 papers from the benchmark corpus:

| Statistic | Value |
|-----------|-------|
| Papers with nonzero endowment | 585 (58.5%) |
| Papers at epsilon (no signal) | 415 (41.5%) |
| Mean endowment | 2.27 |
| Median endowment | 1.00 |
| Std deviation | 5.07 |
| P90 | 7.10 |
| P99 | 23.27 |
| Max | 33.62 |
| Gini coefficient | 0.776 |

The distribution is **highly right-skewed** — a small number of papers have rich data-sharing evidence across multiple signals, while 41.5% have no detectable data-sharing activity from any of the 14 sources.

### 4.4 Signal Prevalence

| Signal | Papers with signal | % of corpus |
|--------|-------------------|-------------|
| Open access | 540 | 54.0% |
| DataCite links (>0) | 81 | 8.1% |
| Downloads (>0) | 32 | 3.2% |
| File deposits (>0) | 23 | 2.3% |
| Dataset classification | 23 | 2.3% |

Open access is the most common signal (necessary but not sufficient). DataCite links are the most *discriminating* signal — present in only 8.1% of papers but carrying the highest weight.

## 5. Comparison with Standard PageRank

### 5.1 What Standard PageRank Would Produce

Standard (uniform) PageRank with damping d=0.85 sets the teleportation probability to 1/N for all nodes. In offline mode (no citer expansion):

```
PR_uniform(p) = (1-d)/N = 0.15/1000 = 0.000150  (identical for all papers)
```

**Every paper gets the same score.** Standard PageRank, without the citation graph edges, is completely non-discriminating. It cannot distinguish ENCODE from a paper with zero data-sharing activity.

In online mode (with citers), standard PageRank would rank papers by *citation influence* — highly cited papers rise to the top regardless of whether they or their citers share data. This is the **h-index / citation count problem all over again**, just computed more expensively.

### 5.2 What DataRank Produces

DataRank replaces 1/N with E_norm(p), producing a 3,362x dynamic range:

| Metric | Uniform PageRank | DataRank |
|--------|-----------------|----------|
| Min score | 0.000150 | 0.0000007 |
| Max score | 0.000150 | 0.002223 |
| Dynamic range | 1x | 3,362x |
| Discriminates data sharing? | No | Yes |

### 5.3 The Role of the Damping Factor

With d=0.85, the score decomposes as:
- **15% from the personalization vector** (direct data-sharing evidence)
- **85% from citation propagation** (data-sharing evidence of citers)

This means that in online mode, a methods paper with modest direct evidence (E=1.0) but 200 citers that are all datasets would score *much higher* than a dataset with rich direct evidence (E=30.0) but no downstream citations. The damping factor controls this tradeoff.

In offline mode (no citers), only the 15% self-contribution survives, which is why the offline ranking is purely proportional to endowment. The online mode is where DataRank truly differentiates from a simple endowment ranking.

### 5.4 Why Not Just Use Endowment Directly?

Endowment alone measures *direct* data sharing. It would rank:

1. A Zenodo dataset with 6,830 downloads (endowment: 33.62)
2. An article that catalyzed 1,158 downstream datasets but has no files itself

The article scores lower on endowment, but DataRank with citer expansion would boost it because its citers (the downstream datasets) have high endowment.

**DataRank = endowment + transitive credit.** This is the fundamental contribution.

## 6. Quantile Classification (S1–S5)

Following the BIP! (Bibliometric-enhanced Impact and Prestige) indicator framework, DataRank scores are mapped to five classes based on corpus-relative percentile position:

| Class | Percentile | 1K Corpus Threshold | Interpretation |
|-------|-----------|---------------------|----------------|
| S1 | Top 0.01% | 0.002223 | Exceptional data-sharing influence |
| S2 | Top 0.1% | 0.001875 | Outstanding |
| S3 | Top 1% | 0.001517 | Excellent |
| S4 | Top 10% | 0.000458 | Above average |
| S5 | Bottom 90% | < 0.000458 | Baseline |

Distribution over 1,000 papers:
- **S1**: 0 papers (corpus too small for top-0.01% to be nonempty)
- **S2**: 1 paper
- **S3**: 9 papers
- **S4**: 90 papers
- **S5**: 900 papers

The class is what should be reported — not the raw score. Raw scores are not comparable across corpora of different sizes.

## 7. Architecture

```
                    ┌─────────────────────────┐
                    │  14-Source Metadata      │
                    │  (CrossRef, DataCite,    │
                    │   OpenAlex, Zenodo, ...) │
                    └──────────┬──────────────┘
                               │
                    ┌──────────▼──────────────┐
                    │  Endowment Function E(p) │
                    │                          │
                    │  Signals:                │
                    │  · DataCite reuse count  │
                    │  · Relation type richness│
                    │  · File deposits + size  │
                    │  · Downloads / views     │
                    │  · Version chain         │
                    │  · Dataset classification│
                    │  · Open access status    │
                    │                          │
                    │  All log-scaled, weighted │
                    └──────────┬──────────────┘
                               │
                   ┌───────────▼───────────────┐
                   │  Personalization Vector    │
                   │  π(p) = E(p) / Σ E(i)     │
                   └───────────┬───────────────┘
                               │
               ┌───────────────┼───────────────┐
               │                               │
    ┌──────────▼──────────┐         ┌──────────▼──────────┐
    │  Self Contribution  │         │  Citer Contribution  │
    │  (1-d) * π(p)       │         │  d * Σ E(q)/outdeg(q)│
    │                     │         │                      │
    │  = 15% of score     │         │  = 85% of score      │
    │  (direct evidence)  │         │  (transitive credit)  │
    └──────────┬──────────┘         └──────────┬──────────┘
               │          ┌────────────────────┘
               │          │   OpenAlex 1-hop
               │          │   citer expansion
               │          │
          ┌────▼──────────▼────┐
          │     DataRank(p)    │
          │  = self + citer    │
          └─────────┬──────────┘
                    │
          ┌─────────▼──────────┐
          │  Quantile Class    │
          │  S1–S5 assignment  │
          │  (corpus-relative) │
          └────────────────────┘
```

## 8. Computational Characteristics

| Property | Value |
|----------|-------|
| Time complexity (offline) | O(N) — one pass over endowments |
| Time complexity (online) | O(N * C) — N papers * C citers each |
| API calls per paper (online) | 1 (resolve OA ID) + ceil(C/200) (citer pages) |
| 1K papers, offline | ~12 seconds |
| 1K papers, online (concurrency=5) | ~2 minutes (estimated with network) |
| 5.3K papers, offline | ~45 seconds |
| Memory | O(N + max_citers) — citers are processed per-paper |

## 9. Limitations and Future Work

### Current Limitations

1. **Citer endowment is approximate.** For citers, we only have OpenAlex metadata (type, OA status, dataset relations) — not the full 14-source endowment. This underestimates citer contributions.

2. **1-hop truncation.** We capture "my citers share data" but not "my citers' citers share data." For most papers the first hop dominates, but for foundational methods papers, deeper propagation could matter.

3. **DataCite link cap.** The pipeline currently returns at most 25 DataCite reverse-search results per paper due to API pagination. Papers like ENCODE (1,158 actual links) are underrepresented. The `datacite_linked_total` field captures the true count but some benchmark data may use the capped list.

4. **Static snapshot.** Scores reflect metadata at query time. Downloads accumulate, new datasets appear, OA status changes. The score is a point-in-time estimate.

5. **Discipline bias.** Fields with established data repositories (genomics, climate science) naturally score higher. Fields where data sharing happens through supplementary materials or informal channels may be underrepresented.

### Future Directions

- **Multi-hop expansion** via cached OpenAlex snapshot (avoiding per-query API costs)
- **Discipline-normalized endowment** (z-score within field)
- **Temporal decay** (recent data sharing weighted more than historical)
- **Full convergence** on a precomputed citation subgraph for high-value corpora
- **Validation** against expert assessments of data-sharing impact (ground truth)

## 10. Summary

DataRank is a **Personalized PageRank variant** where the personalization vector encodes multi-source evidence of data sharing. It compresses 14 APIs, 8 distinct signals, and arbitrary corpus sizes into a single score with a quantile class.

The key design choices:
- **Personalized** (not uniform) PageRank, because the teleportation vector *is* the metric
- **Log-scaled signals**, because diminishing returns prevent count inflation
- **1-hop approximation**, because one propagation step captures the dominant effect at 1000x lower cost than full convergence
- **Quantile classes** (not raw scores), because absolute values are corpus-dependent
- **Multi-source endowment**, because no single API captures all forms of data sharing

In the limiting case of no citation data (offline mode), DataRank reduces to a weighted multi-source data-sharing index. In the limiting case of uniform endowment, it reduces to standard PageRank. DataRank occupies the useful middle: citation-aware, data-sharing-specific, and computationally tractable.
