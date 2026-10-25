"""
Topology Fidelity Test Suite.
Verifies the authoritative topology architecture:
1. Edges are the sole source of truth for topology (no GatewayBranch).
2. Preserves parallel edges with distinct conditions to the same target (zero deduplication).
3. No synthetic start/terminal endpoints synthesized by serializers.
4. Clean branch divergence and convergence (merge) preservation.
5. Loopback edges preserved with loop flags.
6. Exception and timeout paths preserved with exception semantics and dashed rendering.
"""

import pytest
from injester.semantic.schemas import (
    CanonicalProcessModel,
    SemanticProcessNode,
    SemanticProcessEdge,
    ProcessRelationType,
    GroundingVerdict,
    LayaVerdict,
    ProcessEvent,
    ProcessActivity,
    ProcessGateway,
    ProcessTransition,
    GroundedProcessGraph,
)
from injester.semantic.normalizer import ProcessNormalizer
from injester.semantic.compiler import DeterministicGraphCompiler
from injester.semantic.projections import (
    render_flowchart_mermaid,
    render_bpmn_20_xml,
    render_swimlane_mermaid,
)
from injester.synthesis.spans import SpanRegistry, SourceSpan


def _make_registry(span_id="S01", text="Process documentation span"):
    registry = SpanRegistry()
    registry.spans_by_id[span_id] = SourceSpan(
        span_id=span_id,
        chunk_id="c1",
        source_doc="document.docx",
        text=text,
    )
    return registry


def test_topology_fidelity_same_target_different_branches():
    """
    Test 1: Multiple edges from the same gateway to the same target node with different conditions.
    Verifies that compiler and serializers preserve both edges without deduplication or collapsing.
    """
    registry = _make_registry()
    canonical = CanonicalProcessModel(
        process_name="Branch Test",
        objective="Verify non-collapsing branches",
        schema_version="1.0",
        nodes=[
            SemanticProcessNode(node_id="START", node_type="start_event", label="Start", evidence_spans=["S01"]),
            SemanticProcessNode(node_id="GW_01", node_type="decision", label="Is VIP?", evidence_spans=["S01"]),
            SemanticProcessNode(node_id="ACT_NOTIFY", node_type="activity", label="Send Notification", actor="System", evidence_spans=["S01"]),
            SemanticProcessNode(node_id="END", node_type="end_event", label="End", evidence_spans=["S01"]),
        ],
        edges=[
            SemanticProcessEdge(edge_id="E1", source_node_id="START", target_node_id="GW_01", evidence_spans=["S01"]),
            SemanticProcessEdge(
                edge_id="E2",
                source_node_id="GW_01",
                target_node_id="ACT_NOTIFY",
                relation=ProcessRelationType.BRANCH_IF,
                condition="VIP == Yes",
                evidence_spans=["S01"],
            ),
            SemanticProcessEdge(
                edge_id="E3",
                source_node_id="GW_01",
                target_node_id="ACT_NOTIFY",
                relation=ProcessRelationType.DEFAULT_BRANCH,
                condition="VIP == No",
                evidence_spans=["S01"],
            ),
            SemanticProcessEdge(edge_id="E4", source_node_id="ACT_NOTIFY", target_node_id="END", evidence_spans=["S01"]),
        ],
    )

    # 1. Normalization accepts distinct edges
    normalizer = ProcessNormalizer()
    normalized = normalizer.normalize(canonical)
    assert len(normalized.edges) == 4

    # 2. Compilation preserves both transitions
    compiler = DeterministicGraphCompiler()
    res = compiler.compile(
        document_name="document.docx",
        canonical_model=normalized,
        verdicts={},
        span_registry=registry,
    )

    gw_transitions = [t for t in res.graph.transitions if t.from_id == "GW_01" and t.to_id == "ACT_NOTIFY"]
    assert len(gw_transitions) == 2, f"Expected 2 transitions from GW_01 to ACT_NOTIFY, got {len(gw_transitions)}"
    conditions = {t.condition for t in gw_transitions}
    assert conditions == {"VIP == Yes", "VIP == No"}

    # 3. Mermaid serializer renders both distinct flows
    mmd = render_flowchart_mermaid(res.graph)
    assert "GW_01 -->|VIP == Yes| ACT_NOTIFY" in mmd
    assert "GW_01 -->|VIP == No| ACT_NOTIFY" in mmd


def test_topology_fidelity_no_synthetic_endpoints():
    """
    Test 2: Serializers must fail closed and NOT synthesize START or END events if absent in the graph.
    """
    # Create graph with only activities, no start or end event
    graph_no_events = GroundedProcessGraph(
        process_name="No Events Process",
        objective="Verify no synthetic endpoints",
        events=[],
        activities=[
            ProcessActivity(id="ACT_01", actor_id="ACTOR_01", label="Step 1", description="", evidence=[]),
            ProcessActivity(id="ACT_02", actor_id="ACTOR_01", label="Step 2", description="", evidence=[]),
        ],
        gateways=[],
        transitions=[
            ProcessTransition(
                id="T1",
                from_id="ACT_01",
                to_id="ACT_02",
                relation=ProcessRelationType.PRECEDES,
                label="",
                condition="",
            )
        ],
    )

    # 1. Mermaid must contain ACT_01 and ACT_02, but NOT invent START or END nodes
    mmd = render_flowchart_mermaid(graph_no_events)
    assert "ACT_01" in mmd
    assert "ACT_02" in mmd
    assert "START" not in mmd
    assert "END" not in mmd

    # 2. BPMN projection must render actual activities and flows, without inventing phantom startEvent or endEvent
    bpmn = render_bpmn_20_xml(graph_no_events)
    assert "<bpmn2:startEvent" not in bpmn
    assert "<bpmn2:endEvent" not in bpmn
    assert "ACT_01" in bpmn
    assert "ACT_02" in bpmn

    # 3. An empty graph with no nodes fails closed
    with pytest.raises(ValueError, match="no nodes to project"):
        render_bpmn_20_xml(GroundedProcessGraph(process_name="Empty", objective="Empty", events=[], activities=[], gateways=[], transitions=[]))


def test_topology_fidelity_branch_merge():
    """
    Test 3: Diamond pattern (branch divergence and convergence merge)
    GW_01 splits into ACT_A and ACT_B, both converge into ACT_MERGE, then END.
    All transitions must be preserved 1:1.
    """
    registry = _make_registry()
    canonical = CanonicalProcessModel(
        process_name="Merge Process",
        objective="Verify branch convergence",
        schema_version="1.0",
        nodes=[
            SemanticProcessNode(node_id="START", node_type="start_event", label="Start", evidence_spans=["S01"]),
            SemanticProcessNode(node_id="GW_BRANCH", node_type="decision", label="Path Choice", evidence_spans=["S01"]),
            SemanticProcessNode(node_id="ACT_A", node_type="activity", label="Fast Path", actor="Team A", evidence_spans=["S01"]),
            SemanticProcessNode(node_id="ACT_B", node_type="activity", label="Standard Path", actor="Team B", evidence_spans=["S01"]),
            SemanticProcessNode(node_id="ACT_MERGE", node_type="activity", label="Consolidated Review", actor="Manager", evidence_spans=["S01"]),
            SemanticProcessNode(node_id="END", node_type="end_event", label="Finish", evidence_spans=["S01"]),
        ],
        edges=[
            SemanticProcessEdge(edge_id="E1", source_node_id="START", target_node_id="GW_BRANCH", evidence_spans=["S01"]),
            SemanticProcessEdge(edge_id="E2", source_node_id="GW_BRANCH", target_node_id="ACT_A", relation=ProcessRelationType.BRANCH_IF, condition="Priority == High", evidence_spans=["S01"]),
            SemanticProcessEdge(edge_id="E3", source_node_id="GW_BRANCH", target_node_id="ACT_B", relation=ProcessRelationType.DEFAULT_BRANCH, condition="Priority == Normal", evidence_spans=["S01"]),
            SemanticProcessEdge(edge_id="E4", source_node_id="ACT_A", target_node_id="ACT_MERGE", relation=ProcessRelationType.PRECEDES, evidence_spans=["S01"]),
            SemanticProcessEdge(edge_id="E5", source_node_id="ACT_B", target_node_id="ACT_MERGE", relation=ProcessRelationType.PRECEDES, evidence_spans=["S01"]),
            SemanticProcessEdge(edge_id="E6", source_node_id="ACT_MERGE", target_node_id="END", relation=ProcessRelationType.PRECEDES, evidence_spans=["S01"]),
        ],
    )

    normalizer = ProcessNormalizer()
    normalized = normalizer.normalize(canonical)
    assert len(normalized.edges) == 6

    compiler = DeterministicGraphCompiler()
    res = compiler.compile(
        document_name="document.docx",
        canonical_model=normalized,
        verdicts={},
        span_registry=registry,
    )

    assert len(res.graph.transitions) == 6
    # Verify both converge into ACT_MERGE
    merge_incoming = [t for t in res.graph.transitions if t.to_id == "ACT_MERGE"]
    assert len(merge_incoming) == 2
    assert {t.from_id for t in merge_incoming} == {"ACT_A", "ACT_B"}

    mmd = render_flowchart_mermaid(res.graph)
    assert "ACT_A --> ACT_MERGE" in mmd
    assert "ACT_B --> ACT_MERGE" in mmd


def test_topology_fidelity_loop_representation():
    """
    Test 4: Backward loop edge representation.
    Verifies that LOOP_BACK edges are preserved with is_loop=True,
    and rendered without infinite recursion or pruning.
    """
    registry = _make_registry()
    canonical = CanonicalProcessModel(
        process_name="Loop Process",
        objective="Verify loop representation",
        schema_version="1.0",
        nodes=[
            SemanticProcessNode(node_id="START", node_type="start_event", label="Start", evidence_spans=["S01"]),
            SemanticProcessNode(node_id="ACT_DRAFT", node_type="activity", label="Draft Document", actor="Author", evidence_spans=["S01"]),
            SemanticProcessNode(node_id="GW_REVIEW", node_type="decision", label="Review Passed?", evidence_spans=["S01"]),
            SemanticProcessNode(node_id="END", node_type="end_event", label="Approved", evidence_spans=["S01"]),
        ],
        edges=[
            SemanticProcessEdge(edge_id="E1", source_node_id="START", target_node_id="ACT_DRAFT", evidence_spans=["S01"]),
            SemanticProcessEdge(edge_id="E2", source_node_id="ACT_DRAFT", target_node_id="GW_REVIEW", evidence_spans=["S01"]),
            SemanticProcessEdge(edge_id="E3", source_node_id="GW_REVIEW", target_node_id="END", relation=ProcessRelationType.BRANCH_IF, condition="Passed == Yes", evidence_spans=["S01"]),
            SemanticProcessEdge(
                edge_id="E4",
                source_node_id="GW_REVIEW",
                target_node_id="ACT_DRAFT",
                relation=ProcessRelationType.LOOP_BACK,
                condition="Passed == No - Rework",
                evidence_spans=["S01"],
            ),
        ],
    )

    normalizer = ProcessNormalizer()
    normalized = normalizer.normalize(canonical)

    compiler = DeterministicGraphCompiler()
    res = compiler.compile(
        document_name="document.docx",
        canonical_model=normalized,
        verdicts={},
        span_registry=registry,
    )

    loop_transitions = [t for t in res.graph.transitions if t.is_loop]
    assert len(loop_transitions) == 1
    assert loop_transitions[0].from_id == "GW_REVIEW"
    assert loop_transitions[0].to_id == "ACT_DRAFT"
    assert loop_transitions[0].condition == "Passed == No - Rework"

    mmd = render_flowchart_mermaid(res.graph)
    assert "GW_REVIEW -->|Passed == No - Rework| ACT_DRAFT" in mmd


def test_topology_fidelity_exception_and_timeout():
    """
    Test 5: Exception and timeout escalation representation.
    Verifies ESCALATES_TO with trigger_type='timeout' is preserved as is_exception=True,
    has 'Timeout:' formatted label, and renders with dashed line '-.->'.
    """
    registry = _make_registry()
    canonical = CanonicalProcessModel(
        process_name="Escalation Process",
        objective="Verify timeout escalation",
        schema_version="1.0",
        nodes=[
            SemanticProcessNode(node_id="START", node_type="start_event", label="Start", evidence_spans=["S01"]),
            SemanticProcessNode(node_id="ACT_PENDING", node_type="activity", label="Pending Approval", actor="Approver", evidence_spans=["S01"]),
            SemanticProcessNode(node_id="ACT_ESCALATE", node_type="activity", label="Escalate to Director", actor="Director", evidence_spans=["S01"]),
            SemanticProcessNode(node_id="END", node_type="end_event", label="Done", evidence_spans=["S01"]),
        ],
        edges=[
            SemanticProcessEdge(edge_id="E1", source_node_id="START", target_node_id="ACT_PENDING", evidence_spans=["S01"]),
            SemanticProcessEdge(
                edge_id="E2",
                source_node_id="ACT_PENDING",
                target_node_id="ACT_ESCALATE",
                relation=ProcessRelationType.ESCALATES_TO,
                trigger_type="timeout",
                condition="72 hours SLA elapsed",
                evidence_spans=["S01"],
            ),
            SemanticProcessEdge(edge_id="E3", source_node_id="ACT_ESCALATE", target_node_id="END", evidence_spans=["S01"]),
        ],
    )

    normalizer = ProcessNormalizer()
    normalized = normalizer.normalize(canonical)

    compiler = DeterministicGraphCompiler()
    res = compiler.compile(
        document_name="document.docx",
        canonical_model=normalized,
        verdicts={},
        span_registry=registry,
    )

    exc_trans = [t for t in res.graph.transitions if t.is_exception]
    assert len(exc_trans) == 1
    assert exc_trans[0].from_id == "ACT_PENDING"
    assert exc_trans[0].to_id == "ACT_ESCALATE"
    assert "Timeout: 72 hours SLA elapsed" in exc_trans[0].label

    mmd = render_flowchart_mermaid(res.graph)
    assert "-.->" in mmd
    assert "ACT_PENDING -.->|Timeout: 72 hours SLA elapsed| ACT_ESCALATE" in mmd
