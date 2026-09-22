import re
import tempfile
import markdown
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, Request, Depends, UploadFile, File as FastAPIFile, Form, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from injester.config import settings
from injester.infrastructure.db import SessionLocal
from injester.domain.models import Organisation, User, File as DBFile, AuditLog, UserRole
from injester.domain.auth import SecurityContext
from injester.pipeline import InjesterPipeline
from injester.api.deps import get_db

router = APIRouter(tags=["Developer UI"])

templates_dir = Path(__file__).resolve().parent.parent.parent / "templates"
templates = Jinja2Templates(directory=str(templates_dir))

def get_dev_sec_ctx() -> SecurityContext:
    """Developer platform super admin context for internal dev UI operations."""
    return SecurityContext(
        user_id="dev_platform_ui",
        email=settings.SUPERADMIN_EMAIL,
        role=UserRole.SUPER_ADMIN,
        organisation_id=None,
    )

def highlight_citations_in_html(html: str) -> str:
    """Wraps [C#] or [S#] tags in clickable badges linking to citation inspector cards."""
    pattern = r'\[([SC]\d+)\]'
    replacement = r'<a href="#cit-card-\1" class="citation-tag">[\1]</a>'
    return re.sub(pattern, replacement, html)

@router.get("/", response_class=HTMLResponse)
@router.get("/ui", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    orgs = db.query(Organisation).all()
    users = db.query(User).all()
    files = db.query(DBFile).order_by(DBFile.created_at.desc()).all()
    audit_logs = db.query(AuditLog).order_by(AuditLog.created_at.desc()).limit(10).all()

    stats = {
        "org_count": len(orgs),
        "user_count": len(users),
        "file_count": len(files),
        "audit_count": len(audit_logs),
    }

    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "page": "dashboard",
            "stats": stats,
            "recent_files": files[:10],
            "current_org_name": "Platform Developer",
        }
    )

@router.get("/ui/files", response_class=HTMLResponse)
def files_view(request: Request, message: Optional[str] = None, db: Session = Depends(get_db)):
    orgs = db.query(Organisation).all()
    files = db.query(DBFile).order_by(DBFile.created_at.desc()).all()
    return templates.TemplateResponse(
        request=request,
        name="files.html",
        context={
            "page": "files",
            "organisations": orgs,
            "files": files,
            "message": message,
            "current_org_name": "Platform Developer",
        }
    )

@router.post("/ui/files/upload")
async def upload_file_ui(
    tenant_org_id: str = Form(...),
    user_email: str = Form(...),
    file: UploadFile = FastAPIFile(...),
    db: Session = Depends(get_db)
):
    content = await file.read()
    temp_dir = tempfile.mkdtemp()
    temp_path = Path(temp_dir) / file.filename
    temp_path.write_bytes(content)

    user = db.query(User).filter(User.email == user_email).first()
    if not user:
        user = db.query(User).filter(User.role == UserRole.SUPER_ADMIN).first()

    sec_ctx = SecurityContext(
        user_id=user.id if user else None,
        email=user.email if user else user_email,
        role=user.role if user else UserRole.CLIENT_ADMIN,
        organisation_id=tenant_org_id,
    )

    pipeline = InjesterPipeline(session=db)
    try:
        file_rec, ver_rec, chunks = pipeline.ingest_file(
            sec_ctx=sec_ctx,
            file_path=temp_path,
            filename=file.filename
        )
        msg = f"Successfully ingested '{file.filename}' (v{ver_rec.version_number}) with {len(chunks)} chunks indexed into FAISS!"
    except Exception as e:
        msg = f"Failed to ingest: {e}"
    finally:
        temp_path.unlink(missing_ok=True)
        Path(temp_dir).rmdir()

    return RedirectResponse(url=f"/ui/files?message={msg}", status_code=status.HTTP_303_SEE_OTHER)

@router.get("/ui/sop", response_class=HTMLResponse)
def sop_workbench(
    request: Request,
    file_id: Optional[str] = None,
    error: Optional[str] = None,
    db: Session = Depends(get_db)
):
    orgs = db.query(Organisation).all()
    selected_org_id = None
    if file_id:
        target_file = db.get(DBFile, file_id)
        if target_file:
            selected_org_id = target_file.organisation_id

    return templates.TemplateResponse(
        request=request,
        name="sop.html",
        context={
            "page": "sop",
            "organisations": orgs,
            "selected_org_id": selected_org_id or (orgs[0].id if orgs else None),
            "model_name": settings.MODEL_NAME,
            "base_url": settings.OPENAI_BASE_URL,
            "user_email": settings.SUPERADMIN_EMAIL,
            "error": error,
            "sop_result": None,
            "current_org_name": "Platform Developer",
        }
    )

@router.post("/ui/sop/generate", response_class=HTMLResponse)
def generate_sop_ui(
    request: Request,
    tenant_org_id: str = Form(...),
    user_email: str = Form(...),
    topic_goal: str = Form(...),
    db: Session = Depends(get_db)
):
    orgs = db.query(Organisation).all()
    user = db.query(User).filter(User.email == user_email).first()
    if not user:
        user = db.query(User).filter(User.role == UserRole.SUPER_ADMIN).first()

    sec_ctx = SecurityContext(
        user_id=user.id if user else None,
        email=user.email if user else user_email,
        role=user.role if user else UserRole.CLIENT_ADMIN,
        organisation_id=tenant_org_id,
    )

    pipeline = InjesterPipeline(session=db)
    try:
        markdown_sop, report = pipeline.generate_sop(
            sec_ctx=sec_ctx,
            topic_goal=topic_goal
        )

        rendered_html = markdown.markdown(markdown_sop, extensions=['tables', 'fenced_code'])
        rendered_html = highlight_citations_in_html(rendered_html)

        sop_result = {
            "markdown": markdown_sop,
            "is_valid": report.is_valid,
            "errors": report.errors,
            "warnings": report.warnings,
            "verified_citations": report.verified_citation_index,
        }

        return templates.TemplateResponse(
            request=request,
            name="sop.html",
            context={
                "page": "sop",
                "organisations": orgs,
                "selected_org_id": tenant_org_id,
                "model_name": settings.MODEL_NAME,
                "base_url": settings.OPENAI_BASE_URL,
                "user_email": user_email,
                "topic_goal": topic_goal,
                "sop_result": sop_result,
                "rendered_html": rendered_html,
                "error": None,
                "current_org_name": "Platform Developer",
            }
        )
    except Exception as e:
        return templates.TemplateResponse(
            request=request,
            name="sop.html",
            context={
                "page": "sop",
                "organisations": orgs,
                "selected_org_id": tenant_org_id,
                "model_name": settings.MODEL_NAME,
                "base_url": settings.OPENAI_BASE_URL,
                "user_email": user_email,
                "topic_goal": topic_goal,
                "sop_result": None,
                "error": str(e),
                "current_org_name": "Platform Developer",
            }
        )

@router.get("/ui/admin", response_class=HTMLResponse)
def admin_view(request: Request, message: Optional[str] = None, db: Session = Depends(get_db)):
    orgs = db.query(Organisation).order_by(Organisation.created_at.desc()).all()
    audit_logs = db.query(AuditLog).order_by(AuditLog.created_at.desc()).limit(20).all()
    masked_key = f"{settings.OPENAI_API_KEY[:6]}...{settings.OPENAI_API_KEY[-4:]}" if len(settings.OPENAI_API_KEY) > 10 else "***"
    return templates.TemplateResponse(
        request=request,
        name="admin.html",
        context={
            "page": "admin",
            "organisations": orgs,
            "audit_logs": audit_logs,
            "message": message,
            "active_model": settings.MODEL_NAME,
            "active_base_url": settings.OPENAI_BASE_URL,
            "active_key_masked": masked_key,
            "current_org_name": "Platform Developer",
        }
    )

@router.post("/ui/admin/llm-preset")
def switch_llm_preset_ui(preset: str = Form(...)):
    if preset == "lightning":
        settings.switch_to_lightning()
        msg = f"Switched to Lightning AI ({settings.MODEL_NAME})!"
    elif preset == "openrouter_free":
        settings.switch_to_openrouter_free()
        msg = f"Switched to OpenRouter Free AI ({settings.MODEL_NAME})!"
    else:
        msg = "Unknown preset"
    return RedirectResponse(url=f"/ui/admin?message={msg}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/ui/admin/organisations")
def create_org_ui(org_name: str = Form(...), db: Session = Depends(get_db)):
    dev_ctx = get_dev_sec_ctx()
    pipeline = InjesterPipeline(session=db)
    try:
        org = pipeline.repo.create_organisation(dev_ctx, name=org_name)
        msg = f"Successfully onboarded organisation '{org.name}' ({org.id})!"
    except Exception as e:
        msg = f"Error: {e}"
    return RedirectResponse(url=f"/ui/admin?message={msg}", status_code=status.HTTP_303_SEE_OTHER)

@router.post("/ui/admin/admins")
def create_admin_ui(
    target_org_id: str = Form(...),
    admin_email: str = Form(...),
    admin_password: str = Form(...),
    db: Session = Depends(get_db)
):
    dev_ctx = get_dev_sec_ctx()
    pipeline = InjesterPipeline(session=db)
    try:
        user = pipeline.repo.create_client_admin(dev_ctx, org_id=target_org_id, email=admin_email, password=admin_password)
        msg = f"Assigned Client Super Admin '{user.email}'!"
    except Exception as e:
        msg = f"Error: {e}"
    return RedirectResponse(url=f"/ui/admin?message={msg}", status_code=status.HTTP_303_SEE_OTHER)

@router.post("/ui/admin/employees")
def create_employee_ui(
    emp_org_id: str = Form(...),
    emp_email: str = Form(...),
    emp_password: str = Form(...),
    db: Session = Depends(get_db)
):
    dev_ctx = get_dev_sec_ctx()
    pipeline = InjesterPipeline(session=db)
    try:
        user = pipeline.repo.create_employee(dev_ctx, org_id=emp_org_id, email=emp_email, password=emp_password)
        msg = f"Provisioned employee '{user.email}'!"
    except Exception as e:
        msg = f"Error: {e}"
    return RedirectResponse(url=f"/ui/admin?message={msg}", status_code=status.HTTP_303_SEE_OTHER)
