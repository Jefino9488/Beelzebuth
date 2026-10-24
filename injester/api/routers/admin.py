from typing import List
from pydantic import BaseModel, EmailStr
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from injester.config import settings
from injester.domain.auth import SecurityContext
from injester.domain.models import Organisation
from injester.infrastructure.db import TenantRepository
from injester.api.deps import get_db, require_super_admin

router = APIRouter(prefix="/api/admin", tags=["Developer & Super Admin"])

class CreateOrgRequest(BaseModel):
    name: str

class OrgResponse(BaseModel):
    id: str
    name: str
    status: str

class CreateClientAdminRequest(BaseModel):
    email: EmailStr
    password: str

class UserCreatedResponse(BaseModel):
    id: str
    email: str
    role: str
    organisation_id: str

@router.post("/organisations", response_model=OrgResponse)
def onboard_organisation(
    req: CreateOrgRequest,
    sec_ctx: SecurityContext = Depends(require_super_admin),
    db: Session = Depends(get_db)
):
    repo = TenantRepository(db)
    try:
        org = repo.create_organisation(sec_ctx, name=req.name)
        return OrgResponse(id=org.id, name=org.name, status=org.status.value)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

@router.post("/organisations/{org_id}/approve", response_model=OrgResponse)
def approve_organisation(
    org_id: str,
    sec_ctx: SecurityContext = Depends(require_super_admin),
    db: Session = Depends(get_db)
):
    repo = TenantRepository(db)
    try:
        org = repo.approve_organisation(sec_ctx, org_id=org_id)
        return OrgResponse(id=org.id, name=org.name, status=org.status.value)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

@router.post("/organisations/{org_id}/suspend", response_model=OrgResponse)
def suspend_organisation(
    org_id: str,
    sec_ctx: SecurityContext = Depends(require_super_admin),
    db: Session = Depends(get_db)
):
    repo = TenantRepository(db)
    try:
        org = repo.suspend_organisation(sec_ctx, org_id=org_id)
        return OrgResponse(id=org.id, name=org.name, status=org.status.value)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

@router.post("/organisations/{org_id}/admins", response_model=UserCreatedResponse)
def assign_client_admin(
    org_id: str,
    req: CreateClientAdminRequest,
    sec_ctx: SecurityContext = Depends(require_super_admin),
    db: Session = Depends(get_db)
):
    repo = TenantRepository(db)
    try:
        user = repo.create_client_admin(sec_ctx, org_id=org_id, email=req.email, password=req.password)
        return UserCreatedResponse(
            id=user.id,
            email=user.email,
            role=user.role.value,
            organisation_id=user.organisation_id,
        )
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

@router.get("/organisations", response_model=List[OrgResponse])
def list_organisations(
    sec_ctx: SecurityContext = Depends(require_super_admin),
    db: Session = Depends(get_db)
):
    orgs = db.query(Organisation).all()
    return [OrgResponse(id=o.id, name=o.name, status=o.status.value) for o in orgs]

class LLMConfigResponse(BaseModel):
    base_url: str
    model_name: str
    api_key_masked: str
    presets: dict

class UpdateLLMConfigRequest(BaseModel):
    preset: str = ""
    base_url: str = ""
    api_key: str = ""
    model_name: str = ""

@router.get("/llm-config", response_model=LLMConfigResponse)
def get_llm_config(sec_ctx: SecurityContext = Depends(require_super_admin)):
    masked_key = f"{settings.OPENAI_API_KEY[:6]}...{settings.OPENAI_API_KEY[-4:]}" if len(settings.OPENAI_API_KEY) > 10 else "***"
    return LLMConfigResponse(
        base_url=settings.OPENAI_BASE_URL,
        model_name=settings.MODEL_NAME,
        api_key_masked=masked_key,
        presets={
            "lightning": {
                "name": "Lightning AI (Gemini 2.5 Flash-Lite)",
                "base_url": settings.LIGHTNING_BASE_URL,
                "model": settings.LIGHTNING_MODEL,
            },
            "openrouter_free": {
                "name": "OpenRouter (Free AI)",
                "base_url": settings.OPENROUTER_BASE_URL,
                "model": settings.OPENROUTER_FREE_MODEL,
            }
        }
    )

@router.post("/llm-config")
def update_llm_config(
    req: UpdateLLMConfigRequest,
    sec_ctx: SecurityContext = Depends(require_super_admin)
):
    if req.preset == "lightning":
        settings.switch_to_lightning()
    elif req.preset == "openrouter_free":
        settings.switch_to_openrouter_free()
    else:
        if req.base_url and req.api_key and req.model_name:
            settings.update_llm_settings(
                base_url=req.base_url,
                api_key=req.api_key,
                model_name=req.model_name
            )
        else:
            raise HTTPException(status_code=400, detail="Missing required configuration fields")

    return {
        "status": "success",
        "message": "LLM configuration updated successfully",
        "active_model": settings.MODEL_NAME,
        "base_url": settings.OPENAI_BASE_URL,
    }
