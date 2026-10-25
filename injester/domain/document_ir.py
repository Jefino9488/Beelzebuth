"""
Beelzebuth Canonical Document Model — Model A: Document IR.

Provides a faithful, structural representation of ANY source document with stable block IDs,
element-level formatting snapshots, structural locations, and cryptographic fingerprints.

Supported document types: Resume/CV, Report, Manual/SOP, Research Paper, Contract, Generic.
Block types cover all major OOXML constructs: headings, paragraphs, list items, tables,
callouts, figure captions, citations, equations, and clauses.

Note on block ID stability: IDs (block-001, block-002, …) are assigned by traversal order
at extraction time. They are stable for a given file version but will change when the file
is structurally modified. Use xml_signature_hash and fingerprint_hash for durable identity.
"""

from __future__ import annotations

import os
import hashlib
import re
import zipfile
from enum import Enum
from typing import List, Dict, Optional, Any, Set
from pydantic import BaseModel, Field
from lxml import etree

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NSMAP = {"w": W_NS}


# ---------------------------------------------------------------------------
# Document type classification
# ---------------------------------------------------------------------------

class DocumentType(str, Enum):
    """
    Detected document type. Controls which semantic overlays (e.g. GroundedStep extraction,
    citation graph, dependency checking) are activated when loading a session.
    """
    RESUME = "RESUME"           # CV / Resume: sections, experience, education, skills
    REPORT = "REPORT"           # Business report, proposal, executive summary
    MANUAL = "MANUAL"           # SOP, technical manual, installation guide — procedural steps
    RESEARCH_PAPER = "RESEARCH_PAPER"  # Academic paper: sections, citations, equations, figures
    CONTRACT = "CONTRACT"       # Legal document: clauses, obligations, definitions
    GENERIC = "GENERIC"         # All other documents; safe default


def _normalize_heading(text: str) -> str:
    """Strips leading numbering/bullets (e.g. '1.1 ', 'A. ', '(i) ', '• ') and normalizes punctuation."""
    cleaned = re.sub(
        r"^\s*(?:(?:\d+(?:\.\d+)*|[A-Za-z](?:\.|\))|\([A-Za-z0-9]+\)|[-•▪*])\s*[:\.\-]?\s*)+",
        "",
        text,
    )
    if not cleaned.strip():
        cleaned = text
    cleaned = re.sub(r"[^\w\s]", " ", cleaned).strip().lower()
    return cleaned


def _count_keyword_matches_in_headings(headings: List[str], keywords: Set[str]) -> int:
    """
    Robust heading-keyword matcher: supports multi-word phrases and token membership
    (e.g. '1.1 Professional Experience' correctly matches the keyword 'experience').
    Excludes file listing lines and avoids substring collisions for single tokens.
    """
    matched: Set[str] = set()
    for h in headings:
        if h.strip().lower().startswith(("file:", "http", "./", "path:")):
            continue
        norm = _normalize_heading(h)
        tokens = set(re.findall(r"\b[a-z]{3,}\b", norm))
        for kw in keywords:
            if " " in kw:
                if re.search(r"\b" + re.escape(kw) + r"\b", norm):
                    matched.add(kw)
            elif kw in tokens:
                matched.add(kw)
    return len(matched)


def detect_document_type(
    blocks: Dict[str, "DocumentBlock"],
    structural_order: List[str],
    filename: str,
) -> DocumentType:
    """
    Heuristic document-type classifier based on heading vocabulary, block distribution,
    and filename cues. Returns one of the DocumentType variants.
    """
    fname_lower = filename.lower()
    heading_texts = [
        blocks[bid].text_content.lower()
        for bid in structural_order
        if bid in blocks and blocks[bid].formatting.is_heading
    ]
    all_texts_lower = " ".join(
        blocks[bid].text_content.lower()
        for bid in structural_order
        if bid in blocks
    )

    # Resume / CV signals — require strong filename signal OR multiple heading-level cues in a concise document.
    resume_heading_keywords = {"experience", "education", "skills", "objective",
                               "certification", "curriculum vitae", "resume", "linkedin",
                               "work history", "professional summary"}
    if (
        any(k in fname_lower for k in ("resume", "cv", "curriculum vitae"))
        or (
            len(structural_order) < 400
            and _count_keyword_matches_in_headings(
                [h for h in heading_texts if len(h.split()) <= 4 and not h.startswith(("file:", "http", "rule", "step"))],
                resume_heading_keywords,
            ) >= 3
        )
    ):
        return DocumentType.RESUME

    # Contract / Legal signals
    contract_keywords = {"agreement", "clause", "obligation", "whereas",
                         "notwithstanding", "hereinafter", "indemnify", "indemnification",
                         "liability", "terms and conditions", "confidentiality"}
    if (
        any(k in fname_lower for k in ("contract", "agreement", "nda", "mou", "tos"))
        or _count_keyword_matches_in_headings(heading_texts, contract_keywords) >= 2
    ):
        return DocumentType.CONTRACT

    # Research paper signals
    research_keywords = {"abstract", "literature review", "methodology", "bibliography", "hypothesis"}
    if (
        any(k in fname_lower for k in ("paper", "thesis", "dissertation", "journal", "research"))
        or _count_keyword_matches_in_headings(heading_texts, research_keywords) >= 2
    ):
        return DocumentType.RESEARCH_PAPER

    # Manual / SOP signals
    manual_keywords = {"installation", "procedure", "step", "warning", "caution", "note",
                       "configuration", "setup", "maintenance", "operation", "safety",
                       "troubleshooting", "prerequisite", "requirement"}
    list_item_count = sum(
        1 for bid in structural_order
        if bid in blocks and blocks[bid].block_type == "LIST_ITEM"
    )
    has_step_prefix = any(
        re.match(r"^step\s+\d+", blocks[bid].text_content.strip(), re.IGNORECASE)
        for bid in structural_order
        if bid in blocks
    )
    if (
        any(k in fname_lower for k in ("manual", "guide", "sop", "procedure", "installation"))
        or (has_step_prefix and list_item_count > 5)
        or sum(1 for k in manual_keywords if k in all_texts_lower) >= 5
    ):
        return DocumentType.MANUAL

    # Report signals
    report_keywords = {"executive summary", "overview", "recommendation", "analysis",
                       "findings", "background", "scope", "objective", "appendix"}
    if (
        any(k in fname_lower for k in ("report", "proposal", "analysis", "assessment"))
        or _count_keyword_matches_in_headings(heading_texts, report_keywords) >= 2
    ):
        return DocumentType.REPORT

    return DocumentType.GENERIC


# ---------------------------------------------------------------------------
# IR data models
# ---------------------------------------------------------------------------

class FormattingSnapshot(BaseModel):
    """Captures typographic and styling metadata for a block."""
    style_id: Optional[str] = None
    style_name: Optional[str] = None
    is_bold: bool = False
    is_italic: bool = False
    font_name: Optional[str] = None
    font_size_pt: Optional[float] = None
    num_id: Optional[int] = None       # Word numbering.xml reference
    ilvl: Optional[int] = None         # Numbering indent level
    is_heading: bool = False
    heading_level: Optional[int] = None
    is_list_item: bool = False
    is_table: bool = False


class SourceLocationRef(BaseModel):
    """
    Stable source identity for resolving document elements at edit time.
    Combines structural position (element_index within w:body) with content fingerprints.

    IMPORTANT: element_index is stable only for the file version at extraction time.
    After a structural edit, extract a fresh DocumentIR from the modified file.
    Use fingerprint_hash and xml_signature_hash to correlate blocks across versions.
    """
    part_name: str = "word/document.xml"
    element_tag: str = "w:p"            # "w:p" or "w:tbl"
    element_index: int                  # Positional index within w:body children
    xpath: str                          # Structural locator, e.g. "/w:document/w:body/w:p[4]"
    fingerprint_hash: str               # SHA-256 of verbatim text content
    xml_signature_hash: str             # SHA-256 of raw XML element bytes


class DocumentBlock(BaseModel):
    """
    Atomic structural block in Model A (Document IR).

    block_type values:
    - HEADING            — section heading at any level
    - PARAGRAPH          — body paragraph, clause body, or abstract text
    - LIST_ITEM          — numbered or bulleted list item (procedure step candidate)
    - TABLE              — tabular data (specifications, schedules, comparison matrices)
    - CALLOUT            — WARNING / CAUTION / NOTE / TIP callout
    - FIGURE_CAPTION     — image or diagram caption
    - CITATION           — inline or block citation / footnote reference
    - EQUATION           — mathematical expression or formula
    - CLAUSE             — numbered legal clause or contract section
    """
    block_id: str = Field(description="Stable identifier for this extraction, e.g. 'block-001'")
    block_type: str = Field(
        description="HEADING | PARAGRAPH | LIST_ITEM | TABLE | CALLOUT | "
                    "FIGURE_CAPTION | CITATION | EQUATION | CLAUSE"
    )
    text_content: str
    parent_block_id: Optional[str] = None
    sequence_index: int
    formatting: FormattingSnapshot
    location: SourceLocationRef
    span_ids: List[str] = Field(default_factory=list, description="Associated evidence spans [S###]")
    table_data: Optional[List[List[str]]] = None
    # Document-type-specific metadata (e.g. citation key, equation label, clause number)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class DocumentIR(BaseModel):
    """
    Model A: Faithful Structural Source Representation.
    Represents the full document hierarchy independent of semantic interpretations.
    """
    document_id: str
    filename: str
    file_format: str = "DOCX"
    file_hash: str
    document_type: DocumentType = DocumentType.GENERIC
    total_blocks: int = 0
    blocks: Dict[str, DocumentBlock] = Field(default_factory=dict)
    structural_order: List[str] = Field(default_factory=list)


def extract_docx_ir(file_path: str, document_id: Optional[str] = None) -> DocumentIR:
    """
    Extracts a faithful Document IR from a DOCX file using OOXML package parsing.
    Assigns stable block IDs, captures formatting, and generates structural fingerprints.
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"DOCX file not found: {file_path}")

    filename = os.path.basename(file_path)
    with open(file_path, "rb") as f:
        file_bytes = f.read()
    file_hash = hashlib.sha256(file_bytes).hexdigest()
    doc_id = document_id or f"doc_{file_hash[:12]}"

    blocks: Dict[str, DocumentBlock] = {}
    structural_order: List[str] = []

    with zipfile.ZipFile(file_path, "r") as zf:
        if "word/document.xml" not in zf.namelist():
            raise ValueError(f"Corrupt DOCX package: missing word/document.xml in {filename}")
        doc_xml_bytes = zf.read("word/document.xml")

        # Parse style mapping from word/styles.xml
        style_names_by_id: Dict[str, str] = {}
        if "word/styles.xml" in zf.namelist():
            try:
                styles_xml = zf.read("word/styles.xml")
                s_root = etree.fromstring(styles_xml)
                for s in s_root.findall(f"{{{W_NS}}}style"):
                    s_id = s.get(f"{{{W_NS}}}val") or s.get(f"{{{W_NS}}}styleId")
                    name_elem = s.find(f"{{{W_NS}}}name")
                    if s_id and name_elem is not None:
                        style_names_by_id[s_id] = name_elem.get(f"{{{W_NS}}}val", "")
            except Exception:
                pass

    root = etree.fromstring(doc_xml_bytes)
    body = root.find(f"{{{W_NS}}}body")
    if body is None:
        return DocumentIR(
            document_id=doc_id,
            filename=filename,
            file_hash=file_hash,
            document_type=DocumentType.GENERIC,
            total_blocks=0,
            blocks={},
            structural_order=[],
        )

    block_counter = 1
    current_parent_id: Optional[str] = None

    for elem_idx, child in enumerate(body):
        tag_local = etree.QName(child).localname

        if tag_local == "p":
            # Extract paragraph text
            texts = child.findall(f".//{{{W_NS}}}t")
            text_content = "".join(t.text for t in texts if t.text)

            # Analyze properties
            pPr = child.find(f"{{{W_NS}}}pPr")
            style_id = None
            style_name = None
            heading_lvl = None
            is_heading = False
            num_id = None
            ilvl = None

            if pPr is not None:
                pStyle = pPr.find(f"{{{W_NS}}}pStyle")
                if pStyle is not None:
                    style_id = pStyle.get(f"{{{W_NS}}}val")
                    style_name = style_names_by_id.get(style_id, style_id)
                    if style_name and "heading" in style_name.lower():
                        is_heading = True
                        for ch in style_name:
                            if ch.isdigit():
                                heading_lvl = int(ch)
                                break

                numPr = pPr.find(f"{{{W_NS}}}numPr")
                if numPr is not None:
                    ilvl_elem = numPr.find(f"{{{W_NS}}}ilvl")
                    numId_elem = numPr.find(f"{{{W_NS}}}numId")
                    if ilvl_elem is not None:
                        try:
                            ilvl = int(ilvl_elem.get(f"{{{W_NS}}}val", "0"))
                        except ValueError:
                            ilvl = 0
                    if numId_elem is not None:
                        try:
                            num_id = int(numId_elem.get(f"{{{W_NS}}}val", "0"))
                        except ValueError:
                            num_id = 0

            # Run properties (check for bold/italic)
            runs = child.findall(f".//{{{W_NS}}}r")
            is_bold = False
            is_italic = False
            for r in runs:
                rPr = r.find(f"{{{W_NS}}}rPr")
                if rPr is not None:
                    if rPr.find(f"{{{W_NS}}}b") is not None:
                        is_bold = True
                    if rPr.find(f"{{{W_NS}}}i") is not None:
                        is_italic = True

            # Determine block type — general-purpose classification
            txt_upper = text_content.upper()
            is_list_item = bool(num_id is not None or (style_name and "list" in style_name.lower()))
            block_type = "PARAGRAPH"
            metadata: Dict[str, Any] = {}

            if is_heading:
                block_type = "HEADING"
            elif is_list_item:
                block_type = "LIST_ITEM"
            elif any(w in txt_upper for w in ["WARNING:", "CAUTION:", "NOTE:", "DANGER:", "TIP:"]):
                block_type = "CALLOUT"
            elif style_name and "caption" in style_name.lower():
                block_type = "FIGURE_CAPTION"
                metadata["caption_style"] = style_name
            elif style_name and any(k in style_name.lower() for k in ("footnote", "endnote")):
                block_type = "CITATION"
            elif re.match(r"^\s*\d+(\.\d+)*\s+[A-Z]", text_content) and not is_heading:
                # Numbered clause pattern: "1.2.3 DEFINITIONS" style body text
                if style_name and any(k in style_name.lower() for k in ("clause", "article", "section")):
                    block_type = "CLAUSE"
                    metadata["clause_number"] = text_content.split()[0]

            # Compute fingerprints
            text_fingerprint = hashlib.sha256(text_content.encode("utf-8")).hexdigest()
            xml_signature = hashlib.sha256(etree.tostring(child)).hexdigest()

            block_id = f"block-{block_counter:03d}"
            block_counter += 1

            formatting = FormattingSnapshot(
                style_id=style_id,
                style_name=style_name,
                is_bold=is_bold,
                is_italic=is_italic,
                num_id=num_id,
                ilvl=ilvl,
                is_heading=is_heading,
                heading_level=heading_lvl,
                is_list_item=is_list_item,
                is_table=False,
            )

            location = SourceLocationRef(
                part_name="word/document.xml",
                element_tag="w:p",
                element_index=elem_idx,
                xpath=f"/w:document/w:body/w:p[{elem_idx + 1}]",
                fingerprint_hash=text_fingerprint,
                xml_signature_hash=xml_signature,
            )

            parent_id = current_parent_id if not is_heading else None
            if is_heading:
                current_parent_id = block_id

            block = DocumentBlock(
                block_id=block_id,
                block_type=block_type,
                text_content=text_content,
                parent_block_id=parent_id,
                sequence_index=len(structural_order),
                formatting=formatting,
                location=location,
                span_ids=[],
                metadata=metadata,
            )

            blocks[block_id] = block
            structural_order.append(block_id)

        elif tag_local == "tbl":
            # Extract table matrix
            rows_data: List[List[str]] = []
            for tr in child.findall(f".//{{{W_NS}}}tr"):
                row_cells: List[str] = []
                for tc in tr.findall(f".//{{{W_NS}}}tc"):
                    tc_texts = tc.findall(f".//{{{W_NS}}}t")
                    cell_text = "".join(t.text for t in tc_texts if t.text)
                    row_cells.append(cell_text.strip())
                if row_cells:
                    rows_data.append(row_cells)

            flattened_text = " | ".join([" - ".join(r) for r in rows_data])
            text_fingerprint = hashlib.sha256(flattened_text.encode("utf-8")).hexdigest()
            xml_signature = hashlib.sha256(etree.tostring(child)).hexdigest()

            block_id = f"block-{block_counter:03d}"
            block_counter += 1

            formatting = FormattingSnapshot(
                is_table=True,
            )

            location = SourceLocationRef(
                part_name="word/document.xml",
                element_tag="w:tbl",
                element_index=elem_idx,
                xpath=f"/w:document/w:body/w:tbl[{elem_idx + 1}]",
                fingerprint_hash=text_fingerprint,
                xml_signature_hash=xml_signature,
            )

            block = DocumentBlock(
                block_id=block_id,
                block_type="TABLE",
                text_content=flattened_text,
                parent_block_id=current_parent_id,
                sequence_index=len(structural_order),
                formatting=formatting,
                location=location,
                span_ids=[],
                table_data=rows_data,
            )

            blocks[block_id] = block
            structural_order.append(block_id)

    doc_type = detect_document_type(blocks, structural_order, filename)

    return DocumentIR(
        document_id=doc_id,
        filename=filename,
        file_hash=file_hash,
        document_type=doc_type,
        total_blocks=len(blocks),
        blocks=blocks,
        structural_order=structural_order,
    )
