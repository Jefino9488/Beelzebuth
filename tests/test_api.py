import io
import uuid
import pytest
from fastapi.testclient import TestClient

from injester.config import settings
from injester.api.app import app
from injester.infrastructure.db import init_db

@pytest.fixture(scope="module")
def client():
    init_db()
    with TestClient(app) as c:
        yield c

def test_api_health_check(client):
    res = client.get("/api/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "operational"
    assert data["docs_url"] == "/docs"

def test_jinja2_ui_pages(client):
    # Test dashboard
    res_dash = client.get("/ui")
    assert res_dash.status_code == 200
    assert "Pipeline Dashboard" in res_dash.text
    assert "⚡ Injester" in res_dash.text

    # Test files view
    res_files = client.get("/ui/files")
    assert res_files.status_code == 200
    assert "Document Ingestion & File Explorer" in res_files.text

    # Test SOP workbench
    res_sop = client.get("/ui/sop")
    assert res_sop.status_code == 200
    assert "Grounded SOP Generation Workbench" in res_sop.text

    # Test Admin view
    res_admin = client.get("/ui/admin")
    assert res_admin.status_code == 200
    assert "Tenants & Identity Administration" in res_admin.text

def test_full_api_multi_tenant_flow(client):
    # 1. Super Admin Login
    login_res = client.post("/api/auth/login", json={
        "email": settings.SUPERADMIN_EMAIL,
        "password": settings.SUPERADMIN_INITIAL_PASSWORD,
    })
    assert login_res.status_code == 200, login_res.text
    super_token = login_res.json()["access_token"]
    super_headers = {"Authorization": f"Bearer {super_token}"}

    # 2. Super Admin onboards Indian Bank
    bank_name = f"Indian Bank API {uuid.uuid4().hex[:6]}"
    org_res = client.post("/api/admin/organisations", json={"name": bank_name}, headers=super_headers)
    assert org_res.status_code == 200, org_res.text
    org_id = org_res.json()["id"]

    # 3. Super Admin creates Client Admin for Indian Bank
    ca_email = f"admin_{uuid.uuid4().hex[:6]}@bankapi.com"
    ca_pass = "BankAdminSecret2026!"
    ca_create_res = client.post(
        f"/api/admin/organisations/{org_id}/admins",
        json={"email": ca_email, "password": ca_pass},
        headers=super_headers
    )
    assert ca_create_res.status_code == 200, ca_create_res.text

    # 4. Client Admin Login
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
    unauth_res = client.get("/api/files")
    assert unauth_res.status_code == 401
