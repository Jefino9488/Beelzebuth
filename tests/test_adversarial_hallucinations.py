import pytest
from injester.sop.validator import CitationValidator
from injester.sop.spans import SourceSpan, SpanRegistry
from injester.ingestion.schema import DocumentChunk, ProvenanceMetadata
from injester.sop.schemas import SOPDocument, SOPSection, SOPClaim, ClaimCitation

@pytest.fixture
def loan_span_and_chunk():
    """
    Creates an immutable reference span and chunk matching Test Case 2 / Medium.
    Does not modify production registry or source documents.
    """
    raw_text = (
        "If the loan amount requested exceeds $20,000, the application is routed to the Branch Manager "
        "for final approval, irrespective of the Risk Grade assigned by the Credit Analyst."
    )
    chunk = DocumentChunk(
        chunk_id="chunk_loan_adv_01",
        document_id="doc_loan_adv",
        filename="PersonalLoan_Policy.docx",
        tenant_id="tenant_adv",
        text=raw_text,
        section_hierarchy=["Approval Routing"],
        page_numbers=[2],
        provenance=ProvenanceMetadata(
            document_id="doc_loan_adv",
            filename="PersonalLoan_Policy.docx",
            tenant_id="tenant_adv",
            page_number=2,
            section_path=["Approval Routing"],
            element_type="CompositeChunk",
            source_location="Page 2, Section: Approval Routing",
        )
    )
    registry = SpanRegistry.from_chunks([chunk])
    return chunk, registry


def test_adversarial_mutation_1_number_tampering(loan_span_and_chunk):
    """
    Mutation 1: Number tampering
    Baseline: Loans exceeding $20,000 require Branch Manager approval.
    Mutation: Loans exceeding $25,000 require Branch Manager approval.
    Target: MUST be rejected by the validator.
    """
    chunk, registry = loan_span_and_chunk
    validator = CitationValidator()

    section = SOPSection(
        section_title="5. Decision Points",
        content="Loans exceeding $25,000 require Branch Manager approval. [S001]",
        claims=[
            SOPClaim(
                claim_text="Loans exceeding $25,000 require Branch Manager approval.",
                claim_type="rule",
                span_id="S001",
            )
        ]
    )
    doc = SOPDocument(
        title="Personal Loan SOP",
        purpose="Lending",
        target_audience="Officers",
        sections=[section]
    )

    report = validator.validate_document(doc, [chunk])
    assert report.is_valid is False
    assert report.unsupported_claims_count > 0
    assert any("25,000" in u for u in report.unsupported_claims)


def test_adversarial_mutation_2_role_substitution(loan_span_and_chunk):
    """
    Mutation 2: Role substitution
    Baseline: Loans exceeding $20,000 require Branch Manager approval.
    Mutation: Loans exceeding $20,000 require Senior Credit Analyst approval.
    Target: MUST be rejected by the validator.
    """
    chunk, registry = loan_span_and_chunk
    validator = CitationValidator()

    section = SOPSection(
        section_title="5. Decision Points",
        content="Loans exceeding $20,000 require Senior Credit Analyst approval. [S001]",
        claims=[
            SOPClaim(
                claim_text="Loans exceeding $20,000 require Senior Credit Analyst approval.",
                claim_type="rule",
                span_id="S001",
            )
        ]
    )
    doc = SOPDocument(
        title="Personal Loan SOP",
        purpose="Lending",
        target_audience="Officers",
        sections=[section]
    )

    report = validator.validate_document(doc, [chunk])
    assert report.is_valid is False
    assert report.unsupported_claims_count > 0
    assert any("Senior Credit Analyst" in u for u in report.unsupported_claims)


def test_adversarial_mutation_3_unsupported_timeframe_injection(loan_span_and_chunk):
    """
    Mutation 3: Unsupported timeframe injection
    Baseline: Loans exceeding $20,000 require Branch Manager approval.
    Mutation: Loans exceeding $20,000 require Branch Manager approval, who has 2 business days to decide.
    Target: MUST be rejected by the validator.
    """
    chunk, registry = loan_span_and_chunk
    validator = CitationValidator()

    section = SOPSection(
        section_title="5. Decision Points",
        content="Loans exceeding $20,000 require Branch Manager approval, who has 2 business days to decide. [S001]",
        claims=[
            SOPClaim(
                claim_text="Loans exceeding $20,000 require Branch Manager approval, who has 2 business days to decide.",
                claim_type="sla",
                span_id="S001",
            )
        ]
    )
    doc = SOPDocument(
        title="Personal Loan SOP",
        purpose="Lending",
        target_audience="Officers",
        sections=[section]
    )

    report = validator.validate_document(doc, [chunk])
    assert report.is_valid is False
    assert report.unsupported_claims_count > 0
    assert any("2 business days" in u for u in report.unsupported_claims)


def test_adversarial_mutation_4_condition_injection():
    """
    Mutation 4: Condition / prerequisite injection
    Baseline: Branch Manager provides final approval for loans above $20,000.
    Mutation: Branch Manager approves loans over $20,000 after checking the customer's CIBIL score.
    Target: MUST be rejected by the validator.
    """
    raw_text = "Branch Manager provides final approval for loans above $20,000."
    chunk = DocumentChunk(
        chunk_id="chunk_loan_adv_04",
        document_id="doc_loan_adv",
        filename="PersonalLoan_Policy.docx",
        tenant_id="tenant_adv",
        text=raw_text,
        section_hierarchy=["Approval Routing"],
        page_numbers=[2],
        provenance=ProvenanceMetadata(
            document_id="doc_loan_adv",
            filename="PersonalLoan_Policy.docx",
            tenant_id="tenant_adv",
            page_number=2,
            section_path=["Approval Routing"],
            element_type="CompositeChunk",
            source_location="Page 2",
        )
    )
    validator = CitationValidator()

    section = SOPSection(
        section_title="5. Decision Points",
        content="Branch Manager approves loans over $20,000 after checking the customer CIBIL score. [S001]",
        claims=[
            SOPClaim(
                claim_text="Branch Manager approves loans over $20,000 after checking the customer CIBIL score.",
                claim_type="rule",
                span_id="S001",
            )
        ]
    )
    doc = SOPDocument(
        title="Personal Loan SOP",
        purpose="Lending",
        target_audience="Officers",
        sections=[section]
    )

    report = validator.validate_document(doc, [chunk])
    assert report.is_valid is False
    assert report.unsupported_claims_count > 0
    assert any("CIBIL" in u for u in report.unsupported_claims)


def test_adversarial_mutation_5_workflow_sequencing_hallucination():
    """
    Mutation 5: Workflow sequencing hallucination
    Baseline: Reporting Manager reviews and approves or rejects the leave request.
    Mutation: Reporting Manager approves leave after HR verification.
    Target: MUST be rejected by the validator.
    """
    raw_text = "Reporting Manager reviews and approves or rejects the leave request."
    chunk = DocumentChunk(
        chunk_id="chunk_leave_adv_05",
        document_id="doc_leave_adv",
        filename="Leave_Policy.docx",
        tenant_id="tenant_adv",
        text=raw_text,
        section_hierarchy=["Leave Approval"],
        page_numbers=[1],
        provenance=ProvenanceMetadata(
            document_id="doc_leave_adv",
            filename="Leave_Policy.docx",
            tenant_id="tenant_adv",
            page_number=1,
            section_path=["Leave Approval"],
            element_type="CompositeChunk",
            source_location="Page 1",
        )
    )
    validator = CitationValidator()

    section = SOPSection(
        section_title="3. Roles & Responsibilities",
        content="Reporting Manager approves leave after HR verification. [S001]",
        claims=[
            SOPClaim(
                claim_text="Reporting Manager approves leave after HR verification.",
                claim_type="rule",
                span_id="S001",
            )
        ]
    )
    doc = SOPDocument(
        title="Leave Approval SOP",
        purpose="Leave",
        target_audience="Employees",
        sections=[section]
    )

    report = validator.validate_document(doc, [chunk])
    assert report.is_valid is False
    assert report.unsupported_claims_count > 0
    assert any("HR verification" in u for u in report.unsupported_claims)


def test_legitimate_claims_remain_entailed():
    """
    Verify that legitimate paraphrases, grammatical variants, and true assertions
    continue to pass without false positive rejections.
    """
    raw_text = "If the loan amount requested exceeds $20,000, the application is routed to the Branch Manager for final approval."
    chunk = DocumentChunk(
        chunk_id="chunk_legit_01",
        document_id="doc_legit",
        filename="PersonalLoan_Policy.docx",
        tenant_id="tenant_legit",
        text=raw_text,
        section_hierarchy=["Approval Routing"],
        page_numbers=[2],
        provenance=ProvenanceMetadata(
            document_id="doc_legit",
            filename="PersonalLoan_Policy.docx",
            tenant_id="tenant_legit",
            page_number=2,
            section_path=["Approval Routing"],
            element_type="CompositeChunk",
            source_location="Page 2",
        )
    )
    validator = CitationValidator()

    # Valid grammatical variation and rephrasing of the exact rule
    section = SOPSection(
        section_title="5. Decision Points",
        content="Loans exceeding $20,000 require Branch Manager approval. [S001]",
        claims=[
            SOPClaim(
                claim_text="Loans exceeding $20,000 require Branch Manager approval.",
                claim_type="rule",
                span_id="S001",
            )
        ]
    )
    doc = SOPDocument(
        title="Personal Loan SOP",
        purpose="Lending",
        target_audience="Officers",
        sections=[section]
    )

    report = validator.validate_document(doc, [chunk])
    assert report.is_valid is True
    assert report.unsupported_claims_count == 0
    assert report.claim_entailment_score == 1.0
