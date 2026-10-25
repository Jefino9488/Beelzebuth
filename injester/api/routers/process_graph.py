"""
Process Graph & Semantic Verification REST API Router.
Provides enterprise endpoints for:
- Evidence-first procedural proposition extraction
- Local Laya System-1 verification
- Deterministic process graph compilation (authoritative AST + defect register)
- Multi-format projections (BPMN 2.0 XML, Mermaid Flowchart, Swimlane, State Machine)
"""

import uuid
import tempfile
from pathlib import Path
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, UploadFile, File as FastAPIFile, Form, HTTPException, status, Query, Response
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from injester.config import settings
from injester.domain.auth import SecurityContext
from injester.infrastructure.db import TenantRepository, SessionLocal
from injester.infrastructure.jobs import job_manager, JobResponse, JobType
from injester.pipeline import InjesterPipeline
from injester.api.deps import get_db, get_current_sec_ctx
from injester.semantic.schemas import GroundedProcessGraph, AmbiguityRegister, DualOutputResult
from injester.semantic.projections import (
    render_bpmn_20_xml,
    render_flowchart_mermaid,
    render_swimlane_mermaid,
    render_state_machine_mermaid,
)

router = APIRouter(prefix="/api/v1/process-graph", tags=["Process Graph & Semantic Verification"])


class ProcessGraphMetrics(BaseModel):
    activities_count: int = Field(description="Number of verified procedural activities in the authoritative graph")
    gateways_count: int = Field(description="Number of verified decision gateways")
    transitions_count: int = Field(description="Number of verified sequence transitions")
    actors_count: int = Field(description="Number of verified organizational roles / swimlanes")
    defects_quarantined_count: int = Field(description="Number of ungrounded or ambiguous claims excluded from workflow logic")


class ProcessGraphLatency(BaseModel):
    extraction_sec: float = Field(description="Time spent on atomic proposition extraction")
    laya_sec: float = Field(description="Time spent on batched Laya System-1 verification")
    compilation_sec: float = Field(description="Time spent on deterministic AST compilation")
    total_sec: float = Field(description="Total end-to-end execution latency in seconds")


class ProcessGraphResponse(BaseModel):
    document_name: str
    process_name: str
    objective: str
    metrics: ProcessGraphMetrics
    latencies: ProcessGraphLatency
    graph: GroundedProcessGraph
    defect_register: AmbiguityRegister
    bpmn_2_0_xml: str = Field(description="Standard BPMN 2.0 XML for import into Camunda, Signavio, or Enterprise Architect")
    flowchart_mermaid: str = Field(description="Mermaid.js Flowchart syntax string")
    swimlane_mermaid: str = Field(description="Mermaid.js Swimlane syntax string")
    state_machine_mermaid: Optional[str] = Field(default=None, description="Mermaid.js State Machine syntax string if state transitions exist")
    digital_markdown: Optional[str] = Field(default=None, description="Digital Markdown procedure with granular citations and citation index")


@router.post(
    "/generate",
    response_model=ProcessGraphResponse,
    summary="Generate Grounded Process Graph with Laya Verification",
    description=(
        "Executes the Evidence-First Semantic Pipeline on a document: "
        "1. Segments source text into immutable [S###] evidence spans. "
        "2. Extracts atomic procedural propositions (actor, action, condition, modality, epistemic status). "
        "3. Verifies every proposition using locally hosted Laya System-1 ModernBERT weights. "
        "4. Compiles surviving verified propositions into an authoritative Process Graph AST. "
        "5. Quarantines ungrounded, distorted, or conflicting claims into the Ambiguity & Defect Register. "
        "6. Projects verified graph into BPMN 2.0 XML and Mermaid diagrams."
    ),
    response_description="Authoritative Process Graph AST, Quarantined Defect Register, and Multi-Target Projections."
)
async def generate_process_graph_endpoint(
    file: Optional[UploadFile] = FastAPIFile(None, description="Upload a source document (.docx, .pdf, .txt, .md)"),
    file_id: Optional[str] = Form(None, description="Existing document UUID in tenant storage"),
    sec_ctx: SecurityContext = Depends(get_current_sec_ctx),
    db: Session = Depends(get_db)
):
    if not file and not file_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Must provide either a file upload or an existing file_id."
        )

    pipeline = InjesterPipeline(session=db)
    temp_dir = None
    target_path = None

    try:
        if file:
            content = await file.read()
            temp_dir = tempfile.mkdtemp()
            safe_name = Path(file.filename).name if file.filename else f"upload_{uuid.uuid4().hex[:8]}"
            target_path = Path(temp_dir) / safe_name
            target_path.write_bytes(content)
            input_source = target_path
        else:
            input_source = file_id

        # Server-controlled artifact storage path partitioned by tenant
        server_output_dir = settings.STORAGE_DIR / "artifacts" / (sec_ctx.organisation_id or "platform") / str(uuid.uuid4())

        result: DualOutputResult = pipeline.generate_process_graph(
            sec_ctx=sec_ctx,
            file_path_or_id=input_source,
            output_dir=server_output_dir,
        )

        # Generate multi-target projections
        bpmn_xml = render_bpmn_20_xml(result.graph)
        fc_mmd = render_flowchart_mermaid(result.graph)
        sw_mmd = render_swimlane_mermaid(result.graph)
        sm_mmd = render_state_machine_mermaid(result.graph) if getattr(result.graph, 'state_transitions', None) else None

        metrics = ProcessGraphMetrics(
            activities_count=len(result.graph.activities),
            gateways_count=len(result.graph.gateways),
            transitions_count=len(result.graph.transitions),
            actors_count=len(result.graph.actors),
            defects_quarantined_count=len(result.defect_register.defects),
        )

        latencies = ProcessGraphLatency(
            extraction_sec=result.extraction_latency_sec,
            laya_sec=result.laya_latency_sec,
            compilation_sec=result.compilation_latency_sec,
            total_sec=result.total_latency_sec,
        )

        doc_name = file.filename if file else f"document_{file_id}"

        return ProcessGraphResponse(
            document_name=doc_name,
            process_name=result.graph.process_name,
            objective=result.graph.objective,
            metrics=metrics,
            latencies=latencies,
            graph=result.graph,
            defect_register=result.defect_register,
            bpmn_2_0_xml=bpmn_xml,
            flowchart_mermaid=fc_mmd,
            swimlane_mermaid=sw_mmd,
            state_machine_mermaid=sm_mmd,
            digital_markdown=result.digital_markdown,
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate process graph: {str(e)}"
        )
    finally:
        if temp_dir and Path(temp_dir).exists():
            for child in Path(temp_dir).glob("*"):
                child.unlink(missing_ok=True)
            Path(temp_dir).rmdir()


def _get_latest_snapshot_for_file(repo: TenantRepository, sec_ctx: SecurityContext, file_id: str):
    file_record = repo.get_visible_file(sec_ctx, file_id)
    snapshots = repo.list_process_graph_snapshots(sec_ctx)
    version_ids = {v.id for v in file_record.versions} if getattr(file_record, 'versions', None) else set()
    matching = [
        s for s in snapshots
        if (s.source_document_hashes and file_id in s.source_document_hashes)
        or (s.file_version_ids and any(vid in s.file_version_ids for vid in version_ids))
    ]
    if not matching:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Generation required. No existing snapshot found for file '{file_id}'."
        )
    return matching[0]


@router.get(
    "/{file_id}/bpmn",
    summary="Export BPMN 2.0 XML Diagram",
    description="Retrieves standard BPMN 2.0 XML export from the latest snapshot for a tenant document.",
    response_class=Response,
)
def get_bpmn_xml(
    file_id: str,
    download: bool = Query(False, description="Set true to prompt browser file download"),
    sec_ctx: SecurityContext = Depends(get_current_sec_ctx),
    db: Session = Depends(get_db)
):
    repo = TenantRepository(db)
    snapshot = _get_latest_snapshot_for_file(repo, sec_ctx, file_id)
    xml_str = (snapshot.projections or {}).get("bpmn_xml")
    if not xml_str:
        graph = GroundedProcessGraph.model_validate(snapshot.canonical_graph)
        xml_str = render_bpmn_20_xml(graph)
    
    headers = {}
    if download:
        proc_name = snapshot.process_name or f"process_{file_id}"
        headers["Content-Disposition"] = f'attachment; filename="{proc_name.replace(" ", "_")}.bpmn"'
    
    return Response(content=xml_str, media_type="application/xml", headers=headers)


@router.get(
    "/{file_id}/mermaid",
    summary="Retrieve Mermaid.js Syntax for Document",
    description="Retrieves Mermaid flowchart, swimlane, or state machine syntax from the latest snapshot for a tenant document.",
    response_class=PlainTextResponse,
)
def get_mermaid_diagram(
    file_id: str,
    view: str = Query("flowchart", enum=["flowchart", "swimlane", "state_machine"], description="Diagram projection type"),
    sec_ctx: SecurityContext = Depends(get_current_sec_ctx),
    db: Session = Depends(get_db)
):
    repo = TenantRepository(db)
    snapshot = _get_latest_snapshot_for_file(repo, sec_ctx, file_id)
    projections = snapshot.projections or {}
    
    if view == "flowchart" and projections.get("mermaid"):
        return PlainTextResponse(content=projections["mermaid"])

    graph = GroundedProcessGraph.model_validate(snapshot.canonical_graph)
    if view == "swimlane":
        diagram = render_swimlane_mermaid(graph)
    elif view == "state_machine":
        diagram = render_state_machine_mermaid(graph) or "stateDiagram-v2\n    [*] --> NoStateTransitionsDefined"
    else:
        diagram = render_flowchart_mermaid(graph)

    return PlainTextResponse(content=diagram)


@router.get(
    "/{file_id}/defect-register",
    summary="Retrieve Quarantined Ambiguity & Defect Register",
    description="Retrieves the Defect Register containing all ungrounded, conflicting, or distorted propositions.",
)
def get_defect_register(
    file_id: str,
    format: str = Query("markdown", enum=["markdown", "json"], description="Response format"),
    sec_ctx: SecurityContext = Depends(get_current_sec_ctx),
    db: Session = Depends(get_db)
):
    repo = TenantRepository(db)
    snapshot = _get_latest_snapshot_for_file(repo, sec_ctx, file_id)
    if format == "json":
        return snapshot.defect_register
    else:
        projections = snapshot.projections or {}
        if projections.get("defect_md"):
            return PlainTextResponse(content=projections["defect_md"])
        reg = AmbiguityRegister.model_validate(snapshot.defect_register)
        return PlainTextResponse(content=reg.to_markdown())


@router.post(
    "/jobs",
    response_model=JobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Submit Asynchronous Process Graph Generation Job",
    description="Dispatches asynchronous process graph extraction and compilation. Returns job_id for polling."
)
async def submit_process_graph_job(
    file: Optional[UploadFile] = FastAPIFile(None),
    file_id: Optional[str] = Form(None),
    sec_ctx: SecurityContext = Depends(get_current_sec_ctx),
    db: Session = Depends(get_db)
):
    if not file and not file_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Must provide either a file upload or an existing file_id."
        )

    if file:
        content = await file.read()
        temp_dir = tempfile.mkdtemp()
        safe_name = Path(file.filename).name if file.filename else f"upload_{uuid.uuid4().hex[:8]}"
        target_path = Path(temp_dir) / safe_name
        target_path.write_bytes(content)
        input_source = target_path
    else:
        temp_dir = None
        input_source = file_id

    tenant_id = sec_ctx.organisation_id or "platform"
    server_output_dir = settings.STORAGE_DIR / "artifacts" / tenant_id / str(uuid.uuid4())

    def run_job():
        try:
            with SessionLocal() as worker_session:
                pipeline = InjesterPipeline(session=worker_session)
                dual_result = pipeline.generate_process_graph(
                    sec_ctx=sec_ctx,
                    file_path_or_id=input_source,
                    output_dir=server_output_dir
                )
                return {
                    "process_name": dual_result.graph.process_name,
                    "activities_count": len(dual_result.graph.activities),
                    "gateways_count": len(dual_result.graph.gateways),
                    "defects_count": len(dual_result.defect_register.defects),
                    "artifacts_dir": str(server_output_dir),
                }
        finally:
            if temp_dir and os.path.exists(temp_dir):
                import shutil
                shutil.rmtree(temp_dir, ignore_errors=True)

    job = job_manager.submit_job(
        organisation_id=tenant_id,
        user_id=sec_ctx.user_id,
        job_type=JobType.PROCESS_GRAPH,
        target_fn=run_job
    )
    return job.to_response()


@router.get(
    "/snapshots",
    summary="List Process Graph Snapshots",
    description="Lists immutable ProcessGraphSnapshots for the authenticated tenant.",
)
async def list_snapshots_endpoint(
    process_name: Optional[str] = Query(None),
    sec_ctx: SecurityContext = Depends(get_current_sec_ctx),
    db: Session = Depends(get_db)
):
    repo = TenantRepository(db)
    snapshots = repo.list_process_graph_snapshots(sec_ctx=sec_ctx, process_name=process_name)
    return [
        {
            "id": s.id,
            "process_name": s.process_name,
            "schema_version": s.schema_version,
            "created_at": s.created_at.isoformat() if s.created_at else None,
            "file_version_ids": s.file_version_ids,
            "span_registry_hash": s.span_registry_hash,
            "reasoner_model": s.reasoner_model,
        }
        for s in snapshots
    ]


@router.get(
    "/snapshots/{snapshot_id}",
    summary="Get Process Graph Snapshot",
    description="Retrieves a specific immutable ProcessGraphSnapshot including canonical AST, defect register, and projections.",
)
async def get_snapshot_endpoint(
    snapshot_id: str,
    sec_ctx: SecurityContext = Depends(get_current_sec_ctx),
    db: Session = Depends(get_db)
):
    repo = TenantRepository(db)
    try:
        snapshot = repo.get_process_graph_snapshot(sec_ctx=sec_ctx, snapshot_id=snapshot_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))

    return {
        "id": snapshot.id,
        "organisation_id": snapshot.organisation_id,
        "process_name": snapshot.process_name,
        "schema_version": snapshot.schema_version,
        "created_at": snapshot.created_at.isoformat() if snapshot.created_at else None,
        "file_version_ids": snapshot.file_version_ids,
        "source_hashes": snapshot.source_hashes,
        "source_document_hashes": snapshot.source_document_hashes,
        "span_registry_hash": snapshot.span_registry_hash,
        "reasoner_model": snapshot.reasoner_model,
        "laya_model_version": snapshot.laya_model_version,
        "validation_policy_version": snapshot.validation_policy_version,
        "canonical_graph": snapshot.canonical_graph,
        "defect_register": snapshot.defect_register,
        "projections": snapshot.projections,
    }

