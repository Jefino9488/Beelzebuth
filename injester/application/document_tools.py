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
import json
import re
import logging
import secrets
import hmac
import zipfile
import uuid
import hashlib
import sqlite3
from pathlib import Path
from typing import List, Dict, Optional, Any, Tuple, Union
from pydantic import BaseModel, Field

logger = logging.getLogger("injester.document_tools")

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
    token_hash: str
    changeset_id: str
    document_id: str
    document_version: str
    approver_id: str
    created_at: float
    expires_at: float
    consumed: bool = False
    consumed_at: Optional[float] = None
    token: Optional[str] = None


CHANGESET_ID_REGEX = re.compile(r"^[a-zA-Z0-9_\-]{1,64}$")


def validate_changeset_id(changeset_id: str) -> Path:
    """
    Validates ChangeSet ID against expected format and prevents filesystem path traversal.
    Returns the resolved Path inside settings.STORAGE_DIR / 'changesets'.
    Raises ValueError if the ID is invalid or resolves outside the changesets directory.
    """
    if not changeset_id or not isinstance(changeset_id, str):
        raise ValueError("ChangeSet ID must be a non-empty string.")

    cleaned_id = changeset_id.strip()
    if not CHANGESET_ID_REGEX.match(cleaned_id):
        raise ValueError(
            f"Invalid ChangeSet ID format: '{changeset_id}'. "
            f"ChangeSet IDs must be 1-64 characters matching [a-zA-Z0-9_-]."
        )

    cs_dir = (settings.STORAGE_DIR / "changesets").resolve()
    cs_dir.mkdir(parents=True, exist_ok=True)
    target = (cs_dir / f"{cleaned_id}.json").resolve()

    if not target.is_relative_to(cs_dir):
        raise ValueError(
            f"Security Violation: ChangeSet ID '{changeset_id}' resolved to path outside changesets directory."
        )

    return target


def _get_token_db_path() -> Path:
    return settings.WORKSPACE_DIR / "injester.db"


def _connect_token_db() -> sqlite3.Connection:
    """Provides a transactional SQLite connection with WAL mode and schema initialization."""
    db_path = _get_token_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=30.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=5000;")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS approval_tokens (
            token_hash VARCHAR(64) PRIMARY KEY,
            changeset_id VARCHAR(64) NOT NULL,
            document_id VARCHAR(255) NOT NULL,
            document_version VARCHAR(64) NOT NULL,
            approver_id VARCHAR(255) NOT NULL,
            created_at REAL NOT NULL,
            expires_at REAL NOT NULL,
            consumed INTEGER DEFAULT 0 NOT NULL,
            consumed_at REAL
        );
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_approval_tokens_cs ON approval_tokens(changeset_id);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_approval_tokens_exp ON approval_tokens(expires_at);")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS changesets (
            changeset_id VARCHAR(64) PRIMARY KEY,
            document_id VARCHAR(255) NOT NULL,
            document_version VARCHAR(64) NOT NULL,
            status VARCHAR(32) NOT NULL,
            file_path TEXT,
            payload_json TEXT NOT NULL,
            version INTEGER DEFAULT 1 NOT NULL,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        );
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_changesets_doc ON changesets(document_id);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_changesets_status ON changesets(status);")
    conn.commit()
    return conn

_connect_db = _connect_token_db


class DocumentToolService:
    """
    Unified application service for all document operations.
    Maintains active document sessions and proposed/approved ChangeSets.
    Uses authoritative transactional SQLite persistence with optimistic locking
    to synchronize state consistently across MCP, Web Workbench, and CLI processes.
    """

    def __init__(self, pipeline: Optional[DocxRoundTripPipeline] = None):
        self.pipeline = pipeline or DocxRoundTripPipeline()
        self._sessions: Dict[str, DocumentEditSession] = {}
        self._changesets: Dict[str, ChangeSet] = {}
        self._changeset_versions: Dict[str, int] = {}
        self._changeset_mtimes: Dict[str, float] = {}
        self._changeset_to_session: Dict[str, str] = {}
        self._verification_reports: Dict[str, RoundTripVerificationReport] = {}

    def _save_changeset(self, cs: ChangeSet) -> None:
        """
        Persists ChangeSet to transactional SQLite storage and disk JSON with optimistic versioning.
        Authoritative persistent store prevents cross-process race conditions and stale overwrites.
        """
        target = validate_changeset_id(cs.changeset_id)
        payload_json = cs.model_dump_json(indent=2)
        now = time.time()

        try:
            with _connect_db() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT version, status FROM changesets WHERE changeset_id = ?",
                    (cs.changeset_id,)
                )
                row = cursor.fetchone()
                if not row:
                    new_version = 1
                    cursor.execute(
                        """
                        INSERT INTO changesets (
                            changeset_id, document_id, document_version, status,
                            file_path, payload_json, version, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (cs.changeset_id, cs.document_id, cs.document_version, cs.status,
                         cs.file_path, payload_json, new_version, now, now)
                    )
                else:
                    curr_version, curr_status = row
                    known_version = self._changeset_versions.get(cs.changeset_id)
                    # Optimistic concurrency check: if local cache is behind database, reject overwrite
                    if known_version is not None and known_version < curr_version:
                        raise RuntimeError(
                            f"Concurrent modification conflict: ChangeSet '{cs.changeset_id}' was updated by another process "
                            f"(local version: {known_version}, persistent store version: {curr_version}, status: '{curr_status}')."
                        )
                    new_version = curr_version + 1
                    cursor.execute(
                        """
                        UPDATE changesets
                        SET document_version = ?, status = ?, file_path = ?,
                            payload_json = ?, version = ?, updated_at = ?
                        WHERE changeset_id = ? AND version = ?
                        """,
                        (cs.document_version, cs.status, cs.file_path,
                         payload_json, new_version, now, cs.changeset_id, curr_version)
                    )
                    if cursor.rowcount != 1:
                        raise RuntimeError(
                            f"Concurrent modification race condition: ChangeSet '{cs.changeset_id}' was updated concurrently."
                        )
                conn.commit()
        except (RuntimeError, ValueError):
            raise
        except Exception as e:
            raise RuntimeError(f"Database error persisting ChangeSet '{cs.changeset_id}': {e}") from e

        # Also write to disk JSON for export and transparent human inspection
        target.write_text(payload_json)

        # Update local memory cache with authoritative version
        self._changesets[cs.changeset_id] = cs
        self._changeset_versions[cs.changeset_id] = new_version
        self._changeset_mtimes[cs.changeset_id] = target.stat().st_mtime
        if cs.file_path:
            self._changeset_to_session[cs.changeset_id] = cs.file_path

    def _get_changeset(self, changeset_id: str) -> Optional[ChangeSet]:
        """
        Retrieves ChangeSet from authoritative transactional storage.
        Detects if another process updated the persisted record and refreshes local memory cache.
        """
        try:
            target = validate_changeset_id(changeset_id)
        except ValueError:
            # Invalid ID format or path traversal rejected early
            return None

        # 1. Query transactional SQLite repository for authoritative record
        try:
            with _connect_db() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT version, status, payload_json, file_path, updated_at
                    FROM changesets
                    WHERE changeset_id = ?
                    """,
                    (changeset_id,)
                )
                row = cursor.fetchone()
                if row:
                    db_version, db_status, payload_json, file_path, updated_at = row
                    cached_cs = self._changesets.get(changeset_id)
                    cached_version = self._changeset_versions.get(changeset_id)

                    # If cached in memory and version matches DB, return cached instance
                    if cached_cs is not None and cached_version == db_version:
                        return cached_cs

                    # Otherwise, DB has newer or freshly discovered state: reload authoritative ChangeSet
                    fresh_cs = ChangeSet.model_validate_json(payload_json)
                    self._changesets[changeset_id] = fresh_cs
                    self._changeset_versions[changeset_id] = db_version
                    if target.exists():
                        self._changeset_mtimes[changeset_id] = target.stat().st_mtime
                    if file_path or fresh_cs.file_path:
                        self._changeset_to_session[changeset_id] = file_path or fresh_cs.file_path
                    return fresh_cs
        except Exception as e:
            logger.warning("Failed to query ChangeSet from SQLite database: %s", e)

        # 2. Fallback to persisted disk JSON file (e.g. if created outside DB or DB was reinitialized)
        if target.exists():
            try:
                curr_mtime = target.stat().st_mtime
                cached_cs = self._changesets.get(changeset_id)
                cached_mtime = self._changeset_mtimes.get(changeset_id)

                if cached_cs is not None and cached_mtime == curr_mtime:
                    return cached_cs

                payload = target.read_text(encoding="utf-8")
                fresh_cs = ChangeSet.model_validate_json(payload)
                self._changesets[changeset_id] = fresh_cs
                self._changeset_mtimes[changeset_id] = curr_mtime
                if fresh_cs.file_path:
                    self._changeset_to_session[changeset_id] = fresh_cs.file_path

                # Backfill into SQLite for future transactional versioning
                try:
                    with _connect_db() as conn:
                        conn.execute(
                            """
                            INSERT OR REPLACE INTO changesets (
                                changeset_id, document_id, document_version, status,
                                file_path, payload_json, version, created_at, updated_at
                            ) VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)
                            """,
                            (fresh_cs.changeset_id, fresh_cs.document_id, fresh_cs.document_version,
                             fresh_cs.status, fresh_cs.file_path, payload, time.time(), curr_mtime)
                        )
                        conn.commit()
                        self._changeset_versions[changeset_id] = 1
                except Exception:
                    pass

                return fresh_cs
            except Exception as e:
                logger.warning("Failed to load ChangeSet JSON file '%s': %s", target, e)

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
        validate_changeset_id(changeset_id)
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
        Persisted transactionally to SQLite with SHA-256 token hash (never plain credentials).
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
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        now = time.time()
        expires_at = now + ttl_seconds

        try:
            with _connect_token_db() as conn:
                conn.execute(
                    """
                    INSERT INTO approval_tokens (
                        token_hash, changeset_id, document_id, document_version,
                        approver_id, created_at, expires_at, consumed, consumed_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, NULL)
                    """,
                    (token_hash, cs.changeset_id, cs.document_id, cs.document_version, approver_id, now, expires_at),
                )
                conn.commit()
        except Exception as e:
            raise RuntimeError(f"Transactional persistence failure while issuing approval token: {e}") from e

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
        Enforces atomic compare-and-set via conditional SQL UPDATE:
        UPDATE approval_tokens SET consumed = 1, consumed_at = ?
        WHERE token_hash = ? AND changeset_id = ? AND consumed = 0 AND expires_at > ?
        Accepts the token only if cursor.rowcount == 1.
        """
        token_clean = token.strip() if token else ""
        if not token_clean:
            raise AccessDeniedError(
                f"Approval authorization failed: Missing approval_token for ChangeSet '{changeset_id}'."
            )

        token_hash = hashlib.sha256(token_clean.encode("utf-8")).hexdigest()

        try:
            with _connect_token_db() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT token_hash, changeset_id, document_id, document_version,
                           approver_id, created_at, expires_at, consumed, consumed_at
                    FROM approval_tokens
                    WHERE token_hash = ?
                    """,
                    (token_hash,)
                )
                row = cursor.fetchone()
                if not row:
                    raise AccessDeniedError(
                        f"Approval authorization failed: Invalid approval_token for ChangeSet '{changeset_id}'."
                    )

                th, cs_id, doc_id, doc_ver, approver_id, created_at, expires_at, consumed, consumed_at = row

                if cs_id != changeset_id:
                    raise AccessDeniedError(
                        f"Approval authorization failed: Token was issued for ChangeSet '{cs_id}', not '{changeset_id}'."
                    )

                cs = self._get_changeset(changeset_id)
                if cs and doc_ver != cs.document_version:
                    raise AccessDeniedError(
                        "Approval authorization failed: Document version changed since token was issued."
                    )

                now = time.time()
                if now > expires_at:
                    raise AccessDeniedError(
                        f"Approval authorization failed: Approval token has expired (TTL {int(expires_at - created_at)}s elapsed)."
                    )

                if consumed:
                    raise AccessDeniedError(
                        "Approval authorization failed: Approval token has already been consumed (single-use replay detected)."
                    )

                # Atomic compare-and-set conditional update
                cursor.execute(
                    """
                    UPDATE approval_tokens
                    SET consumed = 1, consumed_at = ?
                    WHERE token_hash = ?
                      AND changeset_id = ?
                      AND consumed = 0
                      AND expires_at > ?
                    """,
                    (now, token_hash, changeset_id, now)
                )
                if cursor.rowcount != 1:
                    raise AccessDeniedError(
                        "Approval authorization failed: Approval token has already been consumed or expired (atomic single-use contention)."
                    )
                conn.commit()

                return ApprovalTokenRecord(
                    token_hash=th,
                    changeset_id=cs_id,
                    document_id=doc_id,
                    document_version=doc_ver,
                    approver_id=approver_id,
                    created_at=created_at,
                    expires_at=expires_at,
                    consumed=True,
                    consumed_at=now,
                    token=token_clean,
                )
        except AccessDeniedError:
            raise
        except Exception as e:
            raise RuntimeError(f"Database error during token verification and consumption: {e}") from e

    def verify_approval_token(self, changeset_id: str, token: str) -> bool:
        """Read-only check if an approval token is valid without consuming it."""
        token_clean = token.strip() if token else ""
        if not token_clean:
            return False
        token_hash = hashlib.sha256(token_clean.encode("utf-8")).hexdigest()
        try:
            with _connect_token_db() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT changeset_id, expires_at, consumed FROM approval_tokens WHERE token_hash = ?",
                    (token_hash,)
                )
                row = cursor.fetchone()
                if not row:
                    return False
                cs_id, expires_at, consumed = row
                if cs_id != changeset_id or time.time() > expires_at or consumed:
                    return False
                return True
        except Exception:
            return False

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
        try:
            vr_dir = (settings.STORAGE_DIR / "verification_reports").resolve()
            vr_dir.mkdir(parents=True, exist_ok=True)
            vr_file = vr_dir / f"{changeset_id}.json"
            vr_file.write_text(report.model_dump_json(indent=2), encoding="utf-8")
        except Exception as e:
            logger.warning("Failed to persist verification report for '%s': %s", changeset_id, e)

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
                src_names = set(z_src.namelist())
                dst_names = set(z_dst.namelist())

                # 1. Essential structural package parts required in any valid OOXML Word document
                required_parts = [
                    "[Content_Types].xml",
                    "_rels/.rels",
                    "word/document.xml",
                    "word/_rels/document.xml.rels",
                ]
                for part in required_parts:
                    if part in src_names and part not in dst_names:
                        formatting_preservation = False
                        discrepancies.append(f"Required package part '{part}' missing from recompiled document.")
                    elif part in src_names and part in dst_names and part != "word/document.xml":
                        if z_src.read(part) != z_dst.read(part):
                            formatting_preservation = False
                            discrepancies.append(f"Package part '{part}' was modified (expected byte-identical).")

                # 2. Invariant style, font, numbering, and settings parts
                preserved_parts = [
                    "word/styles.xml",
                    "word/numbering.xml",
                    "word/settings.xml",
                    "word/fontTable.xml",
                    "word/webSettings.xml",
                ]
                for part in preserved_parts:
                    if part in src_names:
                        if part not in dst_names:
                            formatting_preservation = False
                            discrepancies.append(f"Preserved package part '{part}' present in source was dropped in recompiled document.")
                        elif z_src.read(part) != z_dst.read(part):
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
                doc_id = self._changeset_to_session.get(changeset_id, cs.file_path or cs.document_id)
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
                # Target text must exist specifically in the target block ID
                recomp_target = recomp_blocks.get(t_bid)
                if not recomp_target:
                    operation_correctness = False
                    discrepancies.append(
                        f"Operation failure: target block '{t_bid}' not found in recompiled document."
                    )
                elif recomp_target.text_content.strip() != expected_text:
                    operation_correctness = False
                    discrepancies.append(
                        f"Operation failure on block '{t_bid}': expected edit text '{expected_text}', "
                        f"got '{recomp_target.text_content.strip()}'."
                    )
            elif op == ChangeOperationType.MOVE_PROCEDURE_STEP:
                # Check that procedural list items survived in proper sequence
                if cs.after_step_order:
                    doc_id = self._changeset_to_session.get(changeset_id, cs.file_path or cs.document_id)
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
        is_structural_reorder = cs and cs.command.operation in (
            ChangeOperationType.MOVE_PROCEDURE_STEP,
            ChangeOperationType.REORDER_SECTION,
        )

        matched_reopened_ids: Set[str] = set()
        unmodified_checked = 0

        if not is_structural_reorder:
            for bid, orig_b in orig_blocks.items():
                if bid in affected_bids:
                    continue
                match = recomp_blocks.get(bid)
                if match is None:
                    content_preservation = False
                    discrepancies.append(f"Untouched block '{bid}' missing in recompiled document.")
                    continue

                unmodified_checked += 1

                # 1. Byte-level paragraph XML signature equality
                if orig_b.location.xml_signature_hash != match.location.xml_signature_hash:
                    formatting_preservation = False
                    discrepancies.append(
                        f"XML structure drift in untouched block '{bid}': paragraph XML signature altered."
                    )

                # 2. Textual content equality
                if orig_b.text_content.strip() != match.text_content.strip():
                    content_preservation = False
                    discrepancies.append(
                        f"Content drift in untouched block '{bid}': source='{orig_b.text_content[:40]}…', "
                        f"recompiled='{match.text_content[:40]}…'."
                    )

                # 3. Formatting attributes equality
                if (
                    orig_b.formatting.is_bold != match.formatting.is_bold
                    or orig_b.formatting.is_italic != match.formatting.is_italic
                    or orig_b.formatting.heading_level != match.formatting.heading_level
                    or orig_b.formatting.style_id != match.formatting.style_id
                    or orig_b.formatting.num_id != match.formatting.num_id
                    or orig_b.block_type != match.block_type
                ):
                    formatting_preservation = False
                    discrepancies.append(f"Formatting attribute drift in untouched block '{bid}': style/type attributes altered.")

                # 4. Table 2D matrix equality
                if orig_b.block_type == "TABLE" and orig_b.table_data != match.table_data:
                    content_preservation = False
                    discrepancies.append(f"Table matrix content drift in untouched table '{bid}'.")
        else:
            # Occurrence-tracking pool with exact XML signature matching first, then text content matching
            xml_pool: Dict[str, List[DocumentBlock]] = {}
            text_pool: Dict[str, List[DocumentBlock]] = {}
            for rb in recomp_blocks.values():
                if rb.location and rb.location.xml_signature_hash:
                    xml_pool.setdefault(rb.location.xml_signature_hash, []).append(rb)
                text_pool.setdefault(rb.text_content.strip(), []).append(rb)

            for bid, orig_b in orig_blocks.items():
                if bid in affected_bids:
                    continue

                xml_hash = orig_b.location.xml_signature_hash if orig_b.location else None
                match = None
                if xml_hash and xml_hash in xml_pool:
                    match = next((c for c in xml_pool[xml_hash] if c.block_id not in matched_reopened_ids), None)

                if match is None:
                    txt_key = orig_b.text_content.strip()
                    match = next((c for c in text_pool.get(txt_key, []) if c.block_id not in matched_reopened_ids), None)

                if match is None:
                    content_preservation = False
                    discrepancies.append(
                        f"Content drift in untouched block '{bid}': source='{orig_b.text_content[:40]}…' "
                        f"missing or modified in recompiled document."
                    )
                else:
                    matched_reopened_ids.add(match.block_id)
                    unmodified_checked += 1

                    if (
                        orig_b.formatting.is_bold != match.formatting.is_bold
                        or orig_b.formatting.is_italic != match.formatting.is_italic
                        or orig_b.formatting.heading_level != match.formatting.heading_level
                        or orig_b.block_type != match.block_type
                    ):
                        formatting_preservation = False
                        discrepancies.append(f"Formatting drift in untouched block '{bid}': style/type attributes altered.")

                    if orig_b.block_type == "TABLE" and orig_b.table_data != match.table_data:
                        content_preservation = False
                        discrepancies.append(f"Table matrix content drift in untouched table '{bid}'.")

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
                    "scope": "Target block mutated specifically at target block ID to match expected change payload",
                },
                "structural_integrity": {
                    "verified": structural_integrity,
                    "scope": "Block count, document hierarchy, and section sequences intact",
                },
                "content_preservation": {
                    "verified": content_preservation,
                    "scope": "100% of unaffected blocks identical with zero textual or table drift",
                },
                "formatting_preservation": {
                    "verified": formatting_preservation,
                    "scope": "Required & preserved OOXML parts (styles.xml, numbering.xml, settings.xml, rels) present and byte-identical; paragraph XML structure preserved",
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
        validate_changeset_id(changeset_id)
        report = self._verification_reports.get(changeset_id)
        if report:
            return report.model_dump()
        try:
            vr_file = settings.STORAGE_DIR / "verification_reports" / f"{changeset_id}.json"
            if vr_file.exists():
                return json.loads(vr_file.read_text(encoding="utf-8"))
        except Exception:
            pass
        raise KeyError(f"No verification report recorded for ChangeSet '{changeset_id}'.")


# Shared application-level singleton
document_tools = DocumentToolService()
