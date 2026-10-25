"""
Structural & Referential Graph Validator for Grounded Process Graphs.
Enforces multi-layer structural, referential integrity, span existence,
and topological validity on GroundedProcessGraph ASTs without heuristic semantic inference.
"""

from typing import List, Tuple, Optional, Set, Dict

from injester.synthesis.spans import SpanRegistry
from injester.semantic.schemas import GroundedProcessGraph


class SemanticGraphValidator:
    """
    Structural & Referential Process Graph Validator.
    Verifies graph invariants strictly deterministically:
    - Span existence in the authoritative SpanRegistry
    - Referential integrity between nodes, edges, gateways, and events
    - ID uniqueness and branch target existence
    - Evidence completeness (all non-start procedural elements must cite spans)
    Does NOT perform heuristic linguistic or business-semantic inference.
    """

    def __init__(self, span_registry: Optional[SpanRegistry] = None):
        self.span_registry = span_registry or SpanRegistry()

    def validate_semantic_graph(self, graph: GroundedProcessGraph) -> Tuple[bool, List[str], List[str]]:
        """
        Validates all activities, gateways, branches, and transitions in a GroundedProcessGraph.
        Returns:
            (is_valid, errors, warnings)
        """
        errors: List[str] = []
        warnings: List[str] = []

        all_node_ids: Set[str] = set()
        actor_ids: Set[str] = {a.id for a in graph.actors}

        # 1. Validate Events
        for ev in graph.events:
            if not ev.id:
                errors.append("Encountered ProcessEvent with missing or empty ID.")
                continue
            if ev.id in all_node_ids:
                errors.append(f"Duplicate node ID detected: '{ev.id}' declared multiple times.")
            all_node_ids.add(ev.id)

            if ev.actor_id and ev.actor_id not in actor_ids and ev.actor_id != "ACTOR_UNASSIGNED":
                warnings.append(f"Event '{ev.id}' references undeclared actor '{ev.actor_id}'.")

        # 2. Validate Activities
        for act in graph.activities:
            if not act.id:
                errors.append("Encountered ProcessActivity with missing or empty ID.")
                continue
            if act.id in all_node_ids:
                errors.append(f"Duplicate node ID detected: '{act.id}' declared multiple times.")
            all_node_ids.add(act.id)

            # Evidence Span Existence
            if not act.evidence:
                errors.append(f"STRUCTURAL_MISSING_EVIDENCE: Activity '{act.id}' ({act.label}) lacks supporting span citations.")
            else:
                for sid in act.evidence:
                    if not self.span_registry.get_span(sid):
                        errors.append(f"STRUCTURAL_INVALID_SPAN: Activity '{act.id}' cites non-existent span '{sid}'.")

            # Actor Referential Integrity
            if act.actor_id and act.actor_id not in actor_ids and act.actor_id != "ACTOR_UNASSIGNED":
                warnings.append(f"Activity '{act.id}' references undeclared actor '{act.actor_id}'.")

        # 3. Validate Gateways & Decision Branches
        for gw in graph.gateways:
            if not gw.id:
                errors.append("Encountered ProcessGateway with missing or empty ID.")
                continue
            if gw.id in all_node_ids:
                errors.append(f"Duplicate node ID detected: '{gw.id}' declared multiple times.")
            all_node_ids.add(gw.id)

            # Evidence Span Existence
            if not gw.evidence:
                errors.append(f"STRUCTURAL_MISSING_EVIDENCE: Gateway '{gw.id}' ({gw.question}) lacks supporting span citations.")
            else:
                for sid in gw.evidence:
                    if not self.span_registry.get_span(sid):
                        errors.append(f"STRUCTURAL_INVALID_SPAN: Gateway '{gw.id}' cites non-existent span '{sid}'.")

        # 4. Validate Transitions (Referential Invariant: Source and Target must exist)
        for tr in graph.transitions:
            if not tr.from_id or not tr.to_id:
                errors.append(f"STRUCTURAL_INVALID_TRANSITION: Transition must specify from_id and to_id: {tr}")
                continue

            if tr.from_id not in all_node_ids and tr.from_id != "START":
                errors.append(f"STRUCTURAL_DANGLING_TRANSITION: Transition source '{tr.from_id}' does not exist in graph nodes.")

            if tr.to_id not in all_node_ids and not tr.to_id.startswith("END"):
                errors.append(f"STRUCTURAL_DANGLING_TRANSITION: Transition target '{tr.to_id}' does not exist in graph nodes.")

        # 5. Graph Degree & Topology Invariants (Pure Structural Checks)
        out_degrees: Dict[str, int] = {nid: 0 for nid in all_node_ids}
        in_degrees: Dict[str, int] = {nid: 0 for nid in all_node_ids}

        for tr in graph.transitions:
            if tr.from_id in out_degrees:
                out_degrees[tr.from_id] += 1
            if tr.to_id in in_degrees:
                in_degrees[tr.to_id] += 1

        # 6a. START events must have out-degree >= 1
        start_events = [ev for ev in graph.events if ev.type == "start"]
        for sev in start_events:
            if out_degrees.get(sev.id, 0) == 0:
                errors.append(f"START_DISCONNECTED: Start event '{sev.id}' has zero outgoing transitions.")

        # 6b. END events must have out-degree == 0
        end_events = [ev for ev in graph.events if ev.type == "end"]
        for eev in end_events:
            if out_degrees.get(eev.id, 0) > 0:
                errors.append(
                    f"INVALID_END_EVENT_TOPOLOGY: End event '{eev.id}' cannot have outgoing transitions "
                    f"(out-degree={out_degrees[eev.id]}). If followed by subsequent steps, classify as 'intermediate_event'."
                )

        # 6c. Gateways must have in-degree >= 1 and out-degree >= 2
        if len(graph.activities) > 1:
            for gw in graph.gateways:
                if in_degrees.get(gw.id, 0) == 0:
                    warnings.append(f"GATEWAY_FLOATING: Decision gateway '{gw.id}' has in-degree 0 (no incoming transitions).")
                if out_degrees.get(gw.id, 0) < 2:
                    warnings.append(f"GATEWAY_DEGENERATE: Decision gateway '{gw.id}' has out-degree {out_degrees.get(gw.id, 0)} (expected >= 2).")

        is_valid = (len(errors) == 0)
        return is_valid, errors, warnings
