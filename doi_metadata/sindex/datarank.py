"""DataRank — Personalized PageRank for data-sharing influence.

DataRank(p) = (1 - d) * E(p)_norm + d * Σ_{q cites p} [ E(q) / outdeg(q) ]

Where:
  E(p)_norm = E(p) / Σ_i E(i)   (normalized endowment, sums to 1)
  E(q)      = endowment of citer q (lightweight estimate from OpenAlex)
  outdeg(q) = number of references in citer q
  d         = 0.85 damping factor

The 1-hop approximation: instead of iterating to convergence on the full graph,
we compute one step of the power iteration using the immediate citers.
This is equivalent to Personalized PageRank with restart probability (1-d)
approximated by a single propagation step.
"""

from __future__ import annotations

import asyncio
import json
import logging
import statistics
from pathlib import Path

from doi_metadata.sindex.endowment import compute_endowment
from doi_metadata.sindex.models import DataRankCorpus, DataRankResult, PaperEndowment
from doi_metadata.sindex.openalex_graph import (
    citer_endowment_estimate,
    fetch_citer_neighbourhood,
)

logger = logging.getLogger(__name__)

DAMPING = 0.85
EPSILON_ENDOWMENT = 0.01  # Minimum endowment for papers with no data-sharing signals


def compute_datarank_single(
    result: dict,
    citers: list[dict],
    corpus_endowment_sum: float = 1.0,
) -> DataRankResult:
    """Compute DataRank for a single paper given its result and citers.

    Args:
        result: The benchmark result dict for the seed paper.
        citers: List of OpenAlex citer work dicts.
        corpus_endowment_sum: Sum of E(p) across the corpus, for normalization.
    """
    endowment = compute_endowment(result)

    # Ensure minimum endowment
    if endowment.endowment <= 0:
        endowment.endowment = EPSILON_ENDOWMENT

    # Normalized endowment (personalization vector component)
    e_norm = endowment.endowment / corpus_endowment_sum if corpus_endowment_sum > 0 else 0

    # Self contribution: (1 - d) * E_norm
    self_contribution = (1 - DAMPING) * e_norm

    # Citer contribution: d * Σ E(q) / outdeg(q)
    citer_contribution = 0.0
    citers_with_endowment = 0

    for citer in citers:
        e_q = citer_endowment_estimate(citer)
        outdeg = citer.get("referenced_works_count") or 1
        if outdeg < 1:
            outdeg = 1

        contribution = e_q / outdeg
        if contribution > 0:
            citers_with_endowment += 1
        citer_contribution += contribution

    citer_contribution *= DAMPING

    datarank = self_contribution + citer_contribution

    return DataRankResult(
        doi=result.get("doi", ""),
        endowment=endowment,
        self_endowment_contribution=self_contribution,
        citer_contribution=citer_contribution,
        datarank=datarank,
        citer_count=len(citers),
        citers_with_endowment=citers_with_endowment,
    )


def compute_datarank_offline(results: list[dict]) -> DataRankCorpus:
    """Compute DataRank for a corpus using only the existing benchmark data.

    This is the offline mode — no API calls.  Citer contribution is zero
    (we only have the seed papers, not their citers).  Useful for testing the
    endowment function and getting a baseline ranking from direct signals alone.
    """
    # Phase 1: compute all endowments
    endowments: list[PaperEndowment] = []
    for r in results:
        endowments.append(compute_endowment(r))

    corpus_sum = sum(max(e.endowment, EPSILON_ENDOWMENT) for e in endowments)

    # Phase 2: compute DataRank (offline = endowment-only, no citer expansion)
    dr_results: list[DataRankResult] = []
    for r, e in zip(results, endowments):
        if e.endowment <= 0:
            e.endowment = EPSILON_ENDOWMENT

        e_norm = e.endowment / corpus_sum
        self_contribution = (1 - DAMPING) * e_norm

        dr_results.append(DataRankResult(
            doi=r.get("doi", ""),
            endowment=e,
            self_endowment_contribution=self_contribution,
            citer_contribution=0.0,
            datarank=self_contribution,
            citer_count=0,
            citers_with_endowment=0,
        ))

    return _build_corpus(dr_results)


async def compute_datarank_corpus(
    results_dir: Path,
    max_citers: int = 200,
    concurrency: int = 5,
    offline: bool = False,
    max_papers: int = 0,
) -> DataRankCorpus:
    """Compute DataRank for all benchmark results.

    Args:
        results_dir: Path to benchmark/results/ with JSON files.
        max_citers: Max citers to fetch per paper from OpenAlex.
        concurrency: Max concurrent OpenAlex requests.
        offline: If True, skip API calls (endowment-only ranking).
        max_papers: Limit to first N papers (0 = no limit).
    """
    # Load all results
    logger.info("Loading benchmark results from %s ...", results_dir)
    all_results: list[dict] = []
    for f in sorted(results_dir.glob("*.json")):
        try:
            all_results.append(json.loads(f.read_text()))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Skipping %s: %s", f.name, exc)

    if max_papers > 0:
        all_results = all_results[:max_papers]

    logger.info("Loaded %d results", len(all_results))

    if not all_results:
        return DataRankCorpus()

    if offline:
        logger.info("Offline mode — computing endowment-only DataRank")
        return compute_datarank_offline(all_results)

    # Phase 1: compute endowments for all seed papers
    logger.info("Phase 1: Computing endowments for %d papers ...", len(all_results))
    endowments = [compute_endowment(r) for r in all_results]
    corpus_sum = sum(max(e.endowment, EPSILON_ENDOWMENT) for e in endowments)
    logger.info("Corpus endowment sum: %.2f", corpus_sum)

    nonzero = sum(1 for e in endowments if e.endowment > EPSILON_ENDOWMENT)
    logger.info("Papers with nonzero endowment: %d / %d", nonzero, len(endowments))

    # Phase 2: fetch citers from OpenAlex (concurrent with semaphore)
    logger.info("Phase 2: Fetching citers from OpenAlex (concurrency=%d, max_citers=%d) ...",
                concurrency, max_citers)

    semaphore = asyncio.Semaphore(concurrency)
    citer_map: dict[str, list[dict]] = {}  # doi -> citers

    async def _fetch_one(doi: str) -> None:
        async with semaphore:
            try:
                citers, _oa_id = await fetch_citer_neighbourhood(doi, max_citers=max_citers)
                citer_map[doi] = citers
            except Exception as exc:
                logger.warning("Failed to fetch citers for %s: %s", doi, exc)
                citer_map[doi] = []

    tasks = [_fetch_one(r.get("doi", "")) for r in all_results]
    done = 0
    # Process in batches for progress reporting
    batch_size = 50
    for i in range(0, len(tasks), batch_size):
        batch = tasks[i:i + batch_size]
        await asyncio.gather(*batch)
        done += len(batch)
        if done % 100 == 0 or done == len(tasks):
            logger.info("  Fetched citers for %d / %d papers", done, len(tasks))

    # Phase 3: compute DataRank
    logger.info("Phase 3: Computing DataRank ...")
    dr_results: list[DataRankResult] = []
    for r, e in zip(all_results, endowments):
        doi = r.get("doi", "")
        citers = citer_map.get(doi, [])
        dr = compute_datarank_single(r, citers, corpus_endowment_sum=corpus_sum)
        dr_results.append(dr)

    return _build_corpus(dr_results)


def _build_corpus(dr_results: list[DataRankResult]) -> DataRankCorpus:
    """Assign quantile classes and build corpus summary."""
    # Sort by datarank descending
    dr_results.sort(key=lambda x: x.datarank, reverse=True)

    n = len(dr_results)
    scores = [r.datarank for r in dr_results]

    # Assign rank and percentile
    for i, r in enumerate(dr_results):
        r.corpus_rank = i + 1
        r.corpus_percentile = 100.0 * (1 - i / n) if n > 0 else 0

    # Quantile classes (like BIP!)
    for i, r in enumerate(dr_results):
        pct = (i + 1) / n if n > 0 else 1
        if pct <= 0.0001:
            r.quantile_class = "S1"  # top 0.01%
        elif pct <= 0.001:
            r.quantile_class = "S2"  # top 0.1%
        elif pct <= 0.01:
            r.quantile_class = "S3"  # top 1%
        elif pct <= 0.10:
            r.quantile_class = "S4"  # top 10%
        else:
            r.quantile_class = "S5"  # bottom 90%

    # Thresholds
    def _score_at_pct(pct: float) -> float:
        idx = max(0, min(n - 1, int(n * pct)))
        return scores[idx] if scores else 0

    corpus = DataRankCorpus(
        papers=dr_results,
        total_papers=n,
        damping_factor=DAMPING,
        mean_datarank=statistics.mean(scores) if scores else 0,
        median_datarank=statistics.median(scores) if scores else 0,
        max_datarank=scores[0] if scores else 0,
        s1_threshold=_score_at_pct(0.0001),
        s2_threshold=_score_at_pct(0.001),
        s3_threshold=_score_at_pct(0.01),
        s4_threshold=_score_at_pct(0.10),
    )

    return corpus
