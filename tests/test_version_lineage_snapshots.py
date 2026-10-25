import uuid
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from injester.domain.models import Base, Organisation, User, OrgStatus, UserRole, ProcessGraphSnapshot, GenerationRun
from injester.domain.auth import SecurityContext, AccessDeniedError
from injester.infrastructure.db import TenantRepository
from injester.synthesis.spans import SpanRegistry
from injester.ingestion.schema import DocumentChunk, ProvenanceMetadata


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def test_process_graph_snapshot_multi_document_provenance(db_session):
    """
    P3.1 & P3.4: Verify that ProcessGraphSnapshot stores multi-document version IDs,
    cryptographic source hashes, span registry hash, and is persisted and retrieved.
    """
    repo = TenantRepository(db_session)
    super_ctx = SecurityContext(user_id="su", email="su@injester.io", role=UserRole.SUPER_ADMIN, organisation_id="platform")

    org = repo.create_organisation(super_ctx, name="Acme Corp", status=OrgStatus.APPROVED)
    sec_ctx = SecurityContext(user_id="u1", email="u1@acme.com", role=UserRole.CLIENT_ADMIN, organisation_id=org.id)

    file_ver_ids = ["f_ver_001", "f_ver_002"]
    source_hashes = ["hash_abc", "hash_def"]
    source_doc_hashes = {"doc_1": "hash_abc", "doc_2": "hash_def"}

    snapshot = repo.save_process_graph_snapshot(
        sec_ctx=sec_ctx,
        process_name="Purchase Order Approval",
        canonical_graph={"nodes": [], "edges": []},
        defect_register={"defects": []},
        file_version_ids=file_ver_ids,
        source_hashes=source_hashes,
        source_document_hashes=source_doc_hashes,
        span_registry_hash="span_reg_hash_123",
        reasoner_model="qwen2.5:1.5b",
        laya_model_version="openjev-v1",
        projections={"mermaid": "graph TD;"},
    )

    assert snapshot.id is not None
    assert snapshot.organisation_id == org.id
    assert snapshot.file_version_ids == file_ver_ids
    assert snapshot.source_document_hashes == source_doc_hashes
    assert snapshot.span_registry_hash == "span_reg_hash_123"

    # Retrieve snapshot within same tenant
    retrieved = repo.get_process_graph_snapshot(sec_ctx, snapshot.id)
    assert retrieved.id == snapshot.id
    assert retrieved.process_name == "Purchase Order Approval"

    # Cross-tenant access check: another tenant must be denied
    org_other = repo.create_organisation(super_ctx, name="Beta Corp", status=OrgStatus.APPROVED)
    sec_ctx_other = SecurityContext(user_id="u2", email="u2@beta.com", role=UserRole.CLIENT_ADMIN, organisation_id=org_other.id)

    with pytest.raises(AccessDeniedError, match="Access denied to requested snapshot"):
        repo.get_process_graph_snapshot(sec_ctx_other, snapshot.id)


def test_generation_run_freshness_key_and_lineage(db_session):
    """
    P3.2: Verify GenerationRun entity creation and deterministic freshness key calculation.
    """
    repo = TenantRepository(db_session)
    super_ctx = SecurityContext(user_id="su", email="su@injester.io", role=UserRole.SUPER_ADMIN, organisation_id="platform")
    org = repo.create_organisation(super_ctx, name="Delta Corp", status=OrgStatus.APPROVED)
    sec_ctx = SecurityContext(user_id="u3", email="u3@delta.com", role=UserRole.CLIENT_ADMIN, organisation_id=org.id)

    input_vers = ["v2", "v1"]
    input_hashes = {"f1": "h1", "f2": "h2"}
    cfg_hash = "config_sha256_xyz"

    run = repo.save_generation_run(
        sec_ctx=sec_ctx,
        run_type="process_graph",
        input_file_version_ids=input_vers,
        input_hashes=input_hashes,
        config_hash=cfg_hash,
    )

    assert run.id is not None
    assert run.organisation_id == org.id
    assert run.run_type == "process_graph"
    assert len(run.freshness_key) == 64

    # Freshness key must be identical regardless of input order (sorted)
    run2 = repo.save_generation_run(
        sec_ctx=sec_ctx,
        run_type="process_graph",
        input_file_version_ids=["v1", "v2"],
        input_hashes=input_hashes,
        config_hash=cfg_hash,
    )
    assert run.freshness_key == run2.freshness_key


def test_span_registry_version_awareness():
    """
    P3.3: Verify that SpanRegistry accurately incorporates chunk file_version_id
    and never defaults to hardcoded generic 'v1'.
    """
    meta1 = ProvenanceMetadata(
        document_id="doc_loan_abc",
        filename="Loan_Policy.pdf",
        tenant_id="tenant_fin",
        page_number=1,
        source_location="Page 1",
        file_version_id="fver_build_9941",
    )
    chunk1 = DocumentChunk(
        chunk_id="chk_01",
        document_id="doc_loan_abc",
        filename="Loan_Policy.pdf",
        tenant_id="tenant_fin",
        file_version_id="fver_build_9941",
        text="All applicants must provide photo identification prior to underwriting.",
        provenance=meta1,
    )

    registry = SpanRegistry.from_chunks([chunk1])
    spans = registry.get_chunk_spans("chk_01")
    assert len(spans) == 1
    assert spans[0].file_version_id == "fver_build_9941"
    assert "fver_build_9941" in spans[0].canonical_id or "fver_build_9941" == spans[0].file_version_id
    assert spans[0].file_version_id != "v1"
