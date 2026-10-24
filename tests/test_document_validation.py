import pytest
from injester.ingestion.schema import DocumentChunk, ProvenanceMetadata
from injester.sop.schemas import SOPDocument, SOPSection, CitationRef
from injester.sop.validator import CitationValidator
from injester.sop.assembler import SOPAssembler

@pytest.fixture
def sample_evidence():
    meta = ProvenanceMetadata(
        document_id="doc_policy_14",
        filename="IT_Access_Policy.pdf",
        tenant_id="tenant_bank",
        page_number=14,
        section_path=["Access Provisioning"],
        source_location="Page 14, Section: Access Provisioning",
        file_version_id="ver_policy_01",
    )
    chunk = DocumentChunk(
        chunk_id="chunk_8f31",
        document_id="doc_policy_14",
        filename="IT_Access_Policy.pdf",
        tenant_id="tenant_bank",
        text="Employees must obtain manager approval before system access is provisioned.",
        section_hierarchy=["Access Provisioning"],
        page_numbers=[14],
        file_version_id="ver_policy_01",
        provenance=meta,
    )
    return [chunk]

def test_valid_citation_verification(sample_evidence):
    validator = CitationValidator()
    assembler = SOPAssembler()

    section = SOPSection(
        section_title="1. System Access Approval",
        content="Employees must obtain manager approval before system access is provisioned. [C12]",
        citations=[
            CitationRef(
                citation_tag="C12",
                chunk_id="chunk_8f31",
                source_doc="IT_Access_Policy.pdf",
                location="Page 14",
                section="Access Provisioning",
                evidence_quote="Employees must obtain manager approval before system access is provisioned.",
            )
        ]
    )

    doc = SOPDocument(
        title="IT Access Standard Operating Procedure",
        purpose="Standardize employee credential provisioning.",
        target_audience="System Administrators",
        sections=[section],
    )

    report = validator.validate_document(doc, sample_evidence)
    assert report.is_valid is True
    assert len(report.errors) == 0
    assert "C12" in report.verified_citation_index

    # Assemble Markdown
    md_output = assembler.assemble_markdown(doc)
    assert "# IT Access Standard Operating Procedure" in md_output
    assert "[C12]" in md_output
    assert "## Citation Index" in md_output
    assert "Source: IT_Access_Policy.pdf" in md_output
    assert "Chunk ID: chunk_8f31" in md_output

def test_validator_catches_hallucinated_chunk(sample_evidence):
    validator = CitationValidator()

    # Section cites a hallucinated chunk ID
    section = SOPSection(
        section_title="2. Security Controls",
        content="All passwords must be 16 characters. [C1]",
        citations=[
            CitationRef(
                citation_tag="C1",
                chunk_id="chunk_hallucinated_xyz",
                source_doc="IT_Access_Policy.pdf",
                location="Page 99",
                section="Passwords",
                evidence_quote="Fake quote",
            )
        ]
    )

    doc = SOPDocument(
        title="Security SOP",
        purpose="Testing",
        target_audience="Staff",
        sections=[section],
    )

    report = validator.validate_document(doc, sample_evidence)
    assert report.is_valid is False
    assert any("references non-existent chunk ID" in err for err in report.errors)

def test_validator_catches_orphan_citation_tag(sample_evidence):
    validator = CitationValidator()

    # Text contains [C99] but citations list is empty
    section = SOPSection(
        section_title="3. Orphan Tag Test",
        content="Unauthorized access is prohibited. [C99]",
        citations=[]
    )

    doc = SOPDocument(
        title="Access SOP",
        purpose="Testing",
        target_audience="Staff",
        sections=[section],
    )

    report = validator.validate_document(doc, sample_evidence)
    assert report.is_valid is False
    assert any("Citation tag [C99] used in text has no accompanying metadata" in err for err in report.errors)
