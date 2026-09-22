from typing import List, Optional
from pydantic import BaseModel, EmailStr
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from injester.domain.auth import SecurityContext
from injester.domain.models import Folder
from injester.infrastructure.db import TenantRepository
from injester.api.deps import get_db, require_client_admin, get_current_sec_ctx

router = APIRouter(prefix="/api/tenant", tags=["Tenant Management"])

class CreateEmployeeRequest(BaseModel):
    email: EmailStr
    password: str

class EmployeeResponse(BaseModel):
    id: str
    email: str
    role: str
    organisation_id: str

class CreateFolderRequest(BaseModel):
    name: str
    parent_folder_id: Optional[str] = None

class FolderResponse(BaseModel):
    id: str
    name: str
    organisation_id: str
    parent_folder_id: Optional[str] = None

@router.post("/employees", response_model=EmployeeResponse)
def add_employee(
    req: CreateEmployeeRequest,
    sec_ctx: SecurityContext = Depends(require_client_admin),
    db: Session = Depends(get_db)
):
    repo = TenantRepository(db)
    try:
        user = repo.create_employee(
            sec_ctx,
            org_id=sec_ctx.organisation_id,
            email=req.email,
            password=req.password
        )
        return EmployeeResponse(
            id=user.id,
            email=user.email,
            role=user.role.value,
            organisation_id=user.organisation_id,
        )
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

@router.post("/folders", response_model=FolderResponse)
def create_folder(
    req: CreateFolderRequest,
    sec_ctx: SecurityContext = Depends(get_current_sec_ctx),
    db: Session = Depends(get_db)
):
    repo = TenantRepository(db)
    try:
        folder = repo.create_folder(sec_ctx, name=req.name, parent_folder_id=req.parent_folder_id)
        return FolderResponse(
            id=folder.id,
            name=folder.name,
            organisation_id=folder.organisation_id,
            parent_folder_id=folder.parent_folder_id,
        )
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

@router.get("/folders", response_model=List[FolderResponse])
def list_folders(
    sec_ctx: SecurityContext = Depends(get_current_sec_ctx),
    db: Session = Depends(get_db)
):
    if not sec_ctx.organisation_id:
        return []
    folders = db.query(Folder).filter(Folder.organisation_id == sec_ctx.organisation_id).all()
    return [
        FolderResponse(
            id=f.id,
            name=f.name,
            organisation_id=f.organisation_id,
            parent_folder_id=f.parent_folder_id
        ) for f in folders
    ]
