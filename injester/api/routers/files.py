import tempfile
from pathlib import Path
from typing import List, Optional
from pydantic import BaseModel
from fastapi import APIRouter, Depends, UploadFile, File as FastAPIFile, Form, HTTPException, status
from sqlalchemy.orm import Session

from injester.domain.auth import SecurityContext
from injester.domain.models import File as DBFile
from injester.infrastructure.db import TenantRepository
from injester.pipeline import InjesterPipeline
from injester.api.deps import get_db, get_current_sec_ctx

router = APIRouter(prefix="/api/files", tags=["Files & Ingestion"])

class FileVersionResponse(BaseModel):
    version_number: int
    file_size: int
    mime_type: str
    file_hash: str
    created_at: str

class FileResponse(BaseModel):
    id: str
    name: str
    organisation_id: str
    folder_id: Optional[str] = None
    created_by_user_id: Optional[str] = None
    versions: List[FileVersionResponse] = []

@router.post("/upload", response_model=FileResponse)
async def upload_file(
    file: UploadFile = FastAPIFile(...),
    folder_id: Optional[str] = Form(None),
    sec_ctx: SecurityContext = Depends(get_current_sec_ctx),
    db: Session = Depends(get_db)
):
    if not sec_ctx.organisation_id and not sec_ctx.is_super_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Files must be uploaded within a tenant organisation context."
        )

    content = await file.read()
    temp_dir = tempfile.mkdtemp()
    temp_path = Path(temp_dir) / file.filename
    temp_path.write_bytes(content)

    pipeline = InjesterPipeline(session=db)
    try:
        file_rec, ver_rec, chunks = pipeline.ingest_file(
            sec_ctx=sec_ctx,
            file_path=temp_path,
            filename=file.filename,
            folder_id=folder_id
        )
        return FileResponse(
            id=file_rec.id,
            name=file_rec.name,
            organisation_id=file_rec.organisation_id,
            folder_id=file_rec.folder_id,
            created_by_user_id=file_rec.created_by_user_id,
            versions=[
                FileVersionResponse(
                    version_number=v.version_number,
                    file_size=v.file_size,
                    mime_type=v.mime_type,
                    file_hash=v.file_hash,
                    created_at=str(v.created_at),
                ) for v in file_rec.versions
            ]
        )
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
    finally:
        temp_path.unlink(missing_ok=True)
        Path(temp_dir).rmdir()

@router.get("", response_model=List[FileResponse])
def list_files(
    folder_id: Optional[str] = None,
    sec_ctx: SecurityContext = Depends(get_current_sec_ctx),
    db: Session = Depends(get_db)
):
    repo = TenantRepository(db)
    files = repo.list_files(sec_ctx, folder_id=folder_id)
    return [
        FileResponse(
            id=f.id,
            name=f.name,
            organisation_id=f.organisation_id,
            folder_id=f.folder_id,
            created_by_user_id=f.created_by_user_id,
            versions=[
                FileVersionResponse(
                    version_number=v.version_number,
                    file_size=v.file_size,
                    mime_type=v.mime_type,
                    file_hash=v.file_hash,
                    created_at=str(v.created_at),
                ) for v in f.versions
            ]
        ) for f in files
    ]

@router.get("/{file_id}", response_model=FileResponse)
def get_file_details(
    file_id: str,
    sec_ctx: SecurityContext = Depends(get_current_sec_ctx),
    db: Session = Depends(get_db)
):
    repo = TenantRepository(db)
    try:
        f = repo.get_file(sec_ctx, file_id)
        return FileResponse(
            id=f.id,
            name=f.name,
            organisation_id=f.organisation_id,
            folder_id=f.folder_id,
            created_by_user_id=f.created_by_user_id,
            versions=[
                FileVersionResponse(
                    version_number=v.version_number,
                    file_size=v.file_size,
                    mime_type=v.mime_type,
                    file_hash=v.file_hash,
                    created_at=str(v.created_at),
                ) for v in f.versions
            ]
        )
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
