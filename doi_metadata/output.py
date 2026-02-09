"""Output formatters — JSON, summary, conflict report, discrepancy report."""

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

    # Cross-source discrepancy report
    dr = result.discrepancy_report
    if isinstance(dr, dict) and "error" not in dr:
        lines.append("")
        lines.append("=" * 72)
        lines.append("CROSS-SOURCE DISCREPANCY REPORT")
        lines.append("=" * 72)

        # Coverage
        found = dr.get("sources_found", 0)
        not_found = dr.get("sources_not_found", 0)
        errored = dr.get("sources_errored", 0)
        total = found + not_found + errored
        lines.append(f"  Sources: {found}/{total} returned data")
        completeness = dr.get("data_completeness_score")
        if completeness is not None:
            lines.append(f"  Data completeness: {int(completeness * 100)}% of key fields have 2+ source coverage")

        # Coverage matrix
        coverage = dr.get("source_coverage", [])
        if coverage:
            lines.append("")
            lines.append("  Source Coverage Matrix:")
            hdr = f"  {'Source':22s} {'Found':6s} {'Title':6s} {'Cites':6s}"
            hdr += f" {'Auth':6s} {'OA':6s} {'Fund':6s} {'Subj':6s} {'Rel':6s}"
            lines.append(hdr)
            lines.append(f"  {'-' * 76}")
            for sc in coverage:
                if not sc.get("found"):
                    status = sc.get("error", "not found") or "not found"
                    lines.append(f"  {sc['source']:22s} {'---':6s} {status}")
                else:
                    def _yn(key):
                        return "Y" if sc.get(key) else "-"
                    lines.append(
                        f"  {sc['source']:22s} {'Y':6s} {_yn('has_title'):6s} {_yn('has_citations'):6s} "
                        f"{_yn('has_authors'):6s} {_yn('has_oa_info'):6s} {_yn('has_funding'):6s} "
                        f"{_yn('has_subjects'):6s} {_yn('has_related_works'):6s}"
                    )

        # Citation divergence
        cit = dr.get("citations", {})
        if cit.get("counts_by_source"):
            lines.append("")
            level = cit.get("divergence_level", "none")
            risk_marker = {"high": "!!!", "medium": "!!", "low": "!", "none": ""}
            lines.append(f"  Citation Counts {risk_marker.get(level, '')} [{level.upper()} divergence]:")
            for src, count in sorted(cit["counts_by_source"].items(), key=lambda x: -x[1]):
                lines.append(f"    {src:22s} {count:>10,}")
            if cit.get("spread"):
                lines.append(f"    {'Spread':22s} {cit['spread']:>10,} ({cit.get('spread_pct', 0):.0f}%)")
            if cit.get("outlier_sources"):
                lines.append(f"    Outliers: {', '.join(cit['outlier_sources'])}")

        # OA conflicts
        oa = dr.get("oa_status", {})
        if oa.get("status_by_source") and not oa.get("status_agrees"):
            lines.append("")
            lines.append("  OA Status CONFLICT:")
            for src, status in oa["status_by_source"].items():
                lines.append(f"    {src:22s} {status}")
            if oa.get("consensus_status"):
                lines.append(f"    Consensus: {oa['consensus_status']} (Unpaywall preferred)")

        if not oa.get("is_oa_agrees", True) and oa.get("is_oa_by_source"):
            lines.append("")
            lines.append("  OA Boolean CONFLICT:")
            for src, val in oa["is_oa_by_source"].items():
                lines.append(f"    {src:22s} {'Open Access' if val else 'Closed'}")

        if oa.get("sources_only_in"):
            exclusive = sum(len(urls) for urls in oa["sources_only_in"].values())
            lines.append(f"  {exclusive} OA URL(s) found by only one source")

        # Author discrepancies
        auth = dr.get("authors", {})
        if auth.get("count_by_source") and not auth.get("count_agrees"):
            lines.append("")
            lines.append("  Author Count VARIES:")
            for src, count in sorted(auth["count_by_source"].items()):
                lines.append(f"    {src:22s} {count}")
        if auth.get("name_variant_examples"):
            lines.append(f"  Name variants: {'; '.join(auth['name_variant_examples'][:3])}")

        # Funding gaps
        fund = dr.get("funding", {})
        if fund.get("total_unique_grants", 0) > 0:
            lines.append("")
            lines.append(f"  Funding: {fund['total_unique_grants']} unique grants")
            lines.append(f"    Multi-source confirmed: {fund.get('grants_multi_source', 0)}")
            lines.append(f"    Single-source only:     {fund.get('grants_single_source', 0)}")
            if fund.get("grant_count_by_source"):
                lines.append("    Grant count by source:")
                for src, count in sorted(fund["grant_count_by_source"].items(), key=lambda x: -x[1]):
                    lines.append(f"      {src:22s} {count}")

        # References
        ref = dr.get("references", {})
        if ref.get("count_by_source") and not ref.get("count_agrees"):
            lines.append("")
            lines.append("  Reference Count VARIES:")
            for src, count in sorted(ref["count_by_source"].items()):
                lines.append(f"    {src:22s} {count}")

        # Scalar mismatches
        scalars = dr.get("scalar_discrepancies", [])
        if scalars:
            lines.append("")
            lines.append("  Other Scalar Discrepancies:")
            for d in scalars:
                lines.append(f"    [{d.get('risk', 'low').upper():6s}] {d['field']}:")
                for src, val in d.get("values", {}).items():
                    lines.append(f"      {src:22s} = {val}")

        # Risk summary
        lines.append("")
        total_disc = dr.get("total_discrepancies", 0)
        lines.append(
            f"  TOTAL DISCREPANCIES: {total_disc} "
            f"({dr.get('high_risk_count', 0)} high, "
            f"{dr.get('medium_risk_count', 0)} medium, "
            f"{dr.get('low_risk_count', 0)} low)"
        )
        lines.append("=" * 72)

    return "\n".join(lines)


def to_discrepancy_report(result: AggregatedResult) -> str:
    """Standalone discrepancy report — focused view of cross-source disagreements."""
    dr = result.discrepancy_report
    if not isinstance(dr, dict) or "error" in dr:
        error = dr.get("error", "unknown") if isinstance(dr, dict) else "not generated"
        return f"Discrepancy report unavailable: {error}"

    lines: list[str] = []

    # Title
    title = None
    for src in result.sources.values():
        if src.found and src.title:
            title = src.title
            break

    lines.append("=" * 72)
    lines.append("CROSS-SOURCE DISCREPANCY REPORT")
    lines.append(f"DOI: {result.doi}")
    if title:
        lines.append(f"Title: {title}")
    lines.append(f"Registration agency: {result.registration_agency}")
    lines.append(f"Retrieved: {result.retrieved_at.isoformat()}")
    lines.append("=" * 72)

    # Narrative summary at top
    narrative = dr.get("narrative", "")
    if narrative:
        lines.append("")
        lines.append("SUMMARY")
        lines.append("-" * 40)
        # Wrap narrative at ~72 chars
        for sentence in narrative.split(". "):
            sentence = sentence.strip().rstrip(".")
            if sentence:
                lines.append(f"  {sentence}.")

    # Coverage
    lines.append("")
    lines.append("SOURCE COVERAGE")
    lines.append("-" * 40)
    found = dr.get("sources_found", 0)
    not_found = dr.get("sources_not_found", 0)
    errored = dr.get("sources_errored", 0)
    total = found + not_found + errored
    lines.append(f"  {found}/{total} sources returned data")
    completeness = dr.get("data_completeness_score")
    if completeness is not None:
        lines.append(f"  Data completeness: {int(completeness * 100)}%")

    coverage = dr.get("source_coverage", [])
    if coverage:
        lines.append("")
        hdr = f"  {'Source':22s} {'Found':6s} {'Title':6s} {'Cites':6s}"
        hdr += f" {'Auth':6s} {'OA':6s} {'Fund':6s} {'Subj':6s} {'Rel':6s}"
        lines.append(hdr)
        lines.append(f"  {'-' * 76}")
        for sc in coverage:
            if not sc.get("found"):
                status = sc.get("error", "not found") or "not found"
                lines.append(f"  {sc['source']:22s} {'---':6s} {status}")
            else:
                def _yn(key):
                    return "Y" if sc.get(key) else "-"
                lines.append(
                    f"  {sc['source']:22s} {'Y':6s} {_yn('has_title'):6s} {_yn('has_citations'):6s} "
                    f"{_yn('has_authors'):6s} {_yn('has_oa_info'):6s} {_yn('has_funding'):6s} "
                    f"{_yn('has_subjects'):6s} {_yn('has_related_works'):6s}"
                )

    # Citations
    cit = dr.get("citations", {})
    if cit.get("counts_by_source"):
        lines.append("")
        lines.append("CITATION COUNTS")
        lines.append("-" * 40)
        level = cit.get("divergence_level", "none")
        lines.append(f"  Divergence level: {level.upper()}")
        for src, count in sorted(cit["counts_by_source"].items(), key=lambda x: -x[1]):
            lines.append(f"    {src:22s} {count:>10,}")
        if cit.get("spread"):
            lines.append(f"    {'Spread':22s} {cit['spread']:>10,} ({cit.get('spread_pct', 0):.0f}%)")
            lines.append(f"    {'Median':22s} {cit.get('median_count', 0):>10,}")
        if cit.get("outlier_sources"):
            lines.append(f"  Outliers (>30% from median): {', '.join(cit['outlier_sources'])}")

    # OA status
    oa = dr.get("oa_status", {})
    has_oa_data = oa.get("status_by_source") or oa.get("is_oa_by_source")
    if has_oa_data:
        lines.append("")
        lines.append("OPEN ACCESS STATUS")
        lines.append("-" * 40)
        if oa.get("status_by_source"):
            agrees = oa.get("status_agrees", True)
            lines.append(f"  Status agreement: {'YES' if agrees else 'NO - CONFLICT'}")
            for src, status in oa["status_by_source"].items():
                lines.append(f"    {src:22s} {status}")
            if oa.get("consensus_status"):
                lines.append(f"  Consensus: {oa['consensus_status']}")
        if not oa.get("is_oa_agrees", True) and oa.get("is_oa_by_source"):
            lines.append("  is_oa boolean CONFLICT:")
            for src, val in oa["is_oa_by_source"].items():
                lines.append(f"    {src:22s} {'Open Access' if val else 'Closed'}")
        lines.append(f"  Unique OA URLs: {oa.get('unique_oa_urls', 0)}")
        if oa.get("sources_only_in"):
            for src, urls in oa["sources_only_in"].items():
                lines.append(f"  {src}: {len(urls)} exclusive URL(s)")

    # Authors
    auth = dr.get("authors", {})
    if auth.get("count_by_source"):
        lines.append("")
        lines.append("AUTHORS")
        lines.append("-" * 40)
        agrees = auth.get("count_agrees", True)
        lines.append(f"  Count agreement: {'YES' if agrees else 'NO - VARIES'}")
        for src, count in sorted(auth["count_by_source"].items()):
            lines.append(f"    {src:22s} {count}")
        if auth.get("orcid_coverage") is not None:
            lines.append(f"  ORCID coverage: {int(auth['orcid_coverage'] * 100)}%")
        if auth.get("sources_missing_orcids"):
            lines.append(f"  Sources missing ORCIDs: {', '.join(auth['sources_missing_orcids'])}")
        if auth.get("name_variant_examples"):
            lines.append(f"  Name variants: {'; '.join(auth['name_variant_examples'][:3])}")

    # Funding
    fund = dr.get("funding", {})
    if fund.get("total_unique_grants", 0) > 0 or fund.get("grant_count_by_source"):
        lines.append("")
        lines.append("FUNDING")
        lines.append("-" * 40)
        lines.append(f"  Unique grants: {fund.get('total_unique_grants', 0)}")
        lines.append(f"  Multi-source confirmed: {fund.get('grants_multi_source', 0)}")
        lines.append(f"  Single-source only: {fund.get('grants_single_source', 0)}")
        if fund.get("grant_count_by_source"):
            lines.append("  Grant count by source:")
            for src, count in sorted(fund["grant_count_by_source"].items(), key=lambda x: -x[1]):
                lines.append(f"    {src:22s} {count}")
        if fund.get("sources_with_no_funding"):
            lines.append(f"  Sources with no funding data: {', '.join(fund['sources_with_no_funding'][:5])}")

    # References
    ref = dr.get("references", {})
    if ref.get("count_by_source"):
        lines.append("")
        lines.append("REFERENCES")
        lines.append("-" * 40)
        agrees = ref.get("count_agrees", True)
        lines.append(f"  Count agreement: {'YES' if agrees else 'NO - VARIES'}")
        for src, count in sorted(ref["count_by_source"].items()):
            lines.append(f"    {src:22s} {count}")

    # Topics
    topics = dr.get("topics", {})
    if topics.get("vocabulary_count", 0) > 0:
        lines.append("")
        lines.append("TOPICS/SUBJECTS")
        lines.append("-" * 40)
        lines.append(f"  Vocabularies: {topics['vocabulary_count']}")
        lines.append(f"  Multi-source topics: {topics.get('multi_source_topics', 0)}")
        lines.append(f"  Single-source topics: {topics.get('single_source_topics', 0)}")

    # Related works
    rw = dr.get("related_works", {})
    has_rw = rw.get("related_count_by_source") or rw.get("datacite_reverse_count", 0) > 0
    if has_rw:
        lines.append("")
        lines.append("RELATED WORKS")
        lines.append("-" * 40)
        if rw.get("related_count_by_source"):
            for src, count in sorted(rw["related_count_by_source"].items(), key=lambda x: -x[1]):
                lines.append(f"    {src:22s} {count}")
        if rw.get("datacite_reverse_count", 0) > 0:
            lines.append(f"  DataCite reverse search: {rw['datacite_reverse_count']} linked datasets")
        if rw.get("software_links", 0) > 0:
            lines.append(f"  Software links: {rw['software_links']}")
        if rw.get("data_links", 0) > 0:
            lines.append(f"  Data links: {rw['data_links']}")
        if rw.get("has_version_chain"):
            lines.append("  Version chain: yes")

    # Scalars
    scalars = dr.get("scalar_discrepancies", [])
    if scalars:
        lines.append("")
        lines.append("OTHER SCALAR DISCREPANCIES")
        lines.append("-" * 40)
        for d in scalars:
            lines.append(f"  [{d.get('risk', 'low').upper():6s}] {d['field']}:")
            for src, val in d.get("values", {}).items():
                lines.append(f"    {src:22s} = {val}")

    # Risk totals
    lines.append("")
    lines.append("=" * 72)
    total_disc = dr.get("total_discrepancies", 0)
    lines.append(
        f"TOTAL DISCREPANCIES: {total_disc}  "
        f"(HIGH: {dr.get('high_risk_count', 0)}  "
        f"MEDIUM: {dr.get('medium_risk_count', 0)}  "
        f"LOW: {dr.get('low_risk_count', 0)})"
    )
    lines.append("=" * 72)

    return "\n".join(lines)
