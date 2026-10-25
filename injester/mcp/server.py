"""
Injester & Beelzebuth Local MCP Server.
Exposes zero-hallucination document operations, search, readable Markdown synthesis,
and diagram extraction to AI clients (Claude Desktop, Cursor, etc.) via stdio.

IMPORTANT: All logging and diagnostics must go to sys.stderr to avoid
corrupting MCP JSON-RPC protocol frames on sys.stdout.
"""

import sys
import json
import logging
from pathlib import Path
from typing import List, Optional, Dict, Any

from mcp.server.mcpserver import MCPServer

# Redirect standard logging to stderr
logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format="[injester-mcp] %(levelname)s %(message)s"
)
logger = logging.getLogger("injester.mcp")

from injester.application.manager import manager
from injester.application.documents import DocumentService
from injester.application.retrieval import RetrievalService
from injester.application.digest import DigestService
from injester.application.process_graph import ProcessGraphService
from injester.application.document_tools import document_tools

mcp_app = MCPServer(
    name="injester",
    title="Beelzebuth & Injester Community MCP Server",
    description="Devour any document into readable Markdown (.md) and depict them in diagrams (flowcharts, swimlanes, BPMN).",
    version="0.1.0",
)


# ===========================================================================
# Stage 1: Document Discovery & Inspection Tools
# ===========================================================================

@mcp_app.tool()
def list_documents() -> List[Dict[str, Any]]:
    """
    Discover all locally ingested documents in the Injester workspace.
    Returns document IDs, filenames, chunk counts, and registration timestamps.
    """
    logger.info("Executing tool: list_documents")
    manager.ensure_initialized()
    return document_tools.list_documents()


@mcp_app.tool()
def inspect_document(document_id_or_path: str) -> Dict[str, Any]:
    """
    Inspect a document's structural properties, document type (Resume, Manual, Contract, etc.),
    block counts, and procedural step counts.
    """
    logger.info("Executing tool: inspect_document for: %s", document_id_or_path)
    manager.ensure_initialized()
    return document_tools.inspect_document(document_id_or_path)


@mcp_app.tool()
def get_document_structure(document_id_or_path: str) -> Dict[str, Any]:
    """
    Retrieve the hierarchical structural outline of a document: sections, headings,
    block IDs, text previews, and procedural workflow steps.
    """
    logger.info("Executing tool: get_document_structure for: %s", document_id_or_path)
    manager.ensure_initialized()
    return document_tools.get_document_structure(document_id_or_path)


@mcp_app.tool()
def find_blocks(
    document_id_or_path: str,
    query: Optional[str] = None,
    block_type: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Search blocks in a document matching a text query substring or block type (e.g. HEADING, PARAGRAPH, TABLE).
    Returns block IDs, content, and sequence indices for targeted edits.
    """
    logger.info("Executing tool: find_blocks for: %s (query='%s', type='%s')", document_id_or_path, query, block_type)
    manager.ensure_initialized()
    return document_tools.find_blocks(document_id_or_path, query=query, block_type=block_type)


@mcp_app.tool()
def get_block_content(
    document_id_or_path: str,
    block_id: str,
) -> Dict[str, Any]:
    """
    Retrieve detailed content, formatting properties (bold, italic, heading level),
    and source location for a specific block ID.
    """
    logger.info("Executing tool: get_block_content for: %s, block: %s", document_id_or_path, block_id)
    manager.ensure_initialized()
    return document_tools.get_block_content(document_id_or_path, block_id)


# ===========================================================================
# Stage 2: Change Proposal & Review Tools
# ===========================================================================

@mcp_app.tool()
def propose_text_edit(
    document_id_or_path: str,
    block_id: str,
    new_text: str,
    rationale: str = "",
) -> Dict[str, Any]:
    """
    Propose updating the text of a specific paragraph block.
    Generates a reviewable ChangeSet with impact analysis without modifying the source document.
    """
    logger.info("Executing tool: propose_text_edit on: %s, block: %s", document_id_or_path, block_id)
    manager.ensure_initialized()
    return document_tools.propose_text_edit(
        document_id_or_path=document_id_or_path,
        block_id=block_id,
        new_text=new_text,
        rationale=rationale,
    )


@mcp_app.tool()
def propose_section_reorder(
    document_id_or_path: str,
    heading_block_id: str,
    before_heading_block_id: Optional[str] = None,
    rationale: str = "",
) -> Dict[str, Any]:
    """
    Propose moving an entire section (heading and all enclosed blocks/tables) before another section.
    Returns a reviewable ChangeSet with structural validation.
    """
    logger.info("Executing tool: propose_section_reorder on: %s, heading: %s", document_id_or_path, heading_block_id)
    manager.ensure_initialized()
    return document_tools.propose_section_reorder(
        document_id_or_path=document_id_or_path,
        heading_block_id=heading_block_id,
        before_heading_block_id=before_heading_block_id,
        rationale=rationale,
    )


@mcp_app.tool()
def propose_block_move(
    document_id_or_path: str,
    step_id: str,
    before_step_id: Optional[str] = None,
    rationale: str = "",
) -> Dict[str, Any]:
    """
    Propose reordering a procedural step within its procedure scope.
    Checks step prerequisite dependencies and returns an auditable ChangeSet.
    """
    logger.info("Executing tool: propose_block_move on: %s, step: %s", document_id_or_path, step_id)
    manager.ensure_initialized()
    return document_tools.propose_block_move(
        document_id_or_path=document_id_or_path,
        step_id=step_id,
        before_step_id=before_step_id,
        rationale=rationale,
    )


@mcp_app.tool()
def get_changeset(changeset_id: str) -> Dict[str, Any]:
    """Retrieve details, status, and validation impact of a proposed ChangeSet."""
    logger.info("Executing tool: get_changeset for: %s", changeset_id)
    manager.ensure_initialized()
    return document_tools.get_changeset(changeset_id)


@mcp_app.tool()
def preview_changeset(changeset_id: str) -> Dict[str, Any]:
    """
    Generate a human-readable before-and-after diff preview for a proposed ChangeSet,
    highlighting affected blocks, text changes, and dependency validation.
    """
    logger.info("Executing tool: preview_changeset for: %s", changeset_id)
    manager.ensure_initialized()
    return document_tools.preview_changeset(changeset_id)


# ===========================================================================
# Stage 3: Approval, Application & Verification Tools
# ===========================================================================

@mcp_app.tool()
def approve_changeset(
    changeset_id: str,
    rationale: str = "",
    approval_token: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Authorize and approve a proposed ChangeSet.
    Security Boundary: In default manual mode, requires human authorization via approval_token
    (obtained from diff preview review in the Visual Workbench or CLI).
    Unattended autonomous execution requires explicit APPROVAL_MODE=unattended configuration.
    Computes an immutable HMAC-SHA256 signature binding the change payload to the active document version.
    """
    logger.info("Executing tool: approve_changeset for: %s (token_provided=%s)", changeset_id, bool(approval_token))
    manager.ensure_initialized()
    return document_tools.approve_changeset(
        changeset_id=changeset_id,
        rationale=rationale,
        approval_token=approval_token,
    )


@mcp_app.tool()
def apply_changeset(
    changeset_id: str,
    output_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Apply an APPROVED ChangeSet using surgical OOXML AST surgery and re-verify document integrity.
    Re-extracts the modified document and verifies that untouched blocks and styles remain intact.
    """
    logger.info("Executing tool: apply_changeset for: %s", changeset_id)
    manager.ensure_initialized()
    return document_tools.apply_changeset(changeset_id=changeset_id, output_path=output_path)


@mcp_app.tool()
def verify_document(
    source_path: str,
    recompiled_path: str,
    changeset_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Compare original and recompiled documents to verify block preservation,
    layout invariants, and absence of synthetic drift.
    """
    logger.info("Executing tool: verify_document comparing '%s' and '%s'", source_path, recompiled_path)
    manager.ensure_initialized()
    return document_tools.verify_document(
        source_path=source_path,
        recompiled_path=recompiled_path,
        changeset_id=changeset_id,
    )


@mcp_app.tool()
def get_change_report(changeset_id: str) -> Dict[str, Any]:
    """Retrieve the auditable verification report for an applied ChangeSet."""
    logger.info("Executing tool: get_change_report for: %s", changeset_id)
    manager.ensure_initialized()
    return document_tools.get_change_report(changeset_id)


@mcp_app.tool()
def ingest_document(path: str) -> Dict[str, Any]:
    """
    Ingest and index a local document (.pdf, .docx, .txt, .md, .pptx) into the workspace.
    Segments text into granular evidence spans and indexes them into the local FAISS vector store.
    """
    logger.info("Executing tool: ingest_document for path: %s", path)
    manager.ensure_initialized()
    file_path = Path(path).expanduser().resolve()
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    res = DocumentService().ingest(file_path)
    return {
        "status": "success",
        "document_id": res.doc_id,
        "filename": res.name,
        "format": res.format,
        "indexed_chunks": res.chunk_count,
        "file_size_bytes": res.file_size,
    }


@mcp_app.tool()
def search_evidence(query: str, top_k: int = 5) -> List[Dict[str, Any]]:
    """
    Find relevant evidence spans across indexed documents using semantic vector search.
    Returns text chunks with similarity scores and section provenance.
    """
    logger.info("Executing tool: search_evidence with query: '%s'", query)
    manager.ensure_initialized()
    results = RetrievalService().search(query=query, top_k=top_k)
    return [
        {
            "document_id": r.document_id,
            "chunk_id": r.chunk_id,
            "similarity_score": r.score,
            "section": r.section,
            "location": r.location,
            "text": r.text,
        }
        for r in results
    ]


@mcp_app.tool()
def generate_digest(topic: str, document_ids: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    Devour information and synthesize a readable, citation-grounded Markdown document (.md).
    Validates claim entailment against indexed evidence spans.
    """
    logger.info("Executing tool: generate_digest for topic: '%s'", topic)
    manager.ensure_initialized()
    res = DigestService().generate(topic=topic, file_ids=document_ids)
    return {
        "topic": res.topic,
        "is_valid": res.is_valid,
        "verified_citations_count": res.verified_citations_count,
        "errors": res.errors,
        "warnings": res.warnings,
        "markdown": res.markdown,
    }


@mcp_app.tool()
def generate_diagram(
    document_id_or_path: str,
    output_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Extract and depict diagrams (BPMN 2.0 XML, Mermaid flowcharts, swimlanes) from a devoured document.
    Outputs verified diagrams and quarantined defect registers.
    """
    logger.info("Executing tool: generate_diagram for: %s", document_id_or_path)
    manager.ensure_initialized()
    res = ProcessGraphService().generate(
        file_path_or_id=document_id_or_path,
        output_dir=output_dir,
    )
    return {
        "process_name": res.process_name,
        "objective": res.objective,
        "activities_count": res.activities_count,
        "gateways_count": res.gateways_count,
        "transitions_count": res.transitions_count,
        "actors_count": res.actors_count,
        "quarantined_defects_count": res.defects_count,
        "total_latency_seconds": res.total_latency_sec,
        "snapshot_id": res.snapshot_id,
        "generation_run_id": res.generation_run_id,
        "output_directory": res.output_dir,
    }


@mcp_app.tool()
def generate_process_graph(
    document_id_or_path: str,
    output_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Alias for generate_diagram."""
    return generate_diagram(document_id_or_path=document_id_or_path, output_dir=output_dir)


@mcp_app.tool()
def get_generation_result(run_id_or_snapshot_id: str) -> Dict[str, Any]:
    """
    Retrieve output, lineage, and validation details for a previous generation run or snapshot.
    """
    logger.info("Executing tool: get_generation_result for: %s", run_id_or_snapshot_id)
    manager.ensure_initialized()
    pipeline = manager.get_pipeline()
    sec_ctx = manager.sec_ctx()

    try:
        snapshot = pipeline.repo.get_process_graph_snapshot(sec_ctx, run_id_or_snapshot_id)
        return {
            "id": snapshot.id,
            "process_name": snapshot.process_name,
            "schema_version": snapshot.schema_version,
            "reasoner_model": snapshot.reasoner_model,
            "laya_model_version": snapshot.laya_model_version,
            "created_at": str(snapshot.created_at),
            "canonical_graph": snapshot.canonical_graph,
            "defect_register": snapshot.defect_register,
            "projections": list(snapshot.projections.keys()) if snapshot.projections else [],
        }
    except Exception:
        pass

    return {"error": f"Generation record '{run_id_or_snapshot_id}' not found."}


@mcp_app.tool()
def export_artifact(
    snapshot_id: str,
    format: str = "bpmn_xml",
) -> Dict[str, Any]:
    """
    Export a generated artifact for a process graph snapshot.
    Supported formats: 'bpmn_xml', 'flowchart_mermaid', 'swimlane_mermaid', 'defect_markdown'.
    """
    logger.info("Executing tool: export_artifact for snapshot: %s in format: %s", snapshot_id, format)
    manager.ensure_initialized()
    pipeline = manager.get_pipeline()
    sec_ctx = manager.sec_ctx()

    snapshot = pipeline.repo.get_process_graph_snapshot(sec_ctx, snapshot_id)
    projections = snapshot.projections or {}

    format_key = format.lower()
    if format_key in ("bpmn", "bpmn_xml", "bpmn_2_0.xml"):
        content = projections.get("bpmn_xml", "")
    elif format_key in ("mermaid", "flowchart", "flowchart_mermaid"):
        content = projections.get("mermaid", "")
    elif format_key in ("swimlane", "swimlane_mermaid"):
        content = projections.get("swimlane_mermaid", "")
    elif format_key in ("defect", "defect_markdown", "defect_register"):
        content = projections.get("defect_md", "")
    else:
        raise ValueError(f"Unsupported format: '{format}'. Allowed: bpmn_xml, flowchart_mermaid, swimlane_mermaid, defect_markdown")

    return {
        "snapshot_id": snapshot_id,
        "format": format_key,
        "content": content,
    }


def run_stdio_server():
    """Starts the MCP server over stdio transport."""
    logger.info("Initializing Beelzebuth / Injester stdio MCP server...")
    manager.ensure_initialized()
    mcp_app.run(transport="stdio")
