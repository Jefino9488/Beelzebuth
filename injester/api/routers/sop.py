from typing import List, Optional, Dict
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from injester.domain.auth import SecurityContext
from injester.pipeline import InjesterPipeline
from injester.sop.validator import ValidationReport
from injester.api.deps import get_db, get_current_sec_ctx

router = APIRouter(prefix="/api/sop", tags=["SOP Synthesis & Citations"])

class GenerateSOPRequest(BaseModel):
    topic_goal: str
    file_ids: Optional[List[str]] = None

class GenerateSOPResponse(BaseModel):
    markdown_sop: str
    validation: ValidationReport

@router.post("/generate", response_model=GenerateSOPResponse)
def generate_sop_endpoint(
    req: GenerateSOPRequest,
    sec_ctx: SecurityContext = Depends(get_current_sec_ctx),
    db: Session = Depends(get_db)
):
    if not sec_ctx.organisation_id and not sec_ctx.is_super_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot generate SOP without tenant scope."
        )

    pipeline = InjesterPipeline(session=db)
    try:
        markdown_sop, report = pipeline.generate_sop(
            sec_ctx=sec_ctx,
            topic_goal=req.topic_goal,
            file_ids=req.file_ids
        )
        return GenerateSOPResponse(
            markdown_sop=markdown_sop,
            validation=report
        )
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
