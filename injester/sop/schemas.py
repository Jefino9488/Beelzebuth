from typing import List, Dict, Optional, Literal, Union
from pydantic import BaseModel, Field

ClaimType = Literal[
    "rule",          # approval threshold, authorization level, prerequisite
    "threshold",     # numerical criteria, limit, cut-off
    "exception",     # error condition, deviation, escalation, rejection
    "sla",           # turnaround time, timeframe, schedule
    "role",          # responsibility, handoff, actor
    "procedure",     # core operational step or action
    "descriptive",   # scope, purpose, policy context
    "instruction"    # scaffolding / navigational directive
]

class ClaimCitation(BaseModel):
    """
    Structured citation linking a claim to an exact registered source span and chunk.
    """
    citation_tag: str = Field(description="Deterministic span tag used in section text, e.g. 'S001', 'S002'")
    chunk_id: str = Field(description="The exact chunk_id containing the evidence")
    span_id: str = Field(description="The exact deterministic span_id from the evidence chunk, e.g. 'S001'")

class CitationRef(BaseModel):
    """
    Resolved citation reference linking a citation tag to verified chunk and span details.
    Used in the final document and citation index.
    """
    citation_tag: str
    chunk_id: str
    span_id: str = Field(default="")
    source_doc: str = Field(default="")
    location: str = Field(default="")
    section: str = Field(default="")
    evidence_quote: str = Field(default="")
    entailment_status: str = Field(default="pending")

class SOPClaim(BaseModel):
    """
    Granular claim with typed semantic category and immutable span ID binding.
    """
    claim_text: str = Field(description="Factual, rule-based, or procedural assertion")
    claim_type: ClaimType = Field(default="procedure", description="Semantic category of the assertion")
    span_id: str = Field(default="", description="Exact immutable span ID from evidence (e.g. 'S014') that proves this claim")
    citation: Optional[Union[ClaimCitation, CitationRef]] = Field(default=None, description="Optional citation metadata")

class SOPOutlineSection(BaseModel):
    """An outline section proposed for the SOP."""
    section_title: str = Field(description="Title of the section, e.g. '1. Intake & Eligibility'")
    section_goal: str = Field(description="Purpose of this section in the SOP")
    search_queries: List[str] = Field(description="Specific queries to retrieve evidence chunks for this section")
    is_conditional: bool = Field(default=False, description="True if this section was conditionally added based on source evidence")

class SOPOutline(BaseModel):
    """The synthesized outline for the unified SOP."""
    title: str = Field(description="Title of the SOP")
    purpose: str = Field(description="Objective and scope of the standard operating procedure")
    target_audience: str = Field(description="Intended audience (e.g. IT Administrators, Underwriters)")
    sections: List[SOPOutlineSection] = Field(description="Ordered list of sections")

class SOPSection(BaseModel):
    """A generated SOP section with embedded citation tags [S###], claims, and citations."""
    section_title: str = Field(description="Title of the section")
    content: str = Field(description="Detailed procedure text with embedded span citation tags like [S001], [S002]")
    claims: List[SOPClaim] = Field(default_factory=list, description="List of granular assertions with their citations and types")
    citations: List[Union[ClaimCitation, CitationRef]] = Field(default_factory=list, description="Structured citations linking tags to chunk and span IDs")

class SOPDocument(BaseModel):
    """The complete auditable SOP document."""
    title: str
    purpose: str
    target_audience: str
    sections: List[SOPSection]
    citation_index: Dict[str, CitationRef] = Field(default_factory=dict)
