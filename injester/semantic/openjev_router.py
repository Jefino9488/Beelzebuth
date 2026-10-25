"""
OpenJev Fast-Path Request Router.

OpenJev serves as the fast-path decision and routing engine in Beelzebuth:
- Classifies user editing requests (natural language or UI interactions).
- Rapidly maps recognized intents to candidate TypedChangeCommands.
- Identifies whether an action is a pure structural permutation (fast path)
  or a content modification that requires Laya semantic evaluation.
- Offline-by-default; does not perform document mutations or approve changesets.
"""

import re
from typing import Optional, Dict, Any, List, Tuple
from pydantic import BaseModel, Field

from injester.semantic.change_engine import (
    TypedChangeCommand,
    ChangeOperationType,
)
from injester.domain.document_ir import DocumentIR, DocumentType


class RoutingDecision(BaseModel):
    """Routing decision produced by the OpenJev fast-path router."""
    is_supported: bool
    operation: Optional[ChangeOperationType] = None
    command: Optional[TypedChangeCommand] = None
    requires_semantic_evaluation: bool = False
    confidence: float = 0.0
    intent_description: str = ""
    rejection_reason: Optional[str] = None


class OpenJevIntentRouter:
    """
    OpenJev Fast-Path Request Router.
    Routes supported user requests to typed commands without slow LLM round-trips.
    """

    def __init__(self, offline_mode: bool = True):
        self.offline_mode = offline_mode

    def route_request(
        self,
        request_text: str,
        session_doc_id: str,
        session_version: str,
        document_ir: DocumentIR,
        step_order: Optional[List[str]] = None,
        step_to_block_map: Optional[Dict[str, str]] = None,
    ) -> RoutingDecision:
        """
        Classifies user request text into a candidate TypedChangeCommand.
        """
        req = request_text.strip()
        step_order = step_order or []
        step_to_block_map = step_to_block_map or {}

        # 1. Pattern: Move step X before step Y
        # e.g., "Move step 2 before step 1", "Reorder step-02 before step-01"
        step_move_match = re.search(
            r"(?:move|reorder|put)\s+(?:step[-_\s]*)?(\d+|[a-zA-Z0-9_\-]+)\s+(?:before|prior to)\s+(?:step[-_\s]*)?(\d+|[a-zA-Z0-9_\-]+)",
            req,
            re.IGNORECASE,
        )
        if step_move_match:
            t_raw, a_raw = step_move_match.group(1), step_move_match.group(2)
            target_step = self._resolve_step_id(t_raw, step_order)
            anchor_step = self._resolve_step_id(a_raw, step_order)

            if target_step and anchor_step:
                cmd = TypedChangeCommand(
                    operation=ChangeOperationType.MOVE_PROCEDURE_STEP,
                    target_step_id=target_step,
                    before_step_id=anchor_step,
                    source_block_ids=[step_to_block_map.get(target_step, "")],
                    expected_document_version=session_version,
                    rationale=f"OpenJev routed: Move {target_step} before {anchor_step}",
                    proposed_by="openjev_fast_path",
                )
                return RoutingDecision(
                    is_supported=True,
                    operation=ChangeOperationType.MOVE_PROCEDURE_STEP,
                    command=cmd,
                    requires_semantic_evaluation=False,
                    confidence=0.98,
                    intent_description=f"Move procedural step {target_step} before {anchor_step}",
                )

        # 2. Pattern: Move/Reorder section X before section Y
        # e.g., "Move section Education before section Experience", "Put Experience before Education"
        section_move_match = re.search(
            r"(?:move|reorder|put)\s+(?:section\s+)?([A-Za-z0-9\s\-]+?)\s+(?:before|prior to|above)\s+(?:section\s+)?([A-Za-z0-9\s\-]+)",
            req,
            re.IGNORECASE,
        )
        if section_move_match:
            t_name, a_name = section_move_match.group(1).strip(), section_move_match.group(2).strip()
            target_bid = self._find_heading_by_title(t_name, document_ir)
            anchor_bid = self._find_heading_by_title(a_name, document_ir)

            if target_bid and anchor_bid:
                cmd = TypedChangeCommand(
                    operation=ChangeOperationType.REORDER_SECTION,
                    target_block_id=target_bid,
                    before_block_id=anchor_bid,
                    source_block_ids=[target_bid],
                    expected_document_version=session_version,
                    rationale=f"OpenJev routed: Reorder section '{t_name}' before '{a_name}'",
                    proposed_by="openjev_fast_path",
                )
                return RoutingDecision(
                    is_supported=True,
                    operation=ChangeOperationType.REORDER_SECTION,
                    command=cmd,
                    requires_semantic_evaluation=False,
                    confidence=0.95,
                    intent_description=f"Reorder section '{t_name}' before '{a_name}'",
                )

        # 3. Pattern: Update/Edit step instruction text
        # e.g., "Update step 2 instruction to 'Verify BIOS settings'", "Set step-03 instruction: Connect power"
        update_step_match = re.search(
            r"(?:update|change|set|edit)\s+(?:step[-_\s]*)?(\d+|[a-zA-Z0-9_\-]+)\s+(?:instruction|text)?\s*(?:to|:|=)\s*['\"]?(.*?)['\"]?$",
            req,
            re.IGNORECASE,
        )
        if update_step_match:
            t_raw = update_step_match.group(1)
            new_text = update_step_match.group(2).strip()
            target_step = self._resolve_step_id(t_raw, step_order)
            if target_step and new_text:
                cmd = TypedChangeCommand(
                    operation=ChangeOperationType.UPDATE_STEP_INSTRUCTION,
                    target_step_id=target_step,
                    source_block_ids=[step_to_block_map.get(target_step, "")],
                    new_values={"instruction": new_text},
                    expected_document_version=session_version,
                    rationale=f"OpenJev routed: Update instruction for {target_step}",
                    proposed_by="openjev_fast_path",
                )
                return RoutingDecision(
                    is_supported=True,
                    operation=ChangeOperationType.UPDATE_STEP_INSTRUCTION,
                    command=cmd,
                    # Content changes require semantic evaluation by Laya
                    requires_semantic_evaluation=True,
                    confidence=0.92,
                    intent_description=f"Update instruction of step {target_step}",
                )

        # 4. Pattern: Edit paragraph text
        # e.g., "Edit paragraph block-005 text to 'New content'"
        edit_para_match = re.search(
            r"(?:update|edit|change)\s+(?:paragraph|block)\s+([a-zA-Z0-9_\-]+)\s+(?:text\s+)?(?:to|:|=)\s*['\"]?(.*?)['\"]?$",
            req,
            re.IGNORECASE,
        )
        if edit_para_match:
            bid = edit_para_match.group(1).strip()
            new_text = edit_para_match.group(2).strip()
            if bid in document_ir.blocks and new_text:
                cmd = TypedChangeCommand(
                    operation=ChangeOperationType.EDIT_PARAGRAPH_TEXT,
                    target_block_id=bid,
                    source_block_ids=[bid],
                    new_values={"new_text": new_text},
                    expected_document_version=session_version,
                    rationale=f"OpenJev routed: Edit paragraph {bid}",
                    proposed_by="openjev_fast_path",
                )
                return RoutingDecision(
                    is_supported=True,
                    operation=ChangeOperationType.EDIT_PARAGRAPH_TEXT,
                    command=cmd,
                    requires_semantic_evaluation=True,
                    confidence=0.90,
                    intent_description=f"Edit paragraph text for {bid}",
                )

        return RoutingDecision(
            is_supported=False,
            confidence=0.0,
            intent_description="Unrecognized or complex request",
            rejection_reason="Request cannot be safely resolved on OpenJev fast-path; requires full planner or manual command formulation.",
        )

    def _resolve_step_id(self, raw: str, step_order: List[str]) -> Optional[str]:
        """Resolves an index or step identifier into a known session step_id."""
        raw_clean = raw.strip().lower()
        if raw_clean in step_order:
            return raw_clean

        # Check formatted variants (e.g. "step-02", "step-2", "2")
        if raw_clean.isdigit():
            num = int(raw_clean)
            formatted = f"step-{num:02d}"
            if formatted in step_order:
                return formatted
            if 1 <= num <= len(step_order):
                return step_order[num - 1]

        for s in step_order:
            if s.lower() == raw_clean or s.lower().replace("-", "") == raw_clean.replace("-", ""):
                return s
        return None

    def _find_heading_by_title(self, title: str, document_ir: DocumentIR) -> Optional[str]:
        """Finds heading block matching the given section title."""
        target_norm = title.strip().lower()
        for bid in document_ir.structural_order:
            block = document_ir.blocks[bid]
            if block.formatting.is_heading or block.block_type == "HEADING":
                h_text = block.text_content.strip().lower()
                if target_norm == h_text or target_norm in h_text:
                    return bid
        return None
