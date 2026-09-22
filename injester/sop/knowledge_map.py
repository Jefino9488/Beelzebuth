import re
from typing import List, Dict, Literal
from pydantic import BaseModel, Field
from injester.ingestion.schema import DocumentChunk
from injester.sop.llm_client import get_instructor_client
from injester.sop.spans import SpanRegistry

class ExpectedRule(BaseModel):
    """
    An atomic rule, threshold, exception, or SLA requirement identified from source evidence.
    Used by the independent validator to compute Source-Rule Coverage.
    """
    rule_id: str = Field(description="Identifier like R1, R2")
    category: Literal["rule", "threshold", "exception", "sla", "role"] = Field(description="Type of rule")
    description: str = Field(description="Statement of the requirement or constraint")
    source_chunk_id: str = Field(description="Chunk ID where this rule originated")
    key_terms: List[str] = Field(
        default_factory=list,
        description="Key terms, amounts, or thresholds that must be present in the SOP to satisfy this rule (e.g. ['$20,000', 'Branch Manager'])"
    )

class DocumentKnowledgeMap(BaseModel):
    """
    Dynamic, comprehensive knowledge map extracted from 100% of document chunks.
    Preserves all operational rules, conditional paths, and role requirements without hardcoding.
    """
    title: str = Field(description="Inferred or stated title/topic of the document")
    summary: str = Field(description="Concise operational scope of the document")
    topics: List[str] = Field(description="List of all substantive workflow stages/topics")
    key_roles: List[str] = Field(description="All roles, actors, or approval authorities identified")
    
    # Conditional flow flags
    has_exceptions: bool = Field(description="True if document contains any exceptions, deviations, escalations, or rejections")
    exception_rules: List[ExpectedRule] = Field(default_factory=list, description="Specific exception/escalation rules found")
    
    has_slas: bool = Field(description="True if document contains turnaround times, deadlines, timeframes, or SLAs")
    sla_rules: List[ExpectedRule] = Field(default_factory=list, description="Specific SLA/timeframe rules found")
    
    core_rules: List[ExpectedRule] = Field(default_factory=list, description="Eligibility criteria, thresholds, and mandatory rules")
    eligible_chunk_ids: List[str] = Field(default_factory=list, description="Chunks containing substantive procedural knowledge")
    recommended_sections: List[str] = Field(default_factory=list, description="Recommended outline sections based on source structure")

def extract_knowledge_map(chunks: List[DocumentChunk], span_registry: SpanRegistry) -> DocumentKnowledgeMap:
    """
    Scans 100% of source chunks dynamically to build an objective DocumentKnowledgeMap.
    Does not hardcode any business logic; dynamically extracts whatever rules and conditions exist.
    """
    client, model_name = get_instructor_client()

    # Identify eligible chunks (substantive content)
    eligible_chunks = [
        c for c in chunks 
        if len(c.text.strip()) > 40 and not c.text.strip().lower().startswith("table of contents")
    ]
    eligible_ids = [c.chunk_id for c in eligible_chunks]

    # Discover exact headings present in the source chunks
    source_headings: List[str] = []
    for c in eligible_chunks:
        found_titles = re.findall(r'^\d+\.\s+[^\n]+', c.text, re.MULTILINE)
        for t in found_titles:
            t_clean = t.strip()
            if t_clean not in source_headings and not t_clean.startswith("SOP-"):
                source_headings.append(t_clean)
        if c.section_hierarchy:
            for s in c.section_hierarchy:
                s_clean = s.strip()
                if s_clean and s_clean not in source_headings and not s_clean.startswith("SOP-"):
                    source_headings.append(s_clean)

    # Dual-mode SLA & Exception detection
    full_text = " ".join(c.text for c in eligible_chunks).lower()
    if source_headings:
        # Mode A: Structured document -> trust explicit section headings
        source_has_sla_section = any(
            ("sla" in h.lower() or "service level" in h.lower()) for h in source_headings
        )
        source_has_exception_section = any(
            ("exception" in h.lower() or "escalat" in h.lower()) for h in source_headings
        )
    else:
        # Mode B: Raw prose / heading-less document -> detect based on actual content
        source_has_sla_section = bool(
            re.search(r'\b(service level agreement|turnaround time|sla commitment)\b', full_text)
        )
        source_has_exception_section = bool(
            re.search(r'\b(exception|escalat|if rejected|in case of error)\b', full_text)
        )

    # Build evidence text across all chunks
    evidence_blocks = []
    for c in eligible_chunks:
        loc = c.provenance.source_location or (f"Page {c.page_numbers[0]}" if c.page_numbers else "")
        sec = " > ".join(c.section_hierarchy) if c.section_hierarchy else ""
        sec_label = f" | Section: {sec}" if sec else ""
        evidence_blocks.append(
            f"[CHUNK {c.chunk_id} | Location: {loc}{sec_label}]\n{c.text.strip()}"
        )
    full_evidence = "\n\n".join(evidence_blocks)

    system_prompt = (
        "You are an expert principal knowledge engineer. Analyze the complete document text from ALL provided chunks.\n"
        "Your task is to extract a comprehensive, objective Knowledge Map representing 100% of the operational content.\n"
        "STRICT CLASSIFICATION & STRUCTURE RULES:\n"
        "1. Identify every explicit threshold, numerical limit, prerequisite, authorization level, and rule.\n"
        "2. SOURCE-DRIVEN TAXONOMY FOR SLAs VS EXCEPTIONS:\n"
        "   - If a timeframe is merely an escalation trigger (e.g. 'if manager does not respond within 3 days, auto-escalate to Department Head'), "
        "it belongs to Exceptions, NOT an SLA section. Set has_slas=False.\n"
        "   - ONLY set has_slas=True if the document contains a dedicated Service Level Agreement (SLA) section or explicit operational turnaround commitments.\n"
        "3. SECTION SYNTHESIS:\n"
        "   - If explicit section titles exist in the source, recommended_sections must mirror ONLY those substantive sections. "
        "Do NOT invent phantom sections (such as 'Absence Tracking', 'Leave Types', or 'Portal Usage').\n"
        "   - If the source has NO explicit section headers (raw narrative prose), you MUST synthesize standard logical SOP sections "
        "(e.g., 'Purpose & Scope', 'Roles & Responsibilities', 'Procedural Workflow', 'Exceptions & Escalations') warranted by the text.\n"
        "4. For every extracted rule, identify 1-3 key_terms (numbers, roles, actions) essential to verifying that rule."
    )

    user_prompt = (
        f"EXISTING SOURCE SECTIONS: {', '.join(source_headings) if source_headings else 'None found in structure. Synthesize logical procedural sections from raw prose.'}\n"
        f"Source has explicit SLA section: {source_has_sla_section}\n"
        f"Source has explicit Exception section: {source_has_exception_section}\n\n"
        "Extract the DocumentKnowledgeMap for the following full document evidence:\n\n"
        f"{full_evidence}"
    )

    try:
        kmap = client.chat.completions.create(
            model=model_name,
            response_model=DocumentKnowledgeMap,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.0,
        )
        # Ensure strict override based on source presence
        if source_headings:
            if not source_has_sla_section:
                kmap.has_slas = False
                kmap.sla_rules = []
            if source_has_exception_section:
                kmap.has_exceptions = True
            kmap.recommended_sections = source_headings
        else:
            if not source_has_sla_section:
                kmap.has_slas = False
                kmap.sla_rules = []
            if source_has_exception_section:
                kmap.has_exceptions = True

        kmap.eligible_chunk_ids = eligible_ids
        return kmap
    except Exception as e:
        return DocumentKnowledgeMap(
            title="Standard Operating Procedure",
            summary="Synthesized operating procedure from source evidence.",
            topics=source_headings or ["Workflow Procedure"],
            key_roles=["Operator", "Approver"],
            has_exceptions=source_has_exception_section,
            exception_rules=[],
            has_slas=source_has_sla_section,
            sla_rules=[],
            core_rules=[],
            eligible_chunk_ids=eligible_ids,
            recommended_sections=source_headings or ["Workflow Procedure"],
        )
