"""
Leave Approval Document Pipeline Test and Output Validation.
Processes SOP_Easy_LeaveApproval.docx through the EvidenceFirstSemanticPipeline
and logically validates all generated outputs:
1. Markdown Defect Register (MD)
2. BPMN 2.0 XML (BPMN)
3. Mermaid Diagrams (Flowchart & Swimlane)
"""

import os
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, Any


from injester.semantic.pipeline import EvidenceFirstSemanticPipeline
from injester.semantic.schemas import DefectCategory
from injester.semantic.projections import safe_ident


def validate_markdown_defect_register(md_path: Path, result_graph: Any) -> Dict[str, Any]:
    print("\n--- [1/3] Validating Markdown Output (DEFECT_REGISTER.md) ---")
    assert md_path.exists(), f"Markdown file not found: {md_path}"
    content = md_path.read_text(encoding="utf-8")
    lines = content.splitlines()

    assert content.startswith("# Ambiguity & Defect Register:"), "Missing standard H1 title"
    assert "**Total Extracted Propositions**:" in content, "Missing total extracted metric"
    assert "**Verified & Compiled into Graph**:" in content, "Missing total verified metric"
    assert "**Excluded / Logged in Register**:" in content, "Missing total excluded metric"

    table_lines = [l for l in lines if l.strip().startswith("|")]
    if table_lines:
        header = table_lines[0]
        assert "Category" in header and "Proposition" in header and "Cited Span" in header, "Invalid table columns"
        assert "Verification Rationale" in header and "Confidence" in header, "Missing verification columns"

        allowed_categories = {c.value for c in DefectCategory}
        verified_activity_ids = {a.id for a in result_graph.activities}

        defects_checked = 0
        for row in table_lines[2:]:
            cols = [c.strip() for c in row.split("|")[1:-1]]
            if len(cols) >= 7:
                cat = cols[1].strip("`")
                prop = cols[2]
                span = cols[3].strip("`")
                rationale = cols[5]
                conf = float(cols[6])

                assert cat in allowed_categories, f"Unknown defect category: {cat}"
                assert len(rationale) > 0, "Empty rationale in defect record"
                assert 0.0 <= conf <= 1.0, f"Confidence {conf} out of range [0, 1]"

                # Referential Invariant: Excluded node ID must NOT be in verified graph activities
                for act_id in verified_activity_ids:
                    assert prop != act_id, f"Defect node '{prop}' illegally entered verified graph activities!"
                defects_checked += 1

        print(f"  ✓ Markdown table syntax valid with {defects_checked} checked defect rows.")
    else:
        assert "Zero defects or ungrounded propositions detected" in content, "Empty table without zero-defect badge"
        print("  ✓ Zero-defect markdown format verified (100% policy pass).")

    print("  ✓ Markdown Defect Register logically verified.")
    return {"status": "PASSED"}


def validate_bpmn_xml(bpmn_path: Path, result_graph: Any) -> Dict[str, Any]:
    print("\n--- [2/3] Validating BPMN 2.0 XML Output (bpmn_2_0.xml) ---")
    assert bpmn_path.exists(), f"BPMN XML file not found: {bpmn_path}"
    xml_content = bpmn_path.read_text(encoding="utf-8")

    try:
        root = ET.fromstring(xml_content)
    except ET.ParseError as e:
        raise AssertionError(f"BPMN output is not well-formed XML: {e}")

    ns = {
        "bpmn": "http://www.omg.org/spec/BPMN/20100524/MODEL",
        "bpmndi": "http://www.omg.org/spec/BPMN/20100524/DI",
        "dc": "http://www.omg.org/spec/DD/20100524/DC",
        "di": "http://www.omg.org/spec/DD/20100524/DI",
    }

    assert root.tag == f"{{{ns['bpmn']}}}definitions", f"Unexpected root tag: {root.tag}"

    collab = root.find("bpmn:collaboration", ns)
    assert collab is not None, "Missing bpmn:collaboration"
    process = root.find("bpmn:process", ns)
    assert process is not None, "Missing bpmn:process"

    # Swimlanes
    lane_set = process.find("bpmn:laneSet", ns)
    assert lane_set is not None, "Missing bpmn:laneSet"
    lanes = lane_set.findall("bpmn:lane", ns)
    assert len(lanes) >= 1, "At least one lane must exist"

    lane_ids = set()
    node_to_lane = {}
    for lane in lanes:
        lid = lane.attrib["id"]
        lname = lane.attrib.get("name", "")
        assert lid not in lane_ids, f"Duplicate lane ID: {lid}"
        lane_ids.add(lid)
        assert len(lname) > 0, f"Lane {lid} has empty name"

        for node_ref in lane.findall("bpmn:flowNodeRef", ns):
            nid = node_ref.text.strip()
            assert nid not in node_to_lane, f"Node {nid} assigned to multiple lanes!"
            node_to_lane[nid] = lname

    print(f"  ✓ Validated {len(lanes)} swimlanes: {', '.join(lane_ids)}")

    # Nodes
    all_process_node_ids = set()
    for tag in ("startEvent", "userTask", "exclusiveGateway", "parallelGateway", "inclusiveGateway", "endEvent", "intermediateThrowEvent"):
        for elem in process.findall(f"bpmn:{tag}", ns):
            nid = elem.attrib["id"]
            all_process_node_ids.add(nid)
            assert nid in node_to_lane, f"Node '{nid}' ({tag}) is not assigned to any lane!"

    for act in result_graph.activities:
        assert safe_ident(act.id) in all_process_node_ids, f"Verified activity '{act.id}' missing from BPMN XML!"
    for gw in result_graph.gateways:
        assert safe_ident(gw.id) in all_process_node_ids, f"Verified gateway '{gw.id}' missing from BPMN XML!"

    print(f"  ✓ Verified {len(all_process_node_ids)} process nodes properly routed into swimlanes.")

    # Sequence flows
    seq_flows = process.findall("bpmn:sequenceFlow", ns)
    flow_ids = set()
    for flow in seq_flows:
        fid = flow.attrib["id"]
        src = flow.attrib["sourceRef"]
        tgt = flow.attrib["targetRef"]
        assert fid not in flow_ids, f"Duplicate sequenceFlow ID: {fid}"
        flow_ids.add(fid)
        assert src in all_process_node_ids, f"SequenceFlow '{fid}' sourceRef '{src}' not found in process!"
        assert tgt in all_process_node_ids, f"SequenceFlow '{fid}' targetRef '{tgt}' not found in process!"

    print(f"  ✓ Validated {len(seq_flows)} sequence flows with strict referential integrity.")

    # Diagram Interchange (BPMNDI)
    diag = root.find("bpmndi:BPMNDiagram", ns)
    assert diag is not None, "Missing bpmndi:BPMNDiagram"
    plane = diag.find("bpmndi:BPMNPlane", ns)
    assert plane is not None, "Missing bpmndi:BPMNPlane"

    shapes = plane.findall("bpmndi:BPMNShape", ns)
    edges = plane.findall("bpmndi:BPMNEdge", ns)

    shape_elements = set()
    for s in shapes:
        be = s.attrib["bpmnElement"]
        shape_elements.add(be)
        bounds = s.find("dc:Bounds", ns)
        assert bounds is not None, f"Shape {be} missing dc:Bounds"
        w = float(bounds.attrib["width"])
        h = float(bounds.attrib["height"])
        x = float(bounds.attrib["x"])
        y = float(bounds.attrib["y"])
        assert w > 0 and h > 0, f"Invalid dimensions for {be}: {w}x{h}"
        assert x >= 0 and y >= 0, f"Negative coordinates for {be}: ({x}, {y})"

    for lid in lane_ids:
        assert lid in shape_elements, f"Lane '{lid}' missing BPMNDI visual shape!"
    for nid in all_process_node_ids:
        assert nid in shape_elements, f"Node '{nid}' missing BPMNDI visual shape!"

    for e in edges:
        be = e.attrib["bpmnElement"]
        assert be in flow_ids, f"BPMNEdge references non-existent sequenceFlow '{be}'"
        waypoints = e.findall("di:waypoint", ns)
        assert len(waypoints) >= 2, f"Edge {be} has fewer than 2 waypoints"
        for wp in waypoints:
            wx = float(wp.attrib["x"])
            wy = float(wp.attrib["y"])
            assert wx >= 0 and wy >= 0, f"Negative waypoint coordinates: ({wx}, {wy})"

    print(f"  ✓ Validated BPMNDI diagram interchange: {len(shapes)} shapes, {len(edges)} edges with valid waypoints.")
    print("  ✓ BPMN 2.0 XML logically verified.")
    return {"status": "PASSED"}


def validate_mermaid_diagrams(fc_path: Path, sw_path: Path, result_graph: Any) -> Dict[str, Any]:
    print("\n--- [3/3] Validating Mermaid Projections (flowchart.mmd & swimlane.mmd) ---")
    assert fc_path.exists(), f"Flowchart file not found: {fc_path}"
    assert sw_path.exists(), f"Swimlane file not found: {sw_path}"

    fc_content = fc_path.read_text(encoding="utf-8")
    sw_content = sw_path.read_text(encoding="utf-8")

    assert fc_content.strip().startswith("flowchart TD"), "Flowchart missing 'flowchart TD' header"
    assert sw_content.strip().startswith("flowchart TD"), "Swimlane missing 'flowchart TD' header"

    for act in result_graph.activities:
        assert safe_ident(act.id) in fc_content, f"Activity '{act.id}' missing from flowchart.mmd"
    for gw in result_graph.gateways:
        assert safe_ident(gw.id) in fc_content, f"Gateway '{gw.id}' missing from flowchart.mmd"

    print(f"  ✓ Flowchart contains all {len(result_graph.activities)} activities and {len(result_graph.gateways)} gateways.")

    sw_lines = sw_content.splitlines()
    subgraph_count = sum(1 for l in sw_lines if l.strip().startswith("subgraph "))
    end_count = sum(1 for l in sw_lines if l.strip() == "end")
    assert subgraph_count == end_count, f"Mismatched subgraphs in swimlane.mmd ({subgraph_count} != {end_count})"

    for act in result_graph.activities:
        assert safe_ident(act.id) in sw_content, f"Activity '{act.id}' missing from swimlane.mmd"

    print(f"  ✓ Swimlane diagram has {subgraph_count} matched actor subgraphs with complete activity placement.")
    print("  ✓ Mermaid diagrams logically verified.")
    return {"status": "PASSED"}


def validate_sop_markdown(sop_path: Path, result_graph: Any) -> Dict[str, Any]:
    print("\n--- [4/4] Validating Generated SOP Document (SOP.md) ---")
    assert sop_path.exists(), f"SOP Markdown file not found: {sop_path}"
    content = sop_path.read_text(encoding="utf-8")

    assert content.startswith("# "), "Missing standard H1 SOP title"
    assert "Citation Index" in content, "Missing Citation Index section"
    assert len(content) > 500, "SOP content is suspiciously short"

    # Verify presence of inline citations [S###]
    import re
    citations = re.findall(r'\[S\d{3}\]', content)
    assert len(citations) >= 1, "No inline span citations [S###] found in SOP.md"

    # Verify citation index details
    assert "Chunk ID:" in content or "Source Document:" in content or "Source:" in content, "Missing Chunk/Source in Citation Index"

    print(f"  ✓ Validated SOP.md: {len(content.splitlines())} lines with {len(set(citations))} unique cited evidence spans.")
    print("  ✓ SOP with Citations logically verified.")
    return {"status": "PASSED"}


def main():
    doc_path = Path("/home/jefino9488/Downloads/test/SOP_Easy_LeaveApproval.docx").resolve()
    if not doc_path.exists():
        doc_path = Path("sop_testcase_1_leave_approval.md").resolve()

    out_dir = Path("storage/leave_approval_test_outputs").resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    print("=====================================================================")
    print(f"RUNNING TEST ON LEAVE APPROVAL DOCUMENT: {doc_path.name}")
    print(f"OUTPUT DIRECTORY: {out_dir}")
    print("=====================================================================")

    pipeline = EvidenceFirstSemanticPipeline()
    result = pipeline.process_document(file_path=doc_path, output_dir=out_dir)

    print(f"\nPipeline Run Completed:")
    print(f"  - Process Integrity:   {result.defect_register.process_integrity_status}")
    print(f"  - Verified Activities: {len(result.graph.activities)}")
    print(f"  - Verified Gateways:   {len(result.graph.gateways)}")
    print(f"  - Verified Transitions:{len(result.graph.transitions)}")
    print(f"  - Quarantined Defects: {len(result.defect_register.defects)}")

    assert result.defect_register.process_integrity_status in ("VERIFIED", "STRUCTURALLY_DEGRADED"), (
        f"Expected process_integrity_status 'VERIFIED' or 'STRUCTURALLY_DEGRADED', got '{result.defect_register.process_integrity_status}'"
    )

    md_path = out_dir / "DEFECT_REGISTER.md"
    bpmn_path = out_dir / "bpmn_2_0.xml"
    fc_path = out_dir / "flowchart.mmd"
    sw_path = out_dir / "swimlane.mmd"
    sop_path = out_dir / "SOP.md"

    validate_markdown_defect_register(md_path, result.graph)
    validate_bpmn_xml(bpmn_path, result.graph)
    validate_mermaid_diagrams(fc_path, sw_path, result.graph)
    validate_sop_markdown(sop_path, result.graph)

    print("\n=====================================================================")
    print("FINAL LOGICAL VALIDATION SUMMARY:")
    print("  ✓ Markdown Defect Register (MD):  PASSED")
    print("  ✓ BPMN 2.0 XML (BPMN):            PASSED")
    print("  ✓ Mermaid Flowchart & Swimlane:   PASSED")
    print("  ✓ Citation-Grounded SOP (SOP.md): PASSED")
    print("=====================================================================")


if __name__ == "__main__":
    main()
