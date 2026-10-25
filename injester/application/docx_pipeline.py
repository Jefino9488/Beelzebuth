"""
Beelzebuth Integrated DOCX Round-Trip Pipeline.

Orchestrates the complete editing lifecycle for any DOCX document:
DOCX → Document IR → Canonical Session → Typed Change → Validate → Recompile → Reopen & Compare

Key invariants enforced here (addressing prior critical findings):
1. APPROVAL GATE: recompile_and_verify() rejects any ChangeSet not in APPROVED status.
2. STALE SOURCE GUARD: source file is re-hashed immediately before patching; mismatch aborts.
3. PROCEDURE SCOPE: target and anchor steps must share the same parent section block.
4. ONE-TO-ONE BLOCK MATCHING: each original block is matched to exactly one reopened block.
5. EMPTY-UPDATE REJECTION: UPDATE_STEP_INSTRUCTION with empty text is rejected at propose time.
6. GENERAL DOCUMENT SUPPORT: session exposes all blocks, not just procedural steps; GroundedStep
   extraction is an optional semantic overlay enabled for SOP/manual document types.
"""

import os
import io
import re
import zipfile
import hashlib
from typing import List, Dict, Optional, Set, Tuple, Any, Union
from pydantic import BaseModel, Field, ConfigDict

from injester.domain.document_ir import (
    DocumentIR, DocumentBlock, DocumentType, extract_docx_ir,
)
from injester.semantic.change_engine import (
    ChangeEngine,
    TypedChangeCommand,
    ChangeOperationType,
    ChangeImpact,
    ChangeSet,
    COMPILABLE_STATUSES,
)
from injester.infrastructure.docx_patcher import DocxPackagePatcher, DocxPatchError


# ---------------------------------------------------------------------------
# Domain models
# ---------------------------------------------------------------------------

class GroundedStep(BaseModel):
    """
    A procedural workflow step in the semantic process graph (Model B).
    Linked to Model A (Document IR) via source_block_id and evidence_span_id.
    Only populated when the document contains explicit procedural content.
    """
    step_id: str
    label: str
    instruction: str
    source_block_id: str
    evidence_span_id: str
    sequence_index: int
    actor: str = "System Administrator"
    is_independent: bool = True
    depends_on: List[str] = Field(default_factory=list)
    # Procedure membership: parent section block ID that scopes this step
    procedure_parent_block_id: Optional[str] = None


class DocumentEditSession(BaseModel):
    """
    Active in-memory editing session for a DOCX document.
    Supports any document type: resume, report, manual, research paper, contract.
    GroundedStep extraction is optional and only populated for procedure-bearing documents.
    """
    document_id: str
    file_path: str
    # SHA-256 of file bytes at load time — used to detect external modification
    file_hash: str
    document_type: DocumentType
    document_ir: DocumentIR
    # span_id -> text
    span_registry: Dict[str, str] = Field(default_factory=dict)

    # Procedural step overlay — populated only when document_type is MANUAL or SOP-like
    steps: Dict[str, GroundedStep] = Field(default_factory=dict)
    step_order: List[str] = Field(default_factory=list)
    step_to_block_map: Dict[str, str] = Field(default_factory=dict)
    # step_id -> parent block ID (for procedure scope enforcement)
    step_parent_map: Dict[str, Optional[str]] = Field(default_factory=dict)

    # Version token derived from file_hash; must match every TypedChangeCommand
    version_id: str = "v1.0"

    model_config = ConfigDict(arbitrary_types_allowed=True)


# Keep legacy alias so existing tests and callers continue to work
DocxSession = DocumentEditSession


class RoundTripVerificationReport(BaseModel):
    """Auditable verification report returned after recompiling and reopening."""
    is_successful: bool
    source_file: str
    output_file: str
    changeset_id: str
    operation: str
    unmodified_blocks_intact: bool
    unmodified_block_count: int
    step_reordering_verified: bool
    package_styles_preserved: bool
    untouched_zip_entries: List[str] = Field(default_factory=list)
    reopened_step_order: List[str] = Field(default_factory=list)
    detected_discrepancies: List[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

class DocxRoundTripPipeline:
    """
    General-purpose DOCX editing pipeline for any document type.
    """

    def __init__(self):
        self.change_engine = ChangeEngine()

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def load_document(self, docx_path: str) -> DocumentEditSession:
        """
        Ingests a DOCX file:
        1. Extracts Document IR (Model A) via zipfile + lxml parsing.
        2. Detects document type (RESUME, REPORT, MANUAL, RESEARCH_PAPER, CONTRACT, GENERIC).
        3. Registers atomic evidence spans for every block.
        4. If the document is procedure-bearing (MANUAL or likely SOP content), extracts
           GroundedStep objects as a semantic overlay (Model B).
        """
        ir = extract_docx_ir(docx_path)
        with open(docx_path, "rb") as f:
            file_hash = hashlib.sha256(f.read()).hexdigest()

        spans: Dict[str, str] = {}
        steps: Dict[str, GroundedStep] = {}
        step_order: List[str] = []
        step_to_block: Dict[str, str] = {}
        step_parent_map: Dict[str, Optional[str]] = {}

        span_counter = 1
        step_counter = 1

        for b_id in ir.structural_order:
            block = ir.blocks[b_id]
            span_id = f"S{span_counter:03d}"
            span_counter += 1
            spans[span_id] = block.text_content
            block.span_ids.append(span_id)

            # Extract procedural steps for procedure-bearing documents
            if ir.document_type in (DocumentType.MANUAL, DocumentType.GENERIC):
                txt = block.text_content.strip()
                is_step = (
                    block.block_type == "LIST_ITEM"
                    or txt.lower().startswith("step ")
                    or (len(txt) > 3 and txt[0].isdigit() and txt[1] in (".", ")", ":"))
                )
                if is_step and block.block_type != "HEADING":
                    step_id = f"step-{step_counter:02d}"
                    step_counter += 1
                    step = GroundedStep(
                        step_id=step_id,
                        label=txt[:40],
                        instruction=txt,
                        source_block_id=b_id,
                        evidence_span_id=span_id,
                        sequence_index=len(step_order),
                        procedure_parent_block_id=block.parent_block_id,
                    )
                    steps[step_id] = step
                    step_order.append(step_id)
                    step_to_block[step_id] = b_id
                    step_parent_map[step_id] = block.parent_block_id

        return DocumentEditSession(
            document_id=ir.document_id,
            file_path=docx_path,
            file_hash=file_hash,
            document_type=ir.document_type,
            document_ir=ir,
            span_registry=spans,
            steps=steps,
            step_order=step_order,
            step_to_block_map=step_to_block,
            step_parent_map=step_parent_map,
            version_id=f"v_{file_hash[:8]}",
        )

    # ------------------------------------------------------------------
    # Dependency registration
    # ------------------------------------------------------------------

    def register_step_dependency(
        self,
        session: DocumentEditSession,
        step_id: str,
        depends_on_step_id: str,
        reason: str = "",
    ) -> None:
        """
        Declares a prerequisite relationship between two steps.
        Validates both steps exist, rejects duplicates, and detects cycles.
        """
        if step_id not in session.steps:
            raise ValueError(f"Cannot register dependency: step '{step_id}' not found in session.")
        if depends_on_step_id not in session.steps:
            raise ValueError(
                f"Cannot register dependency: prerequisite step '{depends_on_step_id}' not found in session."
            )
        session.steps[step_id].is_independent = False
        session.steps[step_id].depends_on.append(depends_on_step_id)
        self.change_engine.register_dependency(
            step_id,
            depends_on_step_id,
            reason,
            known_step_ids=set(session.steps.keys()),
        )

    # ------------------------------------------------------------------
    # Change proposal
    # ------------------------------------------------------------------

    def propose_edit(
        self,
        session: DocumentEditSession,
        command: TypedChangeCommand,
    ) -> ChangeSet:
        """
        Validates the proposed command against the session and dependency graph.
        Returns an auditable ChangeSet. The ChangeSet status will be PROPOSED
        (requires manual review) or REJECTED.
        """
        impact = self.change_engine.evaluate_command(
            command=command,
            current_step_order=session.step_order,
            document_ir=session.document_ir,
            step_to_block_map=session.step_to_block_map,
            active_document_version=session.version_id,
            step_parent_map=session.step_parent_map,
        )
        return self.change_engine.create_changeset(
            command=command,
            current_step_order=session.step_order,
            impact=impact,
            document_id=session.document_id,
            document_version=session.version_id,
            file_path=session.file_path,
        )

    def approve_changeset(
        self,
        session: DocumentEditSession,
        changeset: ChangeSet,
        approver: Optional[Union[Any, str]] = None,
        rationale: str = "",
        signing_key: Optional[str] = None,
        approver_id: Optional[str] = None,
    ) -> ChangeSet:
        """
        Controlled approval operation.
        Verifies active session bindings, records authenticated approver identity, computes cryptographic signature,
        and deeply freezes the ChangeSet for compilation.
        """
        effective_approver = approver if approver is not None else approver_id
        return self.change_engine.approve_changeset(
            changeset=changeset,
            approver=effective_approver,
            active_session_doc_id=session.document_id,
            active_session_version=session.version_id,
            rationale=rationale,
            signing_key=signing_key,
        )

    # ------------------------------------------------------------------
    # Recompilation & verification
    # ------------------------------------------------------------------

    def recompile_and_verify(
        self,
        session: DocumentEditSession,
        changeset: ChangeSet,
        output_docx_path: str,
    ) -> RoundTripVerificationReport:
        """
        Applies an APPROVED ChangeSet through the surgical OOXML patcher, re-extracts
        the resulting DOCX, and performs a rigorous one-to-one verification of every block.

        Enforced guards:
        - ChangeSet must have status == 'APPROVED' (not PROPOSED, REJECTED, or APPLIED).
        - Source file SHA-256 is re-computed immediately before patching; if the file changed
          since the session was loaded, the operation is aborted.
        - Unmodified blocks are matched one-to-one (each original block to exactly one reopened
          block); duplicate-text paragraphs cannot mask a dropped or altered block.
        - Package parts (styles.xml, numbering.xml, settings.xml) must be byte-identical.
        - UPDATE operations verify the exact new text in the specific target block only.
        """
        # -------------------------------------------------------------------
        # CRITICAL GUARD 1: Approval status, Provenance & Cryptographic Signature
        # -------------------------------------------------------------------
        if changeset.status not in COMPILABLE_STATUSES:
            raise DocxPatchError(
                f"Cannot recompile ChangeSet '{changeset.changeset_id}': "
                f"status is '{changeset.status}' but must be one of {sorted(COMPILABLE_STATUSES)}. "
                f"A ChangeSet must be explicitly approved before document mutation."
            )

        if not changeset.impact.is_valid:
            raise DocxPatchError(
                f"Cannot recompile invalid ChangeSet '{changeset.changeset_id}'. "
                f"Conflicts: {'; '.join(changeset.impact.conflicts)}"
            )

        if not changeset.approved_by or not changeset.approval_signature:
            raise DocxPatchError(
                f"Cannot recompile ChangeSet '{changeset.changeset_id}': "
                f"missing approver identity or cryptographic approval signature. "
                f"Call pipeline.approve_changeset() through an authorized operator."
            )

        expected_sig = self.change_engine.compute_approval_signature(
            changeset_id=changeset.changeset_id,
            document_id=changeset.document_id,
            document_version=changeset.document_version,
            approver_id=changeset.approved_by,
            command=changeset.command,
        )
        if changeset.approval_signature != expected_sig:
            raise DocxPatchError(
                f"Cannot recompile ChangeSet '{changeset.changeset_id}': "
                f"cryptographic approval signature verification failed (possible tampering detected: command payload was altered after approval)."
            )

        if changeset.document_id != session.document_id:
            raise DocxPatchError(
                f"Cannot recompile ChangeSet '{changeset.changeset_id}': "
                f"document ID mismatch (ChangeSet: '{changeset.document_id}', session: '{session.document_id}')."
            )

        if changeset.document_version != session.version_id:
            raise DocxPatchError(
                f"Cannot recompile ChangeSet '{changeset.changeset_id}': "
                f"document version mismatch (ChangeSet: '{changeset.document_version}', session: '{session.version_id}')."
            )

        if changeset.command.expected_document_version != session.version_id:
            raise DocxPatchError(
                f"Cannot recompile ChangeSet '{changeset.changeset_id}': "
                f"command expected version '{changeset.command.expected_document_version}', but session is '{session.version_id}'."
            )

        # -------------------------------------------------------------------
        # CRITICAL GUARD 2: Stale-source detection & Immutable snapshot capture
        # -------------------------------------------------------------------
        with open(session.file_path, "rb") as f:
            source_bytes = f.read()
        current_source_hash = hashlib.sha256(source_bytes).hexdigest()
        if current_source_hash != session.file_hash:
            raise DocxPatchError(
                f"Source file '{session.file_path}' has changed since the session was loaded "
                f"(session hash: {session.file_hash[:12]}…, current: {current_source_hash[:12]}…). "
                f"Reload the document to obtain a fresh session before applying edits."
            )

        # -------------------------------------------------------------------
        # 1. Apply targeted patch (scoped to procedure parent group)
        # -------------------------------------------------------------------
        target_step = changeset.command.target_step_id
        if target_step and target_step in session.step_parent_map:
            target_parent = session.step_parent_map.get(target_step)
            scoped_bids = [
                session.step_to_block_map[s]
                for s in session.step_order
                if session.step_parent_map.get(s) == target_parent and s in session.step_to_block_map
            ]
        else:
            scoped_bids = [
                session.step_to_block_map[s]
                for s in session.step_order
                if s in session.step_to_block_map
            ]

        patch_audit = DocxPackagePatcher.patch_docx(
            source_docx_path=session.file_path,
            output_docx_path=output_docx_path,
            command=changeset.command,
            document_ir=session.document_ir,
            step_to_block_map=session.step_to_block_map,
            procedure_block_ids=scoped_bids,
            source_docx_bytes=source_bytes,
        )

        # -------------------------------------------------------------------
        # 2. Re-extract output DOCX to independently verify
        # -------------------------------------------------------------------
        reopened_ir = extract_docx_ir(output_docx_path)
        discrepancies: List[str] = []

        # -------------------------------------------------------------------
        # 3. Package part byte-identical check
        # -------------------------------------------------------------------
        styles_preserved = True
        with (
            zipfile.ZipFile(io.BytesIO(source_bytes), "r") as src_zip,
            zipfile.ZipFile(output_docx_path, "r") as dst_zip,
        ):
            for check_part in [
                "word/styles.xml",
                "word/numbering.xml",
                "word/settings.xml",
                "word/fontTable.xml",
            ]:
                if check_part in src_zip.namelist() and check_part in dst_zip.namelist():
                    if src_zip.read(check_part) != dst_zip.read(check_part):
                        styles_preserved = False
                        discrepancies.append(
                            f"Package part '{check_part}' was modified (expected byte-identical)."
                        )

        # -------------------------------------------------------------------
        # 4. ONE-TO-ONE unmodified block verification
        # Each original block is matched to EXACTLY ONE reopened block.
        # Duplicate content cannot mask a dropped or altered block.
        # -------------------------------------------------------------------
        step_block_ids: Set[str] = set(session.step_to_block_map.values())
        if changeset.command.operation == ChangeOperationType.EDIT_PARAGRAPH_TEXT:
            target_bid = changeset.command.target_block_id or (
                session.step_to_block_map.get(changeset.command.target_step_id)
                if changeset.command.target_step_id else None
            )
            if target_bid:
                step_block_ids.add(target_bid)
        unmodified_count = 0
        unmodified_intact = True

        # Build an occurrence-tracking pool of reopened blocks (text -> list of blocks)
        reopened_pool: Dict[str, List[DocumentBlock]] = {}
        for rb in reopened_ir.blocks.values():
            key = rb.text_content.strip()
            reopened_pool.setdefault(key, []).append(rb)

        # Track which reopened blocks have already been matched
        matched_reopened_ids: Set[str] = set()

        for b_id, orig_block in session.document_ir.blocks.items():
            if b_id in step_block_ids:
                continue  # procedural steps verified separately in step 5

            orig_text = orig_block.text_content.strip()
            candidates = [
                rb for rb in reopened_pool.get(orig_text, [])
                if rb.block_id not in matched_reopened_ids
            ]

            if not candidates:
                unmodified_intact = False
                discrepancies.append(
                    f"Unmodified block '{b_id}' not found in recompiled document "
                    f"(text: '{orig_text[:50]}…')"
                )
                continue

            # Accept the first available unmatched candidate
            matched_rb = candidates[0]
            matched_reopened_ids.add(matched_rb.block_id)
            unmodified_count += 1

            # Deep formatting checks
            fmt_issues = _compare_formatting(orig_block, matched_rb)
            if fmt_issues:
                for issue in fmt_issues:
                    discrepancies.append(f"Block '{b_id}': {issue}")
                unmodified_intact = False

        # -------------------------------------------------------------------
        # 5. Verify step reordering / instruction update
        # -------------------------------------------------------------------
        step_reordering_verified = False
        is_noop = (
            changeset.impact.details.get("is_noop", False)
            or patch_audit.get("is_noop", False)
        )

        if changeset.command.operation == ChangeOperationType.MOVE_PROCEDURE_STEP:
            if is_noop:
                step_reordering_verified = True
                reopened_steps = list(changeset.before_step_order)
            else:
                target_id = changeset.command.target_step_id
                anchor_id = changeset.command.before_step_id

                target_block = session.document_ir.blocks[
                    session.step_to_block_map[target_id]
                ]

                # Scope verification to the target's procedure section
                target_parent = target_block.parent_block_id
                proc_steps = [
                    s for s in session.step_order
                    if session.document_ir.blocks[
                        session.step_to_block_map[s]
                    ].parent_block_id == target_parent
                ] if target_parent else list(session.step_order)

                expected_proc_order = [
                    s for s in changeset.after_step_order if s in proc_steps
                ]

                # Map each procedure step to its position in the reopened document
                step_pos_map: Dict[str, int] = {}
                for s in proc_steps:
                    s_text = session.document_ir.blocks[
                        session.step_to_block_map[s]
                    ].text_content.strip()
                    for pos_idx, rb_id in enumerate(reopened_ir.structural_order):
                        if reopened_ir.blocks[rb_id].text_content.strip() == s_text:
                            step_pos_map[s] = pos_idx
                            break

                reopened_proc_order = sorted(
                    [s for s in proc_steps if s in step_pos_map],
                    key=lambda s: step_pos_map[s],
                )
                reopened_steps = reopened_proc_order

                # Verify target precedes anchor
                if anchor_id and anchor_id in step_pos_map and target_id in step_pos_map:
                    step_reordering_verified = step_pos_map[target_id] < step_pos_map[anchor_id]
                    if not step_reordering_verified:
                        discrepancies.append(
                            f"Step reordering failed: '{target_id}' does not precede '{anchor_id}' "
                            f"in the reopened document."
                        )
                elif not anchor_id and target_id in step_pos_map:
                    step_reordering_verified = True

                if reopened_proc_order != expected_proc_order:
                    step_reordering_verified = False
                    discrepancies.append(
                        f"Procedure step order mismatch: "
                        f"expected {expected_proc_order}, got {reopened_proc_order}"
                    )

        elif changeset.command.operation == ChangeOperationType.UPDATE_STEP_INSTRUCTION:
            new_text = (changeset.command.new_values or {}).get("instruction") or ""
            if not new_text:
                # Already rejected at propose_edit; belt-and-suspenders check
                step_reordering_verified = False
                discrepancies.append("Empty instruction update: no text to verify.")
            else:
                target_block_id = session.step_to_block_map.get(
                    changeset.command.target_step_id
                )
                # Verify the new text appears in the SPECIFIC target block position,
                # not just anywhere in the document
                target_block = session.document_ir.blocks.get(target_block_id)
                if target_block:
                    # Find the block at the target's structural position in the reopened IR
                    target_elem_idx = target_block.location.element_index
                    target_found = False
                    for rb in reopened_ir.blocks.values():
                        if (
                            abs(rb.location.element_index - target_elem_idx) <= 1
                            and new_text in rb.text_content
                        ):
                            target_found = True
                            break
                    step_reordering_verified = target_found
                    if not target_found:
                        discrepancies.append(
                            f"Updated instruction text not found at target block position "
                            f"(element_index ~{target_elem_idx}). "
                            f"Expected: '{new_text[:60]}…'"
                        )
                else:
                    step_reordering_verified = False
                    discrepancies.append(
                        f"Target block for step '{changeset.command.target_step_id}' not found."
                    )
            reopened_steps = list(changeset.after_step_order)

        elif changeset.command.operation == ChangeOperationType.EDIT_PARAGRAPH_TEXT:
            new_text = (
                (changeset.command.new_values or {}).get("new_text")
                or (changeset.command.new_values or {}).get("instruction")
                or ""
            )
            if not new_text:
                step_reordering_verified = False
                discrepancies.append("Empty text update: no text to verify.")
            else:
                target_bid = changeset.command.target_block_id or (
                    session.step_to_block_map.get(changeset.command.target_step_id)
                    if changeset.command.target_step_id else None
                )
                target_block = session.document_ir.blocks.get(target_bid)
                if target_block:
                    target_elem_idx = target_block.location.element_index
                    target_found = False
                    for rb in reopened_ir.blocks.values():
                        if (
                            abs(rb.location.element_index - target_elem_idx) <= 1
                            and str(new_text) in rb.text_content
                        ):
                            target_found = True
                            break
                    step_reordering_verified = target_found
                    if not target_found:
                        discrepancies.append(
                            f"Updated paragraph text not found at target block position "
                            f"(element_index ~{target_elem_idx}). "
                            f"Expected: '{str(new_text)[:60]}…'"
                        )
                else:
                    step_reordering_verified = False
                    discrepancies.append(f"Target block '{target_bid}' not found in original session.")
            reopened_steps = list(changeset.after_step_order)

        elif changeset.command.operation == ChangeOperationType.REORDER_SECTION:
            target_bid = changeset.command.target_block_id
            anchor_bid = changeset.command.before_block_id
            target_block = session.document_ir.blocks.get(target_bid)
            anchor_block = session.document_ir.blocks.get(anchor_bid) if anchor_bid else None

            if target_block:
                t_text = target_block.text_content.strip()
                t_pos = None
                a_pos = None
                for pos_idx, rb_id in enumerate(reopened_ir.structural_order):
                    rb_text = reopened_ir.blocks[rb_id].text_content.strip()
                    if rb_text == t_text and t_pos is None:
                        t_pos = pos_idx
                    if anchor_block and rb_text == anchor_block.text_content.strip() and a_pos is None:
                        a_pos = pos_idx

                if anchor_block:
                    if t_pos is not None and a_pos is not None:
                        step_reordering_verified = t_pos < a_pos
                        if not step_reordering_verified:
                            discrepancies.append(
                                f"Section reordering failed: target section '{t_text[:30]}' (pos {t_pos}) "
                                f"does not precede anchor section '{anchor_block.text_content[:30]}' (pos {a_pos})."
                            )
                    else:
                        step_reordering_verified = False
                        discrepancies.append("Failed to locate target or anchor heading in reopened document.")
                else:
                    step_reordering_verified = t_pos is not None
            else:
                step_reordering_verified = False
                discrepancies.append(f"Target section heading block '{target_bid}' not found.")
            reopened_steps = list(changeset.after_step_order)

        else:
            reopened_steps = list(changeset.after_step_order)
            step_reordering_verified = True

        is_successful = (
            len(discrepancies) == 0
            and unmodified_intact
            and styles_preserved
            and step_reordering_verified
        )

        return RoundTripVerificationReport(
            is_successful=is_successful,
            source_file=session.file_path,
            output_file=output_docx_path,
            changeset_id=changeset.changeset_id,
            operation=changeset.command.operation.value,
            unmodified_blocks_intact=unmodified_intact,
            unmodified_block_count=unmodified_count,
            step_reordering_verified=step_reordering_verified,
            package_styles_preserved=styles_preserved,
            untouched_zip_entries=patch_audit.get("untouched_parts_preserved", []),
            reopened_step_order=reopened_steps,
            detected_discrepancies=discrepancies,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _compare_formatting(
    orig: DocumentBlock,
    rb: DocumentBlock,
) -> List[str]:
    """
    Returns a list of formatting discrepancies between the original and reopened block.
    """
    issues: List[str] = []
    of, rf = orig.formatting, rb.formatting

    if of.is_heading != rf.is_heading:
        issues.append(f"heading status changed ({of.is_heading} → {rf.is_heading})")
    if of.heading_level != rf.heading_level:
        issues.append(f"heading level changed ({of.heading_level} → {rf.heading_level})")
    if of.is_list_item != rf.is_list_item:
        issues.append(f"list-item status changed ({of.is_list_item} → {rf.is_list_item})")
    if of.num_id != rf.num_id:
        issues.append(f"numId changed ({of.num_id} → {rf.num_id})")
    if of.ilvl != rf.ilvl:
        issues.append(f"ilvl changed ({of.ilvl} → {rf.ilvl})")
    if of.is_bold != rf.is_bold:
        issues.append(f"bold changed ({of.is_bold} → {rf.is_bold})")
    if of.is_italic != rf.is_italic:
        issues.append(f"italic changed ({of.is_italic} → {rf.is_italic})")
    if of.is_table != rf.is_table:
        issues.append(f"table status changed ({of.is_table} → {rf.is_table})")
    if of.is_table and orig.table_data != rb.table_data:
        issues.append("table cell data altered")

    return issues
