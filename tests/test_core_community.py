from pathlib import Path
from injester.application.manager import manager
from injester.application.documents import DocumentService
from injester.application.retrieval import RetrievalService

def test_community_pipeline_and_services():
    manager.ensure_initialized()
    doc_service = DocumentService()
    retrieval_service = RetrievalService()

    # Ingest sample markdown
    sample_file = Path("sample_docs/IT_Access_Policy.md")
    assert sample_file.exists()

    res = doc_service.ingest(sample_file)
    assert res.doc_id
    assert res.chunk_count > 0

    # List documents
    docs = doc_service.list_documents()
    assert any(d.doc_id == res.doc_id for d in docs)

    # Retrieval
    matches = retrieval_service.search("passwords", top_k=3)
    assert len(matches) > 0
    assert any("passwords" in m.text.lower() for m in matches)
