"""PubMed XML parsing helpers."""

from __future__ import annotations

from xml.etree import ElementTree as ET


def _text_content(element: ET.Element | None) -> str:
    if element is None:
        return ""
    return "".join(element.itertext()).strip()


def _list_texts(elements: list[ET.Element]) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for element in elements:
        text = _text_content(element)
        if not text or text in seen:
            continue
        seen.add(text)
        values.append(text)
    return values


def _preferred_article_type(article_types: list[str]) -> str | None:
    if not article_types:
        return None
    preferred_labels = [
        "Systematic Review",
        "Meta-Analysis",
        "Randomized Controlled Trial",
        "Clinical Trial",
        "Comparative Study",
        "Review",
        "Journal Article",
    ]
    lowered = {item.lower(): item for item in article_types}
    for label in preferred_labels:
        if label.lower() in lowered:
            return lowered[label.lower()]
    return None


def parse_pubmed_fetch_xml(xml_text: str) -> dict[str, dict[str, object]]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return {}

    parsed: dict[str, dict[str, object]] = {}
    for article in root.findall(".//PubmedArticle"):
        pmid = _text_content(article.find("./MedlineCitation/PMID"))
        if not pmid:
            continue

        abstract_parts: list[str] = []
        for abstract_text in article.findall(".//Article/Abstract/AbstractText"):
            piece = _text_content(abstract_text)
            if not piece:
                continue
            label = abstract_text.attrib.get("Label")
            abstract_parts.append(f"{label}: {piece}" if label else piece)

        doi = None
        pmc_id = None
        for article_id in article.findall("./PubmedData/ArticleIdList/ArticleId"):
            id_type = article_id.attrib.get("IdType", "").lower()
            value = _text_content(article_id) or None
            if id_type == "doi":
                doi = value
            if id_type == "pmc":
                pmc_id = value

        article_types = _list_texts(article.findall(".//PublicationTypeList/PublicationType"))
        keywords = _list_texts(article.findall(".//KeywordList/Keyword"))
        mesh_terms = _list_texts(article.findall(".//MeshHeadingList/MeshHeading/DescriptorName"))
        authors: list[str] = []
        for author in article.findall(".//AuthorList/Author"):
            collective = _text_content(author.find("./CollectiveName"))
            if collective:
                authors.append(collective)
                continue
            last_name = _text_content(author.find("./LastName"))
            fore_name = _text_content(author.find("./ForeName"))
            initials = _text_content(author.find("./Initials"))
            full_name = " ".join(part for part in (fore_name, last_name) if part).strip()
            if not full_name:
                full_name = " ".join(part for part in (initials, last_name) if part).strip()
            if full_name:
                authors.append(full_name)
        journal = _text_content(article.find(".//Article/Journal/Title")) or None
        issns = _list_texts(article.findall(".//Article/Journal/ISSN"))
        issn_l = _text_content(article.find(".//MedlineJournalInfo/ISSNLinking")) or None
        publication_date = _text_content(article.find(".//Article/Journal/JournalIssue/PubDate")) or None
        title = _text_content(article.find(".//Article/ArticleTitle")) or None
        references = article.findall(".//PubmedData/ReferenceList/Reference")

        parsed[pmid] = {
            "title": title,
            "abstract": "\n".join(abstract_parts).strip(),
            "doi": doi,
            "pmc_id": pmc_id,
            "journal": journal,
            "publication_date": publication_date,
            "article_types": article_types,
            "article_type": _preferred_article_type(article_types),
            "authors": authors,
            "keywords": keywords,
            "mesh_terms": mesh_terms,
            "reference_count": len(references),
            "issn_l": issn_l,
            "issns": issns,
        }
    return parsed
