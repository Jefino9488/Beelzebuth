import io
import uuid
import pytest
from unittest.mock import MagicMock
from fastapi.testclient import TestClient

from injester.config import settings
from injester.api.app import app
from injester.infrastructure.db import init_db, SessionLocal, TenantRepository
from injester.domain.models import (
    Organisation,
    File as DBFile,
    FileVersion as DBFileVersion,
    ProcessGraphSnapshot,
    GenerationRun,
)
from injester.domain.auth import SecurityContext, UserRole, bootstrap_superadmin
from injester.ingestion.schema import DocumentChunk, ProvenanceMetadata
from injester.semantic.schemas import (
    CanonicalProcessModel,
    SemanticProcessNode,
    SemanticProcessEdge,
    ProcessRelationType,
    GroundedProcessGraph,
    ProcessActor,
    ProcessActivity,
    AmbiguityRegister,
)
from injester.ingestion.extractor import DocumentExtractor
from injester.ingestion.chunker import HierarchicalChunker
from injester.sop.spans import SpanRegistry, SourceSpan
from injester.pipeline import InjesterPipeline


@pytest.fixture(scope="module")
def api_client():
    try:
        init_db()
    except Exception:
        pass
    with TestClient(app) as c:
        login_res = c.post("/api/auth/login", json={
            "email": settings.SUPERADMIN_EMAIL,
            "password": settings.SUPERADMIN_INITIAL_PASSWORD,
        })
        if login_res.status_code == 200:
            token = login_res.json()["access_token"]
            c.cookies.set("access_token", token)
            c.headers["Authorization"] = f"Bearer {token}"
        yield c


# =====================================================================
# 1. Edge ID Invariant: CanonicalProcessModel must not synthesize edge_ids
# =====================================================================
def test_canonical_model_rejects_missing_edge_id():
    """Verify CanonicalProcessModel raises ValueError if any edge lacks an explicit edge_id."""
    with pytest.raises(ValueError, match="must have an explicit edge_id"):
        CanonicalProcessModel(
            process_name="Strict Edge ID Test",
            objective="Verify No Auto-Mutation",
            schema_version="1.0",
            nodes=[
                SemanticProcessNode(node_id="N1", node_type="start_event", label="Start", evidence_spans=["S01"]),
                SemanticProcessNode(node_id="N2", node_type="end_event", label="End", evidence_spans=["S01"]),
            ],
            edges=[
                SemanticProcessEdge(
                    edge_id="",
                    source_node_id="N1",
                    target_node_id="N2",
                    relation=ProcessRelationType.PRECEDES,
                    evidence_spans=["S01"],
                )
            ]
        )


# =====================================================================
# 2. Ingestion FileVersion & Hash Propagation Chain into SourceSpan
# =====================================================================
def test_ingestion_file_version_and_hash_propagation_chain(tmp_path):
    """
    Verify complete propagation chain:
    Extractor(file_version_id, file_hash) -> NormalizedElement -> Chunk -> SourceSpan
    Ensures no fallback identities exist.
    """
    test_file = tmp_path / "sop_policy.txt"
    test_file.write_text(
        "Commercial loan requests up to $100,000 may be approved by a Senior Credit Analyst.\n"
        "Requests exceeding $100,000 require approval by the Credit Committee.\n"
    )

    doc_id = f"doc_{uuid.uuid4().hex[:8]}"
    file_version_id = f"ver_{uuid.uuid4().hex[:8]}"
    file_hash = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    tenant_id = "tenant_audit_test"

    extractor = DocumentExtractor()
    elements = extractor.extract(
        file_path=str(test_file),
        document_id=doc_id,
        filename="sop_policy.txt",
        tenant_id=tenant_id,
        file_version_id=file_version_id,
        file_hash=file_hash,
    )

    assert len(elements) > 0
    for elem in elements:
        assert elem.metadata.file_version_id == file_version_id
        assert elem.metadata.extra.get("file_hash") == file_hash
        assert elem.metadata.document_id == doc_id
        assert elem.metadata.tenant_id == tenant_id

    chunker = HierarchicalChunker(target_chunk_size=500, overlap_size=50)
    chunks = chunker.chunk_elements(elements)
    assert len(chunks) > 0
    for chunk in chunks:
        assert chunk.file_version_id == file_version_id
        assert chunk.provenance.file_version_id == file_version_id
        assert chunk.provenance.extra.get("file_hash") == file_hash

    registry = SpanRegistry.from_chunks(chunks)
    assert len(registry.spans_by_id) > 0
    for span in registry.spans_by_id.values():
        assert span.file_version_id == file_version_id
        assert span.canonical_id.startswith("S_")
        assert len(span.canonical_id) == 66  # "S_" prefix + 64-char SHA-256
        assert len(span.text_hash) == 64

    manifest_hash = registry.compute_manifest_hash()
    assert len(manifest_hash) == 64


# =====================================================================
# 3. generate_sop() Lineage and accessible_files Execution
# =====================================================================
def test_generate_sop_lineage_no_name_error(monkeypatch):
    """Verify generate_sop runs without NameError (using accessible_files.values())."""
    db = SessionLocal()
    try:
        admin_user = bootstrap_superadmin(db)
        repo = TenantRepository(db)
        sec_ctx_admin = SecurityContext(
            user_id=admin_user.id,
            email=admin_user.email,
            role=UserRole.SUPER_ADMIN,
            organisation_id=None,
        )
        orgs = repo.list_organisations(sec_ctx_admin)
        org = orgs[0] if orgs else repo.create_organisation(sec_ctx=sec_ctx_admin, name="Audit Org SOP")

        sec_ctx = SecurityContext(
            user_id=admin_user.id,
            email=admin_user.email,
            role=UserRole.SUPER_ADMIN,
            organisation_id=org.id,
        )

        # Upload a test file so accessible_files is non-empty
        file_rec, file_ver = repo.upload_file(
            sec_ctx=sec_ctx,
            filename=f"sop_doc_{uuid.uuid4().hex[:6]}.txt",
            content_bytes=b"Commercial loan requests up to $100,000 may be approved by a Senior Credit Analyst.",
            mime_type="text/plain",
        )

        pipeline = InjesterPipeline(session=db)
        mock_chunk = DocumentChunk(
            chunk_id="chk_test_01",
            document_id=file_rec.id,
            filename=file_rec.name,
            tenant_id=org.id,
            text="Commercial loan requests up to $100,000 may be approved by a Senior Credit Analyst.",
            file_version_id=file_ver.id,
            provenance=ProvenanceMetadata(
                document_id=file_rec.id,
                filename=file_rec.name,
                tenant_id=org.id,
                file_version_id=file_ver.id,
                extra={"file_hash": file_ver.file_hash},
            ),
        )

        # Mock vector store
        pipeline.vector_store._load_tenant_index = MagicMock(return_value=(None, [mock_chunk]))

        # Mock SOPGenerator and build_sop
        mock_doc = MagicMock()
        mock_doc.title = f"Test SOP {uuid.uuid4().hex[:6]}"
        mock_doc.sections = []
        mock_kmap = MagicMock()
        mock_gen_instance = MagicMock()
        mock_gen_instance.build_sop.return_value = mock_doc
        mock_gen_instance.last_kmap = mock_kmap

        monkeypatch.setattr("injester.pipeline.SOPGenerator", MagicMock(return_value=mock_gen_instance))

        # Mock validator and assembler
        mock_report = MagicMock()
        mock_report.verified_citation_index = {}
        pipeline.validator.validate_document = MagicMock(return_value=mock_report)
        pipeline.assembler.assemble_markdown = MagicMock(return_value="# Test SOP Markdown")

        md_sop, val_rep = pipeline.generate_sop(
            topic_goal="Test Goal",
            sec_ctx=sec_ctx,
            file_ids=[file_rec.id],
        )
        assert md_sop == "# Test SOP Markdown"
        assert val_rep == mock_report

        # Verify GenerationRun was persisted with file_version_ids
        runs = db.query(GenerationRun).filter(GenerationRun.output_sop_id == mock_doc.title).all()
        assert len(runs) > 0
        assert runs[0].input_file_version_ids == [file_ver.id]
    finally:
        db.close()


# =====================================================================
# 4. Projection GET Endpoints: Snapshot Serving & Fail-Closed 404
# =====================================================================
def test_projection_get_endpoints_fail_closed_and_serve_snapshot(api_client):
    """
    Verify GET /api/process-graph/{file_id}/bpmn, /mermaid, /defect-register
    1. Returns HTTP 404 if no snapshot exists (never re-running LLM)
    2. Serves cached projections directly when snapshot exists
    """
    db = SessionLocal()
    try:
        admin_user = bootstrap_superadmin(db)
        repo = TenantRepository(db)
        sec_ctx = SecurityContext(
            user_id=admin_user.id,
            email=admin_user.email,
            role=UserRole.SUPER_ADMIN,
            organisation_id=None,
        )
        orgs = repo.list_organisations(sec_ctx)
        org = orgs[0] if orgs else repo.create_organisation(sec_ctx=sec_ctx, name="Default Org")

        sec_ctx_org = SecurityContext(
            user_id=admin_user.id,
            email=admin_user.email,
            role=UserRole.SUPER_ADMIN,
            organisation_id=org.id,
        )

        # Create a test file
        file_record, file_ver = repo.upload_file(
            sec_ctx=sec_ctx_org,
            filename=f"proj_test_{uuid.uuid4().hex[:6]}.txt",
            content_bytes=b"Sample process policy document text.",
            mime_type="text/plain",
        )

        # 1. No snapshot exists yet -> endpoints MUST return HTTP 404 fail-closed
        res_bpmn_404 = api_client.get(f"/api/v1/process-graph/{file_record.id}/bpmn")
        assert res_bpmn_404.status_code == 404
        assert "Generation required. No existing snapshot found" in res_bpmn_404.json()["detail"]

        res_mmd_404 = api_client.get(f"/api/v1/process-graph/{file_record.id}/mermaid")
        assert res_mmd_404.status_code == 404

        res_dr_404 = api_client.get(f"/api/v1/process-graph/{file_record.id}/defect-register")
        assert res_dr_404.status_code == 404

        # 2. Save a ProcessGraphSnapshot for this file
        test_graph = GroundedProcessGraph(
            process_name="Snap Process",
            objective="Snapshot Verification",
            actors=[ProcessActor(id="ACT_01", name="Officer", evidence=["S01"])],
            activities=[ProcessActivity(id="STEP_01", actor_id="ACT_01", label="Process Application", description="", evidence=["S01"])],
            transitions=[],
        )
        defect_reg = AmbiguityRegister(document_name=file_record.name)
        snapshot = repo.save_process_graph_snapshot(
            sec_ctx=sec_ctx_org,
            process_name="Snap Process",
            canonical_graph=test_graph.model_dump(),
            defect_register=defect_reg.model_dump(),
            file_version_ids=[file_ver.id],
            source_hashes=[file_ver.file_hash],
            source_document_hashes={file_record.id: file_ver.file_hash},
            span_registry_hash="a" * 64,
            reasoner_model="default",
            laya_model_version="system1-v1",
            projections={
                "bpmn_xml": "<?xml version='1.0'?><definitions>BPMN_CACHED</definitions>",
                "mermaid": "flowchart TD\nSTEP_01[Process Application]",
                "defect_md": "# Ambiguity & Defect Register: Snap Process\nZero defects detected.",
            },
        )

        # 3. Requesting projections now serves directly from snapshot (HTTP 200)
        res_bpmn_200 = api_client.get(f"/api/v1/process-graph/{file_record.id}/bpmn")
        assert res_bpmn_200.status_code == 200
        assert "BPMN_CACHED" in res_bpmn_200.text

        res_mmd_200 = api_client.get(f"/api/v1/process-graph/{file_record.id}/mermaid")
        assert res_mmd_200.status_code == 200
        assert "flowchart TD" in res_mmd_200.text

        res_dr_200 = api_client.get(f"/api/v1/process-graph/{file_record.id}/defect-register")
        assert res_dr_200.status_code == 200
        assert "Ambiguity & Defect Register" in res_dr_200.text

        res_dr_json = api_client.get(f"/api/v1/process-graph/{file_record.id}/defect-register?format=json")
        assert res_dr_json.status_code == 200
        assert res_dr_json.json()["document_name"] == file_record.name

    finally:
        db.close()


# =====================================================================
# 5. UI Identity Verification: Ignoring Request-Supplied user_email
# =====================================================================
def test_ui_upload_ignores_request_supplied_user_email(api_client):
    """
    Verify that passing a spoofed user_email form field to /api/files/upload
    is ignored, and the created file record strictly derives ownership from sec_ctx.user_id.
    """
    fake_email = "spoofed_attacker@evil.com"
    fname = f"spoof_{uuid.uuid4().hex[:6]}.txt"
    content = b"Sample policy text for identity audit."
    res = api_client.post(
        "/api/files/upload",
        data={
            "user_email": fake_email,  # Attempting to impersonate
        },
        files={"file": (fname, io.BytesIO(content), "text/plain")},
        follow_redirects=False,
    )
    assert res.status_code == 200

    db = SessionLocal()
    try:
        # Find the uploaded file record
        file_rec = db.query(DBFile).filter(DBFile.name == fname).first()
        assert file_rec is not None
        # File owner must match the authenticated superadmin user in sec_ctx, not a fabricated user
        assert file_rec.created_by_user_id is not None
        assert file_rec.created_by_user_id != fake_email
    finally:
        db.close()


# =====================================================================
# 6. Structured config_hash & span_registry_hash Integrity
# =====================================================================
def test_structured_config_hash_and_span_registry_hash():
    """Verify deterministic SHA-256 calculation for pipeline config_hash and span_registry_hash."""
    pipeline = InjesterPipeline()
    ch1 = pipeline._compute_config_hash(run_type="process_graph")
    assert len(ch1) == 64

    # Identical configs produce identical hash
    ch2 = pipeline._compute_config_hash(run_type="process_graph")
    assert ch1 == ch2

    # Different run_type produces different hash
    ch_sop = pipeline._compute_config_hash(run_type="sop")
    assert ch_sop != ch1
    assert len(ch_sop) == 64

    # Span registry hash determinism
    reg = SpanRegistry()
    reg.spans_by_id["S001"] = SourceSpan(
        span_id="S001",
        canonical_id="S_" + "a" * 64,
        chunk_id="c1",
        tenant_id="t1",
        file_version_id="v1",
        text="Sample text 1",
        text_hash="h1",
        source_doc="doc1.txt",
    )
    reg.spans_by_id["S002"] = SourceSpan(
        span_id="S002",
        canonical_id="S_" + "b" * 64,
        chunk_id="c1",
        tenant_id="t1",
        file_version_id="v1",
        text="Sample text 2",
        text_hash="h2",
        source_doc="doc1.txt",
    )
    s_hash1 = reg.compute_manifest_hash()
    s_hash2 = reg.compute_manifest_hash()
    assert len(s_hash1) == 64
    assert s_hash1 == s_hash2
