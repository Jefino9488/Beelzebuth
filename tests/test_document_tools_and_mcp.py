"""
Milestone Acceptance Test Suite: Unified Document-Operation Service & MCP Server.

Validates the full 3-stage document operation workflow:
- Stage 1: Discover & Inspect (list_documents, inspect_document, get_document_structure, find_blocks, get_block_content)
- Stage 2: Propose & Review (propose_text_edit, propose_section_reorder, propose_block_move, preview_changeset)
- Stage 3: Approve, Apply & Verify (approve_changeset, apply_changeset, verify_document, get_change_report)

Hardenings covered:
- P0: MCP cannot self-approve without human authorization (approval_token or explicit APPROVAL_MODE=unattended).
- P0: Filesystem boundaries prevent path traversal, arbitrary file inspection, and out-of-boundary writing.
- P1: Standalone verification independently confirms structural integrity, package styles, operation correctness, and content preservation.
"""

import os
import sys
import shutil
import subprocess
import zipfile
import tempfile
import time
import sqlite3
from concurrent.futures import ThreadPoolExecutor
import pytest

from injester.config import settings
from injester.application.document_tools import DocumentToolService, document_tools
from injester.infrastructure.docx_patcher import DocxPatchError
from injester.semantic.change_engine import ChangeOperationType, TypedChangeCommand
from injester.domain.auth import SecurityContext, AccessDeniedError
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
    """Yields a temporary path inside STORAGE_DIR / 'recompiled' and guarantees cleanup."""
    out_dir = settings.STORAGE_DIR / "recompiled"
    out_dir.mkdir(parents=True, exist_ok=True)
    fd, path = tempfile.mkstemp(suffix=".docx", dir=str(out_dir))
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

    # 2. Preview proposed changeset (pure diff and validation, NO approval token exposed)
    preview = service.preview_changeset(cs_id)
    assert preview["changeset_id"] == cs_id
    assert preview["is_valid"] is True
    assert "approval_token" not in preview
    token = service.issue_approval_token(cs_id)
    assert token.startswith("appr_")
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
    assert verification["operation_correctness"] is True
    assert verification["structural_integrity"] is True
    assert verification["content_preservation"] is True
    assert verification["formatting_preservation"] is True
    assert verification["source_block_count"] == verification["recompiled_block_count"]
    assert len(verification["discrepancies"]) == 0

    # 6. Retrieve auditable change report
    report = service.get_change_report(cs_id)
    assert report["changeset_id"] == cs_id
    assert report["is_successful"] is True
    assert report["unmodified_blocks_intact"] is True


# ===========================================================================
# MCP Server Tool Interface & Authorization Tests
# ===========================================================================

def test_mcp_tools_complete_editing_flow(sample_docx, temp_output_docx):
    """Verifies that MCP tools exposed to external AI clients execute the full 3-stage lifecycle with human token approval."""
    # Ensure manual mode is active
    settings.ALLOW_UNATTENDED_MCP_APPROVAL = False
    settings.APPROVAL_MODE = "manual"

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
    assert "approval_token" not in preview

    # Out-of-band human reviewer issues approval token
    human_token = mcp_server.document_tools.issue_approval_token(cs_id)
    assert human_token is not None
    assert human_token.startswith("appr_")

    # Stage 3: MCP Approval with Human Token & Recompilation
    approval = mcp_server.approve_changeset(
        changeset_id=cs_id,
        rationale="Approved with verified human token.",
        approval_token=human_token,
    )
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
    assert ver["operation_correctness"] is True

    # Audit report retrieval via MCP tool
    report = mcp_server.get_change_report(cs_id)
    assert report["changeset_id"] == cs_id


def test_mcp_unattended_approval_rejected_in_manual_mode(sample_docx):
    """P0 Security: In default manual mode, unattended self-approval by an AI client without token is rejected."""
    settings.ALLOW_UNATTENDED_MCP_APPROVAL = False
    settings.APPROVAL_MODE = "manual"

    prop = mcp_server.propose_text_edit(
        document_id_or_path=sample_docx,
        block_id="block-003",
        new_text="Self-approved mutation.",
    )
    cs_id = prop["changeset_id"]

    # Calling approve_changeset without token fails closed
    with pytest.raises(AccessDeniedError) as exc_info:
        mcp_server.approve_changeset(cs_id, rationale="AI self-approval attempt")
    assert "requires explicit human authorization" in str(exc_info.value)


def test_mcp_unattended_approval_allowed_when_opted_in(sample_docx, temp_output_docx):
    """P0 Security: When APPROVAL_MODE=unattended is explicitly configured, autonomous approval succeeds auditably."""
    settings.ALLOW_UNATTENDED_MCP_APPROVAL = True
    try:
        prop = mcp_server.propose_text_edit(
            document_id_or_path=sample_docx,
            block_id="block-003",
            new_text="Autonomous CI pipeline mutation.",
        )
        cs_id = prop["changeset_id"]

        approval = mcp_server.approve_changeset(cs_id, rationale="Autonomous test run")
        assert approval["status"] == "APPROVED"
        assert approval["approved_by"] == "mcp:unattended_agent"
    finally:
        settings.ALLOW_UNATTENDED_MCP_APPROVAL = False


def test_mcp_tools_section_reorder(sample_docx, temp_output_docx):
    """Verifies proposing, reviewing, approving, and applying section reordering via MCP."""
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
    assert "approval_token" not in prev

    # Approve with out-of-band human token and apply
    token = mcp_server.document_tools.issue_approval_token(cs_id)
    mcp_server.approve_changeset(cs_id, rationale="Approved section move.", approval_token=token)
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


# ===========================================================================
# Filesystem Boundary & Access Denial Tests
# ===========================================================================

def test_filesystem_boundary_rejection(sample_docx):
    """P0 Security: Filesystem boundaries prevent path traversal and unauthorized file access."""
    service = DocumentToolService()

    # 1. Attempting to inspect /etc/passwd or system files outside authorized roots must raise AccessDeniedError
    with pytest.raises(AccessDeniedError) as exc_info:
        service.inspect_document("/etc/passwd")
    assert "Filesystem access violation" in str(exc_info.value)

    # 2. Path traversal escaping the root must be rejected
    with pytest.raises(AccessDeniedError):
        service.inspect_document("../../../../../../../../../etc/shadow")

    # 3. Output write destinations outside authorized roots must raise AccessDeniedError
    prop = service.propose_text_edit(
        sample_docx,
        block_id="block-003",
        new_text="Filesystem write boundary test",
    )
    cs_id = prop["changeset_id"]
    token = service.issue_approval_token(cs_id)
    service.approve_changeset(cs_id, approval_token=token)

    forbidden_dest = "/tmp/forbidden_workspace_escape/malicious.docx"
    with pytest.raises(AccessDeniedError) as exc_info:
        service.apply_changeset(changeset_id=cs_id, output_path=forbidden_dest)
    assert "Filesystem access violation" in str(exc_info.value)


# ===========================================================================
# Hardened Standalone Verification Tests
# ===========================================================================

def test_verification_contract_detects_deliberate_corruption(sample_docx, temp_output_docx):
    """P1 Verification: Standalone verification detects corrupted untouched blocks, wrong edits, and style tampering."""
    service = DocumentToolService()

    # Create legitimate recompiled DOCX
    prop = service.propose_text_edit(
        sample_docx,
        block_id="block-003",
        new_text="Legitimate verified edit.",
    )
    cs_id = prop["changeset_id"]
    token = service.issue_approval_token(cs_id)
    service.approve_changeset(cs_id, approval_token=token)
    service.apply_changeset(cs_id, output_path=temp_output_docx)

    # Baseline verification passes
    base_ver = service.verify_document(sample_docx, temp_output_docx, cs_id)
    assert base_ver["is_verified"] is True
    assert base_ver["content_preservation"] is True
    assert base_ver["operation_correctness"] is True
    assert base_ver["formatting_preservation"] is True

    out_dir = settings.STORAGE_DIR / "recompiled"

    # Test 1: Corrupted untouched block -> content_preservation must fail
    corrupt_content_path = str(out_dir / "corrupted_content.docx")
    try:
        shutil.copyfile(temp_output_docx, corrupt_content_path)
        with zipfile.ZipFile(corrupt_content_path, "r") as zin:
            files = {n: zin.read(n) for n in zin.namelist()}

        doc_xml = files["word/document.xml"].decode("utf-8")
        corrupted_xml = doc_xml.replace("Pre-Boot Physical Workspace Setup", "Tampered Unexpected Content")
        files["word/document.xml"] = corrupted_xml.encode("utf-8")

        with zipfile.ZipFile(corrupt_content_path, "w") as zout:
            for n, data in files.items():
                zout.writestr(n, data)

        v_content = service.verify_document(sample_docx, corrupt_content_path, cs_id)
        assert v_content["is_verified"] is False
        assert v_content["content_preservation"] is False
        assert any("Content drift in untouched block" in d for d in v_content["discrepancies"])
    finally:
        if os.path.exists(corrupt_content_path):
            os.remove(corrupt_content_path)

    # Test 2: Target block text doesn't match expected -> operation_correctness must fail
    corrupt_target_path = str(out_dir / "corrupted_target.docx")
    try:
        shutil.copyfile(temp_output_docx, corrupt_target_path)
        with zipfile.ZipFile(corrupt_target_path, "r") as zin:
            files = {n: zin.read(n) for n in zin.namelist()}

        doc_xml = files["word/document.xml"].decode("utf-8")
        corrupted_xml = doc_xml.replace("Legitimate verified edit.", "Completely Wrong Edit Text")
        files["word/document.xml"] = corrupted_xml.encode("utf-8")

        with zipfile.ZipFile(corrupt_target_path, "w") as zout:
            for n, data in files.items():
                zout.writestr(n, data)

        v_target = service.verify_document(sample_docx, corrupt_target_path, cs_id)
        assert v_target["is_verified"] is False
        assert v_target["operation_correctness"] is False
        assert any("Operation failure on block" in d for d in v_target["discrepancies"])
    finally:
        if os.path.exists(corrupt_target_path):
            os.remove(corrupt_target_path)

    # Test 3: Modified package styles -> formatting_preservation must fail
    corrupt_style_path = str(out_dir / "corrupted_styles.docx")
    try:
        shutil.copyfile(temp_output_docx, corrupt_style_path)
        with zipfile.ZipFile(corrupt_style_path, "r") as zin:
            files = {n: zin.read(n) for n in zin.namelist()}

        files["word/styles.xml"] = files["word/styles.xml"] + b"<!-- injected style tampering -->"

        with zipfile.ZipFile(corrupt_style_path, "w") as zout:
            for n, data in files.items():
                zout.writestr(n, data)

        v_style = service.verify_document(sample_docx, corrupt_style_path, cs_id)
        assert v_style["is_verified"] is False
        assert v_style["formatting_preservation"] is False
        assert any("Package part 'word/styles.xml' was modified" in d for d in v_style["discrepancies"])
    finally:
        if os.path.exists(corrupt_style_path):
            os.remove(corrupt_style_path)


# ===========================================================================
# Robust Error Handling Tests
# ===========================================================================

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


def test_approval_token_expiration_and_replay_prevention(sample_docx):
    """P0 Security: Human approval tokens expire after TTL and are strictly single-use (replay prevention)."""
    service = DocumentToolService()
    prop = service.propose_text_edit(
        sample_docx,
        block_id="block-003",
        new_text="Token security test edit.",
    )
    cs_id = prop["changeset_id"]

    # 1. Test Expired Token
    short_lived_token = service.issue_approval_token(cs_id, approver="human_tester", ttl_seconds=1)
    time.sleep(1.2)
    with pytest.raises(AccessDeniedError) as exc_info:
        service.approve_changeset(cs_id, approval_token=short_lived_token)
    assert "expired" in str(exc_info.value).lower()

    # 2. Test Single-Use (Atomic Consumption)
    valid_token = service.issue_approval_token(cs_id, approver="human_tester", ttl_seconds=60)
    # First approval succeeds
    approved = service.approve_changeset(cs_id, approval_token=valid_token)
    assert approved["status"] == "APPROVED"

    # Replay attempt with same token must fail
    with pytest.raises(AccessDeniedError) as exc_info:
        service.approve_changeset(cs_id, approval_token=valid_token)
    assert "already been consumed" in str(exc_info.value).lower()


def test_sensitive_files_strictly_inaccessible():
    """P0 Security: Sensitive files (.env, config.env, signing keys, databases) are inaccessible through all document tools."""
    service = DocumentToolService()

    sensitive_targets = [
        ".env",
        "config.env",
        ".approval_signing_key",
        "injester.db",
        "storage/injester.db",
        ".git/config",
    ]

    for target in sensitive_targets:
        # inspect_document rejects sensitive targets
        with pytest.raises(AccessDeniedError) as exc:
            service.inspect_document(target)
        assert "access violation" in str(exc.value).lower()

        # find_blocks rejects sensitive targets
        with pytest.raises(AccessDeniedError):
            service.find_blocks(target, query="test")

        # propose_text_edit rejects sensitive targets
        with pytest.raises(AccessDeniedError):
            service.propose_text_edit(target, block_id="block-001", new_text="exploit")

        # MCP ingest_document rejects sensitive targets
        with pytest.raises(AccessDeniedError):
            mcp_server.ingest_document(target)

    with pytest.raises(KeyError):
        service.apply_changeset("cs_invalid_99999")


# ===========================================================================
# Adversarial Security & Verification Rigor Tests
# ===========================================================================

def test_concurrent_token_reuse_atomic_rejection(sample_docx):
    """P0 Security: High-concurrency race condition test. Exactly 1 consumer succeeds and all contenders fail closed."""
    service = DocumentToolService()
    prop = service.propose_text_edit(
        sample_docx,
        block_id="block-003",
        new_text="Concurrent token consumption race test.",
    )
    cs_id = prop["changeset_id"]
    token = service.issue_approval_token(cs_id, approver="alice", ttl_seconds=60)

    successes = []
    denials = []

    def _attempt_approve(worker_id: int):
        svc = DocumentToolService()
        try:
            res = svc.approve_changeset(cs_id, approval_token=token)
            successes.append((worker_id, res))
        except AccessDeniedError as e:
            denials.append((worker_id, str(e)))

    # Execute 10 concurrent approval attempts simultaneously across threads
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(_attempt_approve, i) for i in range(10)]
        for f in futures:
            f.result()

    # Exactly 1 consumer must succeed; all 9 contenders must be denied
    assert len(successes) == 1, f"Expected exactly 1 success, got {len(successes)}"
    assert len(denials) == 9, f"Expected 9 denials, got {len(denials)}"
    assert successes[0][1]["status"] == "APPROVED"
    assert any("already been consumed" in msg.lower() or "atomic contention" in msg.lower() for _, msg in denials)


def test_cross_process_changeset_and_token_flow(sample_docx, temp_output_docx):
    """P1 Reliability: ChangeSet created by one process/service instance is cleanly loaded, token-issued, approved and applied by another."""
    # Service 1 simulates Process 1 (e.g. MCP subprocess)
    proc1_svc = DocumentToolService()
    prop = proc1_svc.propose_text_edit(
        sample_docx,
        block_id="block-003",
        new_text="Cross-process verified transformation.",
    )
    cs_id = prop["changeset_id"]

    # Service 2 simulates Process 2 (e.g. REST API / Visual Workbench) with completely independent in-memory state
    proc2_svc = DocumentToolService()
    assert cs_id not in proc2_svc._changesets, "Process 2 should not have Process 1 memory cache"

    # Process 2 reads persisted ChangeSet from disk and previews it
    preview = proc2_svc.preview_changeset(cs_id)
    assert preview["changeset_id"] == cs_id
    assert preview["diff_summary"]["after"] == "Cross-process verified transformation."
    assert "approval_token" not in preview

    # Process 2 issues single-use human token via SQLite store
    human_token = proc2_svc.issue_approval_token(cs_id, approver="human_lead")
    assert human_token.startswith("appr_")

    # Service 3 simulates Process 3 (e.g. CLI or MCP applying the edit)
    proc3_svc = DocumentToolService()
    approved = proc3_svc.approve_changeset(cs_id, approval_token=human_token)
    assert approved["status"] == "APPROVED"

    report = proc3_svc.apply_changeset(cs_id, output_path=temp_output_docx)
    assert report["is_successful"] is True

    # Replay on any service instance must fail
    with pytest.raises(AccessDeniedError):
        proc1_svc.approve_changeset(cs_id, approval_token=human_token)


def test_verification_fails_when_target_block_text_is_duplicated_elsewhere(sample_docx, temp_output_docx):
    """P1 Verification: Verifier verifies specifically on target block ID, rejecting edits applied to wrong block."""
    service = DocumentToolService()
    prop = service.propose_text_edit(
        sample_docx,
        block_id="block-003",
        new_text="Target Specific Unique Edit",
    )
    cs_id = prop["changeset_id"]
    token = service.issue_approval_token(cs_id)
    service.approve_changeset(cs_id, approval_token=token)
    service.apply_changeset(cs_id, output_path=temp_output_docx)

    # Tamper the recompiled file: move the target text from block-003 to another block, leaving block-003 unmodified
    out_dir = settings.STORAGE_DIR / "recompiled"
    tampered_docx = str(out_dir / "tampered_wrong_block.docx")
    try:
        shutil.copyfile(temp_output_docx, tampered_docx)
        with zipfile.ZipFile(tampered_docx, "r") as zin:
            files = {n: zin.read(n) for n in zin.namelist()}

        doc_xml = files["word/document.xml"].decode("utf-8")
        # Revert block-003 to original and inject target text into block-004 instead
        doc_xml = doc_xml.replace("Target Specific Unique Edit", "Workstation Deployment Guide")
        doc_xml = doc_xml.replace("Overview", "Target Specific Unique Edit")
        files["word/document.xml"] = doc_xml.encode("utf-8")

        with zipfile.ZipFile(tampered_docx, "w") as zout:
            for n, data in files.items():
                zout.writestr(n, data)

        res = service.verify_document(sample_docx, tampered_docx, cs_id)
        assert res["is_verified"] is False
        assert res["operation_correctness"] is False
        assert any("Operation failure on block 'block-003'" in d for d in res["discrepancies"])
    finally:
        if os.path.exists(tampered_docx):
            os.remove(tampered_docx)


def test_verification_detects_dropped_ooxml_package_parts(sample_docx, temp_output_docx):
    """P1 Verification: Verifier checks package part presence; dropped styles or numbering fails verification."""
    service = DocumentToolService()
    prop = service.propose_text_edit(
        sample_docx,
        block_id="block-003",
        new_text="Part drop detection test.",
    )
    cs_id = prop["changeset_id"]
    token = service.issue_approval_token(cs_id)
    service.approve_changeset(cs_id, approval_token=token)
    service.apply_changeset(cs_id, output_path=temp_output_docx)

    out_dir = settings.STORAGE_DIR / "recompiled"
    corrupt_docx = str(out_dir / "dropped_numbering_part.docx")
    try:
        shutil.copyfile(temp_output_docx, corrupt_docx)
        with zipfile.ZipFile(corrupt_docx, "r") as zin:
            # Exclude word/numbering.xml
            files = {n: zin.read(n) for n in zin.namelist() if n != "word/numbering.xml"}

        with zipfile.ZipFile(corrupt_docx, "w") as zout:
            for n, data in files.items():
                zout.writestr(n, data)

        res = service.verify_document(sample_docx, corrupt_docx, cs_id)
        assert res["is_verified"] is False
        assert res["formatting_preservation"] is False
        assert any("Preserved package part 'word/numbering.xml' present in source was dropped" in d for d in res["discrepancies"])
    finally:
        if os.path.exists(corrupt_docx):
            os.remove(corrupt_docx)


def test_persistence_failure_fails_closed(sample_docx, monkeypatch):
    """P0 Security: Persistence failures do not swallow exceptions and fail closed."""
    service = DocumentToolService()
    prop = service.propose_text_edit(
        sample_docx,
        block_id="block-003",
        new_text="Persistence failure test.",
    )
    cs_id = prop["changeset_id"]

    # Deliberately break SQLite connection in _connect_token_db to simulate disk failure / DB lock
    from injester.application import document_tools as dt_mod
    def _broken_db():
        raise sqlite3.OperationalError("Simulated disk I/O failure or database lock")

    monkeypatch.setattr(dt_mod, "_connect_token_db", _broken_db)

    # Issue approval token must raise RuntimeError and NOT return an unpersisted token
    with pytest.raises(RuntimeError) as exc_info:
        service.issue_approval_token(cs_id)
    assert any(term in str(exc_info.value) for term in ["Transactional persistence failure", "Database error querying authoritative ChangeSet"])

    # verify_and_consume must also raise RuntimeError and NOT silently approve
    with pytest.raises(RuntimeError) as exc_info:
        service.verify_and_consume_approval_token(cs_id, "appr_dummy_token_12345")
    assert "Database error during token verification" in str(exc_info.value)


def test_cross_process_stale_cache_invalidation_and_authoritative_application(sample_docx, temp_output_docx):
    """
    Cross-Process Consistency:
    1. Process 1 proposes a ChangeSet and caches it in memory (status: PROPOSED, version: 1).
    2. Process 2 (e.g. Web Workbench) approves it and persists the updated ChangeSet (status: APPROVED, version: 2).
    3. Process 1 (e.g. MCP agent) reads and applies the ChangeSet.
    Authoritative persistence invalidates Process 1's stale cache, applies the approved ChangeSet
    without throwing a ChangeSetNotApprovedError, and never clobbers newer persistent state.
    """
    proc1_svc = DocumentToolService()
    prop = proc1_svc.propose_text_edit(
        sample_docx,
        block_id="block-003",
        new_text="Cross-process cache invalidation verified text.",
    )
    cs_id = prop["changeset_id"]

    # Verify Process 1 holds the proposed ChangeSet in its local memory cache
    assert cs_id in proc1_svc._changesets
    assert proc1_svc._changesets[cs_id].status == "PROPOSED"
    assert proc1_svc._changeset_versions.get(cs_id) == 1

    # Process 2 loads from persistence and approves the ChangeSet
    proc2_svc = DocumentToolService()
    human_token = proc2_svc.issue_approval_token(cs_id, approver="workbench_admin")
    approved_cs = proc2_svc.approve_changeset(cs_id, approval_token=human_token)
    assert approved_cs["status"] == "APPROVED"
    assert proc2_svc._changeset_versions.get(cs_id) == 2

    # CRITICAL TEST: Process 1 still has status == "PROPOSED" in its in-memory dict!
    assert proc1_svc._changesets[cs_id].status == "PROPOSED"

    # Process 1 now applies the changeset. It must detect that persistent store is version 2,
    # refresh its local cache, and successfully compile and verify the document.
    apply_result = proc1_svc.apply_changeset(cs_id, output_path=temp_output_docx)
    assert apply_result["is_successful"] is True
    assert apply_result["unmodified_blocks_intact"] is True

    # Process 1's local cache should now reflect the approved, authoritative state
    assert proc1_svc._changesets[cs_id].status == "APPROVED"
    assert proc1_svc._changeset_versions.get(cs_id) == 2

    # Verify the persistent store was NOT overwritten with stale 'PROPOSED' state
    refreshed_proc2 = DocumentToolService()
    cs_record = refreshed_proc2._get_changeset(cs_id)
    assert cs_record is not None
    assert cs_record.status == "APPROVED"
    assert cs_record.approval_signature is not None


def test_changeset_id_validation_and_path_traversal_rejection(sample_docx):
    """Security Boundary: Validates ChangeSet ID against format rules and prevents filesystem traversal."""
    from injester.application.document_tools import validate_changeset_id

    service = DocumentToolService()

    # Valid ChangeSet IDs must pass
    assert validate_changeset_id("cs_1234567890").name == "cs_1234567890.json"
    assert validate_changeset_id("cs-alpha-beta-01").name == "cs-alpha-beta-01.json"

    # Traversal and invalid patterns must be rejected with ValueError
    malicious_ids = [
        "../../../etc/passwd",
        "cs_test/../secret",
        "cs_test\\..\\secret",
        "cs_test\0evil",
        "cs!@#$%",
        "cs with spaces",
        "",
        "a" * 65,  # Exceeds max length
    ]

    for bad_id in malicious_ids:
        with pytest.raises(ValueError):
            validate_changeset_id(bad_id)

        # _get_changeset returns None for invalid IDs
        assert service._get_changeset(bad_id) is None

        # get_changeset raises ValueError
        with pytest.raises(ValueError):
            service.get_changeset(bad_id)


def test_stale_changeset_save_rejects_concurrent_overwrite(sample_docx):
    """Optimistic Concurrency: Saving a stale in-memory ChangeSet over a newer persistent version is rejected."""
    proc1_svc = DocumentToolService()
    prop = proc1_svc.propose_text_edit(
        sample_docx,
        block_id="block-003",
        new_text="Concurrent save conflict test.",
    )
    cs_id = prop["changeset_id"]

    # Keep a reference to the version 1 ChangeSet in Process 1
    stale_cs = proc1_svc._changesets[cs_id]
    assert proc1_svc._changeset_versions[cs_id] == 1

    # Process 2 updates the ChangeSet to version 2
    proc2_svc = DocumentToolService()
    token = proc2_svc.issue_approval_token(cs_id)
    proc2_svc.approve_changeset(cs_id, approval_token=token)
    assert proc2_svc._changeset_versions[cs_id] == 2

    # Process 1 attempts to blindly overwrite the database using its stale version 1
    with pytest.raises(RuntimeError) as exc_info:
        proc1_svc._save_changeset(stale_cs)

    assert "Concurrent modification conflict" in str(exc_info.value)


def test_sqlite_error_fails_closed_without_stale_json_fallback(sample_docx, monkeypatch):
    """
    P1 Security: When the authoritative SQLite database fails or is unavailable,
    _get_changeset fails closed with RuntimeError. It must NEVER fall back to
    reading unverified or potentially stale JSON files from disk.
    """
    service = DocumentToolService()
    prop = service.propose_text_edit(
        sample_docx,
        block_id="block-003",
        new_text="Authoritative fail closed test text.",
    )
    cs_id = prop["changeset_id"]

    # Verify JSON file exists on disk
    json_path = settings.STORAGE_DIR / "changesets" / f"{cs_id}.json"
    assert json_path.exists(), "JSON mirror should exist on disk"

    # Clear in-memory cache to force a persistent lookup
    service._changesets.clear()
    service._changeset_versions.clear()

    # Simulate SQLite operational failure / lock / disk error
    import sqlite3
    from injester.application import document_tools as dt_mod

    def _broken_db():
        raise sqlite3.OperationalError("Simulated database lock or I/O failure")

    monkeypatch.setattr(dt_mod, "_connect_token_db", _broken_db)

    # Must raise RuntimeError and NOT fall back to reading json_path
    with pytest.raises(RuntimeError) as exc_info:
        service._get_changeset(cs_id)

    assert "Database error querying authoritative ChangeSet" in str(exc_info.value)


def test_cross_os_processes_changeset_lifecycle_integration(sample_docx, temp_output_docx):
    """
    P2 End-to-End Subprocess Integration:
    Launches true, independent OS processes via sys.executable:
    1. OS Process 1 proposes a ChangeSet and holds it in process memory (status: PROPOSED).
    2. OS Process 2 starts independently, loads the ChangeSet from SQLite, issues an approval token,
       and approves the ChangeSet.
    3. OS Process 1 is notified, retrieves the ChangeSet from SQLite (invalidating its stale in-memory cache),
       and applies the verified edit to temp_output_docx.
    Exercises real OS process isolation, SQLite WAL multi-process access, and independent configs.
    """
    import textwrap

    script_proc1 = textwrap.dedent("""
        import sys
        from injester.application.document_tools import DocumentToolService

        sample_docx = sys.argv[1]
        out_docx = sys.argv[2]

        service = DocumentToolService()
        prop = service.propose_text_edit(
            sample_docx,
            block_id="block-003",
            new_text="Verified multi-OS-process transformed content.",
        )
        cs_id = prop["changeset_id"]
        assert cs_id in service._changesets
        assert service._changesets[cs_id].status == "PROPOSED"

        # Signal main test that Process 1 is ready with ChangeSet cached in memory
        print(f"READY:{cs_id}", flush=True)

        # Wait for approval signal from test runner
        line = sys.stdin.readline().strip()
        if line != "APPLY":
            print(f"ERROR: Expected APPLY command, got '{line}'", flush=True)
            sys.exit(1)

        # Process 1 applies the ChangeSet - must detect Process 2's approval in persistent store
        report = service.apply_changeset(cs_id, output_path=out_docx)
        assert report["is_successful"] is True
        assert service._changesets[cs_id].status == "APPROVED"
        print(f"DONE:{cs_id}", flush=True)
        sys.exit(0)
    """)

    script_proc2 = textwrap.dedent("""
        import sys
        from injester.application.document_tools import DocumentToolService

        cs_id = sys.argv[1]
        service = DocumentToolService()

        # Independent OS process issues token and approves
        token = service.issue_approval_token(cs_id, approver="os_admin_process_2")
        approved = service.approve_changeset(cs_id, approval_token=token)
        assert approved["status"] == "APPROVED"
        print(f"APPROVED:{cs_id}", flush=True)
        sys.exit(0)
    """)

    env = os.environ.copy()
    env["PYTHONPATH"] = os.getcwd()

    # Launch OS Subprocess 1
    proc1 = subprocess.Popen(
        [sys.executable, "-u", "-c", script_proc1, sample_docx, temp_output_docx],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )

    try:
        # Read READY signal from Process 1
        ready_line = proc1.stdout.readline().strip()
        assert ready_line.startswith("READY:"), f"Process 1 failed to initialize: {proc1.stderr.read()}"
        cs_id = ready_line.split(":", 1)[1]

        # Launch OS Subprocess 2 to approve the ChangeSet
        proc2_res = subprocess.run(
            [sys.executable, "-c", script_proc2, cs_id],
            capture_output=True,
            text=True,
            env=env,
            check=True,
        )
        assert "APPROVED:" in proc2_res.stdout, f"Process 2 failed to approve: {proc2_res.stderr}"

        # Signal OS Subprocess 1 to apply the ChangeSet
        proc1.stdin.write("APPLY\n")
        proc1.stdin.flush()

        done_line = proc1.stdout.readline().strip()
        assert done_line == f"DONE:{cs_id}", f"Process 1 application failed: {proc1.stderr.read()}"

        proc1.wait(timeout=30)
        assert proc1.returncode == 0

        # Assert output document was compiled successfully
        assert os.path.exists(temp_output_docx)
        service = DocumentToolService()
        verification = service.verify_document(sample_docx, temp_output_docx, changeset_id=cs_id)
        assert verification["is_verified"] is True
        assert verification["operation_correctness"] is True

    finally:
        if proc1.poll() is None:
            proc1.kill()
            proc1.wait()


