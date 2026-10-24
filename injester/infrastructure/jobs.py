"""
Background Job Execution & Telemetry Engine.
Provides asynchronous job dispatch (202 Accepted + job_id) and polling status endpoints
for long-running operations: Document Ingestion, Process Graph Extraction, and SOP Generation.
"""

import uuid
import threading
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, Optional, Any, Callable
from concurrent.futures import ThreadPoolExecutor
from pydantic import BaseModel, Field

class JobStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"

class JobType(str, Enum):
    INGESTION = "INGESTION"
    PROCESS_GRAPH = "PROCESS_GRAPH"
    SOP_GENERATION = "SOP_GENERATION"

class JobResponse(BaseModel):
    job_id: str
    organisation_id: str
    job_type: JobType
    status: JobStatus
    progress: float = Field(default=0.0, ge=0.0, le=1.0)
    message: str = Field(default="")
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    created_at: str
    completed_at: Optional[str] = None

class JobRecord:
    def __init__(
        self,
        job_id: str,
        organisation_id: str,
        user_id: str,
        job_type: JobType
    ):
        self.job_id = job_id
        self.organisation_id = organisation_id
        self.user_id = user_id
        self.job_type = job_type
        self.status = JobStatus.PENDING
        self.progress = 0.0
        self.message = "Job queued"
        self.result: Optional[Dict[str, Any]] = None
        self.error: Optional[str] = None
        self.created_at = datetime.now(timezone.utc)
        self.completed_at: Optional[datetime] = None

    def to_response(self) -> JobResponse:
        return JobResponse(
            job_id=self.job_id,
            organisation_id=self.organisation_id,
            job_type=self.job_type,
            status=self.status,
            progress=self.progress,
            message=self.message,
            result=self.result,
            error=self.error,
            created_at=self.created_at.isoformat(),
            completed_at=self.completed_at.isoformat() if self.completed_at else None,
        )

class JobManager:
    """
    Singleton Thread-safe Background Job Manager.
    """
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance.jobs: Dict[str, JobRecord] = {}
                cls._instance.executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="injester-worker")
            return cls._instance

    def submit_job(
        self,
        organisation_id: str,
        user_id: str,
        job_type: JobType,
        target_fn: Callable[..., Any],
        *args,
        **kwargs
    ) -> JobRecord:
        job_id = str(uuid.uuid4())
        record = JobRecord(
            job_id=job_id,
            organisation_id=organisation_id,
            user_id=user_id,
            job_type=job_type
        )
        self.jobs[job_id] = record

        def worker():
            record.status = JobStatus.RUNNING
            record.message = f"Executing {job_type.value}..."
            record.progress = 0.1
            try:
                result = target_fn(*args, **kwargs)
                record.status = JobStatus.COMPLETED
                record.progress = 1.0
                record.message = "Completed successfully"
                record.completed_at = datetime.now(timezone.utc)
                if hasattr(result, "model_dump"):
                    record.result = result.model_dump()
                elif isinstance(result, dict):
                    record.result = result
                else:
                    record.result = {"output": str(result)}
            except Exception as e:
                record.status = JobStatus.FAILED
                record.error = str(e)
                record.message = f"Execution failed: {e}"
                record.completed_at = datetime.now(timezone.utc)

        self.executor.submit(worker)
        return record

    def get_job(self, job_id: str) -> Optional[JobRecord]:
        return self.jobs.get(job_id)

    def list_jobs(self, organisation_id: Optional[str] = None) -> List[JobRecord]:
        all_records = list(self.jobs.values())
        if organisation_id and organisation_id != "platform":
            return [j for j in all_records if j.organisation_id == organisation_id]
        return all_records

job_manager = JobManager()

