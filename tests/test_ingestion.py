import tempfile
from pathlib import Path
from injester.ingestion.extractor import DocumentExtractor
from injester.ingestion.chunker import HierarchicalChunker

def test_document_extraction_and_provenance():
    extractor = DocumentExtractor()
    chunker = HierarchicalChunker()

    sample_doc = (
        "# Enterprise Data Retention Policy\n\n"
        "## 1. Scope and Objective\n"
        "This policy governs financial records and client transaction logs.\n\n"
        "## 2. Retention Periods\n"
        "Financial audit records must be retained for seven full calendar years.\n"
        "Temporary access logs may be purged after thirty days.\n\n"
        "## 3. Storage Security\n"
        "All backups must be encrypted with AES-256 before upload.\n"
    )

    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
        f.write(sample_doc)
        temp_path = f.name

    try:
        # Extract elements
        elements = extractor.extract(
            file_path=temp_path,
            document_id="doc_retention_001",
            filename="Data_Retention_Policy.md",
            tenant_id="tenant_bank"
        )
        assert len(elements) > 0
        
        # Verify provenance attached to elements
        for elem in elements:
            assert elem.metadata.document_id == "doc_retention_001"
            assert elem.metadata.filename == "Data_Retention_Policy.md"
            assert elem.metadata.tenant_id == "tenant_bank"

        # Chunk elements
        chunks = chunker.chunk_elements(elements)
        assert len(chunks) > 0

        # Verify chunks have valid chunk_ids, section breadcrumbs, and citation formatting
        for chunk in chunks:
            assert chunk.chunk_id.startswith("chunk_")
            assert chunk.document_id == "doc_retention_001"
            assert chunk.tenant_id == "tenant_bank"
            citation_str = chunk.to_citation_format("C1")
            assert "[C1]" in citation_str
            assert "Data_Retention_Policy.md" in citation_str
            assert chunk.chunk_id in citation_str

    finally:
        Path(temp_path).unlink(missing_ok=True)
