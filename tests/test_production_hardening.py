import pytest
from injester.ingestion.schema import DocumentChunk, ProvenanceMetadata
from injester.synthesis.retriever import HybridRetriever
from injester.vectorstore.base import VectorStore
from injester.infrastructure.jobs import JobManager, JobType, JobStatus
from injester.infrastructure.db import init_db, SessionLocal


class MockVectorStore(VectorStore):
    def __init__(self):
        pass
    def add_documents(self, tenant_id: str, chunks):
        pass
    def search(self, tenant_id: str, query: str, top_k: int = 5):
        return []
    def delete_document(self, tenant_id: str, document_id: str):
        pass
    def list_documents(self, tenant_id: str):
        return []
    def get_chunks(self, tenant_id: str, document_ids=None):
        return []


@pytest.fixture
def sample_chunks():
    meta = ProvenanceMetadata(
        document_id="doc_harden_01",
        filename="Security_Checklist.pdf",
        tenant_id="tenant_alpha",
        page_number=1,
        source_location="Page 1",
    )
    chunk1 = DocumentChunk(
        chunk_id="chk_hard_01",
        document_id="doc_harden_01",
        filename="Security_Checklist.pdf",
        tenant_id="tenant_alpha",
        text="Firewall configurations must be reviewed quarterly by Network Security Engineers.",
        provenance=meta,
    )
    chunk2 = DocumentChunk(
        chunk_id="chk_hard_02",
        document_id="doc_harden_01",
        filename="Security_Checklist.pdf",
        tenant_id="tenant_alpha",
        text="Database access logs must be retained for at least 365 calendar days.",
        provenance=meta,
    )
    return [chunk1, chunk2]


def test_bm25_corpus_caching(sample_chunks):
    """P4.1: Verify BM25 index caching across queries for identical chunk sets."""
    vs = MockVectorStore()
    retriever = HybridRetriever(vs)
    HybridRetriever._bm25_cache.clear()

    # Query 1: Cache is cold
    results1 = retriever.retrieve("tenant_alpha", "firewall quarterly", sample_chunks, top_k=2)
    assert len(results1) > 0
    assert "tenant_alpha" in HybridRetriever._bm25_cache
    fingerprint, cached_bm25 = HybridRetriever._bm25_cache["tenant_alpha"]

    # Query 2: Must reuse cached BM25 instance
    results2 = retriever.retrieve("tenant_alpha", "database logs", sample_chunks, top_k=2)
    assert len(results2) > 0
    new_fingerprint, new_bm25 = HybridRetriever._bm25_cache["tenant_alpha"]
    assert new_bm25 is cached_bm25


def test_cross_encoder_exception_fallback(sample_chunks):
    """P4.2: Verify that CrossEncoder runtime errors are handled cleanly and fallback to RRF."""
    vs = MockVectorStore()
    retriever = HybridRetriever(vs)

    class FailingEncoder:
        def predict(self, pairs):
            raise RuntimeError("Simulated GPU OOM or model prediction failure")

    HybridRetriever._cross_encoder = FailingEncoder()

    # Should not raise RuntimeError; must fall back to RRF candidates
    results = retriever.retrieve("tenant_alpha", "firewall", sample_chunks, top_k=1)
    assert len(results) == 1
    assert results[0].chunk_id == "chk_hard_01"

    HybridRetriever._cross_encoder = None


def test_sqlite_wal_init():
    """P4.3: Verify SQLite database initialization executes cleanly with WAL mode."""
    # init_db must execute without errors
    init_db()
    with SessionLocal() as session:
        assert session is not None


def test_job_manager_listing_by_tenant():
    """P4.4: Verify JobManager job submission and tenant isolation filtering."""
    jm = JobManager()
    jm.jobs.clear()

    r1 = jm.submit_job("org_a", "u1", JobType.INGESTION, lambda: {"status": "ok"})
    r2 = jm.submit_job("org_b", "u2", JobType.PROCESS_GRAPH, lambda: {"status": "ok"})

    jobs_a = jm.list_jobs(organisation_id="org_a")
    assert len(jobs_a) == 1
    assert jobs_a[0].job_id == r1.job_id

    jobs_b = jm.list_jobs(organisation_id="org_b")
    assert len(jobs_b) == 1
    assert jobs_b[0].job_id == r2.job_id
