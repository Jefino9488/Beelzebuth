import time
from fastapi.testclient import TestClient
from injester.api.app import app

client = TestClient(app)

def test_web_health():
    res = client.get("/api/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "operational"

def test_web_spa_root():
    res = client.get("/")
    assert res.status_code == 200
    assert "<!doctype html>" in res.text or "<html" in res.text

def test_web_files_list():
    res = client.get("/api/files")
    assert res.status_code == 200
    assert isinstance(res.json(), list)

def test_web_beelzebuth_samples():
    res = client.get("/api/v1/beelzebuth/samples")
    assert res.status_code == 200
    data = res.json()
    assert isinstance(data, list)
    assert len(data) > 0

def test_web_beelzebuth_health():
    res = client.get("/api/v1/beelzebuth/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "operational"

def test_login_route_served_by_spa():
    res = client.get("/login", follow_redirects=False)
    # The login screen is now a client-side route served by the React SPA.
    assert res.status_code == 200
    assert "<div id=\"root\">" in res.text


def test_legacy_ui_redirects_to_dashboard():
    res = client.get("/ui", follow_redirects=False)
    assert res.status_code in (302, 303, 307)
    assert res.headers["location"].endswith("/dashboard")

def test_web_settings_api():
    # GET settings
    res = client.get("/api/v1/settings")
    assert res.status_code == 200
    data = res.json()
    assert "model_name" in data
    assert "openai_base_url" in data
    assert "presets" in data

    # POST settings
    res2 = client.post("/api/v1/settings", json={
        "preset": "ollama",
        "base_url": "http://localhost:11434/v1",
        "model_name": "qwen2.5:7b-ctx16k",
    })
    assert res2.status_code == 200
    assert res2.json()["status"] == "success"

def test_web_beelzebuth_devour(monkeypatch):
    from unittest.mock import MagicMock
    from injester.semantic.schemas import (
        DualOutputResult, GroundedProcessGraph, AmbiguityRegister,
        ProcessActivity, ProcessGateway, ProcessEvent, ProcessTransition,
        ProcessActor, DefectRecord, DefectCategory, ModalityType
    )

    fake_graph = GroundedProcessGraph(
        process_name="Test Flow",
        objective="Verify devour output schema",
        actors=[ProcessActor(id="ACTOR_01", name="Operator")],
        activities=[
            ProcessActivity(id="ACT_01", actor_id="ACTOR_01", label="Step 1", description="Do something", evidence=["S001"])
        ],
        gateways=[
            ProcessGateway(id="GW_01", question="Is valid?", gateway_type="exclusive", evidence=["S002"], actor_id="ACTOR_01")
        ],
        events=[
            ProcessEvent(id="START", type="start", label="Start Process", evidence=["S001"])
        ],
        transitions=[
            ProcessTransition(id="TR_01", from_id="START", to_id="ACT_01", evidence=["S001"])
        ]
    )
    fake_defects = AmbiguityRegister(
        document_name="test.txt",
        defects=[
            DefectRecord(
                proposition_id="P_01",
                evidence_spans=["S001"],
                defect_category=DefectCategory.UNVERIFIED_CLAIM,
                claimed_statement="Ungrounded assertion",
                evidence_text="Source snippet",
                rationale="No proof",
                confidence=0.3
            )
        ]
    )
    fake_result = DualOutputResult(
        graph=fake_graph,
        defect_register=fake_defects,
        sop_markdown="# Process Digest: Test Flow\n\nVerified steps.",
    )

    monkeypatch.setattr(
        "injester.semantic.pipeline.EvidenceFirstSemanticPipeline.process_document",
        lambda *args, **kwargs: fake_result
    )

    res = client.post(
        "/api/v1/beelzebuth/devour",
        files={"file": ("test.txt", b"This is a test document text.", "text/plain")}
    )
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["filename"] == "test.txt"
    assert "process_graph" in data
    assert len(data["process_graph"]["nodes"]) == 3  # activity, gateway, event
    assert data["process_graph"]["nodes"][0]["role"] == "Operator"
    assert len(data["defects"]) == 1
    assert data["defects"][0]["id"] == "P_01"
    assert "sop_markdown" in data

def test_web_beelzebuth_devour_general_document(monkeypatch):
    from injester.semantic.schemas import DualOutputResult, GroundedProcessGraph, AmbiguityRegister
    from injester.ingestion.schema import NormalizedElement, ProvenanceMetadata

    # Simulate a resume / general document with 0 procedural activities
    empty_graph = GroundedProcessGraph(
        process_name="Software Engineer Resume",
        objective="General Profile",
        activities=[],
        gateways=[],
        events=[],
        transitions=[]
    )
    empty_defects = AmbiguityRegister(
        document_name="resume.pdf",
        defects=[]
    )
    fake_elements = [
        NormalizedElement(
            element_id="el_1",
            text="John Doe - AI Engineer",
            element_type="Title",
            metadata=ProvenanceMetadata(document_id="doc1", filename="resume.pdf", tenant_id="local", section_path=["John Doe - AI Engineer"])
        ),
        NormalizedElement(
            element_id="el_2",
            text="Experience",
            element_type="Title",
            metadata=ProvenanceMetadata(document_id="doc1", filename="resume.pdf", tenant_id="local", section_path=["Experience"])
        ),
        NormalizedElement(
            element_id="el_3",
            text="Developed an Agentic AI financial platform using FastAPI, LangChain, and React.",
            element_type="ListItem",
            metadata=ProvenanceMetadata(document_id="doc1", filename="resume.pdf", tenant_id="local", section_path=["Experience"])
        ),
    ]

    fake_result = DualOutputResult(
        graph=empty_graph,
        defect_register=empty_defects,
        elements=fake_elements,
    )

    monkeypatch.setattr(
        "injester.semantic.pipeline.EvidenceFirstSemanticPipeline.process_document",
        lambda *args, **kwargs: fake_result
    )

    res = client.post(
        "/api/v1/beelzebuth/devour",
        files={"file": ("resume.pdf", b"Fake PDF binary content", "application/pdf")}
    )
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["filename"] == "resume.pdf"
    
    # Must contain real digital markdown of the resume
    assert "John Doe - AI Engineer" in data["sop_markdown"]
    assert "Developed an Agentic AI financial platform" in data["sop_markdown"]
    assert "Developed an Agentic AI financial platform" in data["raw_content"]
    
    # General documents must synthesize structural diagram nodes
    assert len(data["process_graph"]["nodes"]) >= 2
    assert "graph TD" in data["process_graph"]["mermaid_code"]
    
    # Defects must be clean (0 defects)
    assert len(data["defects"]) == 0


def test_web_beelzebuth_fast_devour_real_document():
    """Verifies unmocked, real document digestion runs in ~1s without slow LLM calls."""
    doc_text = (
        "# Security Incident Response Policy\n\n"
        "## Overview\n"
        "All security incidents must be reported to the IT Security Team within 1 hour.\n\n"
        "## Containment Protocol\n"
        "The on-call incident commander isolates compromised hosts immediately.\n"
    )

    t0 = time.time()
    res = client.post(
        "/api/v1/beelzebuth/devour",
        files={"file": ("incident_policy.md", doc_text.encode("utf-8"), "text/markdown")}
    )
    latency = time.time() - t0

    assert res.status_code == 200, res.text
    data = res.json()
    assert latency < 5.0  # Must be fast (<5s even under test overhead)
    assert data["filename"] == "incident_policy.md"
    assert "digital_markdown" in data
    assert "Security Incident Response Policy" in data["digital_markdown"]
    assert "[S001]" in data["digital_markdown"]
    assert "Citation & Source Provenance Index" in data["digital_markdown"]
    assert len(data["defects"]) == 0
    assert len(data["spans"]) >= 2


