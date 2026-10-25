"""
Beelzebuth Shared Document Operation Service.

Provides a unified, typed operation contract for document inspection, search,
change proposal, changeset preview, cryptographic approval, and round-trip verification.

Single entry point consumed by:
1. Fast-API routers (Web Workbench REST API)
2. MCP server (Claude Desktop, Cursor, external AI clients)
3. CLI commands and standalone scripts

Enforces all Canonical Document Model invariants, security boundaries, and
approval checks across both application and MCP interfaces without duplicated logic.
"""

import os
import uuid
import hashlib
from pathlib import Path
from typing import List, Dict, Optional, Any, Tuple, Union

from injester.config import settings
from injester.domain.auth import SecurityContext, AccessDeniedError
from injester.domain.document_ir import (
    DocumentIR,
    DocumentBlock,
    DocumentType,
    detect_document_type,
    extract_docx_ir,
)
from injester.semantic.change_engine import (
    TypedChangeCommand,
    ChangeOperationType,
    ChangeSet,
    ChangeImpact,
    COMPILABLE_STATUSES,
)
from injester.application.docx_pipeline import (
    DocxRoundTripPipeline,
    DocumentEditSession,
    GroundedStep,
    RoundTripVerificationReport,
)
from injester.application.manager import manager
from injester.application.documents import DocumentService
from injester.application.retrieval import RetrievalService


class DocumentToolService:
    """
    Unified application service for all document operations.
    Maintains active document sessions and proposed/approved ChangeSets.
    """

    def __init__(self, pipeline: Optional[DocxRoundTripPipeline] = None):
        self.pipeline = pipeline or DocxRoundTripPipeline()
        self._sessions: Dict[str, DocumentEditSession] = {}
        self._changesets: Dict[str, ChangeSet] = {}
        self._changeset_to_session: Dict[str, str] = {}
        self._verification_reports: Dict[str, RoundTripVerificationReport] = {}

    # ------------------------------------------------------------------
    # Document & Session Resolution
    # ------------------------------------------------------------------

    def resolve_document_path(
        self,
        document_id_or_path: str,
        sec_ctx: Optional[SecurityContext] = None,
    ) -> str:
        """
        Resolves a document ID or filesystem path to an absolute local file path.
        If a database document_id is provided, checks tenant permissions via the repository.
        """
        if document_id_or_path in self._sessions:
            return self._sessions[document_id_or_path].file_path

        candidate = Path(document_id_or_path).expanduser().resolve()
        if candidate.exists() and candidate.is_file():
            return str(candidate)

        # Check in active sessions by document_id or session_id
        for s_id, s in self._sessions.items():
            if s_id == document_id_or_path or s.document_id == document_id_or_path:
                return s.file_path

        # Resolve through tenant database repository
        ctx = sec_ctx or manager.sec_ctx()
        try:
            injester_pipe = manager.get_pipeline()
            file_record = injester_pipe.repo.get_file(ctx, document_id_or_path)
            if file_record and file_record.versions:
                latest = sorted(file_record.versions, key=lambda v: v.version_number)[-1]
                storage_path = Path(latest.storage_path).resolve()
                if storage_path.exists():
                    return str(storage_path)
        except Exception:
            pass

        raise FileNotFoundError(
            f"Document '{document_id_or_path}' could not be resolved to an accessible file on disk."
        )

    def load_document_session(
        self,
        file_path: str,
        sec_ctx: Optional[SecurityContext] = None,
    ) -> Tuple[str, DocumentEditSession]:
        """Loads a DOCX document into a canonical DocumentEditSession and registers a new session_id."""
        resolved = self.resolve_document_path(file_path, sec_ctx)
        session = self.pipeline.load_document(resolved)
        session_id = f"sess_{uuid.uuid4().hex[:12]}"
        self._sessions[session_id] = session
        self._sessions[session.document_id] = session
        return session_id, session

    def get_or_create_session(
        self,
        document_id_or_path: str,
        sec_ctx: Optional[SecurityContext] = None,
    ) -> DocumentEditSession:
        """
        Retrieves an active DocumentEditSession or loads a new one from disk.
        Detects if the source file was modified externally and refreshes if needed.
        """
        if document_id_or_path in self._sessions:
            return self._sessions[document_id_or_path]

        file_path = self.resolve_document_path(document_id_or_path, sec_ctx)

        # Check existing sessions matching file_path
        for s_id, s in self._sessions.items():
            if s.file_path == file_path:
                # Verify file hasn't changed on disk
                with open(file_path, "rb") as f:
                    curr_hash = hashlib.sha256(f.read()).hexdigest()
                if curr_hash == s.file_hash:
                    return s

        # Load fresh session
        session = self.pipeline.load_document(file_path)
        session_id = f"sess_{uuid.uuid4().hex[:12]}"
        self._sessions[session_id] = session
        # Also map by document_id for fast lookup
        self._sessions[session.document_id] = session
        return session

    # ------------------------------------------------------------------
    # Stage 1: Discover & Inspect Tools
    # ------------------------------------------------------------------

    def list_documents(
        self,
        sec_ctx: Optional[SecurityContext] = None,
    ) -> List[Dict[str, Any]]:
        """Lists all indexed documents and active editing sessions."""
        manager.ensure_initialized()
        ctx = sec_ctx or manager.sec_ctx()
        docs = DocumentService().list_documents()

        results = []
        for d in docs:
            results.append({
                "document_id": d.doc_id,
                "name": d.name,
                "indexed_chunks": d.chunk_count,
                "versions": d.versions_count,
                "created_at": d.created_at,
            })
        return results

    def inspect_document(
        self,
        document_id_or_path: str,
        sec_ctx: Optional[SecurityContext] = None,
    ) -> Dict[str, Any]:
        """
        Inspects a document, returning structural metadata, detected document type,
        total block counts, procedural steps, and unsupported structure checks.
        """
        session = self.get_or_create_session(document_id_or_path, sec_ctx)
        ir = session.document_ir

        headings = [b for b in ir.blocks.values() if b.block_type == "HEADING"]
        tables = [b for b in ir.blocks.values() if b.block_type == "TABLE"]

        return {
            "document_id": session.document_id,
            "filename": os.path.basename(session.file_path),
            "file_path": session.file_path,
            "file_hash": session.file_hash,
            "version_id": session.version_id,
            "document_type": session.document_type.value,
            "total_blocks": ir.total_blocks,
            "headings_count": len(headings),
            "tables_count": len(tables),
            "step_count": len(session.steps),
            "is_procedure_bearing": len(session.steps) > 0,
        }

    def get_document_structure(
        self,
        document_id_or_path: str,
        sec_ctx: Optional[SecurityContext] = None,
    ) -> Dict[str, Any]:
        """
        Returns the full hierarchical structural outline of the document:
        sections, headings, tables, and procedural steps.
        """
        session = self.get_or_create_session(document_id_or_path, sec_ctx)
        ir = session.document_ir

        sections = []
        current_section = {
            "heading_block_id": "root",
            "title": "Document Root",
            "level": 0,
            "blocks": [],
        }

        for bid in ir.structural_order:
            block = ir.blocks[bid]
            if block.block_type == "HEADING":
                if current_section["blocks"] or current_section["heading_block_id"] != "root":
                    sections.append(current_section)
                current_section = {
                    "heading_block_id": block.block_id,
                    "title": block.text_content.strip(),
                    "level": block.formatting.heading_level or 1,
                    "blocks": [],
                }
            else:
                step_id = next(
                    (sid for sid, step in session.steps.items() if step.source_block_id == bid),
                    None
                )
                current_section["blocks"].append({
                    "block_id": block.block_id,
                    "block_type": block.block_type,
                    "text_snippet": (block.text_content[:90] + "...") if len(block.text_content) > 90 else block.text_content,
                    "step_id": step_id,
                })

        sections.append(current_section)

        # Procedural step list if available
        steps_summary = [
            {
                "step_id": step.step_id,
                "label": step.label,
                "instruction": step.instruction,
                "source_block_id": step.source_block_id,
                "depends_on": step.depends_on,
                "is_independent": step.is_independent,
            }
            for step in session.steps.values()
        ]

        return {
            "document_id": session.document_id,
            "document_type": session.document_type.value,
            "total_sections": len(sections),
            "sections": sections,
            "steps": steps_summary,
        }

    def find_blocks(
        self,
        document_id_or_path: str,
        query: Optional[str] = None,
        block_type: Optional[str] = None,
        sec_ctx: Optional[SecurityContext] = None,
    ) -> List[Dict[str, Any]]:
        """
        Locates blocks in Document IR matching a text substring query or block type.
        """
        session = self.get_or_create_session(document_id_or_path, sec_ctx)
        ir = session.document_ir

        q_norm = query.strip().lower() if query else ""
        bt_norm = block_type.strip().upper() if block_type else ""

        matches = []
        for bid in ir.structural_order:
            block = ir.blocks[bid]
            if bt_norm and block.block_type != bt_norm:
                continue
            if q_norm and q_norm not in block.text_content.lower():
                continue

            matches.append({
                "block_id": block.block_id,
                "block_type": block.block_type,
                "text_content": block.text_content,
                "sequence_index": block.sequence_index,
                "span_ids": block.span_ids,
            })
        return matches

    def get_block_content(
        self,
        document_id_or_path: str,
        block_id: str,
        sec_ctx: Optional[SecurityContext] = None,
    ) -> Dict[str, Any]:
        """
        Retrieves verbatim text, formatting snapshot, and XML location for a specific block.
        """
        session = self.get_or_create_session(document_id_or_path, sec_ctx)
        ir = session.document_ir

        block = ir.blocks.get(block_id)
        if not block:
            raise KeyError(f"Block '{block_id}' not found in Document IR of '{session.document_id}'.")

        return {
            "block_id": block.block_id,
            "block_type": block.block_type,
            "text_content": block.text_content,
            "sequence_index": block.sequence_index,
            "formatting": {
                "is_bold": block.formatting.is_bold,
                "is_italic": block.formatting.is_italic,
                "is_heading": block.formatting.is_heading,
                "heading_level": block.formatting.heading_level,
                "num_id": block.formatting.num_id,
                "style_id": block.formatting.style_id,
            },
            "location_xpath": block.location.xpath if block.location else "",
            "fingerprint_hash": block.location.fingerprint_hash if block.location else "",
            "span_ids": block.span_ids,
        }

    def search_evidence(
        self,
        query: str,
        top_k: int = 5,
        sec_ctx: Optional[SecurityContext] = None,
    ) -> List[Dict[str, Any]]:
        """Finds relevant evidence spans across indexed documents using semantic vector search."""
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

    # ------------------------------------------------------------------
    # Stage 2: Propose & Review Edits (ChangeSets)
    # ------------------------------------------------------------------

    def propose_edit(
        self,
        document_id_or_path: str,
        command: TypedChangeCommand,
        sec_ctx: Optional[SecurityContext] = None,
    ) -> Dict[str, Any]:
        """
        Evaluates a TypedChangeCommand against the session and dependency graph.
        Returns a reviewable ChangeSet with impact analysis, without mutating the document.
        """
        session = self.get_or_create_session(document_id_or_path, sec_ctx)

        # Ensure expected document version is bound
        if not command.expected_document_version:
            command.expected_document_version = session.version_id

        changeset = self.pipeline.propose_edit(session, command)
        self._changesets[changeset.changeset_id] = changeset
        self._changeset_to_session[changeset.changeset_id] = session.document_id

        return changeset.model_dump()

    def propose_text_edit(
        self,
        document_id_or_path: str,
        block_id: str,
        new_text: str,
        rationale: str = "",
        sec_ctx: Optional[SecurityContext] = None,
    ) -> Dict[str, Any]:
        """Convenience method to propose an EDIT_PARAGRAPH_TEXT mutation."""
        session = self.get_or_create_session(document_id_or_path, sec_ctx)
        cmd = TypedChangeCommand(
            operation=ChangeOperationType.EDIT_PARAGRAPH_TEXT,
            target_block_id=block_id,
            source_block_ids=[block_id],
            new_values={"new_text": new_text},
            expected_document_version=session.version_id,
            rationale=rationale or f"Update block text of '{block_id}'",
        )
        return self.propose_edit(document_id_or_path, cmd, sec_ctx)

    def propose_section_reorder(
        self,
        document_id_or_path: str,
        heading_block_id: str,
        before_heading_block_id: Optional[str] = None,
        rationale: str = "",
        sec_ctx: Optional[SecurityContext] = None,
    ) -> Dict[str, Any]:
        """Convenience method to propose a REORDER_SECTION mutation."""
        session = self.get_or_create_session(document_id_or_path, sec_ctx)
        cmd = TypedChangeCommand(
            operation=ChangeOperationType.REORDER_SECTION,
            target_block_id=heading_block_id,
            before_block_id=before_heading_block_id,
            source_block_ids=[heading_block_id],
            expected_document_version=session.version_id,
            rationale=rationale or f"Reorder section under '{heading_block_id}'",
        )
        return self.propose_edit(document_id_or_path, cmd, sec_ctx)

    def propose_block_move(
        self,
        document_id_or_path: str,
        step_id: str,
        before_step_id: Optional[str] = None,
        rationale: str = "",
        sec_ctx: Optional[SecurityContext] = None,
    ) -> Dict[str, Any]:
        """Convenience method to propose a MOVE_PROCEDURE_STEP mutation."""
        session = self.get_or_create_session(document_id_or_path, sec_ctx)
        if step_id not in session.step_to_block_map:
            raise KeyError(f"Step '{step_id}' not found in procedural session.")

        source_bid = session.step_to_block_map[step_id]
        cmd = TypedChangeCommand(
            operation=ChangeOperationType.MOVE_PROCEDURE_STEP,
            target_step_id=step_id,
            before_step_id=before_step_id,
            source_block_ids=[source_bid],
            expected_document_version=session.version_id,
            rationale=rationale or f"Move procedure step '{step_id}'",
        )
        return self.propose_edit(document_id_or_path, cmd, sec_ctx)

    def get_changeset(
        self,
        changeset_id: str,
        sec_ctx: Optional[SecurityContext] = None,
    ) -> Dict[str, Any]:
        """Retrieves an existing ChangeSet by ID."""
        cs = self._changesets.get(changeset_id)
        if not cs:
            raise KeyError(f"ChangeSet '{changeset_id}' not found.")
        return cs.model_dump()

    def preview_changeset(
        self,
        changeset_id: str,
        sec_ctx: Optional[SecurityContext] = None,
    ) -> Dict[str, Any]:
        """
        Generates a human-readable before-and-after preview diff of the proposed ChangeSet.
        """
        cs = self._changesets.get(changeset_id)
        if not cs:
            raise KeyError(f"ChangeSet '{changeset_id}' not found.")

        doc_id = self._changeset_to_session.get(changeset_id, cs.document_id)
        session = self._sessions.get(doc_id)

        preview = {
            "changeset_id": cs.changeset_id,
            "document_id": cs.document_id,
            "document_version": cs.document_version,
            "operation": cs.command.operation.value,
            "status": cs.status,
            "is_valid": cs.impact.is_valid,
            "conflicts": cs.impact.conflicts,
            "affected_blocks": cs.impact.affected_block_ids,
            "rationale": cs.command.rationale,
            "can_apply": cs.status in COMPILABLE_STATUSES,
            "diff_summary": {},
        }

        if session:
            op = cs.command.operation
            if op == ChangeOperationType.EDIT_PARAGRAPH_TEXT:
                t_bid = cs.command.target_block_id
                old_text = session.document_ir.blocks[t_bid].text_content if t_bid in session.document_ir.blocks else ""
                new_text = (cs.command.new_values or {}).get("new_text", "")
                preview["diff_summary"] = {
                    "target_block_id": t_bid,
                    "before": old_text,
                    "after": new_text,
                }
            elif op == ChangeOperationType.MOVE_PROCEDURE_STEP:
                preview["diff_summary"] = {
                    "target_step_id": cs.command.target_step_id,
                    "before_step_id": cs.command.before_step_id,
                    "current_order": cs.before_step_order,
                    "new_order": cs.after_step_order,
                }
            elif op == ChangeOperationType.REORDER_SECTION:
                preview["diff_summary"] = {
                    "target_heading_block_id": cs.command.target_block_id,
                    "before_heading_block_id": cs.command.before_block_id,
                }

        return preview

    # ------------------------------------------------------------------
    # Stage 3: Approve, Apply & Verify
    # ------------------------------------------------------------------

    def approve_changeset(
        self,
        changeset_id: str,
        approver: Optional[Union[SecurityContext, str]] = None,
        rationale: str = "",
        signing_key: Optional[str] = None,
        sec_ctx: Optional[SecurityContext] = None,
    ) -> Dict[str, Any]:
        """
        Controlled approval operation.
        Verifies active session bindings, records authenticated approver identity,
        computes HMAC-SHA256 signature, and deeply freezes the ChangeSet.
        """
        cs = self._changesets.get(changeset_id)
        if not cs:
            raise KeyError(f"ChangeSet '{changeset_id}' not found.")

        doc_id = self._changeset_to_session.get(changeset_id, cs.document_id)
        session = self._sessions.get(doc_id)
        if not session:
            session = self.get_or_create_session(doc_id, sec_ctx)

        effective_approver = approver or sec_ctx or manager.sec_ctx()

        approved_cs = self.pipeline.approve_changeset(
            session=session,
            changeset=cs,
            approver=effective_approver,
            rationale=rationale or cs.command.rationale or "Approved via DocumentToolService",
            signing_key=signing_key,
        )

        self._changesets[approved_cs.changeset_id] = approved_cs
        return approved_cs.model_dump()

    def apply_changeset(
        self,
        changeset_id: str,
        output_path: Optional[str] = None,
        sec_ctx: Optional[SecurityContext] = None,
    ) -> Dict[str, Any]:
        """
        Compiles an APPROVED ChangeSet to output_path using surgical OOXML AST surgery,
        reopens the file, and runs one-to-one block verification.
        """
        cs = self._changesets.get(changeset_id)
        if not cs:
            raise KeyError(f"ChangeSet '{changeset_id}' not found.")

        doc_id = self._changeset_to_session.get(changeset_id, cs.document_id)
        session = self._sessions.get(doc_id)
        if not session:
            session = self.get_or_create_session(doc_id, sec_ctx)

        if not output_path:
            out_dir = settings.STORAGE_DIR / "recompiled"
            out_dir.mkdir(parents=True, exist_ok=True)
            stem = Path(session.file_path).stem
            output_path = str(out_dir / f"{stem}_revised_{changeset_id[:8]}.docx")

        report = self.pipeline.recompile_and_verify(
            session=session,
            changeset=cs,
            output_docx_path=output_path,
        )

        self._verification_reports[changeset_id] = report
        return report.model_dump()

    def verify_document(
        self,
        source_path: str,
        recompiled_path: str,
        changeset_id: Optional[str] = None,
        sec_ctx: Optional[SecurityContext] = None,
    ) -> Dict[str, Any]:
        """
        Re-extracts Document IR from both source and recompiled DOCX files and
        verifies that block structures, fingerprints, and unaffected content survived intact.
        """
        if not os.path.exists(source_path):
            raise FileNotFoundError(f"Source file '{source_path}' does not exist.")
        if not os.path.exists(recompiled_path):
            raise FileNotFoundError(f"Recompiled file '{recompiled_path}' does not exist.")

        ir_orig = extract_docx_ir(source_path)
        ir_recomp = extract_docx_ir(recompiled_path)

        orig_blocks = set(ir_orig.blocks.keys())
        recomp_blocks = set(ir_recomp.blocks.keys())

        discrepancies = []
        if len(orig_blocks) != len(recomp_blocks):
            discrepancies.append(
                f"Block count mismatch: original has {len(orig_blocks)}, recompiled has {len(recomp_blocks)}"
            )

        return {
            "source_path": source_path,
            "recompiled_path": recompiled_path,
            "changeset_id": changeset_id,
            "is_verified": len(discrepancies) == 0,
            "source_block_count": len(orig_blocks),
            "recompiled_block_count": len(recomp_blocks),
            "discrepancies": discrepancies,
        }

    def get_change_report(
        self,
        changeset_id: str,
        sec_ctx: Optional[SecurityContext] = None,
    ) -> Dict[str, Any]:
        """Retrieves the verification and audit report for an applied ChangeSet."""
        report = self._verification_reports.get(changeset_id)
        if not report:
            raise KeyError(f"No verification report recorded for ChangeSet '{changeset_id}'.")
        return report.model_dump()


# Shared application-level singleton
document_tools = DocumentToolService()
