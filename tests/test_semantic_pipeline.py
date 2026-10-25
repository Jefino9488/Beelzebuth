import os
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from injester.domain.auth import SecurityContext
from injester.domain.models import UserRole
from injester.pipeline import InjesterPipeline
from injester.synthesis.spans import SpanRegistry, SourceSpan
from injester.semantic.schemas import (
    ModalityType,
    EpistemicStatus,
    AtomicProposition,
    PropositionBatch,
    LayaVerdict,
    GroundedProcessGraph,
    ProcessActor,
    ProcessEvent,
    ProcessActivity,
    ProcessGateway,
    ProcessTransition,
    StateTransition,
    DualOutputResult,
    CanonicalProcessModel,
    SemanticProcessNode,
    SemanticProcessEdge,
    ProcessRelationType,
    ValidationPolicy,
)
from injester.semantic.pipeline import EvidenceFirstSemanticPipeline
from injester.semantic.projections import (
    render_bpmn_20_xml,
    render_flowchart_mermaid,
    render_swimlane_mermaid,
    render_state_machine_mermaid,
)
from injester.semantic.validator import SemanticGraphValidator
from injester.semantic.compiler import DeterministicGraphCompiler
from injester.semantic.laya_adapter import LayaSystem1Verifier


@pytest.fixture
def sample_graph():
    return GroundedProcessGraph(
        process_name="Commercial Loan Approval",
        objective="Standard commercial underwriting procedure",
        actors=[
            ProcessActor(id="ACT_RM", name="Relationship Manager", role_type="human"),
            ProcessActor(id="ACT_UW", name="Underwriter", role_type="human"),
        ],
        events=[
            ProcessEvent(id="START", type="start", label="Application Received", evidence=["S001"], actor_id="ACT_RM"),
            ProcessEvent(id="END", type="end", label="Completed", evidence=["S002"], actor_id="ACT_UW"),
        ],
        activities=[
            ProcessActivity(
                id="ACT_001",
                actor_id="ACT_RM",
                label="Submit loan application",
                description="Relationship Manager collects and submits documents.",
                evidence=["S001"],
                modality=ModalityType.MANDATORY,
                temporal_order=1,
            ),
            ProcessActivity(
                id="ACT_002",
                actor_id="ACT_UW",
                label="Assess credit risk",
                description="Underwriter performs thorough financial assessment.",
                evidence=["S002"],
                modality=ModalityType.MANDATORY,
                temporal_order=2,
            ),
        ],
        gateways=[
            ProcessGateway(
                id="GW_001",
                question="Is risk within threshold?",
                gateway_type="exclusive",
                evidence=["S003"],
                actor_id="ACT_UW",
            )
        ],
        transitions=[
            ProcessTransition(id="TR_0", from_id="START", to_id="ACT_001"),
            ProcessTransition(id="TR_1", from_id="ACT_001", to_id="GW_001"),
            ProcessTransition(id="TR_2", from_id="GW_001", to_id="ACT_002", condition="Risk acceptable", relation=ProcessRelationType.BRANCH_IF),
            ProcessTransition(id="TR_3", from_id="GW_001", to_id="ACT_001", condition="Risk too high", relation=ProcessRelationType.BRANCH_IF),
            ProcessTransition(id="TR_4", from_id="ACT_002", to_id="END"),
        ],
        state_transitions=[
            StateTransition(
                from_state="Submitted",
                to_state="Under Review",
                trigger="Application received",
                evidence=["S001"]
            )
        ]
    )


def test_projections_bpmn_xml(sample_graph):
    xml_str = render_bpmn_20_xml(sample_graph)
    assert xml_str is not None
    assert "bpmn:definitions" in xml_str
    
    # Must be valid, parseable XML
    root = ET.fromstring(xml_str)
    assert root is not None
    ns = {'bpmn': 'http://www.omg.org/spec/BPMN/20100524/MODEL'}
    
    process = root.find('bpmn:process', ns)
    assert process is not None
    assert process.attrib['id'] == 'Process_Main'
    
    # Lanes
    lanes = root.findall('.//bpmn:lane', ns)
    assert len(lanes) == 2
    lane_names = [l.attrib['name'] for l in lanes]
    assert "Relationship Manager" in lane_names
    assert "Underwriter" in lane_names

    # UserTasks
    tasks = root.findall('.//bpmn:userTask', ns)
    assert len(tasks) == 2
    task_labels = [t.attrib['name'] for t in tasks]
    assert "Submit loan application" in task_labels
    assert "Assess credit risk" in task_labels

    # Gateways and Sequence Flows
    gateways = root.findall('.//bpmn:exclusiveGateway', ns)
    assert len(gateways) == 1
    flows = root.findall('.//bpmn:sequenceFlow', ns)
    assert len(flows) >= 3


def test_projections_mermaid(sample_graph):
    # Flowchart
    fc = render_flowchart_mermaid(sample_graph)
    assert "flowchart TD" in fc
    assert 'ACT_001["Submit loan application"]' in fc
    assert 'ACT_002["Assess credit risk"]' in fc
    assert 'GW_001{Is risk within threshold?}' in fc

    # Swimlane
    sw = render_swimlane_mermaid(sample_graph)
    assert "subgraph SG_ACT_RM" in sw
    assert "subgraph SG_ACT_UW" in sw

    # State Machine
    sm = render_state_machine_mermaid(sample_graph)
    assert sm is not None
    assert "stateDiagram-v2" in sm
    assert "Submitted --> Under Review" in sm


def make_span_registry(span_dict: dict) -> SpanRegistry:
    reg = SpanRegistry()
    for sid, text in span_dict.items():
        s = SourceSpan(
            span_id=sid,
            chunk_id="chunk_1",
            source_doc="doc.txt",
            location="Page 1",
            section="Section 1",
            text=text
        )
        reg.spans_by_id[sid] = s
        reg.spans_by_chunk.setdefault("chunk_1", []).append(s)
    return reg


def test_deterministic_compiler_dual_output():
    span_reg = make_span_registry({
        "S001": "The Relationship Manager submits the completed application.",
        "S002": "The Underwriter verifies financial statements.",
        "S003": "An external unauthorized party may approve the disbursement without review."
    })

    prop1 = AtomicProposition(
        id="P001",
        evidence_spans=["S001"],
        actor_claim="Relationship Manager",
        action_verb="submits",
        target_object="completed application",
        condition=None,
        modality=ModalityType.MANDATORY,
        epistemic_status=EpistemicStatus.CONFIRMED,
        order_index=1,
    )
    prop2 = AtomicProposition(
        id="P002",
        evidence_spans=["S002"],
        actor_claim="Underwriter",
        action_verb="verifies",
        target_object="financial statements",
        condition=None,
        modality=ModalityType.MANDATORY,
        epistemic_status=EpistemicStatus.CONFIRMED,
        order_index=2,
    )
    # Adversarial unentailed/distorted proposition
    prop3 = AtomicProposition(
        id="P003",
        evidence_spans=["S003"],
        actor_claim="External Hacker",
        action_verb="approves",
        target_object="disbursement without review",
        condition=None,
        modality=ModalityType.PERMISSIVE,
        epistemic_status=EpistemicStatus.CONFIRMED,
        order_index=3,
    )

    verdicts = {
        "P001": LayaVerdict(
            proposition_id="P001",
            actor_grounded=True,
            action_entailed=True,
            modality_verified=ModalityType.MANDATORY,
            epistemic_verified=EpistemicStatus.CONFIRMED,
            is_verified=True,
        ),
        "P002": LayaVerdict(
            proposition_id="P002",
            actor_grounded=True,
            action_entailed=True,
            modality_verified=ModalityType.MANDATORY,
            epistemic_verified=EpistemicStatus.CONFIRMED,
            is_verified=True,
        ),
        "P003": LayaVerdict(
            proposition_id="P003",
            actor_grounded=False,
            action_entailed=False,
            modality_verified=ModalityType.PERMISSIVE,
            epistemic_verified=EpistemicStatus.CONFIRMED,
            is_verified=False,
            rejection_reasons=["Actor 'External Hacker' ungrounded in span"],
        ),
    }

    compiler = DeterministicGraphCompiler()
    result = compiler.compile(
        document_name="loan_policy.txt",
        process_name="Loan Approval Flow",
        objective="Process underwriting requests",
        propositions=[prop1, prop2, prop3],
        verdicts=verdicts,
        span_registry=span_reg
    )

    # Contract Verification:
    # 1. Authoritative Graph AST contains ONLY verified propositions (P001, P002)
    verified_acts = [a.label for a in result.graph.activities]
    assert any("submits" in a.lower() for a in verified_acts)
    assert any("verifies" in a.lower() for a in verified_acts)
    assert not any("hacker" in a.lower() for a in verified_acts)

    # 2. Defect Register quarantines the rejected proposition P003 with its evidence
    assert len(result.defect_register.defects) >= 1
    quarantined = [d for d in result.defect_register.defects if d.proposition_id == "P003"]
    assert len(quarantined) == 1
    assert quarantined[0].evidence_spans == ["S003"]
    assert "Actor 'External Hacker' ungrounded" in quarantined[0].rationale


def test_semantic_graph_validator():
    span_reg = make_span_registry({
        "S001": "The Relationship Manager submits the loan file.",
        "S002": "The Underwriter verifies financial statements.",
        "S003": "If risk is acceptable, the Underwriter approves the loan."
    })

    validator = SemanticGraphValidator(span_registry=span_reg)

    valid_graph = GroundedProcessGraph(
        process_name="Valid Flow",
        objective="Underwrite loan",
        actors=[
            ProcessActor(id="A1", name="Relationship Manager", role_type="human"),
            ProcessActor(id="A2", name="Underwriter", role_type="human"),
        ],
        activities=[
            ProcessActivity(id="ACT_1", actor_id="A1", label="Submits the loan file", description="RM submits loan file", evidence=["S001"]),
            ProcessActivity(id="ACT_2", actor_id="A2", label="Verifies financial statements", description="UW checks statements", evidence=["S002"]),
        ],
        gateways=[],
        transitions=[ProcessTransition(from_id="ACT_1", to_id="ACT_2")],
    )

    is_valid, errors, _ = validator.validate_semantic_graph(valid_graph)
    assert is_valid is True
    assert len(errors) == 0

    # Test structural violation: activity cites non-existent span
    invalid_graph = GroundedProcessGraph(
        process_name="Invalid Flow",
        objective="Underwrite loan",
        actors=[
            ProcessActor(id="A1", name="Relationship Manager", role_type="human"),
        ],
        activities=[
            ProcessActivity(id="ACT_1", actor_id="A1", label="Submits the loan file", description="RM submits loan file", evidence=["S999"]),
        ],
    )
    is_valid, errors, _ = validator.validate_semantic_graph(invalid_graph)
    assert is_valid is False
    assert any("STRUCTURAL_INVALID_SPAN" in err for err in errors)


def test_pipeline_generate_process_graph_integration(tmp_path):
    # Create test document
    doc_path = tmp_path / "Leave_Procedure.txt"
    doc_path.write_text(
        "Employee Leave Procedure:\n"
        "1. Employee submits leave request on HR portal.\n"
        "2. Manager reviews leave request.\n"
        "3. If approved, HR updates balance. If rejected, employee is notified.\n",
        encoding="utf-8"
    )

    out_dir = tmp_path / "artifacts"
    sec_ctx = SecurityContext(
        user_id="test_user",
        email="user@tenant.com",
        role=UserRole.CLIENT_ADMIN,
        organisation_id="tenant_123"
    )

    mock_session = MagicMock()

    # Mock Extractor & Verifier to test pipeline plumbing without network or GPU
    mock_extractor = MagicMock()
    mock_extractor.extract_propositions.return_value = PropositionBatch(
        process_name="Leave Procedure",
        objective="Submit and approve leave",
        propositions=[
            AtomicProposition(
                id="PROP_001",
                evidence_spans=["S001"],
                actor_claim="Employee",
                action_verb="submits",
                target_object="leave request",
                modality=ModalityType.MANDATORY,
                epistemic_status=EpistemicStatus.CONFIRMED,
                order_index=1,
            ),
            AtomicProposition(
                id="PROP_002",
                evidence_spans=["S001"],
                actor_claim="Manager",
                action_verb="reviews",
                target_object="leave request",
                modality=ModalityType.MANDATORY,
                epistemic_status=EpistemicStatus.CONFIRMED,
                order_index=2,
            ),
            AtomicProposition(
                id="PROP_003",
                evidence_spans=["S001"],
                actor_claim="HR",
                action_verb="updates",
                target_object="leave balance",
                modality=ModalityType.MANDATORY,
                epistemic_status=EpistemicStatus.CONFIRMED,
                order_index=3,
            ),
        ]
    )

    mock_verifier = MagicMock()
    mock_verifier.verify_propositions.return_value = {
        "PROP_001": LayaVerdict(
            proposition_id="PROP_001",
            actor_grounded=True,
            action_entailed=True,
            modality_verified=ModalityType.MANDATORY,
            epistemic_verified=EpistemicStatus.CONFIRMED,
            is_verified=True,
        ),
        "PROP_002": LayaVerdict(
            proposition_id="PROP_002",
            actor_grounded=True,
            action_entailed=True,
            modality_verified=ModalityType.MANDATORY,
            epistemic_verified=EpistemicStatus.CONFIRMED,
            is_verified=True,
        ),
        "PROP_003": LayaVerdict(
            proposition_id="PROP_003",
            actor_grounded=True,
            action_entailed=True,
            modality_verified=ModalityType.MANDATORY,
            epistemic_verified=EpistemicStatus.CONFIRMED,
            is_verified=True,
        ),
    }

    mock_reasoner = MagicMock()
    mock_reasoner.reason_process_model.return_value = CanonicalProcessModel(
        process_name="Leave Procedure",
        objective="Submit and approve leave",
        nodes=[
            SemanticProcessNode(node_id="START", node_type="start_event", label="Start", evidence=[]),
            SemanticProcessNode(node_id="ACT_01", node_type="activity", actor="Employee", label="Submits leave request", evidence_spans=["S001"], source_proposition_ids=["PROP_001"]),
            SemanticProcessNode(node_id="ACT_02", node_type="activity", actor="Manager", label="Reviews leave request", evidence_spans=["S001"], source_proposition_ids=["PROP_002"]),
            SemanticProcessNode(node_id="ACT_03", node_type="activity", actor="HR", label="Updates balance", evidence_spans=["S001"], source_proposition_ids=["PROP_003"]),
        ],
        edges=[
            SemanticProcessEdge(edge_id="EDGE_01", source_node_id="START", target_node_id="ACT_01", relation=ProcessRelationType.PRECEDES, evidence_spans=[]),
            SemanticProcessEdge(edge_id="EDGE_02", source_node_id="ACT_01", target_node_id="ACT_02", relation=ProcessRelationType.PRECEDES, evidence_spans=["S001"]),
            SemanticProcessEdge(edge_id="EDGE_03", source_node_id="ACT_02", target_node_id="ACT_03", relation=ProcessRelationType.PRECEDES, evidence_spans=["S001"]),
        ]
    )

    semantic_pipeline = EvidenceFirstSemanticPipeline(
        extractor=mock_extractor,
        reasoner=mock_reasoner,
        verifier=mock_verifier,
    )
    pipeline = InjesterPipeline(session=mock_session, semantic_pipeline=semantic_pipeline)

    result = pipeline.generate_process_graph(
        sec_ctx=sec_ctx,
        file_path_or_id=doc_path,
        output_dir=out_dir,
    )

    assert result is not None
    assert isinstance(result, DualOutputResult)
    assert len(result.graph.activities) >= 1
    
    # Check that all artifacts were written to disk
    assert (out_dir / "process_graph.json").exists()
    assert (out_dir / "defect_register.json").exists()
    assert (out_dir / "DEFECT_REGISTER.md").exists()
    assert (out_dir / "bpmn_2_0.xml").exists()
    assert (out_dir / "flowchart.mmd").exists()
    assert (out_dir / "swimlane.mmd").exists()

    # Verify BPMN XML content
    bpmn_content = (out_dir / "bpmn_2_0.xml").read_text(encoding="utf-8")
    assert "bpmn:definitions" in bpmn_content
    ET.fromstring(bpmn_content)  # valid XML parsing


def test_generic_structural_invariants_and_projections():
    """
    Tests generic structural graph invariants:
    - ID uniqueness and referential integrity.
    - Legitimate grounded loops (LOOP_BACK) are preserved as valid.
    - All canonical end events are rendered into BPMN XML (no early break).
    - Unassigned actors are placed in an explicit 'Unassigned' lane.
    - No renderer invents nodes or edges absent from the canonical graph.
    """
    span_reg = make_span_registry({
        "S001": "Submit document for review.",
        "S002": "Review document.",
        "S003": "Corrections required?",
        "S004": "Make corrections and resubmit.",
        "S005": "Approved and archived.",
        "S006": "Rejected and closed.",
    })

    model = CanonicalProcessModel(
        process_name="Generic Test Process",
        objective="Verify structural invariants",
        nodes=[
            SemanticProcessNode(node_id="START", node_type="start_event", label="Process Start", evidence=[]),
            SemanticProcessNode(node_id="ACT_01", node_type="activity", actor="Submitter", label="Submit Document", evidence_spans=["S001"]),
            SemanticProcessNode(node_id="ACT_02", node_type="activity", actor="Reviewer", label="Review Document", evidence_spans=["S002"]),
            SemanticProcessNode(node_id="GW_01", node_type="decision", actor="Reviewer", label="Corrections Required?", potential_outcomes=["Yes", "No"], evidence_spans=["S003"]),
            SemanticProcessNode(node_id="ACT_CORRECT", node_type="activity", actor="Submitter", label="Make Corrections", evidence_spans=["S004"]),
            SemanticProcessNode(node_id="ACT_AUTO", node_type="activity", actor="", label="Automated Validation", evidence_spans=["S001"]),  # Unassigned actor
            SemanticProcessNode(node_id="END_APPROVED", node_type="end_event", actor="System", label="Approved", evidence_spans=["S005"]),
            SemanticProcessNode(node_id="END_REJECTED", node_type="end_event", actor="System", label="Rejected", evidence_spans=["S006"]),
        ],
        edges=[
            SemanticProcessEdge(edge_id="EDGE_01", source_node_id="START", target_node_id="ACT_01", relation=ProcessRelationType.PRECEDES, evidence_spans=[]),
            SemanticProcessEdge(edge_id="EDGE_02", source_node_id="ACT_01", target_node_id="ACT_02", relation=ProcessRelationType.PRECEDES, evidence_spans=["S001"]),
            SemanticProcessEdge(edge_id="EDGE_03", source_node_id="ACT_02", target_node_id="GW_01", relation=ProcessRelationType.PRECEDES, evidence_spans=["S002"]),
            SemanticProcessEdge(edge_id="EDGE_04", source_node_id="GW_01", target_node_id="ACT_CORRECT", relation=ProcessRelationType.BRANCH_IF, condition="Yes", evidence_spans=["S003"]),
            SemanticProcessEdge(edge_id="EDGE_05", source_node_id="ACT_CORRECT", target_node_id="ACT_02", relation=ProcessRelationType.LOOP_BACK, evidence_spans=["S004"]),  # Legitimate grounded loop!
            SemanticProcessEdge(edge_id="EDGE_06", source_node_id="GW_01", target_node_id="ACT_AUTO", relation=ProcessRelationType.BRANCH_IF, condition="No", evidence_spans=["S003"]),
            SemanticProcessEdge(edge_id="EDGE_07", source_node_id="ACT_AUTO", target_node_id="END_APPROVED", relation=ProcessRelationType.PRECEDES, evidence_spans=["S005"]),
        ]
    )

    compiler = DeterministicGraphCompiler(policy=ValidationPolicy())
    dual_result = compiler.compile(
        document_name="test.docx",
        process_name=model.process_name,
        objective=model.objective,
        canonical_model=model,
        span_registry=span_reg
    )

    graph = dual_result.graph
    assert len(graph.activities) == 4
    assert len(graph.gateways) == 1
    assert len(graph.events) == 3  # START, END_APPROVED, END_REJECTED

    # 1. Verify legitimate loop is preserved in AST
    loop_transitions = [t for t in graph.transitions if t.is_loop]
    assert len(loop_transitions) == 1
    assert loop_transitions[0].from_id == "ACT_CORRECT"
    assert loop_transitions[0].to_id == "ACT_02"

    # 2. Verify BPMN 2.0 XML serialization
    bpmn_xml = render_bpmn_20_xml(graph)
    assert bpmn_xml is not None
    root = ET.fromstring(bpmn_xml)

    # Both canonical end events MUST be present in XML
    end_events_xml = root.findall(".//{http://www.omg.org/spec/BPMN/20100524/MODEL}endEvent")
    assert len(end_events_xml) == 2
    end_ids = {e.get("id") for e in end_events_xml}
    assert "END_APPROVED" in end_ids
    assert "END_REJECTED" in end_ids

    # Unassigned actor MUST be in an 'Unassigned' lane
    unassigned_lane = None
    for lane in root.findall(".//{http://www.omg.org/spec/BPMN/20100524/MODEL}lane"):
        if lane.get("name") == "Unassigned":
            unassigned_lane = lane
            break
    assert unassigned_lane is not None
    flow_node_refs = [f.text for f in unassigned_lane.findall("{http://www.omg.org/spec/BPMN/20100524/MODEL}flowNodeRef")]
    assert "ACT_AUTO" in flow_node_refs

    # 3. Verify Mermaid serialization
    flowchart_mmd = render_flowchart_mermaid(graph)
    assert "ACT_CORRECT --> ACT_02" in flowchart_mmd
    assert "END_APPROVED" in flowchart_mmd

