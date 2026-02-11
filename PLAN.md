# S-Index Implementation Plan

## Architecture Overview

Compute a graph-theoretic "data-sharing influence" metric (s-index) using PageRank variations
over a heterogeneous citation/reuse/authorship graph built from our 5,309 benchmark results.

## Module Structure

```
doi_metadata/sindex/
├── __init__.py              # Public API: compute_sindex(results_dir) -> SIndexCorpus
├── graph_builder.py         # Build heterogeneous graph from benchmark results
├── edge_weights.py          # Edge classification and weighting
├── self_citation.py         # Self-citation and same-grant detection
├── pagerank_variants.py     # Three PageRank implementations (weighted, time-decayed, topic-sensitive)
├── composite.py             # Combine variants into final s-index + quantile classes
├── models.py                # Pydantic models for s-index output
└── report.py                # Leaderboard and narrative generation
```

## Graph Model

- **Paper nodes**: Every DOI in corpus
- **Author nodes**: Disambiguated via ORCID/name-key
- **P→P edges**: Citations (standard, influential, data-reuse, supplement, derived)
- **A→P edges**: Authorship with role-based weights

## Three PageRank Variants

1. **Weighted Data-Reuse PageRank**: Data-reuse edges weighted 2x, self-citations damped 90%
2. **Time-Decayed PageRank**: exp(-0.1 * age) decay, half-life ~7 years
3. **Topic-Sensitive PageRank**: Per-field personalized PageRank for field normalization

## Composite Score

```
s_index(paper) = 0.5 * weighted + 0.3 * time_decayed + 0.2 * field_normalized
s_index(author) = Σ [credit_weight(author, paper_i) * s_index(paper_i)]
```

## Key Design Decisions

- scipy.sparse CSR matrix (not NetworkX) for performance
- Purely additive module — no changes to existing code
- Damping: d=0.85, convergence: ε=1e-8, max_iter=100
- Personalization biased toward DataCite-registered DOIs
- Self-citation detection via ORCID overlap, then name-key fallback
- Grant-internal citations damped by 70%
- Quantile classes S1-S5 (matching BIP! convention)

## Implementation Order

1. graph_builder.py — Foundation
2. edge_weights.py + self_citation.py — Edge classification
3. pagerank_variants.py — Core algorithm (Variant 1 first)
4. composite.py + models.py — Combine and structure
5. report.py — Leaderboard generation
6. CLI/API integration
