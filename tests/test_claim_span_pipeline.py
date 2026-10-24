import pytest
from injester.ingestion.schema import DocumentChunk, ProvenanceMetadata
from injester.sop.spans import SpanRegistry, SourceSpan
from injester.sop.schemas import SOPDocument, SOPSection, ClaimCitation, SOPClaim
from injester.sop.validator import CitationValidator

@pytest.fixture
def sample_chunk():
    meta = ProvenanceMetadata(
        document_id="doc_loan_01",
        filename="Loan_Policy.docx",
        tenant_id="tenant_fin",
        page_number=1,
        section_path=["Underwriting"],
        source_location="Page 1, Section: Underwriting",
        file_version_id="ver_loan_01",
    )
    text = (
        "Loan intake conducts initial document verification within 24 hours.\n"
        "Applications with credit scores under 600 must be rejected immediately.\n"
        "Loans exceeding $20,000 require Branch Manager approval regardless of risk grade."
    )
    return DocumentChunk(
        chunk_id="chunk_loan_001",
        document_id="doc_loan_01",
        filename="Loan_Policy.docx",
        tenant_id="tenant_fin",
        text=text,
        section_hierarchy=["Underwriting"],
        page_numbers=[1],
        file_version_id="ver_loan_01",
        provenance=meta,
    )

def test_span_registry_deterministic_segmentation(sample_chunk):
    registry = SpanRegistry.from_chunks([sample_chunk])
    spans = registry.get_chunk_spans("chunk_loan_001")
    
    # Must segment into 3 distinct atomic spans
    assert len(spans) == 3
    assert spans[0].span_id == "S001"
    assert "24 hours" in spans[0].text
    assert spans[1].span_id == "S002"
    assert "under 600" in spans[1].text
    assert spans[2].span_id == "S003"
    assert "$20,000" in spans[2].text
    assert spans[2].chunk_id == "chunk_loan_001"

def test_validator_claim_to_span_entailment(sample_chunk):
    validator = CitationValidator()
    
    # Section with correctly entailed claims
    section = SOPSection(
        section_title="1. Underwriting Authority",
        content="Loans over $20,000 require Branch Manager authorization. [C1]",
        citations=[
            ClaimCitation(
                citation_tag="C1",
                chunk_id="chunk_loan_001",
                span_id="S003",
            )
        ],
        claims=[
            SOPClaim(
                claim_text="Loans exceeding $20,000 require Branch Manager approval.",
                claim_type="rule",
                citation=ClaimCitation(
                    citation_tag="C1",
                    chunk_id="chunk_loan_001",
                    span_id="S003",
                )
            )
        ]
    )

    doc = SOPDocument(
        title="Loan Processing SOP",
        purpose="Underwriting",
        target_audience="Officers",
        sections=[section],
    )

    report = validator.validate_document(doc, [sample_chunk])
    assert report.is_valid is True
    assert len(report.errors) == 0
    assert report.unsupported_claims_count == 0
    assert report.claim_entailment_score == 1.0

def test_validator_catches_unentailed_claim_amount(sample_chunk):
    validator = CitationValidator()
    
    # Claim fabricates a different threshold ($50,000 instead of $20,000 in span S003)
    section = SOPSection(
        section_title="1. Underwriting Authority",
        content="Loans over $50,000 require Branch Manager authorization. [C1]",
        citations=[
            ClaimCitation(
                citation_tag="C1",
                chunk_id="chunk_loan_001",
                span_id="S003",
            )
        ],
        claims=[
            SOPClaim(
                claim_text="Loans exceeding $50,000 require Branch Manager approval.",
                claim_type="threshold",
                citation=ClaimCitation(
                    citation_tag="C1",
                    chunk_id="chunk_loan_001",
                    span_id="S003",
                )
            )
        ]
    )

    doc = SOPDocument(
        title="Loan Processing SOP",
        purpose="Underwriting",
        target_audience="Officers",
        sections=[section],
    )

    report = validator.validate_document(doc, [sample_chunk])
    assert report.is_valid is False
    assert report.unsupported_claims_count > 0
    assert any("50,000" in uc for uc in report.unsupported_claims)

def test_validator_catches_invalid_span_id(sample_chunk):
    validator = CitationValidator()
    
    # Citation references a span ID that doesn't exist
    section = SOPSection(
        section_title="1. Underwriting Authority",
        content="Review within 24 hours. [C1]",
        citations=[
            ClaimCitation(
                citation_tag="C1",
                chunk_id="chunk_loan_001",
                span_id="S999",  # Non-existent
            )
        ],
        claims=[]
    )

    doc = SOPDocument(
        title="Loan Processing SOP",
        purpose="Underwriting",
        target_audience="Officers",
        sections=[section],
    )

    report = validator.validate_document(doc, [sample_chunk])
    assert report.is_valid is False
    assert any("references non-existent span ID 'S999'" in err for err in report.errors)


def test_headingless_document_span_segmentation():
    """Verify that documents with zero headings or section hierarchy produce valid spans."""
    raw_text = (
        "Employees must submit expense reports within 15 calendar days. "
        "Any expense over $500 requires department head signature. "
        "Receipts must be provided for all lodging and airfare."
    )
    chunk = DocumentChunk(
        chunk_id="chunk_headingless_001",
        document_id="doc_headingless",
        filename="travel_rules.txt",
        tenant_id="tenant_general",
        text=raw_text,
        section_hierarchy=[],
        page_numbers=[1],
        provenance=ProvenanceMetadata(
            document_id="doc_headingless",
            filename="travel_rules.txt",
            tenant_id="tenant_general",
            page_number=1,
            section_path=[],
            element_type="NarrativeText",
            source_location="travel_rules.txt",
            file_version_id="ver_travel_01",
        ),
        file_version_id="ver_travel_01",
    )

    registry = SpanRegistry.from_chunks([chunk])
    spans = registry.get_chunk_spans("chunk_headingless_001")

    assert len(spans) == 3
    assert spans[0].span_id == "S001"
    assert "15 calendar days" in spans[0].text
    assert spans[0].section == ""
    assert spans[1].span_id == "S002"
    assert "$500" in spans[1].text
    assert spans[2].span_id == "S003"
    assert "lodging and airfare" in spans[2].text

