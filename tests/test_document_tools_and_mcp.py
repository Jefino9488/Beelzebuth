"""
Milestone Acceptance Test Suite: Unified Document-Operation Service & MCP Server.

Validates the full 3-stage document operation workflow:
- Stage 1: Discover & Inspect (list_documents, inspect_document, get_document_structure, find_blocks, get_block_content)
- Stage 2: Propose & Review (propose_text_edit, propose_section_reorder, propose_block_move, preview_changeset)
- Stage 3: Approve, Apply & Verify (approve_changeset, apply_changeset, verify_document, get_change_report)

Ensures that both the unified DocumentToolService and the MCP server tools share
identical validation rules, tamper-proof cryptographic approval boundaries, and surgical OOXML AST surgery.
"""

import os
import tempfile
import pytest

from injester.application.document_tools import DocumentToolService, document_tools
from injester.infrastructure.docx_patcher import DocxPatchError
from injester.semantic.change_engine import ChangeOperationType, TypedChangeCommand
from injester.domain.auth import SecurityContext
from injester.domain.models import UserRole
import injester.mcp.server as mcp_server


@pytest.fixture
def sample_docx():
    """Path to representative test DOCX fixture."""
    path = os.path.abspath("sample_docs/Workstation_Deployment_Guide.docx")
    assert os.path.exists(path), f"Sample document not found: {path}"
    return path


@pytest.fixture
def temp_output_docx():
    """Yields a temporary path for output DOCX and guarantees cleanup."""
    fd, path = tempfile.mkstemp(suffix=".docx")
    os.close(fd)
    yield path
    if os.path.exists(path):
        os.remove(path)


# ===========================================================================
# Stage 1: Discover & Inspect Tests
# ===========================================================================

def test_document_tools_stage1_discover_and_inspect(sample_docx):
    """Stage 1: Verify inspection, structure outline, block lookup, and content extraction."""
    service = DocumentToolService()

    # 1. Inspect document
    info = service.inspect_document(sample_docx)
    assert info["document_id"] is not None
    assert info["document_type"] == "MANUAL"
    assert info["total_blocks"] >= 15
    assert info["headings_count"] >= 4
    assert info["tables_count"] >= 1
    assert info["step_count"] == 6
    assert info["is_procedure_bearing"] is True

    # 2. Get document structure outline
    structure = service.get_document_structure(sample_docx)
    assert structure["total_sections"] >= 4
    assert len(structure["steps"]) == 6
    step_ids = [s["step_id"] for s in structure["steps"]]
    assert "step-01" in step_ids
    assert "step-06" in step_ids

    # 3. Find blocks by query substring
    bios_blocks = service.find_blocks(sample_docx, query="BIOS")
    assert len(bios_blocks) >= 1
    assert any("BIOS" in b["text_content"] for b in bios_blocks)

    # 4. Find blocks by block_type
    table_blocks = service.find_blocks(sample_docx, block_type="TABLE")
    assert len(table_blocks) >= 1
    assert table_blocks[0]["block_type"] == "TABLE"

    # 5. Get specific block content and formatting metadata
    first_block_id = structure["sections"][1]["blocks"][0]["block_id"]
    content = service.get_block_content(sample_docx, first_block_id)
    assert content["block_id"] == first_block_id
    assert "formatting" in content
    assert "location_xpath" in content
    assert content["text_content"] is not None


# ===========================================================================
# Stage 2: Propose & Review Edits Tests
# ===========================================================================

def test_document_tools_stage2_propose_and_review(sample_docx):
    """Stage 2: Propose edits, verify impact analysis, diff preview, and source non-mutation."""
    service = DocumentToolService()
    initial_hash = service.inspect_document(sample_docx)["file_hash"]

    # 1. Propose paragraph text edit
    prop = service.propose_text_edit(
        document_id_or_path=sample_docx,
        block_id="block-003",
        new_text="Revised corporate workstation deployment guidelines.",
        rationale="Update documentation for corporate hardware upgrade.",
    )
    cs_id = prop["changeset_id"]
    assert prop["status"] == "PROPOSED"
    assert prop["impact"]["is_valid"] is True
    assert "block-003" in prop["impact"]["affected_block_ids"]

    # 2. Preview proposed changeset
    preview = service.preview_changeset(cs_id)
    assert preview["changeset_id"] == cs_id
    assert preview["is_valid"] is True
    assert preview["diff_summary"]["target_block_id"] == "block-003"
    assert preview["diff_summary"]["after"] == "Revised corporate workstation deployment guidelines."
    assert "corporate developer workstations" in preview["diff_summary"]["before"]

    # 3. Verify source document was not modified
    current_hash = service.inspect_document(sample_docx)["file_hash"]
    assert current_hash == initial_hash, "Source file was unexpectedly mutated during proposal."

    # 4. Propose procedural block move
    move_prop = service.propose_block_move(
        document_id_or_path=sample_docx,
        step_id="step-02",
        before_step_id="step-01",
        rationale="Perform network cable connection before monitor connection.",
    )
    assert move_prop["status"] == "PROPOSED"
    move_preview = service.preview_changeset(move_prop["changeset_id"])
    assert move_preview["diff_summary"]["target_step_id"] == "step-02"
    assert move_preview["diff_summary"]["before_step_id"] == "step-01"
    assert move_preview["diff_summary"]["new_order"][0] == "step-02"


# ===========================================================================
# Stage 3: Approve, Apply & Verify Tests
# ===========================================================================

def test_document_tools_stage3_approval_and_verification(sample_docx, temp_output_docx):
    """Stage 3: Enforce approval boundary, apply OOXML surgery, and verify recompiled document."""
    service = DocumentToolService()

    # 1. Propose edit
    prop = service.propose_text_edit(
        document_id_or_path=sample_docx,
        block_id="block-003",
        new_text="Authorized workstation deployment instructions.",
        rationale="Engineering sign-off.",
    )
    cs_id = prop["changeset_id"]

    # 2. Guard: Attempting to apply an unapproved ChangeSet must fail closed
    with pytest.raises(DocxPatchError) as exc_info:
        service.apply_changeset(changeset_id=cs_id, output_path=temp_output_docx)
    assert "must be one of ['APPROVED']" in str(exc_info.value)

    # 3. Approve ChangeSet with authenticated principal
    approver_ctx = SecurityContext(
        user_id="lead_architect",
        email="architect@corp.com",
        role=UserRole.CLIENT_ADMIN,
        organisation_id="eng_dept",
    )
    approved = service.approve_changeset(
        changeset_id=cs_id,
        approver=approver_ctx,
        rationale="Production verification passed.",
    )
    assert approved["status"] == "APPROVED"
    assert approved["approved_by"] == "lead_architect"
    assert len(approved["approval_signature"]) == 64  # SHA-256 HMAC

    # 4. Apply ChangeSet via surgical AST surgery
    apply_result = service.apply_changeset(changeset_id=cs_id, output_path=temp_output_docx)
    assert apply_result["is_successful"] is True
    assert apply_result["unmodified_blocks_intact"] is True
    assert apply_result["detected_discrepancies"] == []
    assert os.path.exists(temp_output_docx)

    # 5. Round-trip verification between original and recompiled files
    verification = service.verify_document(
        source_path=sample_docx,
        recompiled_path=temp_output_docx,
        changeset_id=cs_id,
    )
    assert verification["is_verified"] is True
    assert verification["source_block_count"] == verification["recompiled_block_count"]
    assert len(verification["discrepancies"]) == 0

    # 6. Retrieve auditable change report
    report = service.get_change_report(cs_id)
    assert report["changeset_id"] == cs_id
    assert report["is_successful"] is True
    assert report["unmodified_blocks_intact"] is True


# ===========================================================================
# MCP Server Tool Interface Tests
# ===========================================================================

def test_mcp_tools_complete_editing_flow(sample_docx, temp_output_docx):
    """Verifies that MCP tools exposed to external AI clients execute the full 3-stage lifecycle."""
    # Stage 1: MCP Discovery & Inspection
    doc_info = mcp_server.inspect_document(sample_docx)
    assert doc_info["document_type"] == "MANUAL"
    assert doc_info["step_count"] == 6

    struct = mcp_server.get_document_structure(sample_docx)
    assert len(struct["sections"]) >= 4

    blocks = mcp_server.find_blocks(sample_docx, query="DisplayPort")
    assert len(blocks) >= 1
    target_bid = blocks[0]["block_id"]

    block_detail = mcp_server.get_block_content(sample_docx, target_bid)
    assert "DisplayPort" in block_detail["text_content"]

    # Stage 2: MCP Propose & Review
    new_instruction = "Step 1: Connect ultra-high-definition primary DisplayPort display."
    proposal = mcp_server.propose_text_edit(
        document_id_or_path=sample_docx,
        block_id=target_bid,
        new_text=new_instruction,
        rationale="Update monitor spec via MCP tool.",
    )
    cs_id = proposal["changeset_id"]
    assert proposal["status"] == "PROPOSED"

    preview = mcp_server.preview_changeset(cs_id)
    assert preview["is_valid"] is True
    assert preview["diff_summary"]["after"] == new_instruction

    # Stage 3: MCP Approval & Recompilation
    approval = mcp_server.approve_changeset(cs_id, rationale="Approved via MCP client.")
    assert approval["status"] == "APPROVED"
    assert len(approval["approval_signature"]) == 64

    result = mcp_server.apply_changeset(cs_id, output_path=temp_output_docx)
    assert result["is_successful"] is True
    assert result["unmodified_blocks_intact"] is True

    # Verification via MCP tool
    ver = mcp_server.verify_document(
        source_path=sample_docx,
        recompiled_path=temp_output_docx,
        changeset_id=cs_id,
    )
    assert ver["is_verified"] is True

    # Audit report retrieval via MCP tool
    report = mcp_server.get_change_report(cs_id)
    assert report["changeset_id"] == cs_id


def test_mcp_tools_section_reorder(sample_docx, temp_output_docx):
    """Verifies proposing, reviewing, approving, and applying section reordering via MCP."""
    struct = mcp_server.get_document_structure(sample_docx)
    # Target section 5 (block-016), anchor before section 3 (block-007)
    target_heading = "block-016"
    anchor_heading = "block-007"

    prop = mcp_server.propose_section_reorder(
        document_id_or_path=sample_docx,
        heading_block_id=target_heading,
        before_heading_block_id=anchor_heading,
        rationale="Move safety section before physical setup.",
    )
    cs_id = prop["changeset_id"]
    assert prop["status"] == "PROPOSED"
    assert prop["impact"]["is_valid"] is True

    prev = mcp_server.preview_changeset(cs_id)
    assert prev["diff_summary"]["target_heading_block_id"] == target_heading
    assert prev["diff_summary"]["before_heading_block_id"] == anchor_heading

    # Approve and apply
    mcp_server.approve_changeset(cs_id, rationale="Approved section move.")
    applied = mcp_server.apply_changeset(cs_id, output_path=temp_output_docx)
    assert applied["is_successful"] is True
    assert applied["unmodified_blocks_intact"] is True

    # Verify structural integrity
    ver = mcp_server.verify_document(sample_docx, temp_output_docx, cs_id)
    assert ver["is_verified"] is True


def test_mcp_unapproved_apply_rejected(sample_docx, temp_output_docx):
    """Security Boundary: Calling apply_changeset on an unapproved changeset via MCP fails closed."""
    prop = mcp_server.propose_text_edit(
        document_id_or_path=sample_docx,
        block_id="block-003",
        new_text="Unapproved mutation attempt.",
    )
    cs_id = prop["changeset_id"]

    with pytest.raises(DocxPatchError):
        mcp_server.apply_changeset(cs_id, output_path=temp_output_docx)


def test_invalid_document_or_block_error_handling(sample_docx):
    """Validates robust error handling for non-existent documents, blocks, and changesets."""
    service = DocumentToolService()

    with pytest.raises(FileNotFoundError):
        service.inspect_document("non_existent_file_path.docx")

    with pytest.raises(KeyError):
        service.get_block_content(sample_docx, "non_existent_block_9999")

    with pytest.raises(KeyError):
        service.get_changeset("cs_invalid_99999")

    with pytest.raises(KeyError):
        service.preview_changeset("cs_invalid_99999")

    with pytest.raises(KeyError):
        service.approve_changeset("cs_invalid_99999")

    with pytest.raises(KeyError):
        service.apply_changeset("cs_invalid_99999")
