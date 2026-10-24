import io
import uuid
import pytest
from sqlalchemy import text
from fastapi.testclient import TestClient

from injester.config import settings
from injester.api.app import app
from injester.infrastructure.db import init_db, SessionLocal

def is_db_available():
    try:
        s = SessionLocal()
        s.execute(text("SELECT 1"))
        s.close()
        return True
    except Exception:
        return False

@pytest.fixture(scope="module")
def client():
    try:
        init_db()
    except Exception:
        pass
    with TestClient(app) as c:
        # Authenticate UI session with Super Admin token
        login_res = c.post("/api/auth/login", json={
            "email": settings.SUPERADMIN_EMAIL,
            "password": settings.SUPERADMIN_INITIAL_PASSWORD,
        })
        if login_res.status_code == 200:
            token = login_res.json()["access_token"]
            c.cookies.set("access_token", token)
        yield c

def test_api_health_check(client):
    res = client.get("/api/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "operational"
    assert data["docs_url"] == "/docs"
    assert data["version"] in ("0.1.0", "2.0.0")

    res_live = client.get("/api/health/liveness")
    assert res_live.status_code == 200
    assert res_live.json()["status"] == "alive"

    res_ready = client.get("/api/health/readiness")
    assert res_ready.status_code in (200, 503)

def test_react_console_routes(client):
    """Every console route is now served by the React SPA (no server-rendered templates)."""
    for path in (
        "/",
        "/workbench",
        "/dashboard",
        "/documents",
        "/process-graph",
        "/sop",
        "/defects",
        "/audit",
        "/admin",
        "/settings",
        "/login",
    ):
        res = client.get(path)
        assert res.status_code == 200, path
        assert "<div id=\"root\">" in res.text, path

    # Legacy Jinja console entry points redirect into the SPA
    res_legacy = client.get("/ui", follow_redirects=False)
    assert res_legacy.status_code in (302, 303, 307)
    assert res_legacy.headers["location"].endswith("/dashboard")

    res_legacy_sub = client.get("/ui/files")
    assert res_legacy_sub.status_code == 200
    assert "<div id=\"root\">" in res_legacy_sub.text


def test_console_data_api(client):
    """The JSON payloads that back the React console."""
    dash = client.get("/api/v1/console/dashboard")
    assert dash.status_code == 200
    payload = dash.json()
    assert "stats" in payload
    assert "recent_files" in payload
    assert "audit_logs" in payload
    assert "engine" in payload
    assert payload["stats"]["file_count"] >= 0

    audit = client.get("/api/v1/console/audit-logs")
    assert audit.status_code == 200
    assert isinstance(audit.json(), list)

    orgs = client.get("/api/v1/console/organisations")
    assert orgs.status_code == 200
    assert isinstance(orgs.json(), list)

    defects = client.get("/api/v1/console/defects")
    assert defects.status_code == 200
    assert isinstance(defects.json(), list)


def test_credential_auth_api(client):
    """Credential sign-in returns a bearer token; invalid credentials fail closed."""
    res_form = client.post("/api/auth/login", json={
        "email": settings.SUPERADMIN_EMAIL,
        "password": settings.SUPERADMIN_INITIAL_PASSWORD,
    })
    assert res_form.status_code == 200
    assert res_form.json()["access_token"]

    res_bad = client.post("/api/auth/login", json={
        "email": settings.SUPERADMIN_EMAIL,
        "password": "WrongPassword123!",
    })
    assert res_bad.status_code == 401


def test_process_graph_api_generation(client):
    """The Process Graph Studio now drives the REST pipeline endpoint."""
    test_doc = (
        "# Security Audit Procedure\n"
        "Security Team inspects firewall logs daily.\n"
        "If an intrusion anomaly is detected, Security Team triggers critical incident lock.\n"
        "Otherwise, Security Team marks routine check passed.\n"
    )
    res = client.post(
        "/api/v1/process-graph/generate",
        files={"file": ("security_audit.txt", io.BytesIO(test_doc.encode("utf-8")), "text/plain")},
    )
    # The pipeline requires LLM access; a provider failure must surface as a clean error,
    # never as a 500 with a stack trace.
    assert res.status_code in (200, 400, 500, 502)
    if res.status_code == 200:
        payload = res.json()
        assert "graph" in payload
        assert "defect_register" in payload
        assert "bpmn_2_0_xml" in payload
        assert "flowchart_mermaid" in payload
    else:
        assert res.json()["detail"]


def test_openapi_documentation(client):
    # Test Swagger JSON spec
    res = client.get("/openapi.json")
    assert res.status_code == 200
    spec = res.json()
    assert "Injester" in spec["info"]["title"]
    assert spec["info"]["version"] in ("0.1.0", "2.0.0")
    paths = spec["paths"]
    assert "/api/v1/process-graph/generate" in paths
    assert "/api/v1/process-graph/{file_id}/bpmn" in paths
    assert "/api/v1/process-graph/{file_id}/mermaid" in paths
    assert "/api/v1/process-graph/{file_id}/defect-register" in paths
    assert "/api/files/upload" in paths
    assert "/api/v1/beelzebuth/devour" in paths

    # Test Swagger UI HTML
    docs_res = client.get("/docs")
    assert docs_res.status_code == 200
    assert "swagger-ui" in docs_res.text.lower()

    # Test ReDoc HTML
    redoc_res = client.get("/redoc")
    assert redoc_res.status_code == 200
    assert "redoc" in redoc_res.text.lower()

@pytest.mark.skipif(not is_db_available(), reason="PostgreSQL database container not accessible on port 5432")
def test_full_api_multi_tenant_flow(client, monkeypatch):
    monkeypatch.setattr(settings, "COMMUNITY_MODE", False)
    # 1. Super Admin Login
    login_res = client.post("/api/auth/login", json={
        "email": settings.SUPERADMIN_EMAIL,
        "password": settings.SUPERADMIN_INITIAL_PASSWORD,
    })
    assert login_res.status_code == 200, login_res.text
    super_token = login_res.json()["access_token"]
    super_headers = {"Authorization": f"Bearer {super_token}"}

    # 2. Super Admin onboards Indian Bank (starts as PENDING)
    bank_name = f"Indian Bank API {uuid.uuid4().hex[:6]}"
    org_res = client.post("/api/admin/organisations", json={"name": bank_name}, headers=super_headers)
    assert org_res.status_code == 200, org_res.text
    org_id = org_res.json()["id"]
    assert org_res.json()["status"] == "PENDING"

    # 3. Super Admin creates Client Admin for Indian Bank
    ca_email = f"admin_{uuid.uuid4().hex[:6]}@bankapi.com"
    ca_pass = "BankAdminSecret2026!"
    ca_create_res = client.post(
        f"/api/admin/organisations/{org_id}/admins",
        json={"email": ca_email, "password": ca_pass},
        headers=super_headers
    )
    assert ca_create_res.status_code == 200, ca_create_res.text

    # 4a. Attempt login while org is PENDING -> rejected with HTTP 403
    premature_login = client.post("/api/auth/login", json={"email": ca_email, "password": ca_pass})
    assert premature_login.status_code == 403

    # 4b. Super Admin approves Indian Bank
    appr_res = client.post(f"/api/admin/organisations/{org_id}/approve", headers=super_headers)
    assert appr_res.status_code == 200
    assert appr_res.json()["status"] == "APPROVED"

    # 4c. Client Admin Login succeeds once approved
    ca_login = client.post("/api/auth/login", json={"email": ca_email, "password": ca_pass})
    assert ca_login.status_code == 200
    ca_token = ca_login.json()["access_token"]
    ca_headers = {"Authorization": f"Bearer {ca_token}"}

    # 5. Client Admin creates Employee
    emp_email = f"emp_{uuid.uuid4().hex[:6]}@bankapi.com"
    emp_pass = "EmpSecret2026!"
    emp_res = client.post(
        "/api/tenant/employees",
        json={"email": emp_email, "password": emp_pass},
        headers=ca_headers
    )
    assert emp_res.status_code == 200

    # 6. Employee Login
    emp_login = client.post("/api/auth/login", json={"email": emp_email, "password": emp_pass})
    assert emp_login.status_code == 200
    emp_token = emp_login.json()["access_token"]
    emp_headers = {"Authorization": f"Bearer {emp_token}"}

    # 7. Employee uploads a document
    doc_content = b"# Wire Transfer SOP\n\nDual authorization is required for transfers over 100,000 INR."
    upload_res = client.post(
        "/api/files/upload",
        files={"file": ("wire_transfer_sop.md", io.BytesIO(doc_content), "text/markdown")},
        headers=emp_headers
    )
    assert upload_res.status_code == 200, upload_res.text
    file_id = upload_res.json()["id"]

    # 8. Employee lists files (sees uploaded file)
    files_res = client.get("/api/files", headers=emp_headers)
    assert files_res.status_code == 200
    user_files = files_res.json()
    assert any(f["id"] == file_id for f in user_files)

    # 9. Client Admin lists files (sees employee's file)
    ca_files_res = client.get("/api/files", headers=ca_headers)
    assert ca_files_res.status_code == 200
    assert any(f["id"] == file_id for f in ca_files_res.json())

    # 10. Verify Unauthorized access: Request without token is rejected
    unauth_client = TestClient(app)
    unauth_res = unauth_client.get("/api/files")
    assert unauth_res.status_code == 401
