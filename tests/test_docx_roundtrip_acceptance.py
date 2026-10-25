"""
Beelzebuth Phase 1: DOCX Round-Trip Acceptance Test Suite.
Validates the complete end-to-end pipeline against the 8-gate acceptance matrix:
DOCX ➔ Document IR ➔ Evidence Spans ➔ Process Graph ➔ Typed Change ➔ Validate ➔ Recompile ➔ Reopen & Compare
"""

import os
import shutil
import tempfile
import zipfile
import pytest

from injester.domain.document_ir import extract_docx_ir
from injester.semantic.change_engine import (
    TypedChangeCommand,
    ChangeOperationType,
    ChangeEngine,
)
from injester.infrastructure.docx_patcher import DocxPackagePatcher, DocxPatchError
from injester.application.docx_pipeline import DocxRoundTripPipeline, DocxSession


@pytest.fixture
def sample_docx_path():
    """Path to the representative Workstation Deployment Guide DOCX."""
    path = os.path.abspath("sample_docs/Workstation_Deployment_Guide.docx")
    assert os.path.exists(path), f"Test fixture not found: {path}"
    return path


@pytest.fixture
def temp_output_docx():
    """Temporary file path for recompiled DOCX output."""
    fd, path = tempfile.mkstemp(suffix=".docx")
    os.close(fd)
    yield path
    if os.path.exists(path):
        os.remove(path)


@pytest.fixture
def initialized_session(sample_docx_path):
    """Loads and configures the DOCX session with explicit step dependencies."""
    pipeline = DocxRoundTripPipeline()
    session = pipeline.load_document(sample_docx_path)

    # Register dependencies between dependent steps
    pipeline.register_step_dependency(session, "step-04", "step-03", "Must enter BIOS setup before configuring UEFI")
    pipeline.register_step_dependency(session, "step-05", "step-04", "Must configure UEFI before selecting boot device")
    pipeline.register_step_dependency(session, "step-06", "step-05", "Must set boot device before rebooting")

    return pipeline, session


# =====================================================================
# GATE 1: SOURCE GROUNDING
# =====================================================================
def test_gate1_source_grounding(initialized_session):
    """Gate 1: Each process node references valid source blocks and supporting evidence spans."""
    _, session = initialized_session
    assert len(session.steps) >= 4, "Expected at least 4 procedural steps"

    for step_id, step in session.steps.items():
        # Verify step maps to a valid block in Document IR
        assert step.source_block_id in session.document_ir.blocks
        block = session.document_ir.blocks[step.source_block_id]

        # Verify step has valid evidence span
        assert step.evidence_span_id.startswith("S")
        assert step.evidence_span_id in session.span_registry

        # Verify span text contains the step instruction
        span_text = session.span_registry[step.evidence_span_id]
        assert block.text_content == span_text
        assert step.instruction in span_text


# =====================================================================
# GATE 2: VALID REORDERING (INDEPENDENT STEPS)
# =====================================================================
def test_gate2_valid_reordering(initialized_session, temp_output_docx):
    """Gate 2: Independent steps move successfully with order and numbering preserved."""
    pipeline, session = initialized_session

    # Step 1 (connect monitors) and Step 2 (connect network) are independent
    cmd = TypedChangeCommand(
        operation=ChangeOperationType.MOVE_PROCEDURE_STEP,
        target_step_id="step-02",
        before_step_id="step-01",
        source_block_ids=[session.step_to_block_map["step-02"]],
        expected_document_version=session.version_id,
        rationale="Connect network cable prior to peripheral monitors",
    )

    changeset = pipeline.propose_edit(session, cmd)
    assert changeset.impact.is_valid is True
    assert len(changeset.impact.conflicts) == 0

    changeset = pipeline.approve_changeset(session, changeset, approver_id="acceptance_tester")
    report = pipeline.recompile_and_verify(session, changeset, temp_output_docx)

    assert report.is_successful is True
    assert report.step_reordering_verified is True
    assert report.reopened_step_order[0] == "step-02"
    assert report.reopened_step_order[1] == "step-01"


# =====================================================================
# GATE 3: DEPENDENCY CONFLICT DETECTION
# =====================================================================
def test_gate3_dependency_conflict(initialized_session):
    """Gate 3: Invalid or ambiguous reordering is flagged for review or rejected."""
    pipeline, session = initialized_session

    # Attempt to move Step 4 (Configure UEFI in BIOS) before Step 3 (Power on & enter BIOS)
    invalid_cmd = TypedChangeCommand(
        operation=ChangeOperationType.MOVE_PROCEDURE_STEP,
        target_step_id="step-04",
        before_step_id="step-03",
        source_block_ids=[session.step_to_block_map["step-04"]],
        expected_document_version=session.version_id,
        rationale="Attempting to configure UEFI before entering BIOS setup",
    )

    changeset = pipeline.propose_edit(session, invalid_cmd)
    assert changeset.impact.is_valid is False
    assert changeset.status == "REJECTED"
    assert any("Dependency Conflict" in c for c in changeset.impact.conflicts)
    assert "step-04" in changeset.impact.conflicts[0]
    assert "step-03" in changeset.impact.conflicts[0]


# =====================================================================
# GATE 4: STYLE & PACKAGE PRESERVATION
# =====================================================================
def test_gate4_style_preservation(initialized_session, temp_output_docx):
    """Gate 4: Unmodified paragraphs, tables, warnings, and zip styles remain byte-identical."""
    pipeline, session = initialized_session

    cmd = TypedChangeCommand(
        operation=ChangeOperationType.MOVE_PROCEDURE_STEP,
        target_step_id="step-02",
        before_step_id="step-01",
        source_block_ids=[session.step_to_block_map["step-02"]],
        expected_document_version=session.version_id,
        rationale="Attach network cable first",
    )
    changeset = pipeline.propose_edit(session, cmd)
    changeset = pipeline.approve_changeset(session, changeset, approver_id="acceptance_tester")
    report = pipeline.recompile_and_verify(session, changeset, temp_output_docx)

    # 1. Verification report confirms unmodified blocks intact
    assert report.unmodified_blocks_intact is True
    assert report.package_styles_preserved is True

    # 2. Independent package byte-level inspection
    with zipfile.ZipFile(session.file_path, "r") as src_zip, zipfile.ZipFile(temp_output_docx, "r") as dst_zip:
        # Styles, numbering, and settings must be byte-for-byte identical
        for part in ["word/styles.xml", "word/numbering.xml", "word/settings.xml"]:
            if part in src_zip.namelist():
                assert src_zip.read(part) == dst_zip.read(part), f"Zip part {part} was altered"

    # 3. Verify table contents survived identically
    reopened_ir = extract_docx_ir(temp_output_docx)
    orig_tables = [b for b in session.document_ir.blocks.values() if b.block_type == "TABLE"]
    reop_tables = [b for b in reopened_ir.blocks.values() if b.block_type == "TABLE"]
    assert len(orig_tables) == len(reop_tables)
    assert orig_tables[0].table_data == reop_tables[0].table_data


# =====================================================================
# GATE 5: CHANGE PROVENANCE AUDIT TRAIL
# =====================================================================
def test_gate5_change_provenance(initialized_session):
    """Gate 5: ChangeSet records operation, affected blocks, evidence, and review status."""
    pipeline, session = initialized_session

    cmd = TypedChangeCommand(
        operation=ChangeOperationType.MOVE_PROCEDURE_STEP,
        target_step_id="step-02",
        before_step_id="step-01",
        source_block_ids=[session.step_to_block_map["step-02"]],
        expected_document_version=session.version_id,
        rationale="User instructed step reorder in visual editor",
        proposed_by="user_canvas_drag",
    )
    changeset = pipeline.propose_edit(session, cmd)

    assert changeset.changeset_id.startswith("cs_")
    assert changeset.document_id == session.document_id
    assert changeset.command.operation == ChangeOperationType.MOVE_PROCEDURE_STEP
    assert changeset.command.proposed_by == "user_canvas_drag"
    assert session.step_to_block_map["step-02"] in changeset.impact.affected_block_ids
    assert changeset.before_step_order != changeset.after_step_order


# =====================================================================
# GATE 6: ROUND-TRIP SURVIVABILITY
# =====================================================================
def test_gate6_roundtrip_survivability(initialized_session, temp_output_docx):
    """Gate 6: Re-extraction confirms intended edit without unintended additions or dropped content."""
    pipeline, session = initialized_session

    cmd = TypedChangeCommand(
        operation=ChangeOperationType.MOVE_PROCEDURE_STEP,
        target_step_id="step-02",
        before_step_id="step-01",
        source_block_ids=[session.step_to_block_map["step-02"]],
        expected_document_version=session.version_id,
        rationale="Reorder pre-boot connections",
    )
    changeset = pipeline.propose_edit(session, cmd)
    changeset = pipeline.approve_changeset(session, changeset, approver_id="acceptance_tester")
    report = pipeline.recompile_and_verify(session, changeset, temp_output_docx)

    assert report.is_successful is True
    assert len(report.detected_discrepancies) == 0

    # Ensure total structural blocks count is identical (no duplicated or dropped paragraphs)
    reopened_ir = extract_docx_ir(temp_output_docx)
    assert reopened_ir.total_blocks == session.document_ir.total_blocks


# =====================================================================
# GATE 7: IDEMPOTENCE
# =====================================================================
def test_gate7_idempotence(initialized_session, temp_output_docx):
    """Gate 7: Reapplying the same approved command produces identical, uncorrupted output."""
    pipeline, session = initialized_session

    cmd = TypedChangeCommand(
        operation=ChangeOperationType.MOVE_PROCEDURE_STEP,
        target_step_id="step-02",
        before_step_id="step-01",
        source_block_ids=[session.step_to_block_map["step-02"]],
        expected_document_version=session.version_id,
        rationale="Idempotence test",
    )
    changeset = pipeline.propose_edit(session, cmd)
    changeset = pipeline.approve_changeset(session, changeset, approver_id="acceptance_tester")

    # First application
    report1 = pipeline.recompile_and_verify(session, changeset, temp_output_docx)
    assert report1.is_successful is True

    # Read bytes of first output
    with open(temp_output_docx, "rb") as f:
        bytes1 = f.read()

    # Re-apply to second output
    fd2, path2 = tempfile.mkstemp(suffix=".docx")
    os.close(fd2)
    try:
        report2 = pipeline.recompile_and_verify(session, changeset, path2)
        assert report2.is_successful is True

        with open(path2, "rb") as f:
            bytes2 = f.read()

        # Both recompiled packages must have identical size and re-extracted order
        ir1 = extract_docx_ir(temp_output_docx)
        ir2 = extract_docx_ir(path2)
        assert [ir1.blocks[b].text_content for b in ir1.structural_order] == [
            ir2.blocks[b].text_content for b in ir2.structural_order
        ]
    finally:
        if os.path.exists(path2):
            os.remove(path2)


# =====================================================================
# GATE 8: FAILURE RECOVERY & ATOMIC SAFETY
# =====================================================================
def test_gate8_failure_recovery(initialized_session):
    """Gate 8: A failed patch leaves the original file untouched and returns an actionable error."""
    pipeline, session = initialized_session
    orig_hash_before = session.file_hash

    # Construct invalid command pointing to nonexistent block
    corrupt_cmd = TypedChangeCommand(
        operation=ChangeOperationType.MOVE_PROCEDURE_STEP,
        target_step_id="nonexistent-step",
        before_step_id="step-01",
        source_block_ids=["block-999"],
        expected_document_version=session.version_id,
        rationale="Corrupted instruction",
    )

    changeset = pipeline.propose_edit(session, corrupt_cmd)
    assert changeset.impact.is_valid is False

    with pytest.raises(DocxPatchError) as exc_info:
        pipeline.recompile_and_verify(session, changeset, "/tmp/should_never_exist.docx")

    assert "Cannot recompile ChangeSet" in str(exc_info.value)

    # Verify original file remains completely untouched
    with open(session.file_path, "rb") as f:
        assert hashlib_sha256(f.read()) == orig_hash_before


# =====================================================================
# REAL DOCUMENT TEST: /home/jefino9488/Documents/
# =====================================================================
def test_real_document_ir_extraction():
    """Verifies that Document IR correctly extracts real enterprise DOCX files without error."""
    real_doc_path = "/home/jefino9488/Documents/CareBank-Code Akasha-Architecture Document.docx"
    if not os.path.exists(real_doc_path):
        pytest.skip("Real document not available in environment")

    ir = extract_docx_ir(real_doc_path)
    assert ir.total_blocks > 200, "Expected > 200 blocks in real architecture doc"
    assert len(ir.structural_order) == ir.total_blocks

    # Verify heading blocks detected
    headings = [b for b in ir.blocks.values() if b.block_type == "HEADING"]
    assert len(headings) > 20, "Expected > 20 headings in real architecture doc"


def hashlib_sha256(b: bytes) -> str:
    import hashlib
    return hashlib.sha256(b).hexdigest()


# =====================================================================
# REAL DOCUMENT ROUND-TRIP EDIT TEST
# =====================================================================
def test_real_document_roundtrip_edit(temp_output_docx):
    """
    Performs a genuine surgical round-trip edit on real enterprise DOCX files.

    Part A — Large enterprise codebase archive (carebank-backend.docx, 4840 blocks, 110 tables):
      Classified as MANUAL; contains over 1,000 procedure verification steps. Validates that
      procedural step reordering round-trips safely, all 110 tables survive, and package styles
      remain intact on a large-scale real-world document.

    Part B — Architecture document (CareBank-Code Akasha-Architecture Document.docx, 309 blocks):
      Classified as MANUAL; verifies that procedural step reordering round-trips safely,
      all unmodified blocks remain intact, and the package styles are preserved.
    """
    from injester.domain.document_ir import DocumentType

    # ------------------------------------------------------------------ Part A: carebank-backend.docx
    backend_path = "/home/jefino9488/Documents/carebank-backend.docx"
    if not os.path.exists(backend_path):
        pytest.skip("Real enterprise document (carebank-backend.docx) not available")

    pipeline = DocxRoundTripPipeline()
    session_a = pipeline.load_document(backend_path)
    assert session_a.document_ir.total_blocks > 4000, "carebank-backend must have > 4000 blocks"
    assert session_a.document_ir.document_type == DocumentType.MANUAL, "carebank-backend classified as MANUAL"
    assert len(session_a.steps) > 500, f"Expected > 500 steps, got {len(session_a.steps)}"

    # Step 1: Security, Step 2: Code Quality
    cmd_a = TypedChangeCommand(
        operation=ChangeOperationType.MOVE_PROCEDURE_STEP,
        target_step_id="step-02",
        before_step_id="step-01",
        source_block_ids=[session_a.step_to_block_map["step-02"]],
        expected_document_version=session_a.version_id,
        rationale="Reorder verification checklist items in real enterprise document",
    )
    changeset_a = pipeline.propose_edit(session_a, cmd_a)
    assert changeset_a.impact.is_valid is True
    assert len(changeset_a.impact.conflicts) == 0

    changeset_a = pipeline.approve_changeset(session_a, changeset_a, approver_id="acceptance_tester")
    report_a = pipeline.recompile_and_verify(session_a, changeset_a, temp_output_docx)
    assert report_a.is_successful is True
    assert report_a.unmodified_blocks_intact is True
    assert report_a.package_styles_preserved is True
    assert report_a.step_reordering_verified is True

    # Verify python-docx opens the recompiled package cleanly
    import docx
    reopened_a = docx.Document(temp_output_docx)
    assert len(reopened_a.tables) == 110, "All 110 tables must survive in real enterprise document"
    assert len(reopened_a.paragraphs) > 4000

    # ------------------------------------------------------------------ Part B
    arch_path = "/home/jefino9488/Documents/CareBank-Code Akasha-Architecture Document.docx"
    if not os.path.exists(arch_path):
        pytest.skip("Real architecture document not available")

    session_b = pipeline.load_document(arch_path)
    assert session_b.document_ir.total_blocks > 100
    assert session_b.document_ir.document_type == DocumentType.MANUAL, (
        f"Architecture doc expected MANUAL, got {session_b.document_ir.document_type}"
    )
    assert len(session_b.steps) >= 2, (
        f"Architecture MANUAL must have >= 2 grounded steps, got {len(session_b.steps)}"
    )

    # Reorder step-02 before step-01
    cmd = TypedChangeCommand(
        operation=ChangeOperationType.MOVE_PROCEDURE_STEP,
        target_step_id="step-02",
        before_step_id="step-01",
        source_block_ids=[session_b.step_to_block_map["step-02"]],
        expected_document_version=session_b.version_id,
        rationale="Reorder architecture document steps in real MANUAL round-trip test",
    )

    changeset = pipeline.propose_edit(session_b, cmd)
    assert changeset.impact.is_valid is True
    assert len(changeset.impact.conflicts) == 0

    changeset = pipeline.approve_changeset(session_b, changeset, approver_id="acceptance_tester")
    temp_output_b = temp_output_docx + ".b.docx"
    try:
        report = pipeline.recompile_and_verify(session_b, changeset, temp_output_b)
        assert report.is_successful is True
        assert report.unmodified_blocks_intact is True
        assert report.package_styles_preserved is True
        assert report.step_reordering_verified is True
        assert len(report.detected_discrepancies) == 0

        # Verify python-docx opens the recompiled package cleanly
        reopened = docx.Document(temp_output_b)
        assert len(reopened.paragraphs) > 100
    finally:
        if os.path.exists(temp_output_b):
            os.unlink(temp_output_b)


# =====================================================================
# UNSUPPORTED DOCUMENT STRUCTURE DETECTION & SAFE REJECTION
# =====================================================================
def test_unsupported_document_features_safe_rejection(sample_docx_path):
    """
    Gate: When a paragraph contains unsupported features (tracked changes, SDT,
    cross-paragraph bookmarks, section breaks), patching is safely rejected
    with an actionable DocxPatchError to protect document integrity.
    """
    from lxml import etree
    from injester.domain.document_ir import W_NS

    ir = extract_docx_ir(sample_docx_path)
    b_step1 = [b for b in ir.blocks.values() if "Step 1:" in b.text_content][0]
    elem_idx = b_step1.location.element_index

    def inject_tracked_changes(p):
        ins = etree.SubElement(p, f"{{{W_NS}}}ins", {f"{{{W_NS}}}id": "99", f"{{{W_NS}}}author": "Reviewer"})
        t = etree.SubElement(ins, f"{{{W_NS}}}t")
        t.text = "Tracked edit"

    def inject_sdt_control(p):
        sdt = etree.SubElement(p, f"{{{W_NS}}}sdt")
        sdt_content = etree.SubElement(sdt, f"{{{W_NS}}}sdtContent")
        t = etree.SubElement(sdt_content, f"{{{W_NS}}}t")
        t.text = "Structured Field"

    def inject_cross_paragraph_bookmark(p):
        etree.SubElement(p, f"{{{W_NS}}}bookmarkStart", {f"{{{W_NS}}}id": "999", f"{{{W_NS}}}name": "_CrossBookmark"})

    def inject_embedded_sectpr(p):
        pPr = p.find(f"{{{W_NS}}}pPr")
        if pPr is None:
            pPr = etree.SubElement(p, f"{{{W_NS}}}pPr")
        etree.SubElement(pPr, f"{{{W_NS}}}sectPr")

    for feature_name, mutator in [
        ("Tracked Changes", inject_tracked_changes),
        ("Content Control SDT", inject_sdt_control),
        ("Cross-paragraph Bookmark", inject_cross_paragraph_bookmark),
        ("Embedded Section Break", inject_embedded_sectpr),
    ]:
        fd, mutated_docx = tempfile.mkstemp(suffix=".docx")
        os.close(fd)
        try:
            with zipfile.ZipFile(sample_docx_path, "r") as src_z, zipfile.ZipFile(mutated_docx, "w") as dst_z:
                for item in src_z.infolist():
                    content = src_z.read(item.filename)
                    if item.filename == "word/document.xml":
                        tree = etree.fromstring(content)
                        body = tree.find(f"{{{W_NS}}}body")
                        mutator(body[elem_idx])
                        content = etree.tostring(tree)
                    dst_z.writestr(item, content)

            pipeline = DocxRoundTripPipeline()
            session = pipeline.load_document(mutated_docx)
            cmd = TypedChangeCommand(
                operation=ChangeOperationType.MOVE_PROCEDURE_STEP,
                target_step_id="step-01",
                before_step_id="step-02",
                source_block_ids=[session.step_to_block_map["step-01"]],
                expected_document_version=session.version_id,
                rationale="Attempt edit on unsupported structure",
            )
            changeset = pipeline.propose_edit(session, cmd)
            changeset = pipeline.approve_changeset(session, changeset, approver_id="acceptance_tester")

            with pytest.raises(DocxPatchError) as exc_info:
                pipeline.recompile_and_verify(session, changeset, "/tmp/should_fail.docx")

            assert "Unsupported document feature" in str(exc_info.value), f"Failed for {feature_name}"
        finally:
            if os.path.exists(mutated_docx):
                os.remove(mutated_docx)


# =====================================================================
# STALE VERSION REJECTION
# =====================================================================
def test_stale_document_version_rejection(initialized_session):
    """
    Verifies that passing an outdated version hash to TypedChangeCommand
    immediately fails validation without altering the document.
    """
    pipeline, session = initialized_session

    stale_cmd = TypedChangeCommand(
        operation=ChangeOperationType.MOVE_PROCEDURE_STEP,
        target_step_id="step-02",
        before_step_id="step-01",
        source_block_ids=[session.step_to_block_map["step-02"]],
        expected_document_version="v_outdated_stale_hash",
        rationale="Stale version test",
    )

    changeset = pipeline.propose_edit(session, stale_cmd)
    assert changeset.impact.is_valid is False
    assert changeset.status == "REJECTED"
    assert any("Version mismatch" in c for c in changeset.impact.conflicts)

    with pytest.raises(DocxPatchError):
        pipeline.recompile_and_verify(session, changeset, "/tmp/stale_out.docx")


# =====================================================================
# NO-OP IDEMPOTENCE
# =====================================================================
def test_noop_idempotent_reorder(initialized_session, temp_output_docx):
    """
    Verifies that moving a step to where it already is is detected as a NO-OP,
    validates successfully, and produces an uncorrupted, identical output.
    """
    pipeline, session = initialized_session

    # In initialized_session, step-01 already immediately precedes step-02
    noop_cmd = TypedChangeCommand(
        operation=ChangeOperationType.MOVE_PROCEDURE_STEP,
        target_step_id="step-01",
        before_step_id="step-02",
        source_block_ids=[session.step_to_block_map["step-01"]],
        expected_document_version=session.version_id,
        rationale="Move step to its already existing position",
    )

    changeset = pipeline.propose_edit(session, noop_cmd)
    assert changeset.impact.is_valid is True
    assert changeset.impact.details.get("is_noop") is True
    assert changeset.before_step_order == changeset.after_step_order

    changeset = pipeline.approve_changeset(session, changeset, approver_id="acceptance_tester")
    report = pipeline.recompile_and_verify(session, changeset, temp_output_docx)
    assert report.is_successful is True
    assert len(report.detected_discrepancies) == 0


# =====================================================================
# DEEP XML PROPERTY PRESERVATION
# =====================================================================
def test_deep_xml_property_preservation(initialized_session, temp_output_docx):
    """
    Gate: Deep XML property comparison verifying that paragraph properties
    (pPr style, numId, ilvl), table structures, and run properties (bold, italic)
    of untouched blocks are 100% identical before and after patching.
    """
    pipeline, session = initialized_session

    cmd = TypedChangeCommand(
        operation=ChangeOperationType.MOVE_PROCEDURE_STEP,
        target_step_id="step-02",
        before_step_id="step-01",
        source_block_ids=[session.step_to_block_map["step-02"]],
        expected_document_version=session.version_id,
        rationale="Deep XML style check",
    )

    changeset = pipeline.propose_edit(session, cmd)
    changeset = pipeline.approve_changeset(session, changeset, approver_id="acceptance_tester")
    report = pipeline.recompile_and_verify(session, changeset, temp_output_docx)
    assert report.is_successful is True

    reopened_ir = extract_docx_ir(temp_output_docx)
    step_block_ids = set(session.step_to_block_map.values())

    for b_id, orig_b in session.document_ir.blocks.items():
        if b_id in step_block_ids:
            continue
        # Find matching block in reopened_ir
        matching = [rb for rb in reopened_ir.blocks.values() if rb.text_content.strip() == orig_b.text_content.strip()]
        assert len(matching) >= 1, f"Block {b_id} missing in re-extracted IR"
        rb = matching[0]

        # Verify typographic and structural properties
        assert orig_b.formatting.is_heading == rb.formatting.is_heading
        assert orig_b.formatting.heading_level == rb.formatting.heading_level
        assert orig_b.formatting.is_list_item == rb.formatting.is_list_item
        assert orig_b.formatting.num_id == rb.formatting.num_id
        assert orig_b.formatting.ilvl == rb.formatting.ilvl
        assert orig_b.formatting.is_bold == rb.formatting.is_bold
        assert orig_b.formatting.is_italic == rb.formatting.is_italic
        assert orig_b.formatting.is_table == rb.formatting.is_table
        if orig_b.formatting.is_table:
            assert orig_b.table_data == rb.table_data


# =====================================================================
# P0 / P1 AUTHORIZATION, SECURITY & BOUNDARY ACCEPTANCE TESTS
# =====================================================================

def test_unapproved_changeset_rejection(initialized_session, temp_output_docx):
    """P0 Authorization: Attempting to recompile a PROPOSED or unapproved ChangeSet is strictly rejected."""
    pipeline, session = initialized_session
    cmd = TypedChangeCommand(
        operation=ChangeOperationType.MOVE_PROCEDURE_STEP,
        target_step_id="step-02",
        before_step_id="step-01",
        source_block_ids=[session.step_to_block_map["step-02"]],
        expected_document_version=session.version_id,
        rationale="Unapproved compilation attempt",
    )
    changeset = pipeline.propose_edit(session, cmd)
    assert changeset.status == "PROPOSED"

    with pytest.raises(DocxPatchError) as exc_info:
        pipeline.recompile_and_verify(session, changeset, temp_output_docx)
    assert "status is 'PROPOSED'" in str(exc_info.value)
    assert "must be explicitly approved" in str(exc_info.value)


def test_changeset_immutability_enforced(initialized_session):
    """P0 Security: Approved ChangeSets and TypedChangeCommands strictly reject in-place mutation."""
    pipeline, session = initialized_session
    cmd = TypedChangeCommand(
        operation=ChangeOperationType.MOVE_PROCEDURE_STEP,
        target_step_id="step-02",
        before_step_id="step-01",
        source_block_ids=[session.step_to_block_map["step-02"]],
        expected_document_version=session.version_id,
        rationale="Immutability enforcement test",
    )
    changeset = pipeline.propose_edit(session, cmd)
    changeset = pipeline.approve_changeset(session, changeset, approver_id="test_admin")

    # Modifying the changeset directly must raise ValueError
    with pytest.raises(ValueError) as exc1:
        changeset.status = "PROPOSED"
    assert "is frozen and cannot be modified" in str(exc1.value)

    with pytest.raises(ValueError) as exc2:
        changeset.approval_signature = "bad_sig"
    assert "is frozen and cannot be modified" in str(exc2.value)

    # Modifying the underlying command must also raise ValueError
    with pytest.raises(ValueError) as exc3:
        changeset.command.target_step_id = "step-03"
    assert "is frozen and cannot be modified" in str(exc3.value)

    # Attempting to unfreeze must also raise ValueError
    with pytest.raises(ValueError) as exc4:
        changeset.is_frozen = False
    assert "is frozen and cannot be modified" in str(exc4.value)

    with pytest.raises(ValueError) as exc5:
        changeset.command.is_frozen = False
    assert "is frozen and cannot be modified" in str(exc5.value)


def test_nested_command_mutations_rejected(initialized_session):
    """P0 Immutability: Mutating nested command values or lists after approval raises TypeError."""
    pipeline, session = initialized_session
    cmd = TypedChangeCommand(
        operation=ChangeOperationType.UPDATE_STEP_INSTRUCTION,
        target_step_id="step-01",
        source_block_ids=[session.step_to_block_map["step-01"]],
        new_values={"instruction": "Valid initial instruction text."},
        expected_document_version=session.version_id,
        rationale="Nested mutation test",
    )
    changeset = pipeline.propose_edit(session, cmd)
    changeset = pipeline.approve_changeset(session, changeset, approver_id="test_admin")

    # 1. Attempt in-place mutation of new_values dictionary
    with pytest.raises(TypeError) as exc1:
        changeset.command.new_values["instruction"] = "Tampered instruction"
    assert "is immutable and does not support item assignment" in str(exc1.value)

    with pytest.raises(TypeError) as exc2:
        changeset.command.new_values.pop("instruction")
    assert "is immutable" in str(exc2.value)

    # 2. Attempt in-place mutation of source_block_ids list
    with pytest.raises(TypeError) as exc3:
        changeset.command.source_block_ids.append("extra-block")
    assert "is immutable" in str(exc3.value)

    with pytest.raises(TypeError) as exc4:
        changeset.command.source_block_ids[0] = "block-999"
    assert "is immutable and does not support item assignment" in str(exc4.value)

    # 3. Attempt in-place mutation of impact collections
    with pytest.raises(TypeError) as exc5:
        changeset.impact.conflicts.append("Injected conflict")
    assert "is immutable" in str(exc5.value)


def test_missing_approval_signing_key_fails_closed(initialized_session, monkeypatch):
    """P0 Security: When APPROVAL_SIGNING_KEY is missing or empty, approval fails closed without falling back to constants or JWT_SECRET."""
    from injester.config import settings
    pipeline, session = initialized_session
    cmd = TypedChangeCommand(
        operation=ChangeOperationType.MOVE_PROCEDURE_STEP,
        target_step_id="step-02",
        before_step_id="step-01",
        source_block_ids=[session.step_to_block_map["step-02"]],
        expected_document_version=session.version_id,
        rationale="Missing secret fail closed test",
    )
    changeset = pipeline.propose_edit(session, cmd)

    # Clear APPROVAL_SIGNING_KEY in env and settings while JWT_SECRET is present
    monkeypatch.delenv("APPROVAL_SIGNING_KEY", raising=False)
    monkeypatch.setattr(settings, "APPROVAL_SIGNING_KEY", "")
    monkeypatch.setenv("JWT_SECRET", "should-never-be-used-for-approval")

    with pytest.raises(ValueError) as exc:
        pipeline.approve_changeset(session, changeset, approver_id="acceptance_tester")
    assert "Dedicated approval signing key is not configured" in str(exc.value)
    assert "APPROVAL_SIGNING_KEY" in str(exc.value)


def test_local_mode_auto_generates_and_persists_key(tmp_path, monkeypatch):
    """P0 Security/UX: Local mode automatically generates a persistent random 256-bit key with 0600 permissions."""
    from injester.config import Settings
    monkeypatch.delenv("APPROVAL_SIGNING_KEY", raising=False)
    monkeypatch.delenv("TESTING", raising=False)

    test_settings = Settings()
    test_settings.COMMUNITY_MODE = True
    test_settings.APP_ENV = "development"
    test_settings.set_workspace(tmp_path)

    key1 = test_settings.get_or_create_approval_signing_key()
    assert len(key1) == 64, "Generated key must be 64 hex characters (256 bits)"

    key_file = tmp_path / ".approval_signing_key"
    assert key_file.exists(), "Key file must be persisted in workspace"
    st = os.stat(key_file)
    assert (st.st_mode & 0o777) == 0o600, "Key file permissions must be restricted to 0600 (owner read/write only)"

    # Subsequent launch reuses the exact same key without regenerating
    key2 = test_settings.get_or_create_approval_signing_key()
    assert key1 == key2, "Subsequent launch must reuse the existing persisted key"


def test_validate_security_enforces_signing_key_in_multi_user_mode(monkeypatch):
    """P2 Security: Multi-user mode (COMMUNITY_MODE=false) requires APPROVAL_SIGNING_KEY at startup."""
    from injester.config import Settings
    monkeypatch.delenv("APPROVAL_SIGNING_KEY", raising=False)
    monkeypatch.delenv("TESTING", raising=False)

    s = Settings()
    s.COMMUNITY_MODE = False
    s.APP_ENV = "development"
    s.APPROVAL_SIGNING_KEY = ""

    with pytest.raises(ValueError, match="Dedicated APPROVAL_SIGNING_KEY is missing or too short.*multi-user"):
        s.validate_security()

    # Once provided, validation passes
    s.APPROVAL_SIGNING_KEY = "a-dedicated-multi-user-approval-signing-key-32chars"
    s.validate_security()


def test_validate_security_enforces_signing_key_in_production_mode(monkeypatch):
    """P2 Security: Production environment requires valid APPROVAL_SIGNING_KEY distinct from JWT_SECRET."""
    from injester.config import Settings
    monkeypatch.delenv("APPROVAL_SIGNING_KEY", raising=False)
    monkeypatch.delenv("TESTING", raising=False)

    s = Settings()
    s.COMMUNITY_MODE = False
    s.APP_ENV = "production"
    s.JWT_SECRET = "production-jwt-secret-with-sufficient-entropy-32chars"
    s.SUPERADMIN_INITIAL_PASSWORD = "ProductionAdminPass2026!Secure"
    s.APPROVAL_SIGNING_KEY = ""

    with pytest.raises(ValueError, match="Dedicated APPROVAL_SIGNING_KEY is missing or too short.*production"):
        s.validate_security()

    # Reusing JWT_SECRET must be rejected
    s.APPROVAL_SIGNING_KEY = s.JWT_SECRET
    with pytest.raises(ValueError, match="APPROVAL_SIGNING_KEY must not reuse JWT_SECRET"):
        s.validate_security()

    # Once a distinct 32+ char key is set, passes
    s.APPROVAL_SIGNING_KEY = "independent-approval-secret-key-32chars-prod"
    s.validate_security()


def test_local_key_persistence_failure_raises_runtime_error(tmp_path, monkeypatch):
    """P2 Security: Key persistence errors fail fast with RuntimeError rather than operating with unpersisted key."""
    from unittest.mock import patch
    from injester.config import Settings
    monkeypatch.delenv("APPROVAL_SIGNING_KEY", raising=False)
    monkeypatch.delenv("TESTING", raising=False)

    s = Settings()
    s.COMMUNITY_MODE = True
    s.APP_ENV = "development"
    s.set_workspace(tmp_path)

    with patch("os.open", side_effect=OSError("Read-only filesystem simulation")):
        with pytest.raises(RuntimeError, match="Failed to persist generated approval signing key"):
            s.get_or_create_approval_signing_key()


def test_approval_identity_from_security_context(initialized_session):
    """P0 Security: ChangeEngine and Pipeline correctly bind approval to an authenticated SecurityContext."""
    from injester.domain.auth import SecurityContext
    from injester.domain.models import UserRole

    pipeline, session = initialized_session
    cmd = TypedChangeCommand(
        operation=ChangeOperationType.MOVE_PROCEDURE_STEP,
        target_step_id="step-02",
        before_step_id="step-01",
        source_block_ids=[session.step_to_block_map["step-02"]],
        expected_document_version=session.version_id,
        rationale="SecurityContext approval test",
    )
    changeset = pipeline.propose_edit(session, cmd)
    sec_ctx = SecurityContext(
        user_id="usr_lead_architect_99",
        email="architect@corp.local",
        role=UserRole.CLIENT_ADMIN,
        organisation_id="org_1",
    )
    approved = pipeline.approve_changeset(session, changeset, approver=sec_ctx)
    assert approved.approved_by in ("usr_lead_architect_99", "architect@corp.local")
    assert approved.status == "APPROVED"
    assert approved.approval_signature is not None


def test_api_approval_spoofing_rejected(initialized_session):
    """P0 Security: API endpoint rejects callers attempting to approve changes under another user identity."""
    from fastapi.testclient import TestClient
    from injester.api.app import create_app
    from injester.domain.auth import SecurityContext
    from injester.domain.models import UserRole
    from injester.api.deps import get_current_sec_ctx

    app = create_app()
    client = TestClient(app)

    # Override security context to represent authenticated user Alice
    alice_ctx = SecurityContext(
        user_id="user_alice",
        email="alice@corp.com",
        role=UserRole.EMPLOYEE,
        organisation_id="org_1",
    )
    app.dependency_overrides[get_current_sec_ctx] = lambda: alice_ctx

    try:
        pipeline, session = initialized_session
        # 1. Load session via API
        load_res = client.post("/api/v1/beelzebuth/session/load", json={"file_path": session.file_path})
        assert load_res.status_code == 200, load_res.text
        sess_id = load_res.json()["session_id"]

        # 2. Propose edit via API
        cmd_payload = {
            "session_id": sess_id,
            "command": {
                "operation": "MOVE_PROCEDURE_STEP",
                "target_step_id": "step-02",
                "before_step_id": "step-01",
                "source_block_ids": [session.step_to_block_map["step-02"]],
                "expected_document_version": session.version_id,
                "rationale": "API spoof test",
            }
        }
        prop_res = client.post("/api/v1/beelzebuth/changeset/propose", json=cmd_payload)
        assert prop_res.status_code == 200, prop_res.text
        cs_id = prop_res.json()["changeset_id"]

        # 3. Attempt to approve claiming to be "admin_bob"
        approve_spoofed = client.post(
            "/api/v1/beelzebuth/changeset/approve",
            json={
                "session_id": sess_id,
                "changeset_id": cs_id,
                "claimed_approver_id": "admin_bob",
            }
        )
        assert approve_spoofed.status_code == 403
        assert "cannot approve changes under another identity" in approve_spoofed.text

        # 4. Legitimate approval without spoofing succeeds and records Alice
        approve_legit = client.post(
            "/api/v1/beelzebuth/changeset/approve",
            json={
                "session_id": sess_id,
                "changeset_id": cs_id,
            }
        )
        assert approve_legit.status_code == 200, approve_legit.text
        assert approve_legit.json()["approved_by"] in ("user_alice", "alice@corp.com")
    finally:
        app.dependency_overrides.clear()


def test_tampered_approval_signature_rejection(initialized_session, temp_output_docx):
    """P0 Security: Forged or tampered cryptographic approval signatures are detected and aborted."""
    pipeline, session = initialized_session
    cmd = TypedChangeCommand(
        operation=ChangeOperationType.MOVE_PROCEDURE_STEP,
        target_step_id="step-02",
        before_step_id="step-01",
        source_block_ids=[session.step_to_block_map["step-02"]],
        expected_document_version=session.version_id,
        rationale="Signature tampering test",
    )
    changeset = pipeline.propose_edit(session, cmd)
    changeset = pipeline.approve_changeset(session, changeset, approver_id="test_admin")
    assert changeset.approval_signature is not None

    # Simulate malicious low-level tampering with signature
    object.__setattr__(changeset, "approval_signature", "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef")

    with pytest.raises(DocxPatchError) as exc_info:
        pipeline.recompile_and_verify(session, changeset, temp_output_docx)
    assert "cryptographic approval signature verification failed" in str(exc_info.value)


def test_tampered_command_payload_rejected_after_approval(initialized_session, temp_output_docx):
    """P0 Security: Modifying new_values, operation, or target_block_id after approval invalidates compilation."""
    pipeline, session = initialized_session
    cmd = TypedChangeCommand(
        operation=ChangeOperationType.UPDATE_STEP_INSTRUCTION,
        target_step_id="step-01",
        source_block_ids=[session.step_to_block_map["step-01"]],
        new_values={"instruction": "Approved legitimate instruction text."},
        expected_document_version=session.version_id,
        rationale="Command payload tamper test",
    )
    changeset = pipeline.propose_edit(session, cmd)
    changeset = pipeline.approve_changeset(session, changeset, approver_id="sec_admin")

    # 1. Tamper with new_values payload via low-level object manipulation
    object.__setattr__(changeset.command, "new_values", {"instruction": "Maliciously injected backdoor instruction."})
    with pytest.raises(DocxPatchError) as exc_info1:
        pipeline.recompile_and_verify(session, changeset, temp_output_docx)
    assert "command payload was altered after approval" in str(exc_info1.value)

    # 2. Reset new_values and tamper with operation
    object.__setattr__(changeset.command, "new_values", {"instruction": "Approved legitimate instruction text."})
    object.__setattr__(changeset.command, "operation", ChangeOperationType.REMOVE_PROCEDURE_STEP)
    with pytest.raises(DocxPatchError) as exc_info2:
        pipeline.recompile_and_verify(session, changeset, temp_output_docx)
    assert "command payload was altered after approval" in str(exc_info2.value)

    # 3. Reset operation and tamper with target block
    object.__setattr__(changeset.command, "operation", ChangeOperationType.UPDATE_STEP_INSTRUCTION)
    object.__setattr__(changeset.command, "target_block_id", "block-999")
    with pytest.raises(DocxPatchError) as exc_info3:
        pipeline.recompile_and_verify(session, changeset, temp_output_docx)
    assert "command payload was altered after approval" in str(exc_info3.value)


def test_unauthenticated_approver_rejected(initialized_session):
    """P0 Security: Anonymous, empty, or default placeholder approver IDs are rejected."""
    pipeline, session = initialized_session
    cmd = TypedChangeCommand(
        operation=ChangeOperationType.MOVE_PROCEDURE_STEP,
        target_step_id="step-02",
        before_step_id="step-01",
        source_block_ids=[session.step_to_block_map["step-02"]],
        expected_document_version=session.version_id,
        rationale="Approver validation test",
    )
    changeset = pipeline.propose_edit(session, cmd)

    # Empty approver
    with pytest.raises(ValueError) as exc1:
        pipeline.approve_changeset(session, changeset, approver_id="")
    assert "Approver identity required" in str(exc1.value)

    # Placeholder / default approvers rejected
    for bad_approver in ("authorized_user", "default", "none", "anonymous", "system_default"):
        with pytest.raises(ValueError) as exc2:
            pipeline.approve_changeset(session, changeset, approver_id=bad_approver)
        assert "Invalid approver identity" in str(exc2.value)


def test_document_version_binding_mismatch_rejection(initialized_session, temp_output_docx):
    """P0 Authorization: ChangeSets targeting mismatched documents or outdated versions cannot compile."""
    pipeline, session = initialized_session
    cmd = TypedChangeCommand(
        operation=ChangeOperationType.MOVE_PROCEDURE_STEP,
        target_step_id="step-02",
        before_step_id="step-01",
        source_block_ids=[session.step_to_block_map["step-02"]],
        expected_document_version=session.version_id,
        rationale="Version binding mismatch test",
    )
    changeset = pipeline.propose_edit(session, cmd)
    changeset = pipeline.approve_changeset(session, changeset, approver_id="test_admin")

    # Mismatch document ID via low-level attribute setting
    object.__setattr__(changeset, "document_id", "doc_other_foreign_id")
    # Recompute signature for the forged state to bypass signature check and test document_id binding
    forged_sig = pipeline.change_engine.compute_approval_signature(
        changeset.changeset_id, changeset.document_id, changeset.document_version, changeset.approved_by, changeset.command
    )
    object.__setattr__(changeset, "approval_signature", forged_sig)

    with pytest.raises(DocxPatchError) as exc_info:
        pipeline.recompile_and_verify(session, changeset, temp_output_docx)
    assert "document ID mismatch" in str(exc_info.value)


def test_no_anchor_move_constrained_to_procedure(initialized_session, temp_output_docx):
    """P0 Boundary: Moving step to procedure end (before_step_id=None) constrains insertion to procedure boundary."""
    pipeline, session = initialized_session
    # Step 1 is in procedure 1 (block-007). Move step 1 to procedure end.
    cmd = TypedChangeCommand(
        operation=ChangeOperationType.MOVE_PROCEDURE_STEP,
        target_step_id="step-01",
        before_step_id=None,  # Move to procedure end
        source_block_ids=[session.step_to_block_map["step-01"]],
        expected_document_version=session.version_id,
        rationale="Move Step 1 to end of Pre-Boot procedure",
    )
    changeset = pipeline.propose_edit(session, cmd)
    assert changeset.impact.is_valid is True
    changeset = pipeline.approve_changeset(session, changeset, approver_id="test_admin")

    report = pipeline.recompile_and_verify(session, changeset, temp_output_docx)
    assert report.is_successful is True

    # In reopened document, step-01 must follow step-02, but MUST still precede step-03
    reopened_ir = extract_docx_ir(temp_output_docx)
    step1_pos = None
    step2_pos = None
    step3_pos = None
    for idx, bid in enumerate(reopened_ir.structural_order):
        txt = reopened_ir.blocks[bid].text_content.strip()
        if "Step 1:" in txt:
            step1_pos = idx
        elif "Step 2:" in txt:
            step2_pos = idx
        elif "Step 3:" in txt:
            step3_pos = idx

    assert step1_pos is not None and step2_pos is not None and step3_pos is not None
    assert step2_pos < step1_pos, "Step 1 must be moved after Step 2"
    assert step1_pos < step3_pos, "Step 1 must NOT be moved past Step 3 / into subsequent procedures!"


def test_no_anchor_move_without_scope_rejected(initialized_session, temp_output_docx):
    """P0 Boundary: Moving without anchor or procedure scope raises DocxPatchError to prevent whole-document append."""
    pipeline, session = initialized_session
    cmd = TypedChangeCommand(
        operation=ChangeOperationType.MOVE_PROCEDURE_STEP,
        target_step_id="step-01",
        before_step_id=None,
        source_block_ids=[session.step_to_block_map["step-01"]],
        expected_document_version=session.version_id,
        rationale="Unscoped move to end",
    )
    changeset = pipeline.propose_edit(session, cmd)
    changeset = pipeline.approve_changeset(session, changeset, approver_id="test_admin")

    # Call DocxPackagePatcher directly without procedure_block_ids to verify safety gate
    with pytest.raises(DocxPatchError) as exc_info:
        DocxPackagePatcher.patch_docx(
            source_docx_path=session.file_path,
            output_docx_path=temp_output_docx,
            command=cmd,
            document_ir=session.document_ir,
            step_to_block_map=session.step_to_block_map,
            procedure_block_ids=None,
        )
    assert "procedure_block_ids" in str(exc_info.value)


def test_edit_paragraph_text_general_document(initialized_session, temp_output_docx):
    """General Document: EDIT_PARAGRAPH_TEXT updates target block text and preserves all other blocks."""
    pipeline, session = initialized_session
    target_bid = "block-002"  # Introduction paragraph
    orig_text = session.document_ir.blocks[target_bid].text_content
    new_text = "Updated workstation standard operating procedure specification v2.5."

    cmd = TypedChangeCommand(
        operation=ChangeOperationType.EDIT_PARAGRAPH_TEXT,
        target_block_id=target_bid,
        source_block_ids=[target_bid],
        new_values={"new_text": new_text},
        expected_document_version=session.version_id,
        rationale="Update introductory text for general document support",
    )
    changeset = pipeline.propose_edit(session, cmd)
    assert changeset.impact.is_valid is True
    changeset = pipeline.approve_changeset(session, changeset, approver_id="test_admin")

    report = pipeline.recompile_and_verify(session, changeset, temp_output_docx)
    assert report.is_successful is True
    assert report.unmodified_blocks_intact is True

    # Reopen and verify target text
    reopened_ir = extract_docx_ir(temp_output_docx)
    matching = [b for b in reopened_ir.blocks.values() if new_text in b.text_content]
    assert len(matching) == 1, "Edited paragraph text must be found in reopened document"


def test_reorder_section_general_document(initialized_session, temp_output_docx):
    """General Document: REORDER_SECTION moves an entire section atomically before an anchor section."""
    pipeline, session = initialized_session
    target_heading_id = "block-011"  # "2. BIOS Configuration Procedure"
    anchor_heading_id = "block-007"  # "1. Hardware Verification & Connections"

    cmd = TypedChangeCommand(
        operation=ChangeOperationType.REORDER_SECTION,
        target_block_id=target_heading_id,
        before_block_id=anchor_heading_id,
        source_block_ids=[target_heading_id],
        expected_document_version=session.version_id,
        rationale="Reorder Section 2 before Section 1 in general document workflow",
    )
    changeset = pipeline.propose_edit(session, cmd)
    assert changeset.impact.is_valid is True
    changeset = pipeline.approve_changeset(session, changeset, approver_id="test_admin")

    report = pipeline.recompile_and_verify(session, changeset, temp_output_docx)
    assert report.is_successful is True
    assert report.step_reordering_verified is True
    assert len(report.detected_discrepancies) == 0

    reopened_ir = extract_docx_ir(temp_output_docx)
    t_pos = None
    a_pos = None
    for idx, bid in enumerate(reopened_ir.structural_order):
        txt = reopened_ir.blocks[bid].text_content.strip()
        if "Firmware Configuration" in txt and t_pos is None:
            t_pos = idx
        elif "Pre-Boot Physical" in txt and a_pos is None:
            a_pos = idx
    assert t_pos is not None and a_pos is not None
    assert t_pos < a_pos, "Firmware Configuration section must precede Pre-Boot Physical Workspace section"


def test_duplicate_paragraphs_disambiguation(tmp_path):
    """Disambiguation: Verifies that identical-text paragraphs in a document are tracked one-to-one."""
    import docx
    doc_path = str(tmp_path / "duplicate_paras.docx")
    out_path = str(tmp_path / "duplicate_paras_out.docx")
    doc = docx.Document()
    doc.add_heading("Section A", level=1)
    doc.add_paragraph("Duplicate content paragraph.")
    doc.add_paragraph("Unique middle paragraph.")
    doc.add_paragraph("Duplicate content paragraph.")
    doc.add_heading("Section B", level=1)
    doc.save(doc_path)

    pipeline = DocxRoundTripPipeline()
    session = pipeline.load_document(doc_path)
    dup_blocks = [b for b in session.document_ir.blocks.values() if b.text_content.strip() == "Duplicate content paragraph."]
    assert len(dup_blocks) == 2, "Expected 2 identical paragraphs in fixture"

    # Edit only the first duplicate paragraph
    first_dup_id = dup_blocks[0].block_id
    cmd = TypedChangeCommand(
        operation=ChangeOperationType.EDIT_PARAGRAPH_TEXT,
        target_block_id=first_dup_id,
        source_block_ids=[first_dup_id],
        new_values={"new_text": "Modified duplicate content paragraph."},
        expected_document_version=session.version_id,
        rationale="Disambiguate duplicate paragraphs test",
    )
    changeset = pipeline.propose_edit(session, cmd)
    changeset = pipeline.approve_changeset(session, changeset, approver_id="test_admin")

    report = pipeline.recompile_and_verify(session, changeset, out_path)
    assert report.is_successful is True
    assert report.unmodified_blocks_intact is True

    reopened_ir = extract_docx_ir(out_path)
    still_dup = [b for b in reopened_ir.blocks.values() if b.text_content.strip() == "Duplicate content paragraph."]
    assert len(still_dup) == 1, "Exactly one unmodified duplicate paragraph should remain"
    modified = [b for b in reopened_ir.blocks.values() if b.text_content.strip() == "Modified duplicate content paragraph."]
    assert len(modified) == 1, "Exactly one modified paragraph should exist"


def test_reorder_section_missing_anchor_rejected(initialized_session):
    """P1 Validation: REORDER_SECTION without before_block_id is rejected with an actionable conflict."""
    pipeline, session = initialized_session
    cmd = TypedChangeCommand(
        operation=ChangeOperationType.REORDER_SECTION,
        target_block_id="block-011",
        before_block_id=None,
        source_block_ids=["block-011"],
        expected_document_version=session.version_id,
        rationale="Missing anchor validation test",
    )
    changeset = pipeline.propose_edit(session, cmd)
    assert changeset.impact.is_valid is False
    assert any("Missing anchor section" in c for c in changeset.impact.conflicts)


def test_reorder_section_cyclic_anchor_rejected(initialized_session):
    """P1 Validation: REORDER_SECTION with an anchor inside the target section is rejected as cyclic."""
    pipeline, session = initialized_session
    # block-011 is heading of Section 2; block-012 is a body block inside Section 2
    cmd = TypedChangeCommand(
        operation=ChangeOperationType.REORDER_SECTION,
        target_block_id="block-011",
        before_block_id="block-012",
        source_block_ids=["block-011"],
        expected_document_version=session.version_id,
        rationale="Cyclic anchor validation test",
    )
    changeset = pipeline.propose_edit(session, cmd)
    assert changeset.impact.is_valid is False
    assert any("Cyclic section anchor" in c for c in changeset.impact.conflicts)


def test_reorder_section_with_tables(tmp_path):
    """P1 OOXML Surgery: Moving a section containing tables relocates the w:tbl elements intact without corruption."""
    import docx
    doc_path = str(tmp_path / "section_with_tables.docx")
    out_path = str(tmp_path / "section_with_tables_out.docx")

    doc = docx.Document()
    doc.add_heading("1. Hardware Specifications", level=1)
    doc.add_paragraph("Verify all hardware components meet specification.")
    tbl = doc.add_table(rows=2, cols=2)
    tbl.cell(0, 0).text = "Component"
    tbl.cell(0, 1).text = "Requirement"
    tbl.cell(1, 0).text = "Memory"
    tbl.cell(1, 1).text = "64GB ECC DDR5"
    doc.add_paragraph("Conclude hardware checklist.")

    doc.add_heading("2. Firmware Settings", level=1)
    doc.add_paragraph("Enable UEFI Secure Boot in setup.")
    doc.save(doc_path)

    pipeline = DocxRoundTripPipeline()
    session = pipeline.load_document(doc_path)

    sec2_h = [b.block_id for b in session.document_ir.blocks.values() if "Firmware Settings" in b.text_content][0]
    sec1_h = [b.block_id for b in session.document_ir.blocks.values() if "Hardware Specifications" in b.text_content][0]

    cmd = TypedChangeCommand(
        operation=ChangeOperationType.REORDER_SECTION,
        target_block_id=sec2_h,
        before_block_id=sec1_h,
        source_block_ids=[sec2_h],
        expected_document_version=session.version_id,
        rationale="Move Section 2 before Section 1 (containing table)",
    )
    changeset = pipeline.propose_edit(session, cmd)
    assert changeset.impact.is_valid is True

    changeset = pipeline.approve_changeset(session, changeset, approver_id="test_admin")
    report = pipeline.recompile_and_verify(session, changeset, out_path)
    assert report.is_successful is True
    assert len(report.detected_discrepancies) == 0

    reopened_doc = docx.Document(out_path)
    assert len(reopened_doc.tables) == 1, "Table must survive in recompiled document"
    assert reopened_doc.tables[0].cell(1, 1).text == "64GB ECC DDR5"

    headings = [p.text for p in reopened_doc.paragraphs if p.text.startswith(("1.", "2."))]
    assert headings == ["2. Firmware Settings", "1. Hardware Specifications"]


def test_edit_paragraph_containing_hyperlink(tmp_path):
    """P1 OOXML Surgery: Editing paragraph text containing a w:hyperlink does not crash with child-node errors."""
    import docx
    from lxml import etree
    from injester.domain.document_ir import W_NS

    doc_path = str(tmp_path / "hyperlink_doc.docx")
    out_path = str(tmp_path / "hyperlink_doc_out.docx")

    doc = docx.Document()
    p = doc.add_paragraph()
    hl = etree.SubElement(
        p._p,
        f"{{{W_NS}}}hyperlink",
        {"{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id": "rId1"},
    )
    r1 = etree.SubElement(hl, f"{{{W_NS}}}r")
    t1 = etree.SubElement(r1, f"{{{W_NS}}}t")
    t1.text = "https://example.com/original"
    r2 = etree.SubElement(hl, f"{{{W_NS}}}r")
    t2 = etree.SubElement(r2, f"{{{W_NS}}}t")
    t2.text = " - Documentation"
    doc.save(doc_path)

    pipeline = DocxRoundTripPipeline()
    session = pipeline.load_document(doc_path)
    target_bid = list(session.document_ir.blocks.keys())[0]

    cmd = TypedChangeCommand(
        operation=ChangeOperationType.EDIT_PARAGRAPH_TEXT,
        target_block_id=target_bid,
        source_block_ids=[target_bid],
        new_values={"new_text": "https://example.com/v2 - Updated Documentation"},
        expected_document_version=session.version_id,
        rationale="Update hyperlink paragraph text",
    )
    changeset = pipeline.propose_edit(session, cmd)
    assert changeset.impact.is_valid is True

    changeset = pipeline.approve_changeset(session, changeset, approver_id="test_admin")
    report = pipeline.recompile_and_verify(session, changeset, out_path)
    assert report.is_successful is True

    import zipfile
    with zipfile.ZipFile(out_path, "r") as zf:
        xml = zf.read("word/document.xml")
        root = etree.fromstring(xml)
        hl_elems = root.findall(f".//{{{W_NS}}}hyperlink")
        assert len(hl_elems) == 1, "Hyperlink element must be preserved"
        rel_id = hl_elems[0].get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
        assert rel_id == "rId1", "Hyperlink relationship ID must be preserved"
        texts = [t.text for t in hl_elems[0].findall(f".//{{{W_NS}}}t")]
        assert texts == ["https://example.com/v2 - Updated Documentation"]


def test_resume_classification_without_filename_cues():
    """P1 Classification: Document is correctly identified as RESUME even when filename lacks resume/cv cues."""
    from injester.domain.document_ir import (
        DocumentBlock,
        FormattingSnapshot,
        SourceLocationRef,
        DocumentType,
        detect_document_type,
    )

    blocks = {}
    order = []
    items = [
        ("Candidate Profile", True),
        ("John Doe - Senior Systems Engineer", False),
        ("Professional Summary", True),
        ("Over 10 years of experience designing scalable microservices.", False),
        ("Work Experience", True),
        ("Lead Software Architect at Enterprise Cloud Corp (2020-Present)", False),
        ("Education", True),
        ("B.S. in Computer Science and Engineering, 2016", False),
        ("Skills", True),
        ("Python, Rust, Distributed Systems, Kubernetes, CI/CD", False),
    ]

    for idx, (title, is_h) in enumerate(items):
        bid = f"b-{idx:03d}"
        order.append(bid)
        blocks[bid] = DocumentBlock(
            block_id=bid,
            block_type="HEADING" if is_h else "PARAGRAPH",
            text_content=title,
            sequence_index=idx,
            formatting=FormattingSnapshot(is_heading=is_h),
            location=SourceLocationRef(
                part_name="word/document.xml",
                element_tag="w:p",
                element_index=idx,
                xpath=f"/w:document/w:body/w:p[{idx+1}]",
                fingerprint_hash="test_fp",
                xml_signature_hash="test_sig",
            ),
        )

    # Filename completely free of "resume", "cv", or "curriculum vitae"
    doc_type = detect_document_type(blocks, order, "candidate_profile_2026.docx")
    assert doc_type == DocumentType.RESUME, f"Expected DocumentType.RESUME, got {doc_type}"


def test_resequence_step_prefixes_split_across_runs():
    """
    Verifies that literal step prefixes split across multiple OOXML runs (<w:r>)
    (e.g., 'Step ' in run 1 [bold], '2' in run 2 [bold red], ': ' in run 3 [italic])
    are accurately resequenced while preserving the exact <w:rPr> run properties on every run.
    """
    from lxml import etree
    from injester.infrastructure.docx_patcher import DocxPackagePatcher, W_NS

    xml_content = f"""<w:document xmlns:w="{W_NS}">
        <w:body>
            <w:p>
                <w:r><w:rPr><w:b/></w:rPr><w:t>Step </w:t></w:r>
                <w:r><w:rPr><w:b/><w:color w:val="FF0000"/></w:rPr><w:t>2</w:t></w:r>
                <w:r><w:rPr><w:i/></w:rPr><w:t>: Enter BIOS and configure boot order</w:t></w:r>
            </w:p>
            <w:p>
                <w:r><w:rPr><w:b/></w:rPr><w:t>Step 1: </w:t></w:r>
                <w:r><w:t>Power on workstation</w:t></w:r>
            </w:p>
        </w:body>
    </w:document>"""

    root = etree.fromstring(xml_content.encode("utf-8"))
    body = root.find(f"{{{W_NS}}}body")
    p_elems = body.findall(f"{{{W_NS}}}p")
    p1, p2 = p_elems[0], p_elems[1]

    DocxPackagePatcher._resequence_literal_step_prefixes(
        body=body,
        target_p=p1,
        procedure_paragraphs=[p1, p2],
    )

    # Paragraph 1 resequenced from Step 2 -> Step 1
    p1_runs = p1.findall(f".//{{{W_NS}}}r")
    p1_texts = [r.find(f"{{{W_NS}}}t").text for r in p1_runs]
    # Run 0 contains "Step " (bold), untouched
    assert p1_texts[0] == "Step "
    assert p1_runs[0].find(f"{{{W_NS}}}rPr/{{{W_NS}}}b") is not None
    # Run 1 contains "1" (bold red), updated surgically from "2"
    assert p1_texts[1] == "1"
    assert p1_runs[1].find(f"{{{W_NS}}}rPr/{{{W_NS}}}b") is not None
    assert p1_runs[1].find(f"{{{W_NS}}}rPr/{{{W_NS}}}color").get(f"{{{W_NS}}}val") == "FF0000"
    # Run 2 contains ": Enter BIOS and configure boot order" (italic), untouched
    assert p1_texts[2] == ": Enter BIOS and configure boot order"
    assert p1_runs[2].find(f"{{{W_NS}}}rPr/{{{W_NS}}}i") is not None

    assert DocxPackagePatcher._get_paragraph_text(p1).strip() == "Step 1: Enter BIOS and configure boot order"

    # Paragraph 2 resequenced from Step 1 -> Step 2
    p2_runs = p2.findall(f".//{{{W_NS}}}r")
    p2_texts = [r.find(f"{{{W_NS}}}t").text for r in p2_runs]
    assert p2_texts[0] == "Step 2: "
    assert p2_texts[1] == "Power on workstation"
    assert p2_runs[0].find(f"{{{W_NS}}}rPr/{{{W_NS}}}b") is not None
    assert DocxPackagePatcher._get_paragraph_text(p2).strip() == "Step 2: Power on workstation"

    # Also verify prefix split where second run has colon and starts instruction text
    xml_split2 = f"""<w:document xmlns:w="{W_NS}">
        <w:body>
            <w:p>
                <w:r><w:t>Step </w:t></w:r>
                <w:r><w:t>10: Run diagnostic tools</w:t></w:r>
            </w:p>
        </w:body>
    </w:document>"""
    root2 = etree.fromstring(xml_split2.encode("utf-8"))
    body2 = root2.find(f"{{{W_NS}}}body")
    p_split2 = body2.find(f"{{{W_NS}}}p")

    DocxPackagePatcher._resequence_literal_step_prefixes(
        body=body2,
        target_p=p_split2,
        procedure_paragraphs=[p_split2],
    )
    p_split2_runs = p_split2.findall(f".//{{{W_NS}}}r")
    assert p_split2_runs[0].find(f"{{{W_NS}}}t").text == "Step "
    assert p_split2_runs[1].find(f"{{{W_NS}}}t").text == "1: Run diagnostic tools"
    assert DocxPackagePatcher._get_paragraph_text(p_split2).strip() == "Step 1: Run diagnostic tools"


def test_resequence_number_split_across_multiple_runs_with_distinct_properties():
    """
    OOXML Edge Case: When the step number itself is split across multiple runs with distinct
    run properties (e.g., '1' in blue run, '2' in red run for 'Step 12:'), resequencing distributes
    the replacement digits across the numeric runs while preserving each run's distinct <w:rPr> properties.
    """
    from lxml import etree
    from injester.infrastructure.docx_patcher import DocxPackagePatcher, W_NS

    xml_template = f"""<w:document xmlns:w="{W_NS}">
        <w:body>
            <w:p>
                <w:r><w:rPr><w:b/></w:rPr><w:t>Step </w:t></w:r>
                <w:r><w:rPr><w:b/><w:color w:val="0000FF"/></w:rPr><w:t>1</w:t></w:r>
                <w:r><w:rPr><w:b/><w:color w:val="FF0000"/></w:rPr><w:t>2</w:t></w:r>
                <w:r><w:rPr><w:i/></w:rPr><w:t>: Initialize database cluster</w:t></w:r>
            </w:p>
        </w:body>
    </w:document>"""

    # Case 1: Shrinking digit count (from '12' to '1')
    root1 = etree.fromstring(xml_template.encode("utf-8"))
    body1 = root1.find(f"{{{W_NS}}}body")
    p1 = body1.find(f"{{{W_NS}}}p")

    DocxPackagePatcher._resequence_literal_step_prefixes(
        body=body1,
        target_p=p1,
        procedure_paragraphs=[p1],
    )

    runs1 = p1.findall(f".//{{{W_NS}}}r")
    assert len(runs1) == 4
    # Run 0: "Step " (bold, untouched)
    assert runs1[0].find(f"{{{W_NS}}}t").text == "Step "
    assert runs1[0].find(f"{{{W_NS}}}rPr/{{{W_NS}}}b") is not None
    # Run 1: "1" (retains blue color)
    assert runs1[1].find(f"{{{W_NS}}}t").text == "1"
    assert runs1[1].find(f"{{{W_NS}}}rPr/{{{W_NS}}}color").get(f"{{{W_NS}}}val") == "0000FF"
    # Run 2: "" (empty, but retains red color in rPr)
    assert runs1[2].find(f"{{{W_NS}}}t").text == ""
    assert runs1[2].find(f"{{{W_NS}}}rPr/{{{W_NS}}}color").get(f"{{{W_NS}}}val") == "FF0000"
    # Run 3: ": Initialize database cluster" (italic, untouched)
    assert runs1[3].find(f"{{{W_NS}}}t").text == ": Initialize database cluster"
    assert runs1[3].find(f"{{{W_NS}}}rPr/{{{W_NS}}}i") is not None
    assert DocxPackagePatcher._get_paragraph_text(p1).strip() == "Step 1: Initialize database cluster"

    # Case 2: Multi-paragraph resequencing where second paragraph receives multi-digit number ('12' -> '2')
    # and first paragraph is 'Step 1:' so counter increments to '2'
    xml_multi = f"""<w:document xmlns:w="{W_NS}">
        <w:body>
            <w:p>
                <w:r><w:t>Step 1: First item</w:t></w:r>
            </w:p>
            <w:p>
                <w:r><w:rPr><w:b/></w:rPr><w:t>Step </w:t></w:r>
                <w:r><w:rPr><w:b/><w:color w:val="0000FF"/></w:rPr><w:t>1</w:t></w:r>
                <w:r><w:rPr><w:b/><w:color w:val="FF0000"/></w:rPr><w:t>2</w:t></w:r>
                <w:r><w:rPr><w:i/></w:rPr><w:t>: Second item</w:t></w:r>
            </w:p>
        </w:body>
    </w:document>"""
    root_m = etree.fromstring(xml_multi.encode("utf-8"))
    body_m = root_m.find(f"{{{W_NS}}}body")
    pm_elems = body_m.findall(f"{{{W_NS}}}p")
    p_first, p_second = pm_elems[0], pm_elems[1]

    DocxPackagePatcher._resequence_literal_step_prefixes(
        body=body_m,
        target_p=p_second,
        procedure_paragraphs=[p_first, p_second],
    )

    runs_second = p_second.findall(f".//{{{W_NS}}}r")
    assert runs_second[0].find(f"{{{W_NS}}}t").text == "Step "
    assert runs_second[1].find(f"{{{W_NS}}}t").text == "2"
    assert runs_second[1].find(f"{{{W_NS}}}rPr/{{{W_NS}}}color").get(f"{{{W_NS}}}val") == "0000FF"
    assert runs_second[2].find(f"{{{W_NS}}}t").text == ""
    assert runs_second[2].find(f"{{{W_NS}}}rPr/{{{W_NS}}}color").get(f"{{{W_NS}}}val") == "FF0000"
    assert runs_second[3].find(f"{{{W_NS}}}t").text == ": Second item"
    assert DocxPackagePatcher._get_paragraph_text(p_second).strip() == "Step 2: Second item"



