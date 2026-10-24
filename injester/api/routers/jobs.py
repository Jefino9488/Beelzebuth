"""
Background Job Status REST API Router.
Enforces multi-tenant isolation on job querying.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from injester.domain.auth import SecurityContext
from injester.api.deps import get_current_sec_ctx
from injester.infrastructure.jobs import job_manager, JobResponse

router = APIRouter(prefix="/api/jobs", tags=["Background Jobs & Telemetry"])

@router.get("/{job_id}", response_model=JobResponse)
def get_job_status(
    job_id: str,
    sec_ctx: SecurityContext = Depends(get_current_sec_ctx),
):
    job = job_manager.get_job(job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job '{job_id}' not found."
        )

    # Enforce tenant isolation: user can only see jobs belonging to their organisation
    if not sec_ctx.is_super_admin and job.organisation_id != sec_ctx.organisation_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to job from another organisation."
        )

    return job.to_response()
