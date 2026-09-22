import tempfile
from pathlib import Path
from injester.ingestion.schema import DocumentChunk, ProvenanceMetadata
from injester.vectorstore.faiss_store import FaissVectorStore

def test_faiss_vector_store_tenant_isolation():
    with tempfile.TemporaryDirectory() as temp_dir:
        storage_dir = Path(temp_dir)
        store = FaissVectorStore(base_storage_dir=storage_dir)

        # Chunks for Tenant A (Indian Bank)
        meta_a = ProvenanceMetadata(
            document_id="doc_bank_1",
            filename="Bank_Policy.pdf",
            tenant_id="tenant_bank",
            section_path=["Security"],
            source_location="Page 1",
        )
        chunk_a1 = DocumentChunk(
            chunk_id="chunk_a1",
            document_id="doc_bank_1",
            filename="Bank_Policy.pdf",
            tenant_id="tenant_bank",
            text="Employees must obtain dual manager authorization before wire transfers exceeding 50,000 dollars.",
            provenance=meta_a,
        )

        # Chunks for Tenant B (Healthcare Corp)
        meta_b = ProvenanceMetadata(
            document_id="doc_health_1",
            filename="Health_Records.pdf",
            tenant_id="tenant_health",
            section_path=["HIPAA"],
            source_location="Page 5",
        )
        chunk_b1 = DocumentChunk(
            chunk_id="chunk_b1",
            document_id="doc_health_1",
            filename="Health_Records.pdf",
            tenant_id="tenant_health",
            text="Patient medical records must be safeguarded according to HIPAA privacy standards.",
            provenance=meta_b,
        )

        # Add to respective tenant stores
        store.add_documents("tenant_bank", [chunk_a1])
        store.add_documents("tenant_health", [chunk_b1])

        # Query Tenant A
        bank_results = store.search("tenant_bank", "wire transfer authorization", top_k=5)
        assert len(bank_results) == 1
        assert bank_results[0][0].chunk_id == "chunk_a1"

        # Verify cross-tenant isolation: Healthcare queries inside Tenant A return NOTHING
        health_in_bank = store.search("tenant_bank", "patient medical records HIPAA", top_k=5)
        for chunk, score in health_in_bank:
            assert chunk.tenant_id == "tenant_bank"
            assert chunk.chunk_id != "chunk_b1"

        # Query Tenant B
        health_results = store.search("tenant_health", "patient medical records", top_k=5)
        assert len(health_results) == 1
        assert health_results[0][0].chunk_id == "chunk_b1"
