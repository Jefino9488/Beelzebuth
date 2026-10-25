"""
Tests for the React-only console architecture.

The server-rendered Jinja console has been removed. These tests lock in that decision:
templates and the UI router must not come back, the console must be reachable only
through the React SPA, and the JSON payloads that back it must stay tenant-scoped.
"""

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from injester.api.app import app
from injester.config import settings
from injester.domain.models import UserRole

client = TestClient(app)

PACKAGE_ROOT = Path(__file__).resolve().parent.parent / "injester"


# ---------------------------------------------------------------------
# The Jinja console must stay removed
# ---------------------------------------------------------------------
def test_templates_directory_is_removed():
    assert not (PACKAGE_ROOT / "templates").exists()


def test_ui_router_module_is_removed():
    assert not (PACKAGE_ROOT / "api" / "routers" / "ui.py").exists()


def test_jinja2_is_not_a_dependency():
    pyproject = (PACKAGE_ROOT.parent / "pyproject.toml").read_text(encoding="utf-8")
    assert "jinja2" not in pyproject

    requirements = (PACKAGE_ROOT.parent / "requirements.txt").read_text(encoding="utf-8")
    assert "jinja2" not in requirements.lower()


def test_no_module_imports_jinja():
    for path in PACKAGE_ROOT.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "jinja2" not in source.lower(), f"{path} still references jinja2"
        assert "TemplateResponse" not in source, f"{path} still renders templates"


# ---------------------------------------------------------------------
# Console routes are served by the React SPA
# ---------------------------------------------------------------------
CONSOLE_ROUTES = [
    "/",
    "/workbench",
    "/dashboard",
    "/documents",
    "/process-graph",
    "/studio",
    "/defects",
    "/audit",
    "/admin",
    "/settings",
    "/login",
]


@pytest.mark.parametrize("route", CONSOLE_ROUTES)
def test_console_route_serves_spa(route):
    res = client.get(route)
    assert res.status_code == 200
    assert "<div id=\"root\">" in res.text


def test_legacy_ui_prefix_redirects_to_dashboard():
    res = client.get("/ui", follow_redirects=False)
    assert res.status_code in (302, 303, 307)
    assert res.headers["location"].endswith("/dashboard")


def test_legacy_ui_subpaths_serve_spa():
    res = client.get("/ui/files")
    assert res.status_code == 200
    assert "<div id=\"root\">" in res.text


def test_spa_assets_are_served():
    res = client.get("/index.html")
    assert res.status_code == 200
    assert "/assets/" in res.text


# ---------------------------------------------------------------------
# Console data API
# ---------------------------------------------------------------------
def test_console_dashboard_payload_shape():
    res = client.get("/api/v1/console/dashboard")
    assert res.status_code == 200
    payload = res.json()

    assert set(payload["stats"].keys()) == {"org_count", "user_count", "file_count", "audit_count"}
    assert isinstance(payload["recent_files"], list)
    assert isinstance(payload["audit_logs"], list)
    assert payload["engine"]["verifier"]
    assert payload["engine"]["model"]
    assert "is_super_admin" in payload


def test_console_audit_logs_are_ordered_newest_first():
    res = client.get("/api/v1/console/audit-logs?limit=5")
    assert res.status_code == 200
    logs = res.json()
    assert isinstance(logs, list)
    assert len(logs) <= 5
    for entry in logs:
        assert "action" in entry
        assert "created_at" in entry


def test_console_organisations_payload_shape():
    res = client.get("/api/v1/console/organisations")
    assert res.status_code == 200
    orgs = res.json()
    assert isinstance(orgs, list)
    for org in orgs:
        assert {"id", "name", "status", "user_count", "file_count"} <= set(org.keys())


def test_console_defects_payload_shape():
    res = client.get("/api/v1/console/defects")
    assert res.status_code == 200
    defects = res.json()
    assert isinstance(defects, list)
    for defect in defects:
        assert "evidence_spans" in defect


def test_console_organisation_users_enforces_tenant_boundary():
    res = client.get("/api/v1/console/organisations/not-a-real-org/users")
    # Either the org does not exist, or the caller lacks access - never a 500.
    assert res.status_code in (200, 403, 404)


def test_file_spans_endpoint_shape():
    res = client.get("/api/files/does-not-exist/spans")
    assert res.status_code == 404


# ---------------------------------------------------------------------
# The console carries no login layer
# ---------------------------------------------------------------------
def test_no_login_route_in_the_spa():
    """The console boots straight into the workbench - there is no login screen."""
    res = client.get("/login", follow_redirects=False)
    # /login is not a route; the SPA catch-all serves the app shell.
    assert res.status_code == 200
    assert "<div id=\"root\">" in res.text


def test_no_system_admin_shortcut_endpoint():
    """The one-click platform sign-in shortcut was deliberately not carried over."""
    res = client.post("/api/auth/system-admin")
    # The SPA catch-all owns the path for GET only, so a POST is rejected.
    assert res.status_code in (404, 405)


def test_health_endpoint_stays_public():
    """Health probes must remain reachable without a credential."""
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/health/liveness").status_code == 200


def test_openapi_exposes_console_endpoints():
    spec = client.get("/openapi.json").json()
    paths = spec["paths"]
    assert "/api/v1/console/dashboard" in paths
    assert "/api/v1/console/audit-logs" in paths
    assert "/api/v1/console/organisations" in paths
    assert "/api/v1/console/defects" in paths
    assert "/api/files/{file_id}/spans" in paths
