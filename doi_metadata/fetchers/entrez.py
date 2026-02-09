"""Entrez/PubMed fetcher — comprehensive PubMed XML extraction.

Extracts everything available from the PubmedArticle XML:
- Authoritative PMID/PMCID/PII identifiers
- Structured abstracts (labeled sections) + other-language abstracts
- Publication types (controlled vocabulary: Clinical Trial, Review, etc.)
- Full MeSH headings with descriptor/qualifier UIDs and major topic flags
- Supplementary MeSH concepts (drugs, chemicals, organisms)
- Authors with ORCIDs, affiliations, collective names
- Investigators (consortium/collaborative group members)
- Grants with agency, acronym, country
- Gene symbols
- Databank accession numbers (GenBank, ClinicalTrials.gov, PDB, GEO, etc.)
- Chemicals/substances with NLM UIDs and registry numbers
- Comments/corrections (ErratumFor, RetractionOf, CommentOn, etc.)
- Article date history (received, accepted, revised, published)
- Electronic publication date
- Conflict of interest statement
- Keywords with major topic flags
- Personal name subjects (biography subjects)
- MedlineJournalInfo (NLM ID, country, MedlineTA)
- Publication status, citation subsets
- Individual references with PMIDs/DOIs
- ObjectList (related objects)
"""

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
    Reference,
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


def _parse_person(el: ET.Element, index: int) -> Author:
    """Parse an Author or Investigator element into an Author model."""
    orcid = None
    for ident in el.findall("Identifier"):
        if ident.get("Source") == "ORCID" and ident.text:
            orcid_val = ident.text.strip()
            if "/" in orcid_val:
                orcid_val = orcid_val.rsplit("/", 1)[-1]
            orcid = orcid_val

    affiliations = []
    for aff in el.findall("AffiliationInfo/Affiliation"):
        if aff.text:
            affiliations.append(Affiliation(name=aff.text, source=SOURCE))

    given = _text(el, "ForeName")
    family = _text(el, "LastName")
    suffix = _text(el, "Suffix")
    collective = _text(el, "CollectiveName")

    # Build full_name: prefer collective name, else construct from parts
    full_name = collective
    if not full_name and given and family:
        full_name = f"{given} {family}"
        if suffix:
            full_name += f" {suffix}"
    elif not full_name and family:
        # Fall back to initials + family if no given name
        initials = _text(el, "Initials")
        if initials:
            full_name = f"{initials} {family}"

    return Author(
        name=PersonName(
            given=given,
            family=family,
            full_name=full_name,
            sequence="first" if index == 0 else "additional",
            orcid=orcid,
            source=SOURCE,
        ),
        affiliations=affiliations,
        sources=[SOURCE],
    )


def _parse_date_element(el: ET.Element) -> str | None:
    """Parse a PubMed date element (Year/Month/Day) into YYYY-MM-DD."""
    year = _text(el, "Year")
    if not year:
        return None
    month = _text(el, "Month") or "01"
    day = _text(el, "Day") or "01"
    return f"{year}-{month.zfill(2)}-{day.zfill(2)}"


async def fetch_entrez(doi: str) -> SourceResult:
    result = SourceResult(source=SOURCE, doi=doi)

    # ── Step 1: esearch — find PMID for this DOI ──
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

    # ── Step 2: efetch — get full PubMed XML record ──
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

    # ══════════════════════════════════════════════════════════════════════
    # ARTICLE METADATA
    # ══════════════════════════════════════════════════════════════════════

    # --- Title ---
    result.title = _text(article, "ArticleTitle")
    result.vernacular_title = _text(article, "VernacularTitle")

    # --- Journal ---
    journal = article.find("Journal")
    if journal is not None:
        result.container_title = (
            _text(journal, "Title") or _text(journal, "ISOAbbreviation")
        )
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

        # ISSN (print and/or electronic)
        issns = []
        for issn_el in journal.findall("ISSN"):
            if issn_el.text:
                issns.append(issn_el.text)
        if issns:
            result.issn = issns

    # --- Pagination & ELocationID ---
    result.pages = _text(article, "Pagination/MedlinePgn")
    for eloc in article.findall("ELocationID"):
        eid_type = eloc.get("EIdType")
        if eid_type == "pii" and eloc.text:
            result.pii = eloc.text
        # DOI from ELocationID is redundant with input DOI

    result.language = _text(article, "Language")

    # --- Abstract (structured) ---
    abstract_el = article.find("Abstract")
    if abstract_el is not None:
        parts = []
        structured: dict[str, str] = {}
        for at in abstract_el.findall("AbstractText"):
            label = at.get("Label")
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
        result.publication_types = [
            pt.text for pt in pub_type_list.findall("PublicationType") if pt.text
        ]
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
            result.authors.append(_parse_person(a, i))

    # --- ArticleDate (electronic publication date) ---
    for article_date in article.findall("ArticleDate"):
        if article_date.get("DateType") == "Electronic":
            result.electronic_publication_date = _parse_date_element(article_date)

    # --- Grants (with acronym and country) ---
    grant_list = article.find("GrantList")
    if grant_list is not None:
        for g in grant_list.findall("Grant"):
            result.grants.append(
                Grant(
                    grant_id=_text(g, "GrantID"),
                    agency=_text(g, "Agency"),
                    agency_abbreviation=_text(g, "Acronym"),
                    jurisdiction=_text(g, "Country"),
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

    # --- Conflict of interest ---
    coi = article.find("CoiStatement")
    if coi is not None:
        result.conflict_of_interest = "".join(coi.itertext()).strip() or None

    # ══════════════════════════════════════════════════════════════════════
    # MEDLINE CITATION METADATA
    # ══════════════════════════════════════════════════════════════════════

    if medline is not None:
        # --- MeSH headings ---
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

        # --- Supplementary MeSH concepts (drugs, diseases, organisms) ---
        suppl_mesh = medline.find("SupplMeshList")
        if suppl_mesh is not None:
            for sm in suppl_mesh.findall("SupplMeshName"):
                if sm.text:
                    result.supplementary_mesh.append({
                        "name": sm.text,
                        "type": sm.get("Type", ""),  # Disease, Protocol, Organism
                        "ui": sm.get("UI", ""),
                    })

        # --- Keywords (with major topic tracking) ---
        for kw_list in medline.findall("KeywordList"):
            for kw in kw_list.findall("Keyword"):
                if kw.text:
                    result.keywords.append(kw.text)
                    if kw.get("MajorTopicYN") == "Y":
                        result.major_topic_keywords.append(kw.text)

        # --- Chemicals / substances ---
        chem_list = medline.find("ChemicalList")
        if chem_list is not None:
            result.chemicals = []
            for c in chem_list.findall("Chemical"):
                nos = c.find("NameOfSubstance")
                result.chemicals.append({
                    "name": _text(c, "NameOfSubstance") or "",
                    "registry_number": _text(c, "RegistryNumber") or "",
                    "substance_ui": nos.get("UI", "") if nos is not None else "",
                })

        # --- Gene symbols ---
        gene_list = medline.find("GeneSymbolList")
        if gene_list is not None:
            result.gene_symbols = [
                gs.text for gs in gene_list.findall("GeneSymbol") if gs.text
            ]

        # --- Comments/Corrections (retractions, errata, comments) ---
        cc_list = medline.find("CommentsCorrectionsList")
        if cc_list is not None:
            for cc in cc_list.findall("CommentsCorrections"):
                entry: dict[str, str] = {
                    "ref_type": cc.get("RefType", ""),
                }
                ref_source = _text(cc, "RefSource")
                if ref_source:
                    entry["ref_source"] = ref_source
                cc_pmid = _text(cc, "PMID")
                if cc_pmid:
                    entry["pmid"] = cc_pmid
                note = _text(cc, "Note")
                if note:
                    entry["note"] = note
                result.comment_corrections.append(entry)

        # --- Investigators (consortium/collaborative group members) ---
        investigator_list = medline.find("InvestigatorList")
        if investigator_list is not None:
            for i, inv in enumerate(investigator_list.findall("Investigator")):
                result.investigators.append(_parse_person(inv, i))

        # --- Other abstracts (translated abstracts) ---
        for other_abs in medline.findall("OtherAbstract"):
            abs_type = other_abs.get("Type", "")
            abs_lang = other_abs.get("Language", "")
            parts = []
            for at in other_abs.findall("AbstractText"):
                label = at.get("Label")
                text = "".join(at.itertext()).strip()
                if text:
                    parts.append(f"{label}: {text}" if label else text)
            if parts:
                result.other_abstracts.append({
                    "type": abs_type,
                    "language": abs_lang,
                    "text": "\n".join(parts),
                })

        # --- MedlineJournalInfo ---
        mji = medline.find("MedlineJournalInfo")
        if mji is not None:
            result.country_of_publication = _text(mji, "Country")
            result.nlm_journal_id = _text(mji, "NlmUniqueID")
            result.medline_ta = _text(mji, "MedlineTA")
            # ISSNLinking: add to ISSN list if not already there
            linking_issn = _text(mji, "ISSNLinking")
            if linking_issn and linking_issn not in result.issn:
                result.issn.append(linking_issn)

        # --- Citation subsets ---
        for cs in medline.findall("CitationSubset"):
            if cs.text:
                result.citation_subsets.append(cs.text)

        # --- Personal name subjects (biographies) ---
        pns_list = medline.find("PersonalNameSubjectList")
        if pns_list is not None:
            for pns in pns_list.findall("PersonalNameSubject"):
                entry = {}
                given = _text(pns, "ForeName")
                family = _text(pns, "LastName")
                if given:
                    entry["given"] = given
                if family:
                    entry["family"] = family
                initials = _text(pns, "Initials")
                if initials:
                    entry["initials"] = initials
                suffix = _text(pns, "Suffix")
                if suffix:
                    entry["suffix"] = suffix
                if entry:
                    result.personal_name_subjects.append(entry)

    # ══════════════════════════════════════════════════════════════════════
    # PUBMED DATA
    # ══════════════════════════════════════════════════════════════════════

    if pubmed_data is not None:
        # --- Article IDs (DOI, PMC, PII, MID, etc.) ---
        for aid in pubmed_data.findall("ArticleIdList/ArticleId"):
            id_type = aid.get("IdType")
            if id_type == "pmc" and aid.text:
                result.pmcid = aid.text
            elif id_type == "pii" and aid.text and not result.pii:
                result.pii = aid.text
            elif id_type == "mid" and aid.text:
                # Manuscript ID (NIH Manuscript Submission System)
                result.raw["mid"] = aid.text

        # --- Publication status ---
        pub_status = _text(pubmed_data, "PublicationStatus")
        if pub_status:
            result.publication_status = pub_status

        # --- Article date history ---
        history = pubmed_data.find("History")
        if history is not None:
            for pd in history.findall("PubMedPubDate"):
                status = pd.get("PubStatus")
                date_str = _parse_date_element(pd)
                if status and date_str:
                    result.article_dates[status] = date_str

        # --- References (individual, with PMIDs and DOIs) ---
        ref_list = pubmed_data.find("ReferenceList")
        if ref_list is not None:
            refs = ref_list.findall("Reference")
            result.reference_count = len(refs)
            for ref_el in refs:
                citation_text = _text(ref_el, "Citation")
                ref_doi = None
                ref_pmid = None
                for aid in ref_el.findall("ArticleIdList/ArticleId"):
                    id_type = aid.get("IdType")
                    if id_type == "doi" and aid.text:
                        ref_doi = aid.text
                    elif id_type == "pubmed" and aid.text:
                        ref_pmid = aid.text
                result.references.append(
                    Reference(
                        doi=ref_doi,
                        pmid=ref_pmid,
                        unstructured=citation_text,
                        source=SOURCE,
                    )
                )

        # --- ObjectList (related objects) ---
        obj_list = pubmed_data.find("ObjectList")
        if obj_list is not None:
            for obj in obj_list.findall("Object"):
                obj_entry: dict[str, str] = {
                    "type": obj.get("Type", ""),
                }
                for param in obj.findall("Param"):
                    param_name = param.get("Name", "")
                    if param.text:
                        obj_entry[param_name] = param.text
                result.objects.append(obj_entry)

    # ══════════════════════════════════════════════════════════════════════
    # DERIVED FIELDS
    # ══════════════════════════════════════════════════════════════════════

    # --- Subjects from MeSH (feed into topic profile analysis) ---
    for mt in result.mesh_terms:
        if mt.qualifier_name is None:
            result.subjects.append(
                Subject(value=mt.descriptor_name, scheme="MeSH", source=SOURCE)
            )

    # --- Supplementary MeSH as subjects too ---
    for sm in result.supplementary_mesh:
        if sm.get("name"):
            result.subjects.append(
                Subject(
                    value=sm["name"],
                    scheme=f"SupplMeSH-{sm.get('type', 'Unknown')}",
                    source=SOURCE,
                )
            )

    return result
