"""
Beelzebuth Typed Change Engine & Dependency Impact Validator.
Translates visual direct manipulation and NLP requests into typed, auditable change commands.
Validates step dependencies, detects conflicting operations, and generates structured ChangeSets.

Invariants enforced here:
- Version lineage: every command must carry the current document version hash.
- Dependency integrity: forward and backward prerequisite ordering is verified.
- Procedure scope: target and anchor steps must share the same procedure (parent block).
- Idempotence detection: moving a step to its current position is a safe explicit NO-OP.
- Dependency graph integrity: register_dependency validates both steps exist and detects cycles.
"""

import os
import uuid
import hashlib
import hmac
import json
from datetime import datetime, timezone
from enum import Enum
from typing import List, Dict, Optional, Any, Set, Union
from pydantic import BaseModel, Field

from injester.domain.document_ir import DocumentIR, DocumentBlock


class FrozenDict(dict):
    """An immutable dict that blocks in-place mutations once frozen."""
    def __setitem__(self, key: Any, value: Any) -> None:
        raise TypeError(f"'{self.__class__.__name__}' is immutable and does not support item assignment")
    def __delitem__(self, key: Any) -> None:
        raise TypeError(f"'{self.__class__.__name__}' is immutable and does not support item deletion")
    def clear(self) -> None:
        raise TypeError(f"'{self.__class__.__name__}' is immutable")
    def pop(self, *args: Any, **kwargs: Any) -> Any:
        raise TypeError(f"'{self.__class__.__name__}' is immutable")
    def popitem(self) -> Any:
        raise TypeError(f"'{self.__class__.__name__}' is immutable")
    def setdefault(self, *args: Any, **kwargs: Any) -> Any:
        raise TypeError(f"'{self.__class__.__name__}' is immutable")
    def update(self, *args: Any, **kwargs: Any) -> None:
        raise TypeError(f"'{self.__class__.__name__}' is immutable")


class FrozenList(list):
    """An immutable list that blocks in-place mutations once frozen."""
    def __setitem__(self, idx: Any, value: Any) -> None:
        raise TypeError(f"'{self.__class__.__name__}' is immutable and does not support item assignment")
    def __delitem__(self, idx: Any) -> None:
        raise TypeError(f"'{self.__class__.__name__}' is immutable and does not support item deletion")
    def append(self, x: Any) -> None:
        raise TypeError(f"'{self.__class__.__name__}' is immutable")
    def extend(self, x: Any) -> None:
        raise TypeError(f"'{self.__class__.__name__}' is immutable")
    def insert(self, i: int, x: Any) -> None:
        raise TypeError(f"'{self.__class__.__name__}' is immutable")
    def remove(self, x: Any) -> None:
        raise TypeError(f"'{self.__class__.__name__}' is immutable")
    def pop(self, *args: Any, **kwargs: Any) -> Any:
        raise TypeError(f"'{self.__class__.__name__}' is immutable")
    def clear(self) -> None:
        raise TypeError(f"'{self.__class__.__name__}' is immutable")
    def reverse(self) -> None:
        raise TypeError(f"'{self.__class__.__name__}' is immutable")
    def sort(self, *args: Any, **kwargs: Any) -> None:
        raise TypeError(f"'{self.__class__.__name__}' is immutable")


def deep_freeze(obj: Any) -> Any:
    """Recursively converts nested dictionaries and lists into their immutable counterparts."""
    if isinstance(obj, dict):
        return FrozenDict({k: deep_freeze(v) for k, v in obj.items()})
    elif isinstance(obj, (list, tuple)):
        return FrozenList([deep_freeze(v) for v in obj])
    return obj


class ChangeOperationType(str, Enum):
    # Procedural operations (Manuals, SOPs)
    MOVE_PROCEDURE_STEP = "MOVE_PROCEDURE_STEP"
    UPDATE_STEP_INSTRUCTION = "UPDATE_STEP_INSTRUCTION"
    INSERT_PROCEDURE_STEP = "INSERT_PROCEDURE_STEP"
    REMOVE_PROCEDURE_STEP = "REMOVE_PROCEDURE_STEP"

    # General document operations (Resumes, Reports, Contracts, Papers)
    REORDER_SECTION = "REORDER_SECTION"
    EDIT_PARAGRAPH_TEXT = "EDIT_PARAGRAPH_TEXT"


class TypedChangeCommand(BaseModel):
    """
    Typed, reviewable change command.
    Neither the visual editor nor the AI modifies source documents directly;
    all modifications are submitted via this contract.
    Supports procedural steps (target_step_id) and general document blocks (target_block_id).
    """
    command_id: str = Field(default_factory=lambda: f"cmd_{uuid.uuid4().hex[:10]}")
    operation: ChangeOperationType
    target_step_id: Optional[str] = None
    target_block_id: Optional[str] = None
    before_step_id: Optional[str] = None
    before_block_id: Optional[str] = None
    source_block_ids: List[str] = Field(default_factory=list)
    new_values: Optional[Dict[str, Any]] = None
    expected_document_version: str
    rationale: str = ""
    proposed_by: str = "user"
    # Procedure scope: target and anchor must belong to this procedure's parent block ID.
    # If None, the engine infers it from the target step's block.
    procedure_parent_block_id: Optional[str] = None
    is_frozen: bool = False

    def freeze(self) -> None:
        """Deeply freezes this command and all its nested collections."""
        if self.new_values is not None:
            object.__setattr__(self, "new_values", deep_freeze(self.new_values))
        object.__setattr__(self, "source_block_ids", deep_freeze(self.source_block_ids))
        object.__setattr__(self, "is_frozen", True)

    def __setattr__(self, name: str, value: Any) -> None:
        if getattr(self, "is_frozen", False):
            raise ValueError(
                f"TypedChangeCommand '{getattr(self, 'command_id', '')}' is frozen and cannot be modified after approval."
            )
        super().__setattr__(name, value)


class StepDependency(BaseModel):
    """Prerequisite relationship between procedural steps."""
    step_id: str
    depends_on_step_id: str
    reason: str


class ChangeImpact(BaseModel):
    """Impact analysis report generated before applying a command."""
    is_valid: bool
    conflicts: List[str] = Field(default_factory=list)
    affected_block_ids: List[str] = Field(default_factory=list)
    affected_prose_block_ids: List[str] = Field(default_factory=list)
    requires_review: bool = False
    details: Dict[str, Any] = Field(default_factory=dict)
    has_unregistered_dependencies: bool = False
    is_frozen: bool = False

    def freeze(self) -> None:
        """Deeply freezes the impact analysis report and its collections."""
        object.__setattr__(self, "conflicts", deep_freeze(self.conflicts))
        object.__setattr__(self, "affected_block_ids", deep_freeze(self.affected_block_ids))
        object.__setattr__(self, "affected_prose_block_ids", deep_freeze(self.affected_prose_block_ids))
        object.__setattr__(self, "details", deep_freeze(self.details))
        object.__setattr__(self, "is_frozen", True)

    def __setattr__(self, name: str, value: Any) -> None:
        if getattr(self, "is_frozen", False):
            raise ValueError("ChangeImpact is frozen and cannot be modified after approval.")
        super().__setattr__(name, value)


class ChangeSet(BaseModel):
    """Immutable audit record of an evaluated or applied document change."""
    changeset_id: str = Field(default_factory=lambda: f"cs_{uuid.uuid4().hex[:10]}")
    document_id: str
    file_path: Optional[str] = None
    document_version: str
    command: TypedChangeCommand
    impact: ChangeImpact
    before_step_order: List[str]
    after_step_order: List[str]
    # Lifecycle: PROPOSED → APPROVED or REJECTED → APPLIED
    status: str = "PROPOSED"
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    approved_by: Optional[str] = None
    approved_at: Optional[str] = None
    approval_signature: Optional[str] = None
    is_frozen: bool = False

    def freeze(self) -> None:
        """Deeply freezes the ChangeSet, underlying Command, and Impact report."""
        self.command.freeze()
        self.impact.freeze()
        object.__setattr__(self, "before_step_order", deep_freeze(self.before_step_order))
        object.__setattr__(self, "after_step_order", deep_freeze(self.after_step_order))
        object.__setattr__(self, "is_frozen", True)

    def __setattr__(self, name: str, value: Any) -> None:
        if getattr(self, "is_frozen", False):
            raise ValueError(
                f"ChangeSet '{getattr(self, 'changeset_id', '')}' is frozen and cannot be modified after approval."
            )
        super().__setattr__(name, value)


# ChangeSet statuses that permit recompilation.
COMPILABLE_STATUSES: Set[str] = {"APPROVED"}


class ChangeEngine:
    """
    The Change Engine resolves IDs, validates expected versions,
    evaluates step dependencies, and generates reviewable ChangeSets.
    """
    def __init__(self):
        self.dependencies: Dict[str, List[StepDependency]] = {}  # step_id -> prerequisites

    def register_dependency(
        self,
        step_id: str,
        depends_on_step_id: str,
        reason: str = "",
        known_step_ids: Optional[Set[str]] = None,
    ) -> None:
        """
        Declares that step_id requires depends_on_step_id to have completed previously.
        Validates that both steps are known (when known_step_ids is provided) and that
        no duplicate or self-referential dependency is registered. Detects cycles.
        """
        if step_id == depends_on_step_id:
            raise ValueError(f"Self-referential dependency: step '{step_id}' cannot depend on itself.")

        if known_step_ids is not None:
            if step_id not in known_step_ids:
                raise ValueError(f"Cannot register dependency: step '{step_id}' is not a known step.")
            if depends_on_step_id not in known_step_ids:
                raise ValueError(f"Cannot register dependency: prerequisite step '{depends_on_step_id}' is not a known step.")

        # Duplicate check
        existing = self.dependencies.get(step_id, [])
        for dep in existing:
            if dep.depends_on_step_id == depends_on_step_id:
                return  # Idempotent: already registered

        if step_id not in self.dependencies:
            self.dependencies[step_id] = []
        self.dependencies[step_id].append(
            StepDependency(step_id=step_id, depends_on_step_id=depends_on_step_id, reason=reason)
        )

        # Cycle detection via DFS
        if self._has_cycle(step_id, set()):
            # Roll back the just-added dependency
            self.dependencies[step_id].pop()
            raise ValueError(
                f"Dependency cycle detected: adding '{step_id}' → '{depends_on_step_id}' would create a cycle."
            )

    def _has_cycle(self, start: str, visited: Set[str]) -> bool:
        """Returns True if the dependency graph contains a cycle reachable from start."""
        if start in visited:
            return True
        visited.add(start)
        for dep in self.dependencies.get(start, []):
            if self._has_cycle(dep.depends_on_step_id, set(visited)):
                return True
        return False

    @staticmethod
    def compute_command_digest(command: TypedChangeCommand) -> str:
        """Computes a canonical SHA-256 digest of the complete TypedChangeCommand payload."""
        canonical = {
            "command_id": command.command_id,
            "operation": command.operation.value if hasattr(command.operation, "value") else str(command.operation),
            "target_step_id": command.target_step_id,
            "target_block_id": command.target_block_id,
            "before_step_id": command.before_step_id,
            "before_block_id": command.before_block_id,
            "source_block_ids": sorted(command.source_block_ids or []),
            "new_values": command.new_values or {},
            "expected_document_version": command.expected_document_version,
            "rationale": command.rationale,
            "proposed_by": command.proposed_by,
            "procedure_parent_block_id": command.procedure_parent_block_id,
        }
        payload = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @classmethod
    def compute_approval_signature(
        cls,
        changeset_id: str,
        document_id: str,
        document_version: str,
        approver_id: str,
        command: Any,
        signing_key: Optional[str] = None,
    ) -> str:
        """
        Computes a cryptographic HMAC-SHA256 signature binding the approval to the exact
        document version, authenticated approver identity, and full canonical command payload.
        Requires a dedicated approval signing key provisioned via APPROVAL_SIGNING_KEY or passed explicitly.
        Fails closed if no secret is provisioned.
        """
        key_str = signing_key or os.getenv("APPROVAL_SIGNING_KEY")
        if not key_str:
            try:
                from injester.config import settings
                key_str = settings.APPROVAL_SIGNING_KEY
            except Exception:
                pass

        if not key_str or not key_str.strip():
            raise ValueError(
                "Dedicated approval signing key is not configured. "
                "In multi-user or production deployments, set the APPROVAL_SIGNING_KEY environment variable. "
                "Approvals fail closed when a dedicated secret is absent."
            )

        if isinstance(command, TypedChangeCommand):
            command_id = command.command_id
            command_digest = cls.compute_command_digest(command)
        else:
            command_id = str(command)
            command_digest = hashlib.sha256(command_id.encode("utf-8")).hexdigest()

        payload = f"{changeset_id}:{document_id}:{document_version}:{approver_id}:{command_id}:{command_digest}"
        return hmac.new(key_str.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()

    def approve_changeset(
        self,
        changeset: ChangeSet,
        approver: Optional[Union[Any, str]] = None,
        active_session_doc_id: str = "",
        active_session_version: str = "",
        rationale: str = "",
        signing_key: Optional[str] = None,
        approver_id: Optional[str] = None,
    ) -> ChangeSet:
        """
        Controlled approval operation.
        Verifies document/version bindings, authenticates approver identity, computes an immutable
        HMAC-SHA256 approval signature over the complete command payload, and deeply freezes the ChangeSet.
        """
        effective_approver = approver if approver is not None else approver_id
        if effective_approver is None:
            raise ValueError("Approver identity required to approve ChangeSet. Anonymous approvals are rejected.")

        # Check for SecurityContext object or string principal
        if hasattr(effective_approver, "user_id") or hasattr(effective_approver, "email"):
            uid = getattr(effective_approver, "user_id", None)
            email = getattr(effective_approver, "email", None)
            approver_clean = str(uid or email or "").strip()
            if not approver_clean:
                raise ValueError("Authenticated SecurityContext must contain a non-empty user_id or email.")
        elif isinstance(effective_approver, str):
            if not effective_approver.strip():
                raise ValueError("Approver identity required to approve ChangeSet. Anonymous approvals are rejected.")
            approver_clean = effective_approver.strip()
            disallowed_placeholders = {
                "authorized_user", "default", "none", "anonymous",
                "system_default", "user", "admin", "guest"
            }
            if approver_clean.lower() in disallowed_placeholders:
                raise ValueError(
                    f"Invalid approver identity '{effective_approver}': generic placeholder and unauthenticated "
                    f"approver roles are prohibited. Approvals must be bound to a verified principal identifier."
                )
        else:
            raise TypeError("Approver must be an authenticated SecurityContext or valid principal identifier string.")

        if changeset.status == "APPLIED":
            raise ValueError(f"Cannot approve ChangeSet '{changeset.changeset_id}': already APPLIED.")
        if not changeset.impact.is_valid:
            raise ValueError(
                f"Cannot approve invalid ChangeSet '{changeset.changeset_id}'. "
                f"Conflicts: {'; '.join(changeset.impact.conflicts)}"
            )
        if changeset.document_id != active_session_doc_id:
            raise ValueError(
                f"Document ID mismatch: ChangeSet references '{changeset.document_id}', "
                f"active session is '{active_session_doc_id}'."
            )
        if changeset.document_version != active_session_version:
            raise ValueError(
                f"Document version mismatch: ChangeSet targets '{changeset.document_version}', "
                f"active session is '{active_session_version}'."
            )
        if changeset.command.expected_document_version != active_session_version:
            raise ValueError(
                f"Command version mismatch: Command expected '{changeset.command.expected_document_version}', "
                f"active session is '{active_session_version}'."
            )

        changeset.status = "APPROVED"
        changeset.approved_by = approver_clean
        changeset.approved_at = datetime.now(timezone.utc).isoformat()
        changeset.approval_signature = self.compute_approval_signature(
            changeset.changeset_id,
            changeset.document_id,
            changeset.document_version,
            changeset.approved_by,
            changeset.command,
            signing_key=signing_key,
        )
        changeset.freeze()
        return changeset

    @staticmethod
    def _resolve_section_blocks(heading_block_id: str, document_ir: DocumentIR) -> List[DocumentBlock]:
        """Resolves the heading and all descendant blocks belonging to a section."""
        order = document_ir.structural_order
        if heading_block_id not in order:
            return []
        start_idx = order.index(heading_block_id)
        start_block = document_ir.blocks[heading_block_id]
        start_level = start_block.formatting.heading_level or 1

        section_blocks: List[DocumentBlock] = [start_block]
        for bid in order[start_idx + 1:]:
            b = document_ir.blocks[bid]
            if b.formatting.is_heading or b.block_type == "HEADING":
                lvl = b.formatting.heading_level or 1
                if lvl <= start_level:
                    break
            section_blocks.append(b)
        return section_blocks

    def evaluate_command(
        self,
        command: TypedChangeCommand,
        current_step_order: List[str],
        document_ir: DocumentIR,
        step_to_block_map: Dict[str, str],
        active_document_version: str,
        # Maps step_id -> parent block id for procedure scope enforcement
        step_parent_map: Optional[Dict[str, Optional[str]]] = None,
    ) -> ChangeImpact:
        """
        Evaluates a command against the active document version, step topology, and Document IR.
        Identifies dependency conflicts, affected source blocks, and related prose blocks.
        Supports both procedural steps and general document blocks (sections, paragraphs).
        """
        conflicts: List[str] = []
        affected_blocks: List[str] = []
        affected_prose: List[str] = []
        requires_review = False
        is_noop = False

        # 1. Version Lineage Check
        if command.expected_document_version != active_document_version:
            conflicts.append(
                f"Version mismatch: Command expected version '{command.expected_document_version}', "
                f"but active document is version '{active_document_version}'."
            )
            return ChangeImpact(
                is_valid=False,
                conflicts=conflicts,
                affected_block_ids=[],
                requires_review=True,
            )

        # -------------------------------------------------------------------
        # General Document Operations (Resumes, Reports, Contracts, Papers)
        # -------------------------------------------------------------------
        if command.operation in (ChangeOperationType.EDIT_PARAGRAPH_TEXT, ChangeOperationType.REORDER_SECTION):
            target_bid = command.target_block_id or (
                step_to_block_map.get(command.target_step_id) if command.target_step_id else None
            )
            if not target_bid or target_bid not in document_ir.blocks:
                conflicts.append(f"Target block '{target_bid}' not found in active Document IR.")
                return ChangeImpact(
                    is_valid=False,
                    conflicts=conflicts,
                    affected_block_ids=[],
                    requires_review=True,
                )

            target_block = document_ir.blocks[target_bid]

            if command.operation == ChangeOperationType.EDIT_PARAGRAPH_TEXT:
                new_text = (
                    (command.new_values or {}).get("new_text")
                    or (command.new_values or {}).get("instruction")
                )
                if not new_text or not str(new_text).strip():
                    conflicts.append("Empty text update: 'new_text' must contain non-whitespace text.")
                affected_blocks.append(target_bid)
                is_valid = len(conflicts) == 0
                return ChangeImpact(
                    is_valid=is_valid,
                    conflicts=conflicts,
                    affected_block_ids=affected_blocks,
                    requires_review=False,
                    details={
                        "operation": command.operation.value,
                        "target_block_id": target_bid,
                        "is_noop": target_block.text_content.strip() == (str(new_text) if new_text else "").strip(),
                    },
                )

            elif command.operation == ChangeOperationType.REORDER_SECTION:
                if not (target_block.formatting.is_heading or target_block.block_type == "HEADING"):
                    conflicts.append(
                        f"Target block '{target_bid}' is not a heading; only sections starting with a heading can be reordered."
                    )
                section_blocks = self._resolve_section_blocks(target_bid, document_ir)
                affected_blocks.extend([b.block_id for b in section_blocks])

                anchor_bid = command.before_block_id or (
                    step_to_block_map.get(command.before_step_id) if command.before_step_id else None
                )
                if not anchor_bid:
                    conflicts.append(
                        "Missing anchor section: REORDER_SECTION requires an explicit 'before_block_id' "
                        "specifying the anchor heading before which the section should be inserted."
                    )
                else:
                    if anchor_bid not in document_ir.blocks:
                        conflicts.append(f"Anchor section block '{anchor_bid}' not found in active Document IR.")
                    elif anchor_bid in affected_blocks:
                        conflicts.append(
                            f"Cyclic section anchor: Anchor block '{anchor_bid}' is inside the target section "
                            f"'{target_bid}' being moved. A section cannot be moved before a block within itself."
                        )
                    else:
                        anchor_block = document_ir.blocks[anchor_bid]
                        if not (anchor_block.formatting.is_heading or anchor_block.block_type == "HEADING"):
                            conflicts.append(f"Anchor block '{anchor_bid}' is not a heading block.")

                is_valid = len(conflicts) == 0
                return ChangeImpact(
                    is_valid=is_valid,
                    conflicts=conflicts,
                    affected_block_ids=affected_blocks,
                    requires_review=False,
                    details={
                        "operation": command.operation.value,
                        "target_heading_id": target_bid,
                        "section_block_count": len(section_blocks),
                        "anchor_heading_id": anchor_bid,
                    },
                )

        # -------------------------------------------------------------------
        # Procedural Step Operations (Manuals, SOPs)
        # -------------------------------------------------------------------
        target = command.target_step_id
        if not target or target not in current_step_order:
            conflicts.append(f"Target step '{target}' not found in active procedure steps.")
            return ChangeImpact(
                is_valid=False,
                conflicts=conflicts,
                affected_block_ids=[],
                requires_review=True,
            )

        # 3. Source Block Verification
        target_block_id = step_to_block_map.get(target)
        if target_block_id:
            affected_blocks.append(target_block_id)
            if target_block_id not in document_ir.blocks:
                conflicts.append(f"Source block '{target_block_id}' does not exist in Document IR.")

        for b_id in command.source_block_ids:
            if b_id not in affected_blocks:
                affected_blocks.append(b_id)
            if b_id not in document_ir.blocks:
                conflicts.append(f"Referenced source block '{b_id}' does not exist in Document IR.")

        # 4. Procedure Scope Enforcement
        if command.operation == ChangeOperationType.MOVE_PROCEDURE_STEP:
            before_target = command.before_step_id

            if before_target and before_target not in current_step_order:
                conflicts.append(f"Target anchor step '{before_target}' not found in active steps.")
            else:
                # Scope enforcement: target and anchor must belong to the same procedure
                if step_parent_map is not None and before_target:
                    target_parent = step_parent_map.get(target)
                    anchor_parent = step_parent_map.get(before_target)
                    declared_parent = command.procedure_parent_block_id

                    if target_parent != anchor_parent:
                        conflicts.append(
                            f"Procedure scope violation: Target step '{target}' (parent: {target_parent}) "
                            f"and anchor step '{before_target}' (parent: {anchor_parent}) "
                            f"belong to different procedure sections. Cross-section moves are not permitted."
                        )
                    elif declared_parent is not None and declared_parent != target_parent:
                        conflicts.append(
                            f"Procedure scope mismatch: Command declares procedure parent '{declared_parent}' "
                            f"but target step '{target}' belongs to procedure parent '{target_parent}'."
                        )

                if not conflicts:
                    # Check for explicit NO-OP (already at target position)
                    curr_target_pos = current_step_order.index(target)
                    if before_target:
                        curr_anchor_pos = current_step_order.index(before_target)
                        if curr_target_pos == curr_anchor_pos - 1 or target == before_target:
                            is_noop = True
                    elif curr_target_pos == len(current_step_order) - 1:
                        is_noop = True

                    # Calculate proposed new order
                    new_order = [s for s in current_step_order if s != target]
                    if before_target:
                        insert_idx = new_order.index(before_target)
                        new_order.insert(insert_idx, target)
                    else:
                        new_order.append(target)

                    # Check forward & backward dependency constraints
                    target_pos = new_order.index(target)

                    # A. Does target require any step that now appears AFTER it?
                    prereqs = self.dependencies.get(target, [])
                    for dep in prereqs:
                        prereq_id = dep.depends_on_step_id
                        if prereq_id in new_order:
                            prereq_pos = new_order.index(prereq_id)
                            if prereq_pos > target_pos:
                                conflicts.append(
                                    f"Dependency Conflict: Step '{target}' depends on '{prereq_id}' "
                                    f"({dep.reason or 'prerequisite'}), but would be placed before it."
                                )

                    # B. Does any other step depend on target, but now appears BEFORE target?
                    for other_step, other_prereqs in self.dependencies.items():
                        for dep in other_prereqs:
                            if dep.depends_on_step_id == target and other_step in new_order:
                                other_pos = new_order.index(other_step)
                                if other_pos < target_pos:
                                    conflicts.append(
                                        f"Dependency Conflict: Step '{other_step}' depends on '{target}' "
                                        f"({dep.reason or 'prerequisite'}), but would now precede it."
                                    )

        elif command.operation == ChangeOperationType.UPDATE_STEP_INSTRUCTION:
            # Validate new instruction is non-empty (empty string updates are not supported)
            new_text = (command.new_values or {}).get("instruction") if command.new_values else None
            if not new_text:
                conflicts.append(
                    "Empty instruction update is not permitted. "
                    "Provide a non-empty 'instruction' value in new_values, or use REMOVE_PROCEDURE_STEP."
                )

        # 5. Check Affected Prose / Related Callouts
        if target_block_id and target_block_id in document_ir.blocks:
            tb = document_ir.blocks[target_block_id]
            if tb.parent_block_id:
                for b in document_ir.blocks.values():
                    if b.parent_block_id == tb.parent_block_id and b.block_type in ("PARAGRAPH", "CALLOUT") and b.block_id != target_block_id:
                        if b.block_id not in affected_prose:
                            affected_prose.append(b.block_id)

        is_valid = len(conflicts) == 0
        requires_review = (len(conflicts) > 0) or len(affected_prose) > 0
        has_unreg = len(self.dependencies) == 0

        details = {
            "operation": command.operation.value,
            "target_step": target,
            "proposed_by": command.proposed_by,
            "is_noop": is_noop,
        }
        if has_unreg:
            details["unregistered_dependency_warning"] = (
                "No step dependencies have been registered for this document. "
                "Absence of conflicts does not certify dependency safety."
            )

        return ChangeImpact(
            is_valid=is_valid,
            conflicts=conflicts,
            affected_block_ids=affected_blocks,
            affected_prose_block_ids=affected_prose,
            requires_review=requires_review,
            has_unregistered_dependencies=has_unreg,
            details=details,
        )

    def create_changeset(
        self,
        command: TypedChangeCommand,
        current_step_order: List[str],
        impact: ChangeImpact,
        document_id: str,
        document_version: str,
        file_path: Optional[str] = None,
    ) -> ChangeSet:
        """Constructs an auditable ChangeSet representing the proposed mutation."""
        new_order = list(current_step_order)
        if impact.is_valid and command.operation == ChangeOperationType.MOVE_PROCEDURE_STEP:
            target = command.target_step_id
            before_target = command.before_step_id
            new_order = [s for s in current_step_order if s != target]
            if before_target and before_target in new_order:
                idx = new_order.index(before_target)
                new_order.insert(idx, target)
            else:
                new_order.append(target)

        # Initial status is strictly PROPOSED (if valid) or REJECTED (if invalid).
        # A ChangeSet is NEVER automatically approved: it must be approved via approve_changeset().
        status = "PROPOSED" if impact.is_valid else "REJECTED"

        return ChangeSet(
            document_id=document_id,
            file_path=file_path,
            document_version=document_version,
            command=command,
            impact=impact,
            before_step_order=current_step_order,
            after_step_order=new_order,
            status=status,
        )
