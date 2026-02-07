"""DOI Metadata Aggregator — query 11 scholarly APIs, normalize, reconcile.

Library usage:

    import asyncio
    from doi_metadata import lookup

    result = asyncio.run(lookup("10.1038/s41586-023-06647-8"))

    # Primary data from each source
    for name, src in result.sources.items():
        if src.found:
            print(f"{name}: {src.citation_count} citations, {len(src.authors)} authors")

    # Identifier crosswalk
    print(result.crosswalk.pmid, result.crosswalk.pmcid)

    # Derived analyses
    print(result.analyses.impact)      # citation comparison, FWCI, trends
    print(result.analyses.funding)     # merged funding landscape
    print(result.analyses.oa_audit)    # cross-source OA verification
    print(result.analyses.authors)     # disambiguated author network
    print(result.analyses.topics)      # unified subject mapping

    # Conflicts
    for c in result.conflicts.conflicts:
        print(f"{c.field}: {c.values}")
"""

__version__ = "0.1.0"

# Public API — direct library usage (no server needed)
from doi_metadata.orchestrator import lookup  # noqa: F401, E402
from doi_metadata.models import (  # noqa: F401, E402
    AggregatedResult,
    AnalysesResult,
    Author,
    Citation,
    ConflictReport,
    FieldConflict,
    FileInfo,
    Funder,
    Grant,
    IdentifierCrosswalk,
    ImpactIndicator,
    License,
    MeSHTerm,
    OALocation,
    OAStatus,
    PersonName,
    Reference,
    RelatedWork,
    SourceName,
    SourceResult,
    Subject,
    UsageStat,
    VersionInfo,
)

__all__ = [
    "lookup",
    "AggregatedResult",
    "AnalysesResult",
    "Author",
    "Citation",
    "ConflictReport",
    "FieldConflict",
    "FileInfo",
    "Funder",
    "Grant",
    "IdentifierCrosswalk",
    "ImpactIndicator",
    "License",
    "MeSHTerm",
    "OALocation",
    "OAStatus",
    "PersonName",
    "Reference",
    "RelatedWork",
    "SourceName",
    "SourceResult",
    "Subject",
    "UsageStat",
    "VersionInfo",
]
