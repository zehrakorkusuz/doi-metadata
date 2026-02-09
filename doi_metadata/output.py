"""Output formatters — JSON, summary, conflict report."""

from __future__ import annotations

from doi_metadata.models import AggregatedResult


def to_json(result: AggregatedResult, indent: int = 2) -> str:
    """Full JSON output."""
    return result.model_dump_json(indent=indent, exclude_none=True)


def to_summary(result: AggregatedResult) -> str:
    """Human-readable summary."""
    lines: list[str] = []
    lines.append(f"DOI: {result.doi}")
    lines.append(f"Registration agency: {result.registration_agency}")
    lines.append(f"Retrieved: {result.retrieved_at.isoformat()}")
    lines.append("")

    # Title — pick first non-None
    for src in result.sources.values():
        if src.found and src.title:
            lines.append(f"Title: {src.title}")
            break

    # Sources status
    lines.append("")
    lines.append("Sources:")
    for name, src in sorted(result.sources.items()):
        status = "found" if src.found else ("error" if src.error else "not found")
        extra = ""
        if src.found:
            parts = []
            if src.citation_count is not None:
                parts.append(f"citations={src.citation_count}")
            if src.authors:
                parts.append(f"authors={len(src.authors)}")
            if src.grants:
                parts.append(f"grants={len(src.grants)}")
            if src.references:
                parts.append(f"refs={len(src.references)}")
            if src.files:
                parts.append(f"files={len(src.files)}")
            if src.related_works:
                parts.append(f"related={len(src.related_works)}")
            if src.tldr:
                parts.append("has_tldr")
            if src.mesh_terms:
                parts.append(f"mesh={len(src.mesh_terms)}")
            if src.nih_grants:
                parts.append(f"nih_grants={len(src.nih_grants)}")
            if src.sibling_pmids:
                parts.append(f"sibling_pmids={len(src.sibling_pmids)}")
            if src.openaire_projects:
                parts.append(f"projects={len(src.openaire_projects)}")
            if src.related_software:
                parts.append(f"software={len(src.related_software)}")
            if src.communities:
                parts.append(f"communities={len(src.communities)}")
            if src.publication_types:
                parts.append(f"pub_types={len(src.publication_types)}")
            if src.gene_symbols:
                parts.append(f"genes={len(src.gene_symbols)}")
            if src.databank_accessions:
                parts.append(f"databanks={len(src.databank_accessions)}")
            if src.conflict_of_interest:
                parts.append("has_coi")
            if src.comment_corrections:
                parts.append(f"corrections={len(src.comment_corrections)}")
            if src.investigators:
                parts.append(f"investigators={len(src.investigators)}")
            if src.supplementary_mesh:
                parts.append(f"suppl_mesh={len(src.supplementary_mesh)}")
            if src.chemicals:
                parts.append(f"chemicals={len(src.chemicals)}")
            if parts:
                extra = f" ({', '.join(parts)})"
        lines.append(f"  {name:22s} {status}{extra}")

    # Identifier crosswalk
    cw = result.crosswalk
    lines.append("")
    lines.append("Identifier Crosswalk:")
    lines.append(f"  DOI:       {cw.doi}")
    if cw.pmid:
        lines.append(f"  PMID:      {cw.pmid} (from {cw.pmid_source.value if cw.pmid_source else '?'})")
    if cw.pmcid:
        lines.append(f"  PMCID:     {cw.pmcid}")
    if cw.arxiv_id:
        lines.append(f"  arXiv:     {cw.arxiv_id}")
    if cw.openalex_id:
        lines.append(f"  OpenAlex:  {cw.openalex_id}")
    if cw.s2_paper_id:
        lines.append(f"  S2:        {cw.s2_paper_id}")
    if cw.concept_doi:
        lines.append(f"  Concept:   {cw.concept_doi}")
    if cw.orcids:
        lines.append(f"  ORCIDs:    {len(cw.orcids)} unique")
    if cw.ror_ids:
        lines.append(f"  ROR IDs:   {len(cw.ror_ids)} unique")
    if cw.handles:
        lines.append(f"  Handles:   {len(cw.handles)}")
    if cw.pii:
        lines.append(f"  PII:       {cw.pii}")
    if cw.nlm_unique_id:
        lines.append(f"  NLM ID:    {cw.nlm_unique_id}")
    if cw.grant_ids:
        lines.append(f"  Grants:    {len(cw.grant_ids)} unique IDs")

    # Conflicts
    lines.append("")
    c = result.conflicts
    lines.append(f"Conflicts: {c.conflict_count} | Agreements: {c.agreement_count}")
    for conflict in c.conflicts:
        lines.append(f"  [{conflict.risk.upper():6s}] {conflict.field}:")
        for src, val in conflict.values.items():
            lines.append(f"           {src:22s} = {val}")

    # DataCite linked datasets
    if result.datacite_linked_datasets:
        lines.append("")
        lines.append(f"DataCite linked datasets: {len(result.datacite_linked_datasets)}")
        for ds in result.datacite_linked_datasets[:10]:
            title_short = (ds.title[:60] + "...") if ds.title and len(ds.title) > 60 else ds.title
            lines.append(f"  {ds.identifier:45s} {title_short or ''}")
        if len(result.datacite_linked_datasets) > 10:
            lines.append(f"  ... and {len(result.datacite_linked_datasets) - 10} more")

    # Derived analyses narratives
    if result.analyses:
        lines.append("")
        lines.append("Analyses:")
        analysis_labels = {
            "impact": "Impact Profile",
            "funding": "Funding Landscape",
            "dataset_reuse": "Dataset Reuse",
            "authors": "Author Network",
            "grant_siblings": "Grant Siblings",
            "oa_audit": "OA Audit",
            "topics": "Topic Profile",
        }
        analyses_dict = result.analyses.model_dump(exclude_none=True)
        for key, label in analysis_labels.items():
            data = analyses_dict.get(key)
            if isinstance(data, dict):
                narrative = data.get("narrative", "")
                if narrative and "error" not in data:
                    lines.append(f"  {label}:")
                    lines.append(f"    {narrative}")
                elif "error" in data:
                    lines.append(f"  {label}: error — {data['error']}")

    return "\n".join(lines)
