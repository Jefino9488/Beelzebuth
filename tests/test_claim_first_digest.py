import pytest
from injester.ingestion.schema import DocumentChunk, ProvenanceMetadata
from injester.sop.schemas import (
    SOPClaim,
    VerifiedClaim,
    VerifiedClaimIR,
    SOPOutlineSection,
    SOPDocument,
)
from injester.sop.spans import SpanRegistry
from injester.sop.generator import SOPGenerator
from injester.sop.validator import CitationValidator
from injester.sop.assembler import SOPAssembler


@pytest.fixture
def sample_chunks():
    meta = ProvenanceMetadata(
        document_id="doc_claim_first_01",
        filename="Commercial_Lending_Policy.pdf",
        tenant_id="tenant_bank",
        page_number=3,
        section_path=["Credit Risk", "Delegated Authorities"],
        source_location="Page 3, Section: Delegated Authorities",
        file_version_id="ver_comm_01",
    )
    chunk1 = DocumentChunk(
        chunk_id="chk_comm_01",
        document_id="doc_claim_first_01",
        filename="Commercial_Lending_Policy.pdf",
        tenant_id="tenant_bank",
        text=(
            "Commercial loan requests up to $100,000 may be approved by a Senior Credit Analyst. "
            "Any loan request exceeding $100,000 requires Credit Committee sign-off."
        ),
        section_hierarchy=["Credit Risk", "Delegated Authorities"],
        page_numbers=[3],
        file_version_id="ver_comm_01",
        provenance=meta,
    )
    chunk2 = DocumentChunk(
        chunk_id="chk_comm_02",
        document_id="doc_claim_first_01",
        filename="Commercial_Lending_Policy.pdf",
        tenant_id="tenant_bank",
        text=(
            "If the applicant has an active default on record, the application must be rejected immediately. "
            "The Credit Committee must issue approval decisions within 5 business days."
        ),
        section_hierarchy=["Credit Risk", "Delegated Authorities"],
        page_numbers=[4],
        file_version_id="ver_comm_01",
        provenance=meta,
    )
    return [chunk1, chunk2]


def test_verified_claim_ir_hash_and_model():
    """Verify cryptographic claim hash stability and VerifiedClaim data model invariants."""
    claim_text = "Commercial loan requests up to $100,000 may be approved by a Senior Credit Analyst."
    h1 = VerifiedClaim.compute_hash(claim_text, "rule", ["S001"])
    h2 = VerifiedClaim.compute_hash(claim_text, "rule", ["S001"])
    assert h1 == h2
    assert len(h1) == 64

    # Different span changes hash
    h3 = VerifiedClaim.compute_hash(claim_text, "rule", ["S002"])
    assert h1 != h3

    v_claim = VerifiedClaim(
        claim_id="CLM_001",
        claim_text=claim_text,
        claim_type="rule",
        evidence_spans=["S001"],
        entailment_confidence=1.0,
        source_chunk_ids=["chk_comm_01"],
        claim_hash=h1,
    )
    assert v_claim.claim_id == "CLM_001"
    assert v_claim.evidence_spans == ["S001"]

    ir = VerifiedClaimIR(
        title="Commercial Lending SOP",
        purpose="Credit decisioning",
        target_audience="Analysts",
        claims=[v_claim],
        sections=[SOPOutlineSection(section_title="Authorities", section_goal="Approval limits")]
    )
    assert len(ir.claims) == 1
    assert ir.claims[0].claim_hash == h1


def test_claim_first_filtering_rejects_unentailed_candidates(sample_chunks):
    """
    Verify that candidate claims that mutate thresholds or inject fake conditions
    are rejected during the verification phase and never enter VerifiedClaimIR.
    """
    registry = SpanRegistry.from_chunks(sample_chunks)
    generator = SOPGenerator()
    validator = CitationValidator()

    # S001 text: "Commercial loan requests up to $100,000 may be approved by a Senior Credit Analyst."
    # Candidate A: Valid assertion
    # Candidate B: Fabricated threshold $250,000
    # Candidate C: Fabricated condition "after receiving collateral appraisal"
    candidates = [
        SOPClaim(
            claim_text="Commercial loan requests up to $100,000 may be approved by a Senior Credit Analyst.",
            claim_type="rule",
            span_id="S001",
        ),
        SOPClaim(
            claim_text="Commercial loan requests up to $250,000 may be approved by a Senior Credit Analyst.",
            claim_type="rule",
            span_id="S001",
        ),
        SOPClaim(
            claim_text="Senior Credit Analyst approves loans up to $100,000 after receiving collateral appraisal.",
            claim_type="rule",
            span_id="S001",
        ),
    ]

    verified = generator.verify_claims(candidates, registry, validator)

    # Only Candidate A must pass
    assert len(verified) == 1
    assert verified[0].claim_text == "Commercial loan requests up to $100,000 may be approved by a Senior Credit Analyst."
    assert verified[0].evidence_spans == ["S001"]
    assert verified[0].entailment_confidence == 1.0


def test_deterministic_sop_assembly_from_verified_claims(sample_chunks):
    """
    Verify that verified claims assemble deterministically into markdown sections
    with proper [S###] citation tags and structured claims.
    """
    registry = SpanRegistry.from_chunks(sample_chunks)
    generator = SOPGenerator()

    verified_claims = [
        VerifiedClaim(
            claim_id="CLM_001",
            claim_text="Commercial loan requests up to $100,000 may be approved by a Senior Credit Analyst",
            claim_type="rule",
            evidence_spans=["S001"],
            entailment_confidence=1.0,
            source_chunk_ids=["chk_comm_01"],
            claim_hash=VerifiedClaim.compute_hash("Commercial loan requests up to $100,000 may be approved by a Senior Credit Analyst", "rule", ["S001"]),
        ),
        VerifiedClaim(
            claim_id="CLM_002",
            claim_text="Any loan request exceeding $100,000 requires Credit Committee sign-off",
            claim_type="rule",
            evidence_spans=["S002"],
            entailment_confidence=1.0,
            source_chunk_ids=["chk_comm_01"],
            claim_hash=VerifiedClaim.compute_hash("Any loan request exceeding $100,000 requires Credit Committee sign-off", "rule", ["S002"]),
        ),
    ]

    section = generator.assemble_section_from_verified_claims(
        section_title="1. Delegated Authorities",
        section_goal="Approval limits",
        verified_claims=verified_claims,
        span_registry=registry,
    )

    assert section.section_title == "1. Delegated Authorities"
    assert "[S001]" in section.content
    assert "[S002]" in section.content
    assert len(section.claims) == 2
    assert section.claims[0].span_id == "S001"
    assert section.claims[1].span_id == "S002"
    assert len(section.citations) == 2


def test_build_sop_from_chunks_claim_first_pipeline(sample_chunks):
    """
    End-to-end verification of Claim-First pipeline:
    Source Chunks -> VerifiedClaimIR -> SOPDocument -> ValidationReport (Pass with 0 errors).
    """
    generator = SOPGenerator()
    registry = SpanRegistry.from_chunks(sample_chunks)

    sop_doc, report, markdown_sop = generator.build_sop_from_chunks(
        topic_goal="Commercial Lending Approvals",
        chunks=sample_chunks,
        span_registry=registry,
    )

    assert isinstance(sop_doc, SOPDocument)
    assert len(sop_doc.sections) > 0
    assert report.is_valid is True
    assert report.unsupported_claims_count == 0
    assert report.claim_entailment_score == 1.0
    assert "# " in markdown_sop
    assert "## Citation Index" in markdown_sop
