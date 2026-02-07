"""Build identifier crosswalk from all source results."""

from __future__ import annotations

from doi_metadata.models import IdentifierCrosswalk, SourceName, SourceResult


def build_crosswalk(doi: str, results: dict[str, SourceResult]) -> IdentifierCrosswalk:
    """Merge identifiers discovered across all source results."""
    cw = IdentifierCrosswalk(doi=doi)

    # Priority order for PMID: Europe PMC > OpenAlex > S2 > NIH Reporter > OpenAIRE
    pmid_priority = [
        SourceName.EUROPE_PMC,
        SourceName.OPENALEX,
        SourceName.SEMANTIC_SCHOLAR,
        SourceName.NIH_REPORTER,
        SourceName.OPENAIRE,
    ]
    for src in pmid_priority:
        r = results.get(src.value)
        if r and r.found and r.pmid:
            cw.pmid = r.pmid
            cw.pmid_source = src
            break

    # PMCID: same priority
    for src in pmid_priority:
        r = results.get(src.value)
        if r and r.found and r.pmcid:
            cw.pmcid = r.pmcid
            cw.pmcid_source = src
            break

    # arXiv: S2 > OpenAIRE
    for src in [SourceName.SEMANTIC_SCHOLAR, SourceName.OPENAIRE]:
        r = results.get(src.value)
        if r and r.found and r.arxiv_id:
            cw.arxiv_id = r.arxiv_id
            break

    # OpenAlex ID
    oa = results.get(SourceName.OPENALEX.value)
    if oa and oa.found and oa.openalex_id:
        cw.openalex_id = oa.openalex_id

    # S2 IDs
    s2 = results.get(SourceName.SEMANTIC_SCHOLAR.value)
    if s2 and s2.found:
        cw.s2_paper_id = s2.s2_paper_id
        cw.s2_corpus_id = s2.s2_corpus_id

    # DBLP
    if s2 and s2.found and s2.raw:
        ext = s2.raw.get("externalIds", {}) or {}
        if ext.get("DBLP"):
            cw.dblp_id = ext["DBLP"]

    # Zenodo concept DOI/recid
    zen = results.get(SourceName.ZENODO.value)
    if zen and zen.found and zen.version_info:
        cw.concept_doi = zen.version_info.concept_doi
        cw.concept_recid = zen.version_info.concept_recid

    # Collect all ORCIDs from all sources
    orcids: set[str] = set()
    for r in results.values():
        if not r.found:
            continue
        for author in r.authors:
            if author.name.orcid:
                orcids.add(author.name.orcid)
    cw.orcids = sorted(orcids)

    # Collect all ROR IDs from all sources
    ror_ids: set[str] = set()
    for r in results.values():
        if not r.found:
            continue
        for author in r.authors:
            for aff in author.affiliations:
                if aff.ror_id:
                    ror_ids.add(aff.ror_id)
    cw.ror_ids = sorted(ror_ids)

    # Collect handles from OpenAIRE alternate_ids
    openaire = results.get(SourceName.OPENAIRE.value)
    if openaire and openaire.found:
        for alt_id in openaire.alternate_ids:
            if alt_id.startswith("handle:"):
                cw.handles.append(alt_id.replace("handle:", ""))
            elif alt_id.startswith("mag_id:"):
                cw.mag_id = alt_id.replace("mag_id:", "")

    return cw
