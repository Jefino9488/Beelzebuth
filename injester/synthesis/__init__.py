"""Document synthesis, span anchoring, and verification module."""
from injester.synthesis.spans import SpanRegistry, SourceSpan
from injester.synthesis.validator import CitationValidator, ValidationReport
from injester.synthesis.assembler import DigestAssembler
from injester.synthesis.generator import DigestGenerator
from injester.synthesis.schemas import (
    DigestClaim,
    DigestOutline,
    DigestOutlineSection,
    DigestSection,
    DigestDocument,
    ClaimCitation,
    CitationRef,
    VerifiedClaim,
    VerifiedClaimIR,
)

DocumentAssembler = DigestAssembler
DocumentGenerator = DigestGenerator

__all__ = [
    "SpanRegistry",
    "SourceSpan",
    "CitationValidator",
    "ValidationReport",
    "DigestAssembler",
    "DocumentAssembler",
    "DigestGenerator",
    "DocumentGenerator",
    "DigestClaim",
    "DigestOutline",
    "DigestOutlineSection",
    "DigestSection",
    "DigestDocument",
    "ClaimCitation",
    "CitationRef",
    "VerifiedClaim",
    "VerifiedClaimIR",
]
