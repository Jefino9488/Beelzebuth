"""
Unit tests for OpenJev fast-path routing and Laya semantic evaluation engines.
"""

import pytest
from injester.domain.document_ir import (
    DocumentIR, DocumentBlock, FormattingSnapshot, DocumentType, SourceLocationRef
)
from injester.semantic.openjev_router import OpenJevIntentRouter
from injester.semantic.laya_evaluator import LayaSemanticEvaluator
from injester.semantic.change_engine import ChangeOperationType


@pytest.fixture
def sample_document_ir():
    loc = SourceLocationRef(xpath="/w:document/w:body/w:p[1]", element_index=0, fingerprint_hash="fp0", xml_signature_hash="sig0")
    blocks = {
        "b_head1": DocumentBlock(
            block_id="b_head1",
            block_type="HEADING",
            text_content="Work Experience",
            sequence_index=0,
            location=loc,
            formatting=FormattingSnapshot(is_heading=True, heading_level=1),
        ),
        "b_p1": DocumentBlock(
            block_id="b_p1",
            block_type="PARAGRAPH",
            text_content="Software Engineer at Acme Corp.",
            sequence_index=1,
            location=SourceLocationRef(xpath="/w:document/w:body/w:p[2]", element_index=1, fingerprint_hash="fp1", xml_signature_hash="sig1"),
            formatting=FormattingSnapshot(),
            parent_block_id="b_head1",
        ),
        "b_head2": DocumentBlock(
            block_id="b_head2",
            block_type="HEADING",
            text_content="Education",
            sequence_index=2,
            location=SourceLocationRef(xpath="/w:document/w:body/w:p[3]", element_index=2, fingerprint_hash="fp2", xml_signature_hash="sig2"),
            formatting=FormattingSnapshot(is_heading=True, heading_level=1),
        ),
        "b_p2": DocumentBlock(
            block_id="b_p2",
            block_type="PARAGRAPH",
            text_content="B.S. in Computer Science, Tech University.",
            sequence_index=3,
            location=SourceLocationRef(xpath="/w:document/w:body/w:p[4]", element_index=3, fingerprint_hash="fp3", xml_signature_hash="sig3"),
            formatting=FormattingSnapshot(),
            parent_block_id="b_head2",
        ),
    }
    return DocumentIR(
        document_id="doc_test_123",
        filename="resume.docx",
        file_hash="hash123456",
        document_type=DocumentType.RESUME,
        blocks=blocks,
        structural_order=["b_head1", "b_p1", "b_head2", "b_p2"],
    )


def test_openjev_route_step_reorder():
    router = OpenJevIntentRouter()
    step_order = ["step-01", "step-02", "step-03"]
    step_to_block = {"step-01": "b1", "step-02": "b2", "step-03": "b3"}

    decision = router.route_request(
        request_text="Move step 2 before step 1",
        session_doc_id="doc_123",
        session_version="v_abc123",
        document_ir=DocumentIR(document_id="doc_123", filename="test.docx", file_hash="hash123", document_type=DocumentType.MANUAL),
        step_order=step_order,
        step_to_block_map=step_to_block,
    )

    assert decision.is_supported is True
    assert decision.operation == ChangeOperationType.MOVE_PROCEDURE_STEP
    assert decision.command.target_step_id == "step-02"
    assert decision.command.before_step_id == "step-01"
    assert decision.requires_semantic_evaluation is False


def test_openjev_route_section_reorder(sample_document_ir):
    router = OpenJevIntentRouter()

    decision = router.route_request(
        request_text="Reorder section Education before section Work Experience",
        session_doc_id=sample_document_ir.document_id,
        session_version="v1.0",
        document_ir=sample_document_ir,
    )

    assert decision.is_supported is True
    assert decision.operation == ChangeOperationType.REORDER_SECTION
    assert decision.command.target_block_id == "b_head2"
    assert decision.command.before_block_id == "b_head1"
    assert decision.requires_semantic_evaluation is False


def test_openjev_route_instruction_update():
    router = OpenJevIntentRouter()
    step_order = ["step-01", "step-02"]
    step_to_block = {"step-01": "b1", "step-02": "b2"}

    decision = router.route_request(
        request_text="Update step 1 instruction to 'Ensure power cable is securely attached'",
        session_doc_id="doc_123",
        session_version="v1.0",
        document_ir=DocumentIR(document_id="doc_123", filename="test.docx", file_hash="hash123", document_type=DocumentType.MANUAL),
        step_order=step_order,
        step_to_block_map=step_to_block,
    )

    assert decision.is_supported is True
    assert decision.operation == ChangeOperationType.UPDATE_STEP_INSTRUCTION
    assert decision.command.target_step_id == "step-01"
    assert decision.command.new_values["instruction"] == "Ensure power cable is securely attached"
    # Content modifications must require Laya semantic evaluation
    assert decision.requires_semantic_evaluation is True


def test_openjev_route_unsupported_request(sample_document_ir):
    router = OpenJevIntentRouter()

    decision = router.route_request(
        request_text="Synthesize an executive summary explaining quantum computing",
        session_doc_id=sample_document_ir.document_id,
        session_version="v1.0",
        document_ir=sample_document_ir,
    )

    assert decision.is_supported is False
    assert decision.command is None
    assert "cannot be safely resolved on OpenJev fast-path" in decision.rejection_reason


def test_laya_evaluator_meaning_preserved():
    evaluator = LayaSemanticEvaluator(entailment_threshold=0.80)
    orig = "Connect the DisplayPort cable from monitor 1 to port DP-1 on the workstation."
    prop = "Connect DisplayPort cable from monitor 1 to port DP-1 on the workstation."

    verdict = evaluator.evaluate_edit(orig, prop)
    assert verdict.is_supported is True
    assert verdict.drift_detected is False
    assert verdict.requires_human_review is False
    assert verdict.entailment_score >= 0.80


def test_laya_evaluator_negation_inversion():
    evaluator = LayaSemanticEvaluator()
    orig = "Do not connect the auxiliary power supply before verifying 240V input."
    prop = "Connect the auxiliary power supply before verifying 240V input."

    verdict = evaluator.evaluate_edit(orig, prop)
    assert verdict.is_supported is False
    assert verdict.drift_detected is True
    assert verdict.requires_human_review is True
    assert "negation inversion" in verdict.rationale.lower()


def test_laya_evaluator_dropped_technical_specifier():
    evaluator = LayaSemanticEvaluator()
    orig = "Configure RAID controller firmware to version 3200 with 64GB cache."
    prop = "Configure RAID controller firmware to current version with cache."

    verdict = evaluator.evaluate_edit(orig, prop)
    assert verdict.drift_detected is True
    assert "3200" in verdict.dropped_constraints or "64GB" in verdict.dropped_constraints
    assert verdict.requires_human_review is True


def test_laya_evaluator_empty_text():
    evaluator = LayaSemanticEvaluator()
    verdict = evaluator.evaluate_edit("Valid text", "")
    assert verdict.is_supported is False
    assert verdict.drift_detected is True
    assert verdict.requires_human_review is True
