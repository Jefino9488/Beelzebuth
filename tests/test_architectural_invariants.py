"""
Architectural Invariant Test Suite.
Verifies the 15 fundamental system contracts across:
1. Semantic purity boundary (no heuristic dictionaries, no prescriptive prompts, non-mutating model)
2. Compiler gating & defect register quarantine (tri-state verdicts, referential integrity, AST purity)
3. Multi-target projection fidelity (no silent orphan pruning, unbiased BPMN lanes)
4. Multi-tenant security, RBAC & lifecycle (folder isolation, audit logging, org status lifecycle)
5. Physical storage sanitization & provenance (version race protection, blob isolation)
6. Asynchronous job execution (HTTP 202 Accepted + job_id polling)
"""

import io
import uuid
import hashlib
import inspect
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from injester.config import settings
from injester.api.app import app
from injester.domain.models import UserRole, OrgStatus, AuditLog, ProcessGraphSnapshot, File, FileVersion
from injester.domain.auth import SecurityContext, AccessDeniedError
from injester.infrastructure.db import TenantRepository, SessionLocal, init_db
from injester.infrastructure.jobs import job_manager, JobType, JobStatus
from injester.semantic.schemas import (
    CanonicalProcessModel,
    SemanticProcessNode,
    SemanticProcessEdge,
    ProcessRelationType,
    ElementStatus,
    GroundingVerdict,
    LayaVerdict,
    AtomicProposition,
    ModalityType,
    EpistemicStatus,
    DefectCategory,
)
from injester.semantic.reasoner import SemanticProcessReasoner
from injester.semantic.validator import SemanticGraphValidator
from injester.semantic.laya_adapter import LayaSystem1Verifier
from injester.semantic.compiler import DeterministicGraphCompiler
from injester.semantic.projections import render_flowchart_mermaid, render_bpmn_20_xml, ACTOR_UNASSIGNED
from injester.synthesis.spans import SpanRegistry, SourceSpan


# =====================================================================
# FIXTURES
# =====================================================================

@pytest.fixture(scope="module")
def api_client():
    init_db()
    with TestClient(app) as client:
        # Authenticate superadmin session cookie for UI / management
        login_res = client.post("/api/auth/login", json={
            "email": settings.SUPERADMIN_EMAIL,
            "password": settings.SUPERADMIN_INITIAL_PASSWORD,
        })
        if login_res.status_code == 200:
            token = login_res.json()["access_token"]
            client.cookies.set("access_token", token)
        yield client


# =====================================================================
# INVARIANT 1: Semantic Reasoner Prompt Has No Prescriptive Heuristics
# =====================================================================
def test_invariant_01_semantic_reasoner_prompt_purity():
    """Invariant 1: Reasoner prompt does not prescribe business actor heuristics or forced terminal events."""
    prompt = SemanticProcessReasoner.SYSTEM_PROMPT
    assert "Assign actor 'System' if" not in prompt
    assert "Prune introductory steps" not in prompt
    assert "Every process MUST have an EndEvent" not in prompt
    assert "source_proposition_ids" in prompt
    assert "schema_version" in prompt


# =====================================================================
# INVARIANT 2: Pure Referential Validator (No Heuristic Dictionaries)
# =====================================================================
def test_invariant_02_validator_has_no_heuristic_dictionaries():
    """Invariant 2: Structural validator contains no role dictionaries, qualifiers, or sequence reversal rules."""
    validator = SemanticGraphValidator()
    heuristic_attrs = [
        "ROLE_QUALIFIERS",
        "ACTION_SYNONYMS",
        "REVERSE_CONNECTIVES",
        "PASSIVE_INDICATORS",
        "DEFAULT_ROLES",
        "STOP_WORDS",
    ]
    for attr in heuristic_attrs:
        assert not hasattr(validator, attr), f"Validator illegally contains heuristic attribute '{attr}'"

    # Validator source code must not perform regex lookups for business semantics
    source = inspect.getsource(SemanticGraphValidator)
    assert "chief" not in source.lower()
    assert "manager" not in source.lower()


# =====================================================================
# INVARIANT 3: Laya Adapter Structural Fallback Purity
# =====================================================================
def test_invariant_03_laya_fallback_purity():
    """Invariant 3: Laya fallback only checks span existence, never faking semantic predictions or token overlaps."""
    verifier = LayaSystem1Verifier()
    source = inspect.getsource(verifier._fallback_verify)
    # Must not fake semantic role or action overlap heuristics
    assert "ROLE_QUALIFIERS" not in source
    assert "recipient" not in source.lower()
    assert "all(" not in source or "span_registry.get_span" in source


# =====================================================================
# INVARIANT 4: CanonicalProcessModel Invariants Are Non-Mutating
# =====================================================================
def test_invariant_04_canonical_model_validation_is_non_mutating():
    """Invariant 4: validate_graph_invariants never mutates relation types or synthetic names."""
    model = CanonicalProcessModel(
        process_name="Test Invariant",
        objective="Verify non-mutation",
        schema_version="1.0",
        nodes=[
            SemanticProcessNode(node_id="N1", node_type="decision", label="Check Limit", condition="amount > 1000", evidence_spans=["S001"]),
            SemanticProcessNode(node_id="N2", node_type="activity", label="Approve", evidence_spans=["S001"]),
        ],
        edges=[
            SemanticProcessEdge(
                edge_id="E1",
                source_node_id="N1",
                target_node_id="N2",
                relation=ProcessRelationType.PRECEDES,  # Explicitly PRECEDES from reasoner
                condition="amount > 1000",
                evidence_spans=["S001"]
            )
        ]
    )

    # Validating graph invariants must not rewrite relation to BRANCH_IF
    model.validate_graph_invariants()
    assert model.edges[0].relation == ProcessRelationType.PRECEDES
    assert model.schema_version == "1.0"


# =====================================================================
# INVARIANT 5: Explicit Proposition Linking in Canonical IR
# =====================================================================
def test_invariant_05_explicit_proposition_linking():
    """Invariant 5: Nodes and edges contain explicit proposition tracking lists."""
    node = SemanticProcessNode(
        node_id="N_TEST",
        node_type="activity",
        label="Test Action",
        evidence_spans=["S001"],
        source_proposition_ids=["PROP_1", "PROP_2"],
        required_proposition_ids=["PROP_1"]
    )
    edge = SemanticProcessEdge(
        edge_id="E1",
        source_node_id="N1",
        target_node_id="N2",
        evidence_spans=["S001"],
        source_proposition_ids=["PROP_TRANS_1"]
    )
    assert "PROP_1" in node.source_proposition_ids
    assert "PROP_1" in node.required_proposition_ids
    assert "PROP_TRANS_1" in edge.source_proposition_ids


# =====================================================================
# INVARIANT 6: Tri-State Compiler Gating Contract
# =====================================================================
def test_invariant_06_tri_state_compiler_gating():
    """Invariant 6: Compiler gating contract enforces SUPPORTED->VERIFIED, UNCERTAIN->AMBIGUOUS, UNSUPPORTED->REJECTED."""
    registry = SpanRegistry()
    registry.spans_by_id["S001"] = SourceSpan(
        span_id="S001",
        chunk_id="chunk_1",
        source_doc="doc.txt",
        text="Officer reviews and approves the loan."
    )

    canonical = CanonicalProcessModel(
        process_name="Gating Process",
        objective="Verify Tri-State Gating",
        schema_version="1.0",
        nodes=[
            SemanticProcessNode(node_id="ACT_SUP", node_type="activity", label="Supported Action", evidence_spans=["S001"], required_proposition_ids=["P_SUP"]),
            SemanticProcessNode(node_id="ACT_UNC", node_type="activity", label="Uncertain Action", evidence_spans=["S001"], required_proposition_ids=["P_UNC"]),
            SemanticProcessNode(node_id="ACT_REJ", node_type="activity", label="Rejected Action", evidence_spans=["S001"], required_proposition_ids=["P_REJ"]),
        ],
        edges=[]
    )

    verdicts = {
        "P_SUP": LayaVerdict(proposition_id="P_SUP", verdict=GroundingVerdict.SUPPORTED, actor_grounded=True, action_entailed=True, is_verified=True),
        "P_UNC": LayaVerdict(proposition_id="P_UNC", verdict=GroundingVerdict.UNCERTAIN, actor_grounded=True, action_entailed=False, is_verified=False),
        "P_REJ": LayaVerdict(proposition_id="P_REJ", verdict=GroundingVerdict.UNSUPPORTED, actor_grounded=False, action_entailed=False, is_verified=False),
    }

    compiler = DeterministicGraphCompiler()
    result = compiler.compile(
        document_name="doc.txt",
        canonical_model=canonical,
        verdicts=verdicts,
        span_registry=registry
    )

    # 1. Supported node is in authoritative AST
    verified_ids = [a.id for a in result.graph.activities]
    assert "ACT_SUP" in verified_ids

    # 2. Uncertain and Rejected nodes are quarantined to Defect Register
    assert "ACT_UNC" not in verified_ids
    assert "ACT_REJ" not in verified_ids
    defect_prop_ids = [d.proposition_id for d in result.defect_register.defects]
    assert "ACT_UNC" in defect_prop_ids
    assert "ACT_REJ" in defect_prop_ids


# =====================================================================
# INVARIANT 7: Ambiguous and Rejected Edges Excluded from Verified Transitions
# =====================================================================
def test_invariant_07_ambiguous_and_rejected_edges_excluded_from_ast():
    """Invariant 7: Edges marked ambiguous or unsupported never enter verified_edges / transitions."""
    registry = SpanRegistry()
    registry.spans_by_id["S001"] = SourceSpan(span_id="S001", chunk_id="chunk_1", source_doc="doc.txt", text="Test transition text.")

    canonical = CanonicalProcessModel(
        process_name="Edge Gating",
        objective="Edge Exclusion Verification",
        schema_version="1.0",
        nodes=[
            SemanticProcessNode(node_id="A1", node_type="activity", label="A1", evidence_spans=["S001"], required_proposition_ids=["P1"]),
            SemanticProcessNode(node_id="A2", node_type="activity", label="A2", evidence_spans=["S001"], required_proposition_ids=["P1"]),
            SemanticProcessNode(node_id="A3", node_type="activity", label="A3", evidence_spans=["S001"], required_proposition_ids=["P1"]),
        ],
        edges=[
            SemanticProcessEdge(edge_id="E1", source_node_id="A1", target_node_id="A2", evidence_spans=["S001"], is_ambiguous=False, confidence=0.95),
            SemanticProcessEdge(edge_id="E2", source_node_id="A2", target_node_id="A3", evidence_spans=["S001"], is_ambiguous=True, confidence=0.60),  # Ambiguous!
        ]
    )

    verdicts = {
        "P1": LayaVerdict(proposition_id="P1", verdict=GroundingVerdict.SUPPORTED, actor_grounded=True, action_entailed=True, is_verified=True),
    }

    compiler = DeterministicGraphCompiler()
    result = compiler.compile(
        document_name="doc.txt",
        canonical_model=canonical,
        verdicts=verdicts,
        span_registry=registry
    )

    # Transition A1 -> A2 is verified
    trans_pairs = [(t.from_id, t.to_id) for t in result.graph.transitions]
    assert ("A1", "A2") in trans_pairs
    # Ambiguous transition A2 -> A3 MUST NOT be in AST
    assert ("A2", "A3") not in trans_pairs
    # Ambiguous transition MUST be in Defect Register
    assert any("EDGE_A2_A3" in d.proposition_id for d in result.defect_register.defects)


# =====================================================================
# INVARIANT 8: Multi-Target Projections Do Not Prune or Guess Lanes
# =====================================================================
def test_invariant_08_projections_no_orphan_pruning_no_lane_guessing():
    """Invariant 8: Mermaid & BPMN projections preserve disconnected nodes and assign unassigned actors explicitly."""
    from injester.semantic.schemas import GroundedProcessGraph, ProcessActivity, ProcessTransition, ProcessEvent

    graph = GroundedProcessGraph(
        process_name="Projection Test",
        objective="Verify Projections",
        events=[
            ProcessEvent(id="START", type="start", label="Start", evidence=[]),
            ProcessEvent(id="END", type="end", label="End", evidence=[]),
        ],
        activities=[
            ProcessActivity(id="ACT_CONNECTED", actor_id="ACTOR_RM", label="Connected Activity", description=""),
            ProcessActivity(id="ACT_ORPHAN", actor_id=ACTOR_UNASSIGNED, label="Orphan Activity", description=""),
        ],
        transitions=[]  # Zero transitions; both are topologically disconnected
    )

    # 1. Mermaid flowchart must contain both nodes (no silent pruning)
    mmd = render_flowchart_mermaid(graph)
    assert "ACT_CONNECTED" in mmd
    assert "ACT_ORPHAN" in mmd

    # 2. BPMN XML routes ACT_ORPHAN into the explicit Unassigned lane
    bpmn = render_bpmn_20_xml(graph)
    assert "Unassigned" in bpmn
    assert ("Lane_Unassigned" in bpmn or "lane_ACTOR_UNASSIGNED" in bpmn or 'name="Unassigned"' in bpmn)


# =====================================================================
# INVARIANT 9: Schema Version Invariant ("1.0")
# =====================================================================
def test_invariant_09_schema_version_invariant():
    """Invariant 9: CanonicalProcessModel and ProcessGraphSnapshot enforce schema_version = '1.0'."""
    model = CanonicalProcessModel(process_name="P", objective="O")
    assert model.schema_version == "1.0"

    snapshot = ProcessGraphSnapshot(
        organisation_id="org_1",
        process_name="P",
        schema_version="1.0",
        file_version_ids=["v1"],
        source_hashes=["hash1"],
        span_registry_hash="spanhash1",
        reasoner_model="gemini",
        laya_model_version="laya_v1",
        validation_policy_version="1.0",
        canonical_graph={},
        defect_register={},
    )
    assert snapshot.schema_version == "1.0"


# =====================================================================
# INVARIANT 10: Multi-Tenant Boundary Check & Audit Logging
# =====================================================================
def test_invariant_10_cross_tenant_denial_audited(db_session, superadmin_ctx):
    """Invariant 10: Cross-tenant data access raises AccessDeniedError and writes CROSS_TENANT_ACCESS_DENIED audit entry."""
    repo = TenantRepository(db_session)
    org_a = repo.create_organisation(superadmin_ctx, name=f"Org A {uuid.uuid4().hex[:6]}")
    org_b = repo.create_organisation(superadmin_ctx, name=f"Org B {uuid.uuid4().hex[:6]}")
    repo.approve_organisation(superadmin_ctx, org_a.id)
    repo.approve_organisation(superadmin_ctx, org_b.id)

    admin_a = repo.create_client_admin(superadmin_ctx, org_id=org_a.id, email=f"a_{uuid.uuid4().hex[:6]}@a.com", password="P1!")
    ctx_a = SecurityContext(user_id=admin_a.id, email=admin_a.email, role=UserRole.CLIENT_ADMIN, organisation_id=org_a.id)

    # Admin A uploads file in Org A
    file_a, _ = repo.upload_file(sec_ctx=ctx_a, filename="SecretA.pdf", content_bytes=b"Confidential Org A")

    admin_b = repo.create_client_admin(superadmin_ctx, org_id=org_b.id, email=f"b_{uuid.uuid4().hex[:6]}@b.com", password="P2!")
    ctx_b = SecurityContext(user_id=admin_b.id, email=admin_b.email, role=UserRole.CLIENT_ADMIN, organisation_id=org_b.id)

    # Admin B attempts to access File A -> MUST raise AccessDeniedError
    with pytest.raises(AccessDeniedError):
        repo.get_file(ctx_b, file_a.id)

    # Verify audit log recorded the attempted breach
    audit = db_session.query(AuditLog).filter(
        AuditLog.action == "CROSS_TENANT_ACCESS_DENIED",
        AuditLog.user_id == ctx_b.user_id
    ).first()
    assert audit is not None
    assert file_a.id in audit.details


# =====================================================================
# INVARIANT 11: Employee Folder Isolation
# =====================================================================
def test_invariant_11_employee_folder_isolation(db_session, superadmin_ctx):
    """Invariant 11: Employees are strictly isolated to folders they created."""
    repo = TenantRepository(db_session)
    org = repo.create_organisation(superadmin_ctx, name=f"Bank {uuid.uuid4().hex[:6]}")
    repo.approve_organisation(superadmin_ctx, org.id)

    ca = repo.create_client_admin(superadmin_ctx, org_id=org.id, email=f"ca_{uuid.uuid4().hex[:6]}@b.com", password="P!")
    ca_ctx = SecurityContext(user_id=ca.id, email=ca.email, role=UserRole.CLIENT_ADMIN, organisation_id=org.id)

    emp1 = repo.create_employee(ca_ctx, org_id=org.id, email=f"e1_{uuid.uuid4().hex[:6]}@b.com", password="P!")
    emp2 = repo.create_employee(ca_ctx, org_id=org.id, email=f"e2_{uuid.uuid4().hex[:6]}@b.com", password="P!")
    e1_ctx = SecurityContext(user_id=emp1.id, email=emp1.email, role=UserRole.EMPLOYEE, organisation_id=org.id)
    e2_ctx = SecurityContext(user_id=emp2.id, email=emp2.email, role=UserRole.EMPLOYEE, organisation_id=org.id)

    # Employee 1 creates a folder
    f1 = repo.create_folder(e1_ctx, name="Employee1 Folder")

    # Employee 1 can see it
    e1_folders = repo.list_folders(e1_ctx)
    assert any(f.id == f1.id for f in e1_folders)

    # Employee 2 CANNOT see Employee 1's folder
    e2_folders = repo.list_folders(e2_ctx)
    assert not any(f.id == f1.id for f in e2_folders)

    # Client Admin CAN see Employee 1's folder
    ca_folders = repo.list_folders(ca_ctx)
    assert any(f.id == f1.id for f in ca_folders)


# =====================================================================
# INVARIANT 12: Sanitized Physical Storage Paths (UUID Blobs)
# =====================================================================
def test_invariant_12_sanitized_blob_paths(db_session, superadmin_ctx):
    """Invariant 12: Physical storage uses sanitized blob names and contains no path traversal."""
    repo = TenantRepository(db_session)
    org = repo.create_organisation(superadmin_ctx, name=f"Storage Org {uuid.uuid4().hex[:6]}")
    repo.approve_organisation(superadmin_ctx, org.id)
    ca = repo.create_client_admin(superadmin_ctx, org_id=org.id, email=f"admin_{uuid.uuid4().hex[:6]}@s.com", password="P!")
    ctx = SecurityContext(user_id=ca.id, email=ca.email, role=UserRole.CLIENT_ADMIN, organisation_id=org.id)

    malicious_filename = "../../../etc/passwd.txt"
    file_rec, ver_rec = repo.upload_file(sec_ctx=ctx, filename=malicious_filename, content_bytes=b"safe content")

    # Human display name is sanitized
    assert ".." not in file_rec.name
    assert file_rec.name == "passwd.txt"

    # Physical storage path ends with .blob and contains no path traversal
    storage_path = Path(ver_rec.storage_path)
    assert storage_path.suffix == ".blob"
    assert ".." not in str(storage_path)
    assert storage_path.exists()


# =====================================================================
# INVARIANT 13: File Version Calculation Race Protection
# =====================================================================
def test_invariant_13_file_version_coalesce_max(db_session, superadmin_ctx):
    """Invariant 13: Version number increases sequentially from database max, not length of in-memory collection."""
    repo = TenantRepository(db_session)
    org = repo.create_organisation(superadmin_ctx, name=f"Version Org {uuid.uuid4().hex[:6]}")
    repo.approve_organisation(superadmin_ctx, org.id)
    ca = repo.create_client_admin(superadmin_ctx, org_id=org.id, email=f"admin_{uuid.uuid4().hex[:6]}@v.com", password="P!")
    ctx = SecurityContext(user_id=ca.id, email=ca.email, role=UserRole.CLIENT_ADMIN, organisation_id=org.id)

    file_rec, v1 = repo.upload_file(sec_ctx=ctx, filename="Doc.pdf", content_bytes=b"v1")
    assert v1.version_number == 1

    _, v2 = repo.upload_file(sec_ctx=ctx, filename="Doc.pdf", content_bytes=b"v2", existing_file_id=file_rec.id)
    assert v2.version_number == 2

    _, v3 = repo.upload_file(sec_ctx=ctx, filename="Doc.pdf", content_bytes=b"v3", existing_file_id=file_rec.id)
    assert v3.version_number == 3


# =====================================================================
# INVARIANT 14: Organisation Status Lifecycle (PENDING -> 403 Forbidden until APPROVED)
# =====================================================================
def test_invariant_14_organisation_lifecycle_blocks_pending(api_client):
    """Invariant 14: New organisations start PENDING and reject logins with 403 until APPROVED."""
    # 1. Super Admin onboards new organisation
    login_super = api_client.post("/api/auth/login", json={
        "email": settings.SUPERADMIN_EMAIL,
        "password": settings.SUPERADMIN_INITIAL_PASSWORD
    })
    token = login_super.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    org_res = api_client.post("/api/admin/organisations", json={"name": f"PendingBank_{uuid.uuid4().hex[:6]}"}, headers=headers)
    assert org_res.status_code == 200
    org_id = org_res.json()["id"]
    assert org_res.json()["status"] == "PENDING"

    # 2. Provision admin for pending org
    admin_email = f"lead_{uuid.uuid4().hex[:6]}@pendingbank.com"
    api_client.post(
        f"/api/admin/organisations/{org_id}/admins",
        json={"email": admin_email, "password": "PendingPassword2026!"},
        headers=headers
    )

    # 3. User attempts login while PENDING -> HTTP 403 Forbidden
    login_attempt = api_client.post("/api/auth/login", json={"email": admin_email, "password": "PendingPassword2026!"})
    assert login_attempt.status_code == 403

    # 4. Super Admin approves organisation
    appr = api_client.post(f"/api/admin/organisations/{org_id}/approve", headers=headers)
    assert appr.status_code == 200
    assert appr.json()["status"] == "APPROVED"

    # 5. User logs in successfully once APPROVED
    login_success = api_client.post("/api/auth/login", json={"email": admin_email, "password": "PendingPassword2026!"})
    assert login_success.status_code == 200


# =====================================================================
# INVARIANT 15: Background Job Execution (202 Accepted + Job Polling)
# =====================================================================
def test_invariant_15_async_job_execution(api_client):
    """Invariant 15: Submitting background job returns 202 Accepted + job_id, queryable via /api/jobs/{id}."""
    login_super = api_client.post("/api/auth/login", json={
        "email": settings.SUPERADMIN_EMAIL,
        "password": settings.SUPERADMIN_INITIAL_PASSWORD
    })
    token = login_super.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    sample_doc = b"1. Customer submits inquiry.\n2. Support agent verifies account.\n"

    # Submit job
    res = api_client.post(
        "/api/v1/process-graph/jobs",
        files={"file": ("process.txt", io.BytesIO(sample_doc), "text/plain")},
        headers=headers
    )
    assert res.status_code == 202
    data = res.json()
    assert "job_id" in data
    job_id = data["job_id"]
    assert data["job_type"] == "PROCESS_GRAPH"

    # Poll job status
    poll_res = api_client.get(f"/api/jobs/{job_id}", headers=headers)
    assert poll_res.status_code == 200
    poll_data = poll_res.json()
    assert poll_data["job_id"] == job_id
    assert poll_data["status"] in (JobStatus.PENDING.value, JobStatus.RUNNING.value, JobStatus.COMPLETED.value)


# =====================================================================
# INVARIANT 16: START Outgoing Degree Invariant (out-degree >= 1)
# =====================================================================
def test_invariant_16_start_outgoing_degree_invariant():
    """Invariant 16: START event must have out-degree >= 1; out-degree 0 is rejected."""
    registry = SpanRegistry()
    registry.spans_by_id["S001"] = SourceSpan(span_id="S001", chunk_id="c1", source_doc="doc.txt", text="Initiate flow.")

    # 1. Validator flags START_DISCONNECTED on out-degree 0
    from injester.semantic.schemas import GroundedProcessGraph, ProcessEvent, ProcessActivity
    graph_disconnected_start = GroundedProcessGraph(
        process_name="Disconnected Start",
        objective="Verify Start Invariant",
        events=[ProcessEvent(id="START", type="start", label="Start", evidence=["S001"])],
        activities=[ProcessActivity(id="ACT_01", actor_id="ACTOR_EMP", label="Submit", description="", evidence=["S001"])],
        transitions=[]  # 0 outgoing transitions from START
    )
    validator = SemanticGraphValidator(registry)
    is_valid, errors, warnings = validator.validate_semantic_graph(graph_disconnected_start)
    assert not is_valid
    assert any("START_DISCONNECTED" in err for err in errors)

    # 2. Compiler flags REJECTED if START has no outgoing transitions
    canonical = CanonicalProcessModel(
        process_name="Disconnected Start",
        objective="Verify Start",
        schema_version="1.0",
        nodes=[
            SemanticProcessNode(node_id="START", node_type="start_event", label="Start", evidence_spans=["S001"]),
            SemanticProcessNode(node_id="ACT_01", node_type="activity", label="Submit", evidence_spans=["S001"], required_proposition_ids=["P1"]),
        ],
        edges=[]
    )
    compiler = DeterministicGraphCompiler()
    res = compiler.compile(
        document_name="doc.txt",
        canonical_model=canonical,
        verdicts={"P1": LayaVerdict(proposition_id="P1", verdict=GroundingVerdict.SUPPORTED, actor_grounded=True, action_entailed=True, is_verified=True)},
        span_registry=registry
    )
    assert res.defect_register.process_integrity_status == "REJECTED"


# =====================================================================
# INVARIANT 17: End Event Outgoing Degree Invariant (out-degree == 0)
# =====================================================================
def test_invariant_17_end_event_outgoing_degree_rejected():
    """Invariant 17: CanonicalProcessModel and validator reject end_event with out-degree > 0."""
    # 1. CanonicalProcessModel raises ValueError on end_event with outgoing edge
    with pytest.raises(ValueError, match="cannot have outgoing transition"):
        CanonicalProcessModel(
            process_name="Invalid End Event",
            objective="Verify End Event Invariant",
            schema_version="1.0",
            nodes=[
                SemanticProcessNode(node_id="START", node_type="start_event", label="Start", evidence_spans=["S001"]),
                SemanticProcessNode(node_id="END_APPROVED", node_type="end_event", label="Approved", evidence_spans=["S001"]),
                SemanticProcessNode(node_id="ACT_SUBSEQUENT", node_type="activity", label="Followup", evidence_spans=["S001"]),
            ],
            edges=[
                SemanticProcessEdge(edge_id="E1", source_node_id="START", target_node_id="END_APPROVED", evidence_spans=["S001"]),
                SemanticProcessEdge(edge_id="E2", source_node_id="END_APPROVED", target_node_id="ACT_SUBSEQUENT", evidence_spans=["S001"]),
            ]
        )

    # 2. Validator flags INVALID_END_EVENT_TOPOLOGY if AST contains end event with out-degree > 0
    from injester.semantic.schemas import GroundedProcessGraph, ProcessEvent, ProcessActivity, ProcessTransition
    graph_bad_end = GroundedProcessGraph(
        process_name="Bad End",
        objective="Verify Validator",
        events=[
            ProcessEvent(id="START", type="start", label="Start", evidence=[]),
            ProcessEvent(id="END_APPROVED", type="end", label="Approved", evidence=[]),
        ],
        activities=[ProcessActivity(id="ACT_10", actor_id="ACTOR_HR", label="Month-end update", description="", evidence=[])],
        transitions=[
            ProcessTransition(from_id="START", to_id="END_APPROVED"),
            ProcessTransition(from_id="END_APPROVED", to_id="ACT_10"),
        ]
    )
    validator = SemanticGraphValidator()
    is_valid, errors, warnings = validator.validate_semantic_graph(graph_bad_end)
    assert not is_valid
    assert any("INVALID_END_EVENT_TOPOLOGY" in err for err in errors)


# =====================================================================
# INVARIANT 18: Intermediate Event Classification Validity
# =====================================================================
def test_invariant_18_intermediate_event_validity():
    """Invariant 18: Procedural milestones followed by subsequent steps are valid intermediate_event nodes."""
    registry = SpanRegistry()
    registry.spans_by_id["S001"] = SourceSpan(span_id="S001", chunk_id="c1", source_doc="doc.txt", text="Leave request approved; HR updates record.")

    # Canonical model accepts intermediate_event with both incoming and outgoing transitions
    canonical = CanonicalProcessModel(
        process_name="Milestone Process",
        objective="Verify Milestone",
        schema_version="1.0",
        nodes=[
            SemanticProcessNode(node_id="START", node_type="start_event", label="Start", evidence_spans=["S001"]),
            SemanticProcessNode(node_id="EVENT_APPROVED", node_type="intermediate_event", label="Leave Request Approved", evidence_spans=["S001"], required_proposition_ids=["P1"]),
            SemanticProcessNode(node_id="ACT_UPDATE", node_type="activity", label="HR Updates Leave Balance", actor="HR Admin", evidence_spans=["S001"], required_proposition_ids=["P1"]),
            SemanticProcessNode(node_id="END_DONE", node_type="end_event", label="Process Completed", evidence_spans=["S001"]),
        ],
        edges=[
            SemanticProcessEdge(edge_id="E1", source_node_id="START", target_node_id="EVENT_APPROVED", evidence_spans=["S001"]),
            SemanticProcessEdge(edge_id="E2", source_node_id="EVENT_APPROVED", target_node_id="ACT_UPDATE", evidence_spans=["S001"]),
            SemanticProcessEdge(edge_id="E3", source_node_id="ACT_UPDATE", target_node_id="END_DONE", evidence_spans=["S001"]),
        ]
    )
    canonical.validate_graph_invariants()

    compiler = DeterministicGraphCompiler()
    res = compiler.compile(
        document_name="doc.txt",
        canonical_model=canonical,
        verdicts={"P1": LayaVerdict(proposition_id="P1", verdict=GroundingVerdict.SUPPORTED, actor_grounded=True, action_entailed=True, is_verified=True)},
        span_registry=registry
    )

    # Verified AST contains the intermediate event
    event_types = {e.id: e.type for e in res.graph.events}
    assert event_types.get("EVENT_APPROVED") == "intermediate"

    # Validator accepts the resulting AST
    validator = SemanticGraphValidator(registry)
    is_valid, errors, warnings = validator.validate_semantic_graph(res.graph)
    assert is_valid


# =====================================================================
# INVARIANT 19: Gateway Predecessors Rejected -> DEPENDENCY_BLOCKED
# =====================================================================
def test_invariant_19_gateway_predecessors_rejected_dependency_blocked():
    """Invariant 19: When all predecessors of a gateway are rejected, the gateway is quarantined as DEPENDENCY_BLOCKED."""
    registry = SpanRegistry()
    registry.spans_by_id["S001"] = SourceSpan(span_id="S001", chunk_id="c1", source_doc="doc.txt", text="Test flow.")

    canonical = CanonicalProcessModel(
        process_name="Blocked Gateway Process",
        objective="Verify Dependency Block",
        schema_version="1.0",
        nodes=[
            SemanticProcessNode(node_id="START", node_type="start_event", label="Start", evidence_spans=["S001"]),
            SemanticProcessNode(node_id="ACT_MAIN", node_type="activity", label="Main Flow", evidence_spans=["S001"], required_proposition_ids=["P_SUP"]),
            SemanticProcessNode(node_id="ACT_PRE", node_type="activity", label="Predecessor", evidence_spans=["S001"], required_proposition_ids=["P_REJ"]),
            SemanticProcessNode(node_id="GW_01", node_type="decision", label="Check Conditions", evidence_spans=["S001"], required_proposition_ids=["P_SUP"]),
            SemanticProcessNode(node_id="ACT_POST", node_type="activity", label="Downstream Action", evidence_spans=["S001"], required_proposition_ids=["P_SUP"]),
            SemanticProcessNode(node_id="END_MAIN", node_type="end_event", label="End Main", evidence_spans=["S001"]),
        ],
        edges=[
            SemanticProcessEdge(edge_id="E1", source_node_id="START", target_node_id="ACT_MAIN", evidence_spans=["S001"]),
            SemanticProcessEdge(edge_id="E2", source_node_id="ACT_MAIN", target_node_id="END_MAIN", evidence_spans=["S001"]),
            SemanticProcessEdge(edge_id="E3", source_node_id="START", target_node_id="ACT_PRE", evidence_spans=["S001"]),
            SemanticProcessEdge(edge_id="E4", source_node_id="ACT_PRE", target_node_id="GW_01", evidence_spans=["S001"]),
            SemanticProcessEdge(edge_id="E5", source_node_id="GW_01", target_node_id="ACT_POST", relation=ProcessRelationType.BRANCH_IF, condition="Yes", evidence_spans=["S001"]),
        ]
    )

    verdicts = {
        "P_REJ": LayaVerdict(proposition_id="P_REJ", verdict=GroundingVerdict.UNSUPPORTED, actor_grounded=False, action_entailed=False, is_verified=False),
        "P_SUP": LayaVerdict(proposition_id="P_SUP", verdict=GroundingVerdict.SUPPORTED, actor_grounded=True, action_entailed=True, is_verified=True),
    }

    compiler = DeterministicGraphCompiler()
    res = compiler.compile(
        document_name="doc.txt",
        canonical_model=canonical,
        verdicts=verdicts,
        span_registry=registry
    )

    # GW_01 and ACT_POST are not in authoritative AST
    ast_gw_ids = [g.id for g in res.graph.gateways]
    ast_act_ids = [a.id for a in res.graph.activities]
    assert "GW_01" not in ast_gw_ids
    assert "ACT_POST" not in ast_act_ids
    assert "ACT_MAIN" in ast_act_ids

    # Quarantined as DEPENDENCY_BLOCKED in defect register
    defects = res.defect_register.defects
    blocked_props = [d.proposition_id for d in defects if d.defect_category == DefectCategory.DEPENDENCY_BLOCKED]
    assert "GW_01" in blocked_props
    assert "ACT_POST" in blocked_props
    assert res.defect_register.process_integrity_status == "STRUCTURALLY_DEGRADED"


# =====================================================================
# INVARIANT 20: Multi-Incoming Gateway Retains Reachability
# =====================================================================
def test_invariant_20_multi_incoming_gateway_reachability_retention():
    """Invariant 20: A gateway with 1 valid incoming + 1 rejected incoming remains reachable and is NOT quarantined."""
    registry = SpanRegistry()
    registry.spans_by_id["S001"] = SourceSpan(span_id="S001", chunk_id="c1", source_doc="doc.txt", text="Multi-path approval flow.")

    canonical = CanonicalProcessModel(
        process_name="Multi Path Gateway",
        objective="Verify Gateway Retention",
        schema_version="1.0",
        nodes=[
            SemanticProcessNode(node_id="START", node_type="start_event", label="Start", evidence_spans=["S001"]),
            SemanticProcessNode(node_id="ACT_VALID", node_type="activity", label="Valid Step", evidence_spans=["S001"], required_proposition_ids=["P_VALID"]),
            SemanticProcessNode(node_id="ACT_REJ", node_type="activity", label="Rejected Step", evidence_spans=["S001"], required_proposition_ids=["P_REJ"]),
            SemanticProcessNode(node_id="GW_MERGE", node_type="decision", label="Review Merge", evidence_spans=["S001"], required_proposition_ids=["P_VALID"]),
            SemanticProcessNode(node_id="END_DONE", node_type="end_event", label="Done", evidence_spans=["S001"]),
        ],
        edges=[
            SemanticProcessEdge(edge_id="E1", source_node_id="START", target_node_id="ACT_VALID", evidence_spans=["S001"]),
            SemanticProcessEdge(edge_id="E2", source_node_id="START", target_node_id="ACT_REJ", evidence_spans=["S001"]),
            SemanticProcessEdge(edge_id="E3", source_node_id="ACT_VALID", target_node_id="GW_MERGE", evidence_spans=["S001"]),
            SemanticProcessEdge(edge_id="E4", source_node_id="ACT_REJ", target_node_id="GW_MERGE", evidence_spans=["S001"]),
            SemanticProcessEdge(edge_id="E5", source_node_id="GW_MERGE", target_node_id="END_DONE", relation=ProcessRelationType.BRANCH_IF, condition="Ok", evidence_spans=["S001"]),
        ]
    )

    verdicts = {
        "P_VALID": LayaVerdict(proposition_id="P_VALID", verdict=GroundingVerdict.SUPPORTED, actor_grounded=True, action_entailed=True, is_verified=True),
        "P_REJ": LayaVerdict(proposition_id="P_REJ", verdict=GroundingVerdict.UNSUPPORTED, actor_grounded=False, action_entailed=False, is_verified=False),
    }

    compiler = DeterministicGraphCompiler()
    res = compiler.compile(
        document_name="doc.txt",
        canonical_model=canonical,
        verdicts=verdicts,
        span_registry=registry
    )

    # GW_MERGE remains reachable via ACT_VALID and is compiled into AST
    ast_gw_ids = [g.id for g in res.graph.gateways]
    assert "GW_MERGE" in ast_gw_ids

    # GW_MERGE is NOT quarantined as DEPENDENCY_BLOCKED
    blocked_props = [d.proposition_id for d in res.defect_register.defects if d.defect_category == DefectCategory.DEPENDENCY_BLOCKED]
    assert "GW_MERGE" not in blocked_props


# =====================================================================
# INVARIANT 21: Independent Component Separation & Evidence Invariant
# =====================================================================
def test_invariant_21_independent_component_evidence_invariant():
    """Invariant 21: Independent components require valid independence evidence; retained without START reachability."""
    registry = SpanRegistry()
    registry.spans_by_id["S_IND"] = SourceSpan(span_id="S_IND", chunk_id="c1", source_doc="doc.txt", text="Annual audit is conducted independently.")

    canonical = CanonicalProcessModel(
        process_name="Independent Process",
        objective="Verify Independent Component",
        schema_version="1.0",
        nodes=[
            SemanticProcessNode(node_id="START", node_type="start_event", label="Start", evidence_spans=["S_IND"]),
            SemanticProcessNode(node_id="ACT_MAIN", node_type="activity", label="Main Step", evidence_spans=["S_IND"], required_proposition_ids=["P1"]),
            # Valid independent component
            SemanticProcessNode(
                node_id="ACT_AUDIT",
                node_type="activity",
                label="Periodic Audit",
                evidence_spans=["S_IND"],
                is_independent=True,
                independence_evidence_spans=["S_IND"],
                required_proposition_ids=["P1"]
            ),
        ],
        edges=[
            SemanticProcessEdge(edge_id="E1", source_node_id="START", target_node_id="ACT_MAIN", evidence_spans=["S_IND"]),
        ]
    )

    compiler = DeterministicGraphCompiler()
    res = compiler.compile(
        document_name="doc.txt",
        canonical_model=canonical,
        verdicts={"P1": LayaVerdict(proposition_id="P1", verdict=GroundingVerdict.SUPPORTED, actor_grounded=True, action_entailed=True, is_verified=True)},
        span_registry=registry
    )

    # ACT_AUDIT is accepted into AST activities despite zero edges to START
    ast_act_ids = [a.id for a in res.graph.activities]
    assert "ACT_AUDIT" in ast_act_ids

    # ACT_AUDIT is NOT quarantined as DEPENDENCY_BLOCKED
    blocked_props = [d.proposition_id for d in res.defect_register.defects if d.defect_category == DefectCategory.DEPENDENCY_BLOCKED]
    assert "ACT_AUDIT" not in blocked_props


# =====================================================================
# INVARIANT 22: Valid Cyclic Loop Traversal
# =====================================================================
def test_invariant_22_valid_loop_does_not_fail_reachability():
    """Invariant 22: Valid rework/retry loops (LOOP_BACK) do not cause infinite recursion and are fully reached."""
    registry = SpanRegistry()
    registry.spans_by_id["S001"] = SourceSpan(span_id="S001", chunk_id="c1", source_doc="doc.txt", text="Submit, review, revise loop.")

    canonical = CanonicalProcessModel(
        process_name="Loop Process",
        objective="Verify Loop Reachability",
        schema_version="1.0",
        nodes=[
            SemanticProcessNode(node_id="START", node_type="start_event", label="Start", evidence_spans=["S001"]),
            SemanticProcessNode(node_id="ACT_SUBMIT", node_type="activity", label="Submit", evidence_spans=["S001"], required_proposition_ids=["P1"]),
            SemanticProcessNode(node_id="GW_CHECK", node_type="decision", label="Approved?", evidence_spans=["S001"], required_proposition_ids=["P1"]),
            SemanticProcessNode(node_id="END_DONE", node_type="end_event", label="Done", evidence_spans=["S001"]),
        ],
        edges=[
            SemanticProcessEdge(edge_id="E1", source_node_id="START", target_node_id="ACT_SUBMIT", evidence_spans=["S001"]),
            SemanticProcessEdge(edge_id="E2", source_node_id="ACT_SUBMIT", target_node_id="GW_CHECK", evidence_spans=["S001"]),
            SemanticProcessEdge(edge_id="E3", source_node_id="GW_CHECK", target_node_id="ACT_SUBMIT", relation=ProcessRelationType.LOOP_BACK, condition="Needs Correction", evidence_spans=["S001"]),
            SemanticProcessEdge(edge_id="E4", source_node_id="GW_CHECK", target_node_id="END_DONE", relation=ProcessRelationType.BRANCH_IF, condition="Approved", evidence_spans=["S001"]),
        ]
    )

    compiler = DeterministicGraphCompiler()
    res = compiler.compile(
        document_name="doc.txt",
        canonical_model=canonical,
        verdicts={"P1": LayaVerdict(proposition_id="P1", verdict=GroundingVerdict.SUPPORTED, actor_grounded=True, action_entailed=True, is_verified=True)},
        span_registry=registry
    )

    # All nodes reached and verified
    act_ids = [a.id for a in res.graph.activities]
    assert "ACT_SUBMIT" in act_ids
    assert len(res.graph.gateways) == 1
    # Loop transition preserved
    loop_trans = [t for t in res.graph.transitions if t.is_loop]
    assert len(loop_trans) == 1
    assert loop_trans[0].from_id == "GW_CHECK"
    assert loop_trans[0].to_id == "ACT_SUBMIT"


# =====================================================================
# INVARIANT 23: Pure Structural Validator (No NLP Text Inspection)
# =====================================================================
def test_invariant_23_validator_actor_contradiction_purity():
    """Invariant 23: Validator does not inspect natural-language text for actor contradictions; leaves semantics to reasoner."""
    registry = SpanRegistry()
    registry.spans_by_id["S001"] = SourceSpan(span_id="S001", chunk_id="c1", source_doc="doc.txt", text="System updates the leave calendar.")

    # Even if label text mentions 'System' while actor is 'Reporting Manager', validator only checks structural topology
    from injester.semantic.schemas import GroundedProcessGraph, ProcessActivity, ProcessActor
    graph = GroundedProcessGraph(
        process_name="Actor Test",
        objective="Verify Structural Purity",
        actors=[ProcessActor(id="ACTOR_RM", name="Reporting Manager", evidence=["S001"])],
        activities=[
            ProcessActivity(id="ACT_01", actor_id="ACTOR_RM", label="System updates the leave calendar", description="", evidence=["S001"])
        ],
        transitions=[]
    )
    validator = SemanticGraphValidator(registry)
    is_valid, errors, warnings = validator.validate_semantic_graph(graph)

    # Structural validator passes; does not reject based on text heuristic
    assert is_valid
    # Confirm validator code does not contain keyword regexes for 'system' vs human actors
    src = inspect.getsource(SemanticGraphValidator)
    assert "system" not in src.lower() or "span_registry" in src.lower()


# =====================================================================
# INVARIANT 24: Timeout Escalation Representation
# =====================================================================
def test_invariant_24_timeout_escalation_representation():
    """Invariant 24: SLA timeouts model as ESCALATES_TO with trigger_type='timeout' and render as exception transitions."""
    registry = SpanRegistry()
    registry.spans_by_id["S001"] = SourceSpan(span_id="S001", chunk_id="c1", source_doc="doc.txt", text="If no response in 3 business days, escalate.")

    canonical = CanonicalProcessModel(
        process_name="Timeout Process",
        objective="Verify Timeout Escalation",
        schema_version="1.0",
        nodes=[
            SemanticProcessNode(node_id="START", node_type="start_event", label="Start", evidence_spans=["S001"]),
            SemanticProcessNode(node_id="ACT_REVIEW", node_type="activity", label="Manager Review", actor="Manager", evidence_spans=["S001"], required_proposition_ids=["P1"]),
            SemanticProcessNode(node_id="ACT_ESCALATE", node_type="activity", label="Escalate to Dept Head", actor="Dept Head", evidence_spans=["S001"], required_proposition_ids=["P1"]),
        ],
        edges=[
            SemanticProcessEdge(edge_id="E1", source_node_id="START", target_node_id="ACT_REVIEW", evidence_spans=["S001"]),
            SemanticProcessEdge(
                edge_id="E2",
                source_node_id="ACT_REVIEW",
                target_node_id="ACT_ESCALATE",
                relation=ProcessRelationType.ESCALATES_TO,
                trigger_type="timeout",
                condition="3 business days",
                evidence_spans=["S001"]
            ),
        ]
    )

    compiler = DeterministicGraphCompiler()
    res = compiler.compile(
        document_name="doc.txt",
        canonical_model=canonical,
        verdicts={"P1": LayaVerdict(proposition_id="P1", verdict=GroundingVerdict.SUPPORTED, actor_grounded=True, action_entailed=True, is_verified=True)},
        span_registry=registry
    )

    # Transition has is_exception=True
    exc_transitions = [t for t in res.graph.transitions if t.is_exception]
    assert len(exc_transitions) == 1
    assert "Timeout" in exc_transitions[0].label

    # Mermaid render contains dashed arrow -.->
    mmd = render_flowchart_mermaid(res.graph)
    assert "-.->" in mmd
    assert "ACT_REVIEW -.->|Timeout: 3 business days| ACT_ESCALATE" in mmd


# =====================================================================
# INVARIANT 25: Strict Decoupled Accounting Identity
# =====================================================================
def test_invariant_25_decoupled_accounting_identity():
    """Invariant 25: Proposition partition identity (supported + uncertain + unsupported + missing == extracted) holds strictly."""
    registry = SpanRegistry()
    registry.spans_by_id["S001"] = SourceSpan(span_id="S001", chunk_id="c1", source_doc="doc.txt", text="Multiple propositions test.")

    propositions = [
        AtomicProposition(id="P1", actor_claim="A", action_verb="acts", target_object="T", modality=ModalityType.MANDATORY, epistemic_status=EpistemicStatus.CONFIRMED, evidence_spans=["S001"]),
        AtomicProposition(id="P2", actor_claim="B", action_verb="acts", target_object="T", modality=ModalityType.MANDATORY, epistemic_status=EpistemicStatus.CONFIRMED, evidence_spans=["S001"]),
        AtomicProposition(id="P3", actor_claim="C", action_verb="acts", target_object="T", modality=ModalityType.MANDATORY, epistemic_status=EpistemicStatus.CONFIRMED, evidence_spans=["S001"]),
        AtomicProposition(id="P4", actor_claim="D", action_verb="acts", target_object="T", modality=ModalityType.MANDATORY, epistemic_status=EpistemicStatus.CONFIRMED, evidence_spans=["S001"]),
    ]

    verdicts = {
        "P1": LayaVerdict(proposition_id="P1", verdict=GroundingVerdict.SUPPORTED, actor_grounded=True, action_entailed=True, is_verified=True),
        "P2": LayaVerdict(proposition_id="P2", verdict=GroundingVerdict.UNCERTAIN, actor_grounded=True, action_entailed=False, is_verified=False),
        "P3": LayaVerdict(proposition_id="P3", verdict=GroundingVerdict.UNSUPPORTED, actor_grounded=False, action_entailed=False, is_verified=False),
        # P4 has no verdict -> missing
    }

    canonical = CanonicalProcessModel(
        process_name="Accounting Process",
        objective="Verify Accounting",
        schema_version="1.0",
        nodes=[
            SemanticProcessNode(node_id="ACT_01", node_type="activity", label="Act", evidence_spans=["S001"], required_proposition_ids=["P1"]),
        ],
        edges=[]
    )

    compiler = DeterministicGraphCompiler()
    res = compiler.compile(
        document_name="doc.txt",
        canonical_model=canonical,
        propositions=propositions,
        verdicts=verdicts,
        span_registry=registry
    )

    ar = res.defect_register
    # Strict partition identity
    assert ar.total_propositions_extracted == 4
    assert ar.propositions_supported == 1
    assert ar.propositions_uncertain == 1
    assert ar.propositions_unsupported == 1
    assert ar.propositions_missing == 1
    assert (ar.propositions_supported + ar.propositions_uncertain + ar.propositions_unsupported + ar.propositions_missing) == ar.total_propositions_extracted

    # Node counts are separate from propositions
    assert ar.total_nodes_generated == 1
    assert ar.total_nodes_verified == 1
    assert ar.total_nodes_quarantined == 0


# =====================================================================
# INVARIANT 26: Renderer Fails Closed on Invalid End Event
# =====================================================================
def test_invariant_26_renderer_fails_closed_on_invalid_end_event():
    """Invariant 26: render_bpmn_20_xml raises ValueError if endEvent has outgoing flows (never silently converting)."""
    from injester.semantic.schemas import GroundedProcessGraph, ProcessEvent, ProcessActivity, ProcessTransition
    graph_invalid_end = GroundedProcessGraph(
        process_name="Terminal Purity Failure",
        objective="Verify Fail Closed",
        events=[
            ProcessEvent(id="START", type="start", label="Start", evidence=[]),
            ProcessEvent(id="END_ILLEGAL", type="end", label="Premature End", evidence=[]),
        ],
        activities=[
            ProcessActivity(id="ACT_AFTER", actor_id="ACTOR_UNASSIGNED", label="After End", description="", evidence=[])
        ],
        transitions=[
            ProcessTransition(from_id="START", to_id="END_ILLEGAL"),
            ProcessTransition(from_id="END_ILLEGAL", to_id="ACT_AFTER"),
        ]
    )

    # Must raise ValueError and fail closed
    with pytest.raises(ValueError, match="Projections fail closed on invalid terminal topology"):
        render_bpmn_20_xml(graph_invalid_end)
