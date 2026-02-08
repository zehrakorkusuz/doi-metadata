"""Entrez/PubMed fetcher — authoritative PMID, MeSH, publication types, gene symbols, databank accessions."""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET

from doi_metadata.config import settings
from doi_metadata.fetchers.base import fetch_json, get_client
from doi_metadata.models import (
    Affiliation,
    Author,
    Grant,
    MeSHTerm,
    PersonName,
    SourceName,
    SourceResult,
    Subject,
)

logger = logging.getLogger(__name__)
SOURCE = SourceName.ENTREZ

EUTILS_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"


def _eutils_params() -> dict[str, str]:
    """Common parameters for all E-utilities calls."""
    params: dict[str, str] = {}
    if settings.entrez_email:
        params["email"] = settings.entrez_email
    if settings.entrez_api_key:
        params["api_key"] = settings.entrez_api_key
    return params


async def _fetch_xml(url: str, params: dict[str, str], source_name: str) -> ET.Element | None:
    """Fetch XML from E-utilities and return the root Element, or None on 404/error."""
    client = await get_client()
    try:
        resp = await client.get(url, params=params)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return ET.fromstring(resp.text)
    except Exception as exc:
        logger.warning("%s: XML fetch failed: %s", source_name, exc)
        return None


def _text(el: ET.Element | None, path: str) -> str | None:
    """Extract text from a subelement, or None if missing."""
    if el is None:
        return None
    node = el.find(path)
    return node.text if node is not None else None


def _all_text(el: ET.Element, path: str) -> list[str]:
    """Extract text from all matching subelements."""
    return [n.text for n in el.findall(path) if n.text]


async def fetch_entrez(doi: str) -> SourceResult:
    result = SourceResult(source=SOURCE, doi=doi)

    # Step 1: esearch — find PMID for this DOI
    search_params = {
        **_eutils_params(),
        "db": "pubmed",
        "term": f"{doi}[doi]",
        "retmode": "json",
    }

    try:
        data = await fetch_json(
            f"{EUTILS_BASE}/esearch.fcgi",
            params=search_params,
            source_name="Entrez-esearch",
        )
    except Exception as exc:
        result.error = str(exc)
        return result

    if not data:
        return result

    id_list = data.get("esearchresult", {}).get("idlist", [])
    if not id_list:
        return result

    pmid = id_list[0]

    # Step 2: efetch — get full PubMed XML record
    fetch_params = {
        **_eutils_params(),
        "db": "pubmed",
        "id": pmid,
        "retmode": "xml",
    }

    root = await _fetch_xml(f"{EUTILS_BASE}/efetch.fcgi", fetch_params, "Entrez-efetch")
    if root is None:
        return result

    article_el = root.find(".//PubmedArticle")
    if article_el is None:
        return result

    result.found = True
    result.pmid = pmid

    medline = article_el.find("MedlineCitation")
    article = medline.find("Article") if medline is not None else None
    pubmed_data = article_el.find("PubmedData")

    if article is None:
        return result

    # Store raw as a simple dict summary (XML doesn't map cleanly to raw dict)
    result.raw = {"pmid": pmid, "source_format": "pubmed_xml"}

    # --- Basic metadata ---
    result.title = _text(article, "ArticleTitle")
    result.vernacular_title = _text(article, "VernacularTitle")

    journal = article.find("Journal")
    if journal is not None:
        result.container_title = _text(journal, "Title") or _text(journal, "ISOAbbreviation")
        ji = journal.find("JournalIssue")
        if ji is not None:
            result.volume = _text(ji, "Volume")
            result.issue = _text(ji, "Issue")
            pub_date = ji.find("PubDate")
            if pub_date is not None:
                year = _text(pub_date, "Year")
                if year:
                    result.publication_year = int(year)
                    month = _text(pub_date, "Month") or "01"
                    day = _text(pub_date, "Day") or "01"
                    result.publication_date = f"{year}-{month}-{day}"
                elif _text(pub_date, "MedlineDate"):
                    # e.g. "2023 Jan-Feb"
                    md = _text(pub_date, "MedlineDate") or ""
                    parts = md.split()
                    if parts and parts[0].isdigit():
                        result.publication_year = int(parts[0])

        issn_el = journal.find("ISSN")
        if issn_el is not None and issn_el.text:
            result.issn = [issn_el.text]

    result.pages = _text(article, "Pagination/MedlinePgn")
    result.language = _text(article, "Language")

    # --- Abstract ---
    abstract_el = article.find("Abstract")
    if abstract_el is not None:
        parts = []
        structured: dict[str, str] = {}
        for at in abstract_el.findall("AbstractText"):
            label = at.get("Label")
            # AbstractText can contain mixed content; get all text including tail of children
            text = "".join(at.itertext()).strip()
            if text:
                parts.append(f"{label}: {text}" if label else text)
                if label:
                    structured[label] = text
        result.abstract = "\n".join(parts) if parts else None
        if structured:
            result.structured_abstract = structured

    # --- Publication types ---
    pub_type_list = article.find("PublicationTypeList")
    if pub_type_list is not None:
        result.publication_types = [pt.text for pt in pub_type_list.findall("PublicationType") if pt.text]
        # Map to work_type: pick the most specific
        pt_set = {pt.lower() for pt in result.publication_types}
        if "review" in pt_set:
            result.work_type = "review"
        elif "clinical trial" in pt_set or any("clinical trial" in pt for pt in pt_set):
            result.work_type = "clinical-trial"
        elif "meta-analysis" in pt_set:
            result.work_type = "meta-analysis"
        elif "preprint" in pt_set:
            result.work_type = "preprint"
        elif "journal article" in pt_set:
            result.work_type = "journal-article"
        elif "dataset" in pt_set:
            result.work_type = "dataset"

    # --- Authors ---
    author_list = article.find("AuthorList")
    if author_list is not None:
        for i, a in enumerate(author_list.findall("Author")):
            orcid = None
            for ident in a.findall("Identifier"):
                if ident.get("Source") == "ORCID" and ident.text:
                    # Normalize: may be full URL or just the ID
                    orcid_val = ident.text.strip()
                    if "/" in orcid_val:
                        orcid_val = orcid_val.rsplit("/", 1)[-1]
                    orcid = orcid_val

            affiliations = []
            for aff in a.findall("AffiliationInfo/Affiliation"):
                if aff.text:
                    affiliations.append(Affiliation(name=aff.text, source=SOURCE))

            given = _text(a, "ForeName")
            family = _text(a, "LastName")
            collective = _text(a, "CollectiveName")

            result.authors.append(
                Author(
                    name=PersonName(
                        given=given,
                        family=family,
                        full_name=collective or (f"{given} {family}" if given and family else None),
                        sequence="first" if i == 0 else "additional",
                        orcid=orcid,
                        source=SOURCE,
                    ),
                    affiliations=affiliations,
                    sources=[SOURCE],
                )
            )

    # --- MeSH headings ---
    if medline is not None:
        mesh_list = medline.find("MeshHeadingList")
        if mesh_list is not None:
            for mh in mesh_list.findall("MeshHeading"):
                desc = mh.find("DescriptorName")
                if desc is not None and desc.text:
                    result.mesh_terms.append(
                        MeSHTerm(
                            descriptor_name=desc.text,
                            descriptor_ui=desc.get("UI"),
                            is_major_topic=desc.get("MajorTopicYN") == "Y",
                            source=SOURCE,
                        )
                    )
                    for qual in mh.findall("QualifierName"):
                        if qual.text:
                            result.mesh_terms.append(
                                MeSHTerm(
                                    descriptor_name=desc.text,
                                    descriptor_ui=desc.get("UI"),
                                    qualifier_name=qual.text,
                                    qualifier_ui=qual.get("UI"),
                                    is_major_topic=qual.get("MajorTopicYN") == "Y",
                                    source=SOURCE,
                                )
                            )

        # --- Keywords ---
        for kw_list in medline.findall("KeywordList"):
            for kw in kw_list.findall("Keyword"):
                if kw.text:
                    result.keywords.append(kw.text)

        # --- Chemicals / substances ---
        chem_list = medline.find("ChemicalList")
        if chem_list is not None:
            result.chemicals = [
                {
                    "name": _text(c, "NameOfSubstance") or "",
                    "registry_number": _text(c, "RegistryNumber") or "",
                    "substance_ui": (
                        c.find("NameOfSubstance").get("UI", "")
                        if c.find("NameOfSubstance") is not None
                        else ""
                    ),
                }
                for c in chem_list.findall("Chemical")
            ]

        # --- Gene symbols ---
        gene_list = medline.find("GeneSymbolList")
        if gene_list is not None:
            result.gene_symbols = [gs.text for gs in gene_list.findall("GeneSymbol") if gs.text]

    # --- Grants ---
    grant_list = article.find("GrantList")
    if grant_list is not None:
        for g in grant_list.findall("Grant"):
            result.grants.append(
                Grant(
                    grant_id=_text(g, "GrantID"),
                    agency=_text(g, "Agency"),
                    source=SOURCE,
                )
            )

    # --- Databank accession numbers ---
    dbi_list = article.find("DataBankList")
    if dbi_list is not None:
        for db in dbi_list.findall("DataBank"):
            db_name = _text(db, "DataBankName")
            accessions = _all_text(db, "AccessionNumberList/AccessionNumber")
            if db_name:
                result.databank_accessions.append({
                    "databank": db_name,
                    "accession_numbers": accessions,
                })

    # --- Article IDs (DOI, PMC, PII, etc.) ---
    if pubmed_data is not None:
        for aid in pubmed_data.findall("ArticleIdList/ArticleId"):
            id_type = aid.get("IdType")
            if id_type == "pmc" and aid.text:
                result.pmcid = aid.text
            elif id_type == "doi" and aid.text:
                # Confirm DOI matches
                pass

        # --- Article dates ---
        history = pubmed_data.find("History")
        if history is not None:
            for pd in history.findall("PubMedPubDate"):
                status = pd.get("PubStatus")
                year = _text(pd, "Year")
                month = _text(pd, "Month") or "01"
                day = _text(pd, "Day") or "01"
                if status and year:
                    result.article_dates[status] = f"{year}-{month.zfill(2)}-{day.zfill(2)}"

        # --- Reference count ---
        ref_list = pubmed_data.find("ReferenceList")
        if ref_list is not None:
            refs = ref_list.findall("Reference")
            result.reference_count = len(refs)

    # --- Conflict of interest ---
    coi = article.find("CoiStatement")
    if coi is not None:
        result.conflict_of_interest = "".join(coi.itertext()).strip() or None

    # --- Subjects from MeSH (also add as Subject for topic profile) ---
    for mt in result.mesh_terms:
        if mt.qualifier_name is None:  # Only descriptors, not qualifier variants
            result.subjects.append(
                Subject(value=mt.descriptor_name, scheme="MeSH", source=SOURCE)
            )

    return result
