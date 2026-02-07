"""Reconciliation engine — compare overlapping fields across sources, flag conflicts."""

from __future__ import annotations

from doi_metadata.models import ConflictReport, FieldConflict, SourceResult


def _compare_scalar(field: str, results: dict[str, SourceResult], extractor, risk: str = "medium") -> FieldConflict | None:
    """Compare a scalar field across sources. Returns a conflict if values disagree."""
    values: dict[str, object] = {}
    for name, r in results.items():
        if not r.found:
            continue
        val = extractor(r)
        if val is not None:
            values[name] = val

    if len(values) <= 1:
        return None

    unique_vals = set(str(v) for v in values.values())
    if len(unique_vals) <= 1:
        return None

    return FieldConflict(field=field, values=values, risk=risk)


def reconcile(doi: str, results: dict[str, SourceResult]) -> ConflictReport:
    """Run all reconciliation checks and produce a conflict report."""
    report = ConflictReport(doi=doi)
    conflicts: list[FieldConflict] = []

    # --- Citation counts (HIGH risk) ---
    c = _compare_scalar("citation_count", results, lambda r: r.citation_count, risk="high")
    if c:
        conflicts.append(c)

    # --- Reference counts ---
    c = _compare_scalar("reference_count", results, lambda r: r.reference_count, risk="low")
    if c:
        conflicts.append(c)

    # --- Title ---
    c = _compare_scalar("title", results, lambda r: r.title.strip().rstrip(".") if r.title else None, risk="low")
    if c:
        conflicts.append(c)

    # --- Publication year ---
    c = _compare_scalar("publication_year", results, lambda r: r.publication_year, risk="low")
    if c:
        conflicts.append(c)

    # --- OA status (MEDIUM risk) ---
    c = _compare_scalar("oa_status", results, lambda r: r.oa_status.value if r.oa_status else None, risk="medium")
    if c:
        conflicts.append(c)

    c = _compare_scalar("is_oa", results, lambda r: r.is_oa, risk="medium")
    if c:
        conflicts.append(c)

    # --- Work type ---
    c = _compare_scalar("work_type", results, lambda r: r.work_type, risk="low")
    if c:
        conflicts.append(c)

    # --- Author count (proxy for author list conflicts) ---
    c = _compare_scalar(
        "author_count",
        results,
        lambda r: len(r.authors) if r.authors else None,
        risk="high",
    )
    if c:
        conflicts.append(c)

    # --- Publisher ---
    c = _compare_scalar("publisher", results, lambda r: r.publisher, risk="low")
    if c:
        conflicts.append(c)

    # --- Container / journal title ---
    c = _compare_scalar("container_title", results, lambda r: r.container_title, risk="low")
    if c:
        conflicts.append(c)

    report.conflicts = conflicts
    report.conflict_count = len(conflicts)

    # Count agreements (fields where 2+ sources agree)
    agreement_checks = [
        lambda r: r.title,
        lambda r: r.publication_year,
        lambda r: r.citation_count,
        lambda r: r.is_oa,
    ]
    for check in agreement_checks:
        values = set()
        for r in results.values():
            if r.found:
                v = check(r)
                if v is not None:
                    values.add(str(v))
        if len(values) == 1:
            report.agreement_count += 1

    return report
