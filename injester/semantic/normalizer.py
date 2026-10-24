"""
Structural Process Normalizer for Canonical Process Models.
Performs deterministic structural normalization and invariant checks on CanonicalProcessModel
prior to execution grounding compilation. Rejects invalid topologies; does NOT invent missing semantics.
"""

from typing import Dict, List, Set
from injester.semantic.schemas import CanonicalProcessModel, ProcessRelationType, SemanticProcessEdge



class ProcessNormalizer:
    """
    Deterministic structural normalizer between Semantic Reasoner and Compiler.
    Rejects structural inconsistencies without altering or hallucinating process semantics.
    """

    def normalize(self, model: CanonicalProcessModel) -> CanonicalProcessModel:
        self._clean_edges(model)
        self._validate_references(model)
        self._validate_gateway_topology(model)
        self._validate_terminal_topology(model)
        self._validate_branch_conditions(model)
        self._validate_loop_edges(model)
        self._validate_parallel_edges(model)
        self._validate_reachability_and_structure(model)
        return model

    def _validate_reachability_and_structure(self, model: CanonicalProcessModel) -> None:
        """Full structural validation using NetworkX graph algorithms."""
        import networkx as nx

        G = nx.MultiDiGraph()
        for node in model.nodes:
            G.add_node(node.node_id, node_type=node.node_type)
        for edge in model.edges:
            G.add_edge(edge.source_node_id, edge.target_node_id, key=edge.edge_id,
                       relation=edge.relation, condition=edge.condition)

        # 1. Find start nodes
        start_nodes = [n.node_id for n in model.nodes if n.node_type == "start_event"]

        # 2. Check all nodes reachable from start
        for start in start_nodes:
            reachable = nx.descendants(G, start) | {start}
            orphans = set(G.nodes()) - reachable
            non_independent = [
                nid for nid in orphans
                if not any(getattr(n, "is_independent", False) for n in model.nodes if n.node_id == nid)
            ]
            if non_independent:
                for nid in non_independent:
                    if nid not in model.disconnected_node_ids:
                        model.disconnected_node_ids.append(nid)

        # 3. Check end nodes reachable from start
        end_nodes = [n.node_id for n in model.nodes if n.node_type == "end_event"]
        for start in start_nodes:
            for end in end_nodes:
                if end in G.nodes() and not nx.has_path(G, start, end):
                    if end not in model.disconnected_node_ids:
                        model.disconnected_node_ids.append(end)

        # 4. Process nodes with 0 out-degree (dead ends, excluding end_events) - quarantine to disconnected_node_ids, never fabricate synthetic edges
        for node in model.nodes:
            if node.node_type not in ("end_event",) and G.out_degree(node.node_id) == 0:
                if node.node_id not in model.disconnected_node_ids:
                    model.disconnected_node_ids.append(node.node_id)


    def _clean_edges(self, model: CanonicalProcessModel) -> None:
        """
        Removes invalid self-loops and redundant duplicate edges from canonical model.
        """
        cleaned = []
        seen = set()
        for edge in model.edges:
            # Drop self-loops (source == target)
            if edge.source_node_id == edge.target_node_id:
                continue
            key = (edge.source_node_id, edge.target_node_id, (edge.condition or "").strip().lower())
            if key in seen:
                continue
            seen.add(key)
            cleaned.append(edge)
        model.edges = cleaned


    def _validate_references(self, model: CanonicalProcessModel) -> None:
        node_ids = {node.node_id for node in model.nodes}
        for edge in model.edges:
            if edge.source_node_id not in node_ids:
                raise ValueError(
                    f"Edge '{edge.edge_id}' references unknown source node '{edge.source_node_id}'."
                )
            if edge.target_node_id not in node_ids:
                raise ValueError(
                    f"Edge '{edge.edge_id}' references unknown target node '{edge.target_node_id}'."
                )

    def _validate_gateway_topology(self, model: CanonicalProcessModel) -> None:
        outgoing: Dict[str, List] = {}
        for edge in model.edges:
            outgoing.setdefault(edge.source_node_id, []).append(edge)

        for node in model.nodes:
            if node.node_type != "decision":
                continue

            edges = outgoing.get(node.node_id, [])
            if not edges:
                raise ValueError(
                    f"Decision node '{node.node_id}' has no outgoing branch."
                )

            for edge in edges:
                if edge.relation not in {
                    ProcessRelationType.BRANCH_IF,
                    ProcessRelationType.DEFAULT_BRANCH,
                    ProcessRelationType.PRECEDES,
                    ProcessRelationType.LOOP_BACK,
                    ProcessRelationType.ESCALATES_TO,
                    ProcessRelationType.PARALLEL_SPLIT,
                }:
                    raise ValueError(
                        f"Decision node '{node.node_id}' has invalid outgoing relation '{edge.relation}'."
                    )

    def _validate_terminal_topology(self, model: CanonicalProcessModel) -> None:
        end_nodes = {
            node.node_id for node in model.nodes if node.node_type == "end_event"
        }
        for edge in model.edges:
            if edge.source_node_id in end_nodes:
                raise ValueError(
                    f"End event '{edge.source_node_id}' cannot have outgoing transition or edges."
                )

    def _validate_branch_conditions(self, model: CanonicalProcessModel) -> None:
        for edge in model.edges:
            if edge.relation == ProcessRelationType.BRANCH_IF:
                if not edge.condition:
                    raise ValueError(
                        f"Branch edge '{edge.edge_id}' has no explicit condition."
                    )
            elif edge.relation == ProcessRelationType.DEFAULT_BRANCH:
                if not edge.condition:
                    edge.condition = "Default"

    def _validate_loop_edges(self, model: CanonicalProcessModel) -> None:
        for edge in model.edges:
            if edge.relation == ProcessRelationType.LOOP_BACK:
                if not edge.source_node_id or not edge.target_node_id:
                    raise ValueError(
                        f"Loop edge '{edge.edge_id}' must specify both source and target nodes."
                    )

    def _validate_parallel_edges(self, model: CanonicalProcessModel) -> None:
        for edge in model.edges:
            if edge.relation in {ProcessRelationType.PARALLEL_SPLIT, ProcessRelationType.PARALLEL_JOIN}:
                if not edge.source_node_id or not edge.target_node_id:
                    raise ValueError(
                        f"Parallel edge '{edge.edge_id}' must specify both source and target nodes."
                    )


CanonicalModelValidator = ProcessNormalizer
