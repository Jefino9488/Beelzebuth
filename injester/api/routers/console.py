"""
Console Data REST API Router.
Serves the JSON payloads that back the React console (dashboard telemetry, audit trail,
defect register, organisation roster). These replace the server-rendered Jinja console.
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from injester.config import settings
from injester.domain.auth import SecurityContext
from injester.domain.models import AuditLog, Organisation, User
from injester.domain.models import File as DBFile
from injester.infrastructure.db import TenantRepository
from injester.api.deps import get_db, get_current_sec_ctx

router = APIRouter(prefix="/api/v1/console", tags=["Console Data"])


class AuditLogEntry(BaseModel):
    id: str
    action: str
    details: Optional[str] = None
    user_id: Optional[str] = None
    user_email: Optional[str] = None
    organisation_id: Optional[str] = None
    created_at: str


class ConsoleFileEntry(BaseModel):
    id: str
    name: str
    organisation_id: str
    organisation_name: Optional[str] = None
    format: str
    version_count: int
    file_hash: Optional[str] = None
    created_at: str


class DashboardStats(BaseModel):
    org_count: int
    user_count: int
    file_count: int
    audit_count: int


class EngineStatus(BaseModel):
    database: str
    vectorstore: str
    verifier: str
    device: str
    model: str
    workspace_dir: str
    storage_dir: str


class DashboardResponse(BaseModel):
    stats: DashboardStats
    recent_files: List[ConsoleFileEntry]
    audit_logs: List[AuditLogEntry]
    engine: EngineStatus
    is_super_admin: bool
    current_org_name: str


class OrganisationEntry(BaseModel):
    id: str
    name: str
    status: str
    user_count: int
    file_count: int
    created_at: str


class ConsoleUserEntry(BaseModel):
    id: str
    email: str
    role: str
    organisation_id: str | None
    is_active: bool
    created_at: str


class DefectEntry(BaseModel):
    id: Optional[str] = None
    category: Optional[str] = None
    severity: Optional[str] = None
    claimed_statement: Optional[str] = None
    rationale: Optional[str] = None
    confidence: Optional[float] = None
    evidence_spans: List[str] = []
    evidence_text: Optional[str] = None
    document_name: Optional[str] = None


def _file_format(name: str) -> str:
    """Extracts the uppercase file extension for display badges."""
    suffix = Path(name).suffix
    return suffix.lstrip(".").upper() if suffix else "FILE"


def _audit_entry(log: AuditLog, user_email: Optional[str] = None) -> AuditLogEntry:
    """Serializes an audit log row for the console."""
    return AuditLogEntry(
        id=log.id,
        action=log.action,
        details=log.details,
        user_id=log.user_id,
        user_email=user_email,
        organisation_id=log.organisation_id,
        created_at=str(log.created_at),
    )


def _file_entry(file_record, org_name: Optional[str] = None) -> ConsoleFileEntry:
    """Serializes a file record for the console."""
    versions = getattr(file_record, "versions", None) or []
    latest_hash = None
    if versions:
        latest = sorted(versions, key=lambda v: v.version_number)[-1]
        latest_hash = latest.file_hash
    resolved_org = org_name
    if resolved_org is None:
        organisation = getattr(file_record, "organisation", None)
        resolved_org = organisation.name if organisation else None
    return ConsoleFileEntry(
        id=file_record.id,
        name=file_record.name,
        organisation_id=file_record.organisation_id,
        organisation_name=resolved_org,
        format=_file_format(file_record.name),
        version_count=len(versions),
        file_hash=latest_hash,
        created_at=str(file_record.created_at),
    )


@router.get("/dashboard", response_model=DashboardResponse)
def get_dashboard(
    sec_ctx: SecurityContext = Depends(get_current_sec_ctx),
    db: Session = Depends(get_db),
):
    """Operational telemetry: KPI counts, recent documents, audit trail and engine status."""
    repo = TenantRepository(db)
    files = repo.list_visible_files(sec_ctx)
    audit_logs = repo.list_visible_audit_logs(sec_ctx, limit=15)

    if sec_ctx.is_super_admin:
        orgs = db.query(Organisation).all()
        users = db.query(User).all()
    else:
        orgs = [db.get(Organisation, sec_ctx.organisation_id)] if sec_ctx.organisation_id else []
        users = db.query(User).filter(User.organisation_id == sec_ctx.organisation_id).all()

    user_emails = {u.id: u.email for u in users}
    superadmin_emails = {
        u.id: u.email for u in db.query(User).filter(User.role == "SUPER_ADMIN").all()
    } if sec_ctx.is_super_admin else {}

    recent_files = [_file_entry(f) for f in files[:8]]

    return DashboardResponse(
        stats=DashboardStats(
            org_count=len([o for o in orgs if o]),
            user_count=len(users),
            file_count=len(files),
            audit_count=len(audit_logs),
        ),
        recent_files=recent_files,
        audit_logs=[
            _audit_entry(log, user_emails.get(log.user_id) or superadmin_emails.get(log.user_id))
            for log in audit_logs
        ],
        engine=EngineStatus(
            database="Online",
            vectorstore="FAISS Active",
            verifier=f"{settings.SYSTEM1_PROVIDER.upper()} System-1 Verifier",
            device="CUDA Accelerated / CPU Fallback",
            model=settings.MODEL_NAME,
            workspace_dir=str(settings.WORKSPACE_DIR),
            storage_dir=str(settings.STORAGE_DIR),
        ),
        is_super_admin=sec_ctx.is_super_admin,
        current_org_name=sec_ctx.organisation_id or "Platform",
    )


@router.get("/audit-logs", response_model=List[AuditLogEntry])
def get_audit_logs(
    limit: int = Query(default=50, ge=1, le=500),
    sec_ctx: SecurityContext = Depends(get_current_sec_ctx),
    db: Session = Depends(get_db),
):
    """Tenant-scoped audit trail, most recent first."""
    repo = TenantRepository(db)
    logs = repo.list_visible_audit_logs(sec_ctx, limit=limit)

    known_users = {
        u.id: u.email
        for u in db.query(User).filter(User.id.in_([lg.user_id for lg in logs if lg.user_id])).all()
    } if logs else {}

    return [_audit_entry(log, known_users.get(log.user_id)) for log in logs]


@router.get("/organisations", response_model=List[OrganisationEntry])
def get_organisations(
    sec_ctx: SecurityContext = Depends(get_current_sec_ctx),
    db: Session = Depends(get_db),
):
    """Organisation roster with user and document counts."""
    repo = TenantRepository(db)
    orgs = repo.list_organisations(sec_ctx)

    entries: List[OrganisationEntry] = []
    for org in orgs:
        if not org:
            continue
        user_count = db.query(User).filter(User.organisation_id == org.id).count()
        file_count = db.query(DBFile).filter(DBFile.organisation_id == org.id).count()
        entries.append(
            OrganisationEntry(
                id=org.id,
                name=org.name,
                status=org.status.value,
                user_count=user_count,
                file_count=file_count,
                created_at=str(org.created_at),
            )
        )
    return entries


@router.get("/organisations/{org_id}/users", response_model=List[ConsoleUserEntry])
def get_organisation_users(
    org_id: str,
    sec_ctx: SecurityContext = Depends(get_current_sec_ctx),
    db: Session = Depends(get_db),
):
    """Lists the users provisioned inside an organisation, enforcing the tenant boundary."""
    if not sec_ctx.is_super_admin:
        sec_ctx.assert_tenant_access(org_id)

    users = db.query(User).filter(User.organisation_id == org_id).all()
    return [
        ConsoleUserEntry(
            id=user.id,
            email=user.email,
            role=user.role.value,
            organisation_id=user.organisation_id,
            is_active=bool(user.is_active),
            created_at=str(user.created_at),
        )
        for user in users
    ]


@router.get("/defects", response_model=List[DefectEntry])
def get_defects(
    sec_ctx: SecurityContext = Depends(get_current_sec_ctx),
):
    """
    Defect register: claims quarantined by the System-1 verifier during the most recent
    process-graph run for the caller's tenant.
    """
    org_id = sec_ctx.organisation_id or "platform"
    artifacts_dir = settings.STORAGE_DIR / "artifacts" / org_id

    defects: List[DefectEntry] = []
    if artifacts_dir.exists():
        try:
            run_dirs = sorted(
                (p for p in artifacts_dir.iterdir() if p.is_dir()),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            for run_dir in run_dirs:
                # The pipeline emits `defect_register.json`; older runs used `DEFECT_REGISTER.json`.
                candidate = run_dir / "defect_register.json"
                if not candidate.exists():
                    candidate = run_dir / "DEFECT_REGISTER.json"
                if not candidate.exists():
                    continue
                data = json.loads(candidate.read_text(encoding="utf-8"))
                raw_defects = data.get("defects", [])
                defects = [
                    DefectEntry(
                        id=d.get("id"),
                        category=_enum_value(d.get("defect_category") or d.get("category")),
                        severity=_enum_value(d.get("severity")),
                        claimed_statement=d.get("claimed_statement"),
                        rationale=d.get("rationale"),
                        confidence=d.get("confidence"),
                        evidence_spans=d.get("evidence_spans") or [],
                        evidence_text=d.get("evidence_text"),
                        document_name=d.get("document_name"),
                    )
                    for d in raw_defects
                ]
                if defects:
                    break
        except Exception:
            defects = []

    return defects


def _enum_value(raw: Any) -> Optional[str]:
    """Normalizes an enum-or-string defect field into a plain string."""
    if raw is None:
        return None
    value = getattr(raw, "value", raw)
    return str(value)
