from typing import List, Dict, Optional, Literal, Union, Any
from pydantic import BaseModel, Field, field_validator


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

class VerifiedClaim(BaseModel):
    """
    Independently verified atomic claim grounded against immutable source evidence spans.
    """
    claim_id: str = Field(description="Unique identifier for the claim (e.g. 'CLM_001')")
    claim_text: str = Field(description="Factual, rule-based, or procedural assertion")
    claim_type: ClaimType = Field(default="procedure", description="Semantic category of the assertion")
    evidence_spans: List[str] = Field(description="List of cited immutable span IDs proving this claim")
    entailment_confidence: float = Field(default=1.0, description="Verification confidence score")
    verifier_provider: str = Field(default="exact_match", description="Verification engine: exact_match, deterministic_rules, or neural_nli")
    verifier_model: Optional[str] = Field(default=None, description="Model used for neural NLI verification")
    source_chunk_ids: List[str] = Field(default_factory=list, description="Associated chunk IDs")
    source_proposition_ids: List[str] = Field(default_factory=list, description="Associated atomic proposition IDs if compiled from graph")
    claim_hash: str = Field(default="", description="Cryptographic fingerprint of the claim and its evidence")

    @classmethod
    def compute_hash(cls, claim_text: str, claim_type: str, evidence_spans: List[str]) -> str:
        import hashlib
        raw = f"{claim_type}:{claim_text.strip().lower()}:{','.join(sorted(evidence_spans))}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

class VerifiedClaimIR(BaseModel):
    """
    Authoritative Intermediate Representation of verified claims prior to prose assembly.
    Ensures that SOP generation is claim-first: evidence establishes -> claims verified -> prose assembled.
    """
    title: str = Field(default="Standard Operating Procedure")
    purpose: str = Field(default="")
    target_audience: str = Field(default="")
    claims: List[VerifiedClaim] = Field(default_factory=list)
    sections: List['SOPOutlineSection'] = Field(default_factory=list)

class SOPOutlineSection(BaseModel):
    """An outline section proposed for the SOP."""
    section_title: str = Field(description="Title of the section, e.g. '1. Intake & Eligibility'")
    section_goal: str = Field(description="Purpose of this section in the SOP")
    search_queries: List[str] = Field(default_factory=list, description="Specific queries to retrieve evidence chunks for this section")
    is_conditional: bool = Field(default=False, description="True if this section was conditionally added based on source evidence")

    @field_validator("search_queries", mode="before")
    @classmethod
    def validate_search_queries(cls, v: Any) -> List[str]:
        if isinstance(v, str):
            return [v]
        if isinstance(v, dict):
            return [v.get("query", str(v))]
        if isinstance(v, list):
            res = []
            for item in v:
                if isinstance(item, dict):
                    res.append(item.get("query", str(item)))
                elif isinstance(item, str):
                    res.append(item)
                else:
                    res.append(str(item))
            return res
        return []

class SOPOutline(BaseModel):
    """The synthesized outline for the unified SOP."""
    title: str = Field(default="Standard Operating Procedure", description="Title of the SOP")
    purpose: str = Field(default="", description="Objective and scope of the standard operating procedure")
    target_audience: str = Field(default="", description="Intended audience (e.g. IT Administrators, Underwriters)")
    sections: List[SOPOutlineSection] = Field(default_factory=list, description="Ordered list of sections")


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

class CandidateClaimsResponse(BaseModel):
    """Container for candidate claims extracted prior to independent verification."""
    claims: List[SOPClaim] = Field(default_factory=list, description="Extracted candidate claims citing exact span IDs")
