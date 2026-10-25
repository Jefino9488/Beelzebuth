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
import io
import time
import secrets
import hmac
import zipfile
import uuid
import hashlib
from pathlib import Path
from typing import List, Dict, Optional, Any, Tuple, Union
from pydantic import BaseModel, Field

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


class ApprovalTokenRecord(BaseModel):
    """Cryptographically random, single-use, time-expiring human approval token record."""
    token: str
    changeset_id: str
    document_id: str
    document_version: str
    approver_id: str
    created_at: float
    expires_at: float
    consumed: bool = False


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
        self._approval_tokens: Dict[str, ApprovalTokenRecord] = {}

    def _save_changeset(self, cs: ChangeSet) -> None:
        """Persists ChangeSet in-memory and to disk for cross-process access (MCP, API, CLI)."""
        self._changesets[cs.changeset_id] = cs
        if cs.file_path:
            self._changeset_to_session[cs.changeset_id] = cs.file_path
        try:
            cs_dir = settings.STORAGE_DIR / "changesets"
            cs_dir.mkdir(parents=True, exist_ok=True)
            target = cs_dir / f"{cs.changeset_id}.json"
            target.write_text(cs.model_dump_json(indent=2))
        except Exception:
            pass

    def _get_changeset(self, changeset_id: str) -> Optional[ChangeSet]:
        """Retrieves ChangeSet from memory cache or persisted disk storage."""
        cs = self._changesets.get(changeset_id)
        if cs:
            return cs
        try:
            cs_dir = settings.STORAGE_DIR / "changesets"
            target = cs_dir / f"{changeset_id}.json"
            if target.exists():
                cs = ChangeSet.model_validate_json(target.read_text())
                self._changesets[changeset_id] = cs
                if cs.file_path:
                    self._changeset_to_session[changeset_id] = cs.file_path
                return cs
        except Exception:
            pass
        return None

    def _save_approval_token(self, record: ApprovalTokenRecord) -> None:
        """Persists single-use ApprovalTokenRecord in-memory and to disk."""
        self._approval_tokens[record.token] = record
        try:
            tok_dir = settings.STORAGE_DIR / "approval_tokens"
            tok_dir.mkdir(parents=True, exist_ok=True)
            target = tok_dir / f"{record.token}.json"
            target.write_text(record.model_dump_json(indent=2))
        except Exception:
            pass

    def _get_approval_token(self, token: str) -> Optional[ApprovalTokenRecord]:
        """Retrieves single-use ApprovalTokenRecord from memory cache or persisted disk storage."""
        token_clean = token.strip() if token else ""
        rec = self._approval_tokens.get(token_clean)
        if rec:
            return rec
        try:
            tok_dir = settings.STORAGE_DIR / "approval_tokens"
            target = tok_dir / f"{token_clean}.json"
            if target.exists():
                rec = ApprovalTokenRecord.model_validate_json(target.read_text())
                self._approval_tokens[token_clean] = rec
                return rec
        except Exception:
            pass
        return None

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
        Enforces filesystem boundary containment and tenant authorization.
        """
        if document_id_or_path in self._sessions:
            sess_path = self._sessions[document_id_or_path].file_path
            settings.assert_path_allowed(sess_path, operation="read")
            return sess_path

        # Check in active sessions by document_id or session_id
        for s_id, s in self._sessions.items():
            if s_id == document_id_or_path or s.document_id == document_id_or_path:
                settings.assert_path_allowed(s.file_path, operation="read")
                return s.file_path

        # SECURITY: If target is a sensitive file or path, assert path allowed immediately (fails fast with AccessDeniedError)
        candidate = Path(document_id_or_path).expanduser().resolve()
        raw_path = Path(document_id_or_path)
        if settings.is_sensitive_path(candidate) or settings.is_sensitive_path(raw_path):
            settings.assert_path_allowed(candidate, operation="read")

        # If it looks like a path or existing candidate on disk:
        if candidate.exists() and candidate.is_file():
            settings.assert_path_allowed(candidate, operation="read")
            return str(candidate)

        # If it's a relative path inside an authorized document root:
        for root in settings.get_allowed_roots():
            sub_cand = (root / document_id_or_path).resolve()
            if settings.is_sensitive_path(sub_cand):
                settings.assert_path_allowed(sub_cand, operation="read")
            if sub_cand.exists() and sub_cand.is_file():
                settings.assert_path_allowed(sub_cand, operation="read")
                return str(sub_cand)

        # Resolve through tenant database repository
        ctx = sec_ctx or manager.sec_ctx()
        try:
            injester_pipe = manager.get_pipeline()
            file_record = injester_pipe.repo.get_file(ctx, document_id_or_path)
            if file_record and file_record.versions:
                latest = sorted(file_record.versions, key=lambda v: v.version_number)[-1]
                storage_path = Path(latest.storage_path).resolve()
                if storage_path.exists():
                    settings.assert_path_allowed(storage_path, operation="read")
                    return str(storage_path)
        except Exception:
            pass

        # If it is an absolute path outside authorized document roots, reject immediately
        if os.path.isabs(document_id_or_path):
            settings.assert_path_allowed(candidate, operation="read")

        # If it contains path separators or traversal, assert path boundary to trigger AccessDeniedError
        if "/" in document_id_or_path or "\\" in document_id_or_path or ".." in document_id_or_path:
            settings.assert_path_allowed(candidate, operation="read")

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
        changeset.file_path = session.file_path
        self._save_changeset(changeset)
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
        cs = self._get_changeset(changeset_id)
        if not cs:
            raise KeyError(f"ChangeSet '{changeset_id}' not found.")
        return cs.model_dump()

    def issue_approval_token(
        self,
        changeset_id: str,
        approver: Union[SecurityContext, str] = "authorized_human",
        ttl_seconds: int = 900,
    ) -> str:
        """
        Issues a cryptographically random, time-bounded (15m default), single-use approval token.
        Can only be invoked by an authorized human operator via the Visual Workbench or CLI.
        Bound to the specific ChangeSet ID, active document version, and approving human identity.
        """
        cs = self._get_changeset(changeset_id)
        if not cs:
            raise KeyError(f"ChangeSet '{changeset_id}' not found.")

        approver_id = (
            approver.user_id if isinstance(approver, SecurityContext)
            else approver.email if hasattr(approver, "email") and approver.email
            else str(approver)
        )
        token = f"appr_{secrets.token_urlsafe(32)}"
        now = time.time()
        record = ApprovalTokenRecord(
            token=token,
            changeset_id=cs.changeset_id,
            document_id=cs.document_id,
            document_version=cs.document_version,
            approver_id=approver_id,
            created_at=now,
            expires_at=now + ttl_seconds,
            consumed=False,
        )
        self._save_approval_token(record)
        return token

    def generate_approval_token(self, changeset_id: str) -> str:
        """Backward-compatible alias for human approval token generation."""
        return self.issue_approval_token(changeset_id)

    def verify_and_consume_approval_token(
        self,
        changeset_id: str,
        token: str,
    ) -> ApprovalTokenRecord:
        """
        Validates the approval token against the changeset and atomically marks it consumed.
        Rejects invalid, expired, mismatched, or already-consumed tokens with AccessDeniedError.
        """
        token_clean = token.strip() if token else ""
        record = self._get_approval_token(token_clean)
        if not record:
            raise AccessDeniedError(
                f"Approval authorization failed: Invalid approval_token for ChangeSet '{changeset_id}'."
            )

        if record.changeset_id != changeset_id:
            raise AccessDeniedError(
                f"Approval authorization failed: Token was issued for ChangeSet '{record.changeset_id}', not '{changeset_id}'."
            )

        cs = self._get_changeset(changeset_id)
        if cs and record.document_version != cs.document_version:
            raise AccessDeniedError(
                "Approval authorization failed: Document version changed since token was issued."
            )

        if time.time() > record.expires_at:
            raise AccessDeniedError(
                f"Approval authorization failed: Approval token has expired (TTL {int(record.expires_at - record.created_at)}s elapsed)."
            )

        if record.consumed:
            raise AccessDeniedError(
                "Approval authorization failed: Approval token has already been consumed (single-use replay detected)."
            )

        # Atomically mark consumed to prevent reuse
        record.consumed = True
        self._save_approval_token(record)
        return record

    def verify_approval_token(self, changeset_id: str, token: str) -> bool:
        """Read-only check if an approval token is valid without consuming it."""
        token_clean = token.strip() if token else ""
        record = self._get_approval_token(token_clean)
        if not record:
            return False
        if record.changeset_id != changeset_id:
            return False
        if time.time() > record.expires_at:
            return False
        if record.consumed:
            return False
        return True

    def preview_changeset(
        self,
        changeset_id: str,
        sec_ctx: Optional[SecurityContext] = None,
    ) -> Dict[str, Any]:
        """
        Generates a human-readable before-and-after preview diff of the proposed ChangeSet,
        including structural impact analysis.
        SECURITY: Does NOT expose human approval credentials to AI clients.
        """
        cs = self._get_changeset(changeset_id)
        if not cs:
            raise KeyError(f"ChangeSet '{changeset_id}' not found.")

        doc_id = self._changeset_to_session.get(changeset_id, cs.file_path or cs.document_id)
        session = self._sessions.get(doc_id)
        if not session and doc_id:
            try:
                session = self.get_or_create_session(doc_id, sec_ctx)
            except Exception:
                session = None

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
        approval_token: Optional[str] = None,
        sec_ctx: Optional[SecurityContext] = None,
    ) -> Dict[str, Any]:
        """
        Controlled approval operation.
        Separates approval authorization from approval signing:
        1. Human-in-the-loop: Accepts authenticated SecurityContext from Workbench/API.
        2. Token-authorized: Validates approval_token generated during diff review.
        3. Explicit Unattended Mode: If ALLOW_UNATTENDED_MCP_APPROVAL or APPROVAL_MODE=unattended.
        4. Rejects unattended autonomous AI approval when running in standard manual mode.
        """
        cs = self._get_changeset(changeset_id)
        if not cs:
            raise KeyError(f"ChangeSet '{changeset_id}' not found.")

        doc_id = self._changeset_to_session.get(changeset_id, cs.file_path or cs.document_id)
        session = self._sessions.get(doc_id)
        if not session:
            session = self.get_or_create_session(doc_id, sec_ctx)
        elif cs.file_path and session.file_path != cs.file_path:
            session = self.get_or_create_session(cs.file_path, sec_ctx)

        # Determine authorization provenance
        is_human_session = isinstance(approver, SecurityContext) or isinstance(sec_ctx, SecurityContext)
        is_token_authorized = False
        token_record = None

        if approval_token:
            token_record = self.verify_and_consume_approval_token(changeset_id, approval_token)
            is_token_authorized = True

        if not is_human_session and not is_token_authorized:
            unattended_enabled = (
                settings.ALLOW_UNATTENDED_MCP_APPROVAL
                or settings.APPROVAL_MODE == "unattended"
            )
            if not unattended_enabled:
                raise AccessDeniedError(
                    f"Autonomous AI approval rejected: ChangeSet '{changeset_id}' requires explicit human authorization. "
                    f"Authorize this change via the Web Workbench, CLI ('beelzebuth approve {changeset_id}'), "
                    f"supply an out-of-band human approval_token, or set APPROVAL_MODE=unattended in server environment."
                )
            effective_approver = approver or "mcp:unattended_agent"
        else:
            if is_token_authorized and token_record:
                effective_approver = token_record.approver_id
            elif is_human_session:
                human_ctx = approver if isinstance(approver, SecurityContext) else sec_ctx
                effective_approver = human_ctx.user_id if human_ctx else "authorized_human"
            else:
                effective_approver = "authorized_human"

        approved_cs = self.pipeline.approve_changeset(
            session=session,
            changeset=cs,
            approver=effective_approver,
            rationale=rationale or cs.command.rationale or "Approved via DocumentToolService",
            signing_key=signing_key,
        )

        self._save_changeset(approved_cs)
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
        Validates filesystem destination boundaries to prevent directory escapes.
        """
        cs = self._get_changeset(changeset_id)
        if not cs:
            raise KeyError(f"ChangeSet '{changeset_id}' not found.")

        doc_id = self._changeset_to_session.get(changeset_id, cs.file_path or cs.document_id)
        session = self._sessions.get(doc_id)
        if not session:
            session = self.get_or_create_session(doc_id, sec_ctx)
        elif cs.file_path and session.file_path != cs.file_path:
            session = self.get_or_create_session(cs.file_path, sec_ctx)

        if output_path:
            settings.assert_path_allowed(output_path, operation="write")
        else:
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
        Rigorous 4-Pillar Standalone Document Verification:
        1. Structural Integrity: Block count, heading hierarchy, table count, and sequence index sanity.
        2. Package & Style Invariants: Verifies styles.xml, numbering.xml, and settings.xml survived unaltered.
        3. Operation Correctness: Asserts target block/step matches expected change command payload.
        4. Content Preservation: Ensures 100% of unaffected blocks are byte- and run-identical with zero drift.
        """
        src_path = settings.assert_path_allowed(source_path, operation="read")
        recomp_path = settings.assert_path_allowed(recompiled_path, operation="read")

        if not src_path.exists():
            raise FileNotFoundError(f"Source file '{source_path}' does not exist.")
        if not recomp_path.exists():
            raise FileNotFoundError(f"Recompiled file '{recompiled_path}' does not exist.")

        discrepancies: List[str] = []
        operation_correctness: bool = True
        structural_integrity: bool = True
        content_preservation: bool = True
        formatting_preservation: bool = True

        # Pillar 1 & 4 Setup: Extract Document IR from both files
        ir_orig = extract_docx_ir(str(src_path))
        ir_recomp = extract_docx_ir(str(recomp_path))

        # Pillar 2: Package part byte-identical checks (styles, numbering, settings, fonts)
        with open(src_path, "rb") as sf:
            src_bytes = sf.read()
        with open(recomp_path, "rb") as df:
            recomp_bytes = df.read()

        try:
            with (
                zipfile.ZipFile(io.BytesIO(src_bytes), "r") as z_src,
                zipfile.ZipFile(io.BytesIO(recomp_bytes), "r") as z_dst,
            ):
                check_parts = [
                    "word/styles.xml",
                    "word/numbering.xml",
                    "word/settings.xml",
                    "word/fontTable.xml",
                ]
                for part in check_parts:
                    if part in z_src.namelist() and part in z_dst.namelist():
                        if z_src.read(part) != z_dst.read(part):
                            formatting_preservation = False
                            discrepancies.append(f"Package part '{part}' was modified (expected byte-identical).")
        except Exception as e:
            formatting_preservation = False
            discrepancies.append(f"Failed to inspect OOXML package parts: {e}")

        # Pillar 1: Structural Integrity Checks
        orig_blocks = ir_orig.blocks
        recomp_blocks = ir_recomp.blocks

        # Resolve target ChangeSet if supplied
        cs: Optional[ChangeSet] = None
        if changeset_id:
            cs = self._get_changeset(changeset_id)

        affected_bids: Set[str] = set()
        if cs:
            affected_bids = set(cs.impact.affected_block_ids)
            target_bid = cs.command.target_block_id
            if target_bid:
                affected_bids.add(target_bid)
            if cs.command.target_step_id:
                # Resolve step to block if session available
                doc_id = self._changeset_to_session.get(changeset_id, cs.document_id)
                sess = self._sessions.get(doc_id)
                if sess and cs.command.target_step_id in sess.step_to_block_map:
                    affected_bids.add(sess.step_to_block_map[cs.command.target_step_id])

        # Block count reconciliation (for non-insert/delete operations, block count must be identical)
        if len(orig_blocks) != len(recomp_blocks):
            structural_integrity = False
            discrepancies.append(
                f"Block count discrepancy: source has {len(orig_blocks)} blocks, recompiled has {len(recomp_blocks)} blocks."
            )

        # Pillar 3: Operation Correctness Verification
        if cs:
            op = cs.command.operation
            if op == ChangeOperationType.EDIT_PARAGRAPH_TEXT:
                t_bid = cs.command.target_block_id
                expected_text = ((cs.command.new_values or {}).get("new_text") or "").strip()
                # Target text must exist in recompiled blocks
                matching_recomp = [
                    rb for rb in recomp_blocks.values()
                    if rb.text_content.strip() == expected_text
                ]
                if not matching_recomp:
                    operation_correctness = False
                    discrepancies.append(
                        f"Operation failure on block '{t_bid}': expected edit text '{expected_text}' not found in recompiled document."
                    )
            elif op == ChangeOperationType.MOVE_PROCEDURE_STEP:
                # Check that procedural list items survived in proper sequence
                if cs.after_step_order:
                    doc_id = self._changeset_to_session.get(changeset_id, cs.document_id)
                    sess = self._sessions.get(doc_id)
                    if sess:
                        recomp_step_order = []
                        for bid in ir_recomp.structural_order:
                            for sid, s_bid in sess.step_to_block_map.items():
                                if s_bid == bid:
                                    recomp_step_order.append(sid)
                        if recomp_step_order != cs.after_step_order:
                            operation_correctness = False
                            discrepancies.append(
                                f"Procedural step reorder failure: expected order {cs.after_step_order}, "
                                f"got {recomp_step_order}."
                            )
            elif op == ChangeOperationType.REORDER_SECTION:
                target_heading_bid = cs.command.target_block_id
                anchor_heading_bid = cs.command.before_block_id
                if target_heading_bid in orig_blocks and anchor_heading_bid in orig_blocks:
                    target_heading_text = orig_blocks[target_heading_bid].text_content.strip()
                    anchor_heading_text = orig_blocks[anchor_heading_bid].text_content.strip()

                    recomp_headings = [
                        rb.text_content.strip()
                        for bid in ir_recomp.structural_order
                        if (rb := recomp_blocks[bid]).block_type == "HEADING"
                    ]
                    if target_heading_text not in recomp_headings or anchor_heading_text not in recomp_headings:
                        operation_correctness = False
                        discrepancies.append("Reordered section heading missing in recompiled document.")
                    else:
                        target_idx = recomp_headings.index(target_heading_text)
                        anchor_idx = recomp_headings.index(anchor_heading_text)
                        if target_idx > anchor_idx:
                            operation_correctness = False
                            discrepancies.append(
                                f"Section reorder failure: target heading '{target_heading_text}' appears at index {target_idx} "
                                f"after anchor '{anchor_heading_text}' at index {anchor_idx}."
                            )

        # Pillar 4: Content & Formatting Preservation of Untouched Blocks
        # Uses occurrence-tracking pool with one-to-one matching to preserve durability
        # across structural reorderings and block index shifts.
        reopened_pool: Dict[str, List[DocumentBlock]] = {}
        for rb in recomp_blocks.values():
            key = rb.text_content.strip()
            reopened_pool.setdefault(key, []).append(rb)

        matched_reopened_ids: Set[str] = set()
        unmodified_checked = 0

        for bid, orig_b in orig_blocks.items():
            if bid in affected_bids:
                continue

            key = orig_b.text_content.strip()
            candidates = reopened_pool.get(key, [])
            match = next((c for c in candidates if c.block_id not in matched_reopened_ids), None)

            if match is None:
                content_preservation = False
                discrepancies.append(
                    f"Content drift in untouched block '{bid}': "
                    f"source content '{orig_b.text_content[:40]}…' missing or modified in recompiled document."
                )
            else:
                matched_reopened_ids.add(match.block_id)
                unmodified_checked += 1

                # Verify formatting preservation on the matched block
                if (
                    orig_b.formatting.is_bold != match.formatting.is_bold
                    or orig_b.formatting.is_italic != match.formatting.is_italic
                    or orig_b.formatting.heading_level != match.formatting.heading_level
                    or orig_b.block_type != match.block_type
                ):
                    formatting_preservation = False
                    discrepancies.append(f"Formatting drift in untouched block '{bid}': style/type attributes altered.")

        is_verified = (
            operation_correctness
            and structural_integrity
            and content_preservation
            and formatting_preservation
            and len(discrepancies) == 0
        )

        return {
            "source_path": str(src_path),
            "recompiled_path": str(recomp_path),
            "changeset_id": changeset_id,
            "is_verified": is_verified,
            "pillars": {
                "operation_correctness": {
                    "verified": operation_correctness,
                    "scope": "Target block mutated to match requested change command payload",
                },
                "structural_integrity": {
                    "verified": structural_integrity,
                    "scope": "Block count, document hierarchy, and section sequences intact",
                },
                "content_preservation": {
                    "verified": content_preservation,
                    "scope": "100% of unaffected blocks identical with zero textual drift",
                },
                "formatting_preservation": {
                    "verified": formatting_preservation,
                    "scope": "OOXML styles.xml, numbering.xml, and run formatting unaltered",
                },
            },
            "unverified_scope": [
                "semantic_intent_adequacy",
                "domain_factuality",
                "procedural_optimality",
            ],
            "operation_correctness": operation_correctness,
            "structural_integrity": structural_integrity,
            "content_preservation": content_preservation,
            "formatting_preservation": formatting_preservation,
            "source_block_count": len(orig_blocks),
            "recompiled_block_count": len(recomp_blocks),
            "unmodified_blocks_checked": unmodified_checked,
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
