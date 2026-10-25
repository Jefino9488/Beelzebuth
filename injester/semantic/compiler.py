"""
Deterministic Graph Compiler for the Evidence-First Pipeline.
Transforms Grounded Semantic Process Models into authoritative Process Graph AST
and companion Ambiguity & Defect Register under strict non-hallucinating rules.

CRITICAL ARCHITECTURAL PRINCIPLE:
The compiler does NOT infer process semantics, sequence order, gateway targets, or actor equivalences.
All semantic interpretation is performed by the Semantic Process Reasoner.
The compiler is strictly responsible for:
1. Evidence span existence and Laya grounding validation gating.
2. First-class ambiguity recording in the AmbiguityRegister.
3. Deterministic assembly of the verified CanonicalProcessModel into GroundedProcessGraph AST.
"""

import re
from typing import List, Dict, Tuple, Optional, Set
from collections import deque
from injester.synthesis.spans import SpanRegistry
from injester.semantic.schemas import (
    AtomicProposition,
    LayaVerdict,
    GroundedProcessGraph,
    ProcessActor,
    ProcessActivity,
    ProcessGateway,
    ProcessEvent,
    ProcessTransition,
    AmbiguityRegister,
    DefectRecord,
    DefectCategory,
    DualOutputResult,
    CanonicalProcessModel,
    SemanticProcessNode,
    SemanticProcessEdge,
    ActorResolution,
    ProcessRelationType,
    ElementStatus,
    GroundingVerdict,
    ValidationPolicy,
)


class DeterministicGraphCompiler:
    """
    Deterministically compiles verified semantic process models into canonical GroundedProcessGraph AST
    and partitions rejected, ungrounded, or ambiguous elements into the AmbiguityRegister.
    """

    def __init__(
        self,
        policy: Optional[ValidationPolicy] = None,
        confidence_threshold: float = 0.70,
        ambiguity_threshold: float = 0.60
    ):
        self.policy = policy or ValidationPolicy(
            entailment_confidence_threshold=confidence_threshold,
            actor_confidence_threshold=confidence_threshold,
            ambiguity_floor=ambiguity_threshold
        )

    def _verify_provenance(
        self,
        proposition_ids: List[str],
        required_proposition_ids: List[str],
        verdicts: Dict[str, LayaVerdict],
    ) -> Tuple[bool, List[str]]:
        ids = list(dict.fromkeys(
            proposition_ids + required_proposition_ids
        ))
        if not ids:
            return False, ["No proposition provenance attached."]

        missing = [
            pid for pid in ids if pid not in verdicts
        ]
        if missing:
            return False, [
                f"Missing System-1 verdict for {pid}"
                for pid in missing
            ]

        rejected = [
            pid for pid in ids if not verdicts[pid].is_verified
        ]
        if rejected:
            return False, [
                f"Proposition '{pid}' failed grounding verification."
                for pid in rejected
            ]

        return True, []

    def compile(
        self,
        document_name: str,
        process_name: str = "",
        objective: str = "",
        span_registry: Optional[SpanRegistry] = None,
        canonical_model: Optional[CanonicalProcessModel] = None,
        propositions: Optional[List[AtomicProposition]] = None,
        verdicts: Optional[Dict[str, LayaVerdict]] = None,
    ) -> DualOutputResult:
        """
        Executes structural and grounding validation, records ambiguities, and
        assembles the authoritative GroundedProcessGraph AST.
        """
        registry = span_registry if span_registry is not None else SpanRegistry()
        if canonical_model is not None:
            return self._compile_from_canonical_model(
                document_name=document_name,
                process_name=process_name or canonical_model.process_name,
                objective=objective or canonical_model.objective,
                canonical_model=canonical_model,
                verdicts=verdicts or {},
                span_registry=registry,
                propositions=propositions
            )
        else:
            # Fallback for legacy / mock proposition unit tests
            return self._compile_from_propositions(
                document_name=document_name,
                process_name=process_name,
                objective=objective,
                propositions=propositions or [],
                verdicts=verdicts or {},
                span_registry=registry
            )

    def _compile_from_canonical_model(
        self,
        document_name: str,
        process_name: str,
        objective: str,
        canonical_model: CanonicalProcessModel,
        verdicts: Dict[str, LayaVerdict],
        span_registry: SpanRegistry,
        propositions: Optional[List[AtomicProposition]] = None
    ) -> DualOutputResult:
        defects: List[DefectRecord] = []

        # 1. Process Actor Resolutions (First-Class Ambiguity Handling)
        canonical_actors_map: Dict[str, str] = {}
        for res in canonical_model.actor_resolutions:
            if res.is_ambiguous or res.confidence < self.policy.actor_confidence_threshold:
                defects.append(DefectRecord(
                    proposition_id=f"ACTOR_{res.raw_mention}",
                    evidence_spans=res.evidence_spans,
                    defect_category=DefectCategory.AMBIGUOUS_ACTOR,
                    claimed_statement=f"Actor mention '{res.raw_mention}' contextually mapped to '{res.canonical_actor}'",
                    evidence_text=", ".join(res.possible_actors) if res.possible_actors else "",
                    rationale=res.justification or "Contextual actor equivalence ambiguous in document context",
                    confidence=res.confidence,
                    actor_involved=res.raw_mention
                ))
                if res.confidence < self.policy.ambiguity_floor:
                    canonical_actors_map[res.raw_mention.lower()] = res.raw_mention
                    continue
            canonical_actors_map[res.raw_mention.lower()] = res.canonical_actor

        # 2. Validate Nodes against Evidence Spans & Laya Verdicts
        verified_nodes: Dict[str, SemanticProcessNode] = {}
        for node in canonical_model.nodes:
            # 2a. Check span existence in SpanRegistry
            spans = [span_registry.get_span(sid) for sid in node.evidence_spans if span_registry.get_span(sid)]
            if not spans and node.node_type not in ("start_event", "end_event"):
                defects.append(DefectRecord(
                    proposition_id=node.node_id,
                    evidence_spans=node.evidence_spans,
                    defect_category=DefectCategory.UNVERIFIED_CLAIM,
                    claimed_statement=f"{node.node_type.upper()}: {node.label}",
                    evidence_text="",
                    rationale=f"Cited span IDs {node.evidence_spans} not found in span registry",
                    confidence=0.0,
                    actor_involved=node.actor
                ))
                node.status = ElementStatus.REJECTED
                continue

            # 2b. Laya Verdict Aggregation via source_proposition_ids & required_proposition_ids
            node_prop_ids = list(node.source_proposition_ids)
            if not node_prop_ids and propositions:
                node_spans = set(node.evidence_spans)
                node_prop_ids = [p.id for p in propositions if set(p.evidence_spans) & node_spans]


            relevant_prop_ids = list(set(
                node_prop_ids + 
                node.required_proposition_ids + 
                ([node.node_id] if node.node_id in verdicts else [])
            ))

            node_verdicts = [verdicts[pid] for pid in relevant_prop_ids if pid in verdicts]
            required_prop_ids = set(node.required_proposition_ids or relevant_prop_ids)

            node_status = ElementStatus.VERIFIED
            node_defect_cat = None
            node_rationale: List[str] = []

            # Aggregation Contract:
            # 1. Any required proposition UNSUPPORTED / contradicted -> REJECTED
            # 2. At least one required proposition UNCERTAIN (and none UNSUPPORTED) -> AMBIGUOUS
            # 3. All required propositions SUPPORTED -> VERIFIED
            if node_verdicts:
                if node.required_proposition_ids:
                    any_unsupported = any(
                        (v.verdict == GroundingVerdict.UNSUPPORTED)
                        for v in node_verdicts if v.proposition_id in node.required_proposition_ids
                    )
                    any_uncertain = any(
                        (v.verdict == GroundingVerdict.UNCERTAIN or not v.is_verified)
                        for v in node_verdicts if v.proposition_id in node.required_proposition_ids
                    )

                    if any_unsupported:
                        node_status = ElementStatus.REJECTED
                        failing = next(v for v in node_verdicts if v.proposition_id in node.required_proposition_ids and v.verdict == GroundingVerdict.UNSUPPORTED)
                        node_defect_cat = DefectCategory.ACTION_UNENTAILED if not failing.action_entailed else DefectCategory.UNGROUNDED_ROLE
                        node_rationale = failing.rejection_reasons or ["Proposition unsupported by evidence"]
                    elif any_uncertain:
                        node_status = ElementStatus.AMBIGUOUS
                        node_defect_cat = DefectCategory.LOW_CONFIDENCE
                        node_rationale = ["Proposition grounding uncertain; quarantined to Defect Register"]
                    else:
                        node_status = ElementStatus.VERIFIED
                else:
                    # For nodes matching propositions via evidence spans:
                    # Verified if at least one proposition is verified supported and none unsupported
                    any_unsupported = any(v.verdict == GroundingVerdict.UNSUPPORTED for v in node_verdicts)
                    has_verified_support = any(v.is_verified and v.verdict == GroundingVerdict.SUPPORTED for v in node_verdicts)

                    if any_unsupported:
                        node_status = ElementStatus.REJECTED
                        failing = next(v for v in node_verdicts if v.verdict == GroundingVerdict.UNSUPPORTED)
                        node_defect_cat = DefectCategory.ACTION_UNENTAILED if not failing.action_entailed else DefectCategory.UNGROUNDED_ROLE
                        node_rationale = failing.rejection_reasons or ["Proposition unsupported by evidence"]
                    elif has_verified_support:
                        node_status = ElementStatus.VERIFIED
                    else:
                        node_status = ElementStatus.AMBIGUOUS
                        node_defect_cat = DefectCategory.LOW_CONFIDENCE
                        node_rationale = ["No supporting proposition verified with high confidence; quarantined to Defect Register"]
            elif node.node_type in ("activity", "decision") and relevant_prop_ids and not node_verdicts:
                node_status = ElementStatus.REJECTED
                node_defect_cat = DefectCategory.UNVERIFIED_CLAIM
                node_rationale = [f"Missing Laya verdicts for propositions {relevant_prop_ids}"]

            node.status = node_status

            if node_status != ElementStatus.VERIFIED:
                defects.append(DefectRecord(
                    proposition_id=node.node_id,
                    evidence_spans=node.evidence_spans,
                    defect_category=node_defect_cat or DefectCategory.UNVERIFIED_CLAIM,
                    claimed_statement=f"{node.actor}: {node.label}" if node.actor else node.label,
                    evidence_text=" ".join(s.text for s in spans) if spans else "",
                    rationale="; ".join(node_rationale) if node_rationale else f"Node marked {node_status.value}",
                    confidence=0.5 if node_status == ElementStatus.AMBIGUOUS else 0.0,
                    actor_involved=node.actor
                ))
                continue

            verified_nodes[node.node_id] = node

        # 3. Detect & Record Disconnected Components into AmbiguityRegister (Without deleting them)
        all_edge_nodes = {e.source_node_id for e in canonical_model.edges} | {e.target_node_id for e in canonical_model.edges}
        for node in canonical_model.nodes:
            if node.node_type in ("activity", "decision") and not node.is_independent:
                if node.node_id not in all_edge_nodes:
                    defects.append(DefectRecord(
                        proposition_id=node.node_id,
                        evidence_spans=node.evidence_spans,
                        defect_category=DefectCategory.STRUCTURALLY_UNRESOLVED,
                        claimed_statement=f"Disconnected {node.node_type}: {node.label}",
                        evidence_text="",
                        rationale=f"Node '{node.node_id}' is disconnected from process topology and not marked independent.",
                        confidence=0.5,
                        actor_involved=node.actor
                    ))

        # 4. Validate Directed Edges
        verified_edges: List[SemanticProcessEdge] = []
        for edge in canonical_model.edges:
            # Referential Invariant: Both source and target must exist in verified nodes
            if edge.source_node_id not in verified_nodes:
                defects.append(DefectRecord(
                    proposition_id=f"EDGE_{edge.source_node_id}_{edge.target_node_id}",
                    evidence_spans=edge.evidence_spans,
                    defect_category=DefectCategory.UNGROUNDED_TRANSITION,
                    claimed_statement=f"Transition from {edge.source_node_id} to {edge.target_node_id}",
                    evidence_text="",
                    rationale=f"Source node '{edge.source_node_id}' was excluded or does not exist",
                    confidence=0.0
                ))
                edge.status = ElementStatus.REJECTED
                continue

            if edge.target_node_id not in verified_nodes:
                defects.append(DefectRecord(
                    proposition_id=f"EDGE_{edge.source_node_id}_{edge.target_node_id}",
                    evidence_spans=edge.evidence_spans,
                    defect_category=DefectCategory.UNGROUNDED_TRANSITION,
                    claimed_statement=f"Transition from {edge.source_node_id} to {edge.target_node_id}",
                    evidence_text="",
                    rationale=f"Target node '{edge.target_node_id}' was excluded or does not exist",
                    confidence=0.0
                ))
                edge.status = ElementStatus.REJECTED
                continue

            # Check edge evidence spans (all transitions except START need evidence)
            is_from_start = (
                edge.source_node_id == "START" or
                (edge.source_node_id in verified_nodes and verified_nodes[edge.source_node_id].node_type == "start_event")
            )
            if not is_from_start:
                edge_spans = [span_registry.get_span(sid) for sid in edge.evidence_spans if span_registry.get_span(sid)]
                if not edge_spans:
                    defects.append(DefectRecord(
                        proposition_id=f"EDGE_{edge.source_node_id}_{edge.target_node_id}",
                        evidence_spans=edge.evidence_spans,
                        defect_category=DefectCategory.UNVERIFIED_CLAIM,
                        claimed_statement=f"Transition {edge.source_node_id} -> {edge.target_node_id}",
                        evidence_text="",
                        rationale=f"Edge cited span IDs {edge.evidence_spans} not found in span registry",
                        confidence=0.0
                    ))
                    edge.status = ElementStatus.REJECTED
                    continue

            # Check edge proposition verdicts if specified
            edge_prop_ids = list(set(edge.source_proposition_ids + edge.required_proposition_ids))
            edge_verdicts = [verdicts[pid] for pid in edge_prop_ids if pid in verdicts]
            if edge_verdicts:
                if any(v.verdict == GroundingVerdict.UNSUPPORTED for v in edge_verdicts):
                    edge.status = ElementStatus.REJECTED

                    defects.append(DefectRecord(
                        proposition_id=f"EDGE_{edge.source_node_id}_{edge.target_node_id}",
                        evidence_spans=edge.evidence_spans,
                        defect_category=DefectCategory.UNGROUNDED_TRANSITION,
                        claimed_statement=f"Transition {edge.source_node_id} -> {edge.target_node_id}",
                        evidence_text="",
                        rationale="Supporting proposition rejected by Laya verifier",
                        confidence=0.0
                    ))
                    continue

            # Check edge ambiguity and confidence against policy
            is_edge_ambiguous = edge.is_ambiguous or (edge.confidence < self.policy.entailment_confidence_threshold)
            if edge_verdicts and any(v.verdict == GroundingVerdict.UNCERTAIN for v in edge_verdicts):
                is_edge_ambiguous = True

            if is_edge_ambiguous:
                edge.status = ElementStatus.AMBIGUOUS if edge.confidence >= self.policy.ambiguity_floor else ElementStatus.REJECTED
                defects.append(DefectRecord(
                    proposition_id=f"EDGE_{edge.source_node_id}_{edge.target_node_id}",
                    evidence_spans=edge.evidence_spans,
                    defect_category=DefectCategory.UNGROUNDED_TRANSITION if edge.status == ElementStatus.REJECTED else DefectCategory.LOW_CONFIDENCE,
                    claimed_statement=f"Transition {edge.source_node_id} -> {edge.target_node_id} ({edge.relation.value})",
                    evidence_text="",
                    rationale=edge.justification or ("Transition below confidence threshold" if edge.status == ElementStatus.REJECTED else "Transition is ambiguous; quarantined to Defect Register"),
                    confidence=edge.confidence
                ))
                continue
            else:
                edge.status = ElementStatus.VERIFIED
                verified_edges.append(edge)


        # 5. Forward Reachability Traversal (BFS) and Structural Defect Recording
        start_nodes = [
            nid for nid, n in verified_nodes.items()
            if (n.node_type == "start_event" or nid.upper() == "START")
        ]
        has_explicit_start = bool(start_nodes)

        if has_explicit_start:
            start_roots = list(start_nodes)

            adj: Dict[str, List[str]] = {nid: [] for nid in verified_nodes}
            for edge in verified_edges:
                if edge.source_node_id in adj:
                    adj[edge.source_node_id].append(edge.target_node_id)

            visited_from_start: Set[str] = set(start_roots)
            queue = deque(start_roots)
            while queue:
                curr = queue.popleft()
                for nxt in adj.get(curr, []):
                    if nxt not in visited_from_start and nxt in verified_nodes:
                        visited_from_start.add(nxt)
                        queue.append(nxt)

            # Independent components with valid evidence
            def has_valid_independence(n: SemanticProcessNode) -> bool:
                if not getattr(n, "is_independent", False):
                    return False
                spans = getattr(n, "independence_evidence_spans", [])
                return bool(spans and any(span_registry.get_span(sid) is not None for sid in spans))

            independent_roots = [
                nid for nid, n in verified_nodes.items()
                if has_valid_independence(n) and nid not in visited_from_start
            ]
            visited_independent: Set[str] = set(independent_roots)
            queue_ind = deque(independent_roots)
            while queue_ind:
                curr = queue_ind.popleft()
                for nxt in adj.get(curr, []):
                    if nxt not in visited_independent and nxt in verified_nodes:
                        visited_independent.add(nxt)
                        queue_ind.append(nxt)

            valid_reachable = visited_from_start | visited_independent

            # Audit unreachable procedural nodes in Defect Register
            for nid, node in list(verified_nodes.items()):
                if node.node_type not in ("start_event", "end_event") and nid not in valid_reachable:
                    # If ALL canonical incoming predecessors were rejected/excluded, quarantine as DEPENDENCY_BLOCKED
                    incoming = [e for e in canonical_model.edges if e.target_node_id == nid]
                    all_predecessors_rejected = bool(incoming) and all(
                        e.source_node_id not in verified_nodes for e in incoming
                    )
                    if all_predecessors_rejected:
                        defects.append(DefectRecord(
                            proposition_id=nid,
                            evidence_spans=node.evidence_spans,
                            defect_category=DefectCategory.DEPENDENCY_BLOCKED,
                            claimed_statement=f"{node.node_type.upper()}: {node.label}",
                            evidence_text="",
                            rationale=f"Node '{nid}' blocked because all upstream dependencies were rejected.",
                            confidence=0.0,
                            actor_involved=node.actor
                        ))
                        del verified_nodes[nid]
                    else:
                        defects.append(DefectRecord(
                            proposition_id=nid,
                            evidence_spans=node.evidence_spans,
                            defect_category=DefectCategory.STRUCTURALLY_UNRESOLVED,
                            claimed_statement=f"{node.node_type.upper()}: {node.label}",
                            evidence_text="",
                            rationale=f"Node '{nid}' has an incomplete path from process START; retained in graph AST.",
                            confidence=0.5,
                            actor_involved=node.actor
                        ))

            # Filter verified_edges to ensure referential integrity
            surviving_edges = []
            for edge in verified_edges:
                if edge.source_node_id in verified_nodes and edge.target_node_id in verified_nodes:
                    surviving_edges.append(edge)
                else:
                    edge.status = ElementStatus.REJECTED
                    defects.append(DefectRecord(
                        proposition_id=edge.edge_id or f"EDGE_{edge.source_node_id}_{edge.target_node_id}",
                        evidence_spans=edge.evidence_spans,
                        defect_category=DefectCategory.UNGROUNDED_TRANSITION,
                        claimed_statement=f"Transition {edge.source_node_id} -> {edge.target_node_id}",
                        evidence_text="",
                        rationale="Transition pruned because incident node was excluded",
                        confidence=0.0
                    ))
            verified_edges = surviving_edges

        # 6. Construct GroundedProcessGraph AST
        actors_dict: Dict[str, ProcessActor] = {}
        activities: List[ProcessActivity] = []
        gateways: List[ProcessGateway] = []
        events: List[ProcessEvent] = []
        transitions: List[ProcessTransition] = []

        # Build AST Nodes
        for node in verified_nodes.values():
            raw_actor = (node.actor or "").strip()
            is_start_end = node.node_type in ("start_event", "end_event")
            is_spurious_actor = raw_actor.lower() in ("start", "end", "unassigned", "")

            if raw_actor and not (is_start_end and is_spurious_actor):
                canonical_actor = canonical_actors_map.get(raw_actor.lower(), raw_actor)
                actor_id = f"ACTOR_{re.sub(r'[^a-zA-Z0-9]', '_', canonical_actor.upper())}"
                if actor_id not in actors_dict:
                    actors_dict[actor_id] = ProcessActor(
                        id=actor_id,
                        name=canonical_actor,
                        evidence=list(set(node.evidence_spans))
                    )
                else:
                    actors_dict[actor_id].evidence = list(set(actors_dict[actor_id].evidence + node.evidence_spans))
            else:
                actor_id = "ACTOR_UNASSIGNED"
                if not is_start_end and actor_id not in actors_dict:
                    actors_dict[actor_id] = ProcessActor(
                        id=actor_id,
                        name="Unassigned",
                        evidence=[]
                    )

            if node.node_type == "start_event":
                actor_id_for_event = actor_id if (raw_actor and not is_spurious_actor) else None
                events.append(ProcessEvent(
                    id=node.node_id,
                    type="start",
                    label=node.label,
                    evidence=node.evidence_spans,
                    actor_id=actor_id_for_event
                ))
            elif node.node_type == "end_event":
                actor_id_for_event = actor_id if (raw_actor and not is_spurious_actor) else None
                events.append(ProcessEvent(
                    id=node.node_id,
                    type="end",
                    label=node.label,
                    evidence=node.evidence_spans,
                    actor_id=actor_id_for_event
                ))
            elif node.node_type == "intermediate_event":
                events.append(ProcessEvent(
                    id=node.node_id,
                    type="intermediate",
                    label=node.label,
                    evidence=node.evidence_spans,
                    actor_id=actor_id if (raw_actor and not is_spurious_actor) else None
                ))
            elif node.node_type == "decision":
                gateways.append(ProcessGateway(
                    id=node.node_id,
                    question=node.label,
                    gateway_type="exclusive",
                    evidence=node.evidence_spans,
                    actor_id=actor_id if raw_actor else None
                ))
            else:  # activity
                activities.append(ProcessActivity(
                    id=node.node_id,
                    actor_id=actor_id,
                    label=node.label,
                    description=node.description,
                    evidence=node.evidence_spans,
                    temporal_order=len(activities) + 1
                ))

        # Build AST Transitions directly from verified edges (1:1 preservation of topology)
        for edge in verified_edges:
            lbl = edge.condition
            if edge.trigger_type == "timeout" and edge.condition and "timeout" not in edge.condition.lower():
                lbl = f"Timeout: {edge.condition}"
            transitions.append(ProcessTransition(
                id=edge.edge_id or f"TRANS_{edge.source_node_id}_{edge.target_node_id}",
                from_id=edge.source_node_id,
                to_id=edge.target_node_id,
                relation=edge.relation,
                label=lbl,
                condition=edge.condition,
                trigger_type=edge.trigger_type,
                evidence=edge.evidence_spans,
                source_proposition_ids=edge.source_proposition_ids,
                is_loop=(edge.relation == ProcessRelationType.LOOP_BACK),
                is_exception=(edge.relation == ProcessRelationType.ESCALATES_TO)
            ))

        start_event_ids = [ev.id for ev in events if ev.type == "start"]
        terminal_event_ids = [ev.id for ev in events if ev.type == "end"]
        graph = GroundedProcessGraph(
            process_name=process_name,
            objective=objective,
            events=events,
            actors=list(actors_dict.values()),
            activities=activities,
            gateways=gateways,
            transitions=transitions,
            start_event_ids=start_event_ids,
            terminal_event_ids=terminal_event_ids,
        )

        # Post-compilation structural integrity check via NetworkX
        self._final_graph_integrity_check(graph, defects)

        # Decoupled Proposition Accounting (Strict Partition Identity)
        if propositions:
            total_props = len(propositions)
            props_supp = sum(
                1 for p in propositions
                if verdicts.get(p.id) and verdicts[p.id].verdict == GroundingVerdict.SUPPORTED and verdicts[p.id].is_verified
            )
            props_unc = sum(
                1 for p in propositions
                if verdicts.get(p.id) and verdicts[p.id].verdict == GroundingVerdict.UNCERTAIN
            )
            props_unsupp = sum(
                1 for p in propositions
                if verdicts.get(p.id) and verdicts[p.id].verdict == GroundingVerdict.UNSUPPORTED
            )
            props_miss = total_props - (props_supp + props_unc + props_unsupp)
        elif verdicts:
            total_props = len(verdicts)
            props_supp = sum(
                1 for v in verdicts.values()
                if v.verdict == GroundingVerdict.SUPPORTED and v.is_verified
            )
            props_unc = sum(
                1 for v in verdicts.values()
                if v.verdict == GroundingVerdict.UNCERTAIN
            )
            props_unsupp = sum(
                1 for v in verdicts.values()
                if v.verdict == GroundingVerdict.UNSUPPORTED
            )
            props_miss = total_props - (props_supp + props_unc + props_unsupp)
        else:
            total_props = 0
            props_supp = 0
            props_unc = 0
            props_unsupp = 0
            props_miss = 0

        # Graph AST Topology Accounting
        total_nodes_gen = len(canonical_model.nodes)
        total_nodes_ver = len(verified_nodes)
        total_nodes_quar = total_nodes_gen - total_nodes_ver

        total_edges_gen = len(canonical_model.edges)
        total_edges_ver = len(verified_edges)
        total_edges_quar = total_edges_gen - total_edges_ver

        # Process Integrity Status Evaluation
        start_nodes = [nid for nid, n in verified_nodes.items() if n.node_type == "start_event" or nid.upper() == "START"]
        start_has_outgoing = any(e.source_node_id in start_nodes for e in verified_edges) if start_nodes else True

        if has_explicit_start and (not start_nodes or not start_has_outgoing):
            process_status = "REJECTED"
        elif not any(n.node_type == "activity" for n in verified_nodes.values()) and total_nodes_gen > 0:
            process_status = "REJECTED"
        elif any(d.defect_category in (DefectCategory.DEPENDENCY_BLOCKED, DefectCategory.INVALID_TERMINAL_TOPOLOGY) for d in defects):
            process_status = "STRUCTURALLY_DEGRADED"
        elif total_nodes_quar > 0 or total_edges_quar > 0:
            process_status = "STRUCTURALLY_DEGRADED"
        else:
            process_status = "VERIFIED"

        defect_register = AmbiguityRegister(
            document_name=document_name,
            total_propositions_extracted=total_props,
            propositions_supported=props_supp,
            propositions_uncertain=props_unc,
            propositions_unsupported=props_unsupp,
            propositions_missing=props_miss,
            total_nodes_generated=total_nodes_gen,
            total_nodes_verified=total_nodes_ver,
            total_nodes_quarantined=total_nodes_quar,
            total_edges_generated=total_edges_gen,
            total_edges_verified=total_edges_ver,
            total_edges_quarantined=total_edges_quar,
            process_integrity_status=process_status,
            total_verified=total_nodes_ver,
            total_rejected=len(defects),
            defects=defects
        )

        return DualOutputResult(
            graph=graph,
            defect_register=defect_register
        )

    def _final_graph_integrity_check(self, graph: GroundedProcessGraph, defects: List[DefectRecord]) -> None:
        """Post-compilation structural integrity check using NetworkX graph algorithms."""
        import networkx as nx

        G = nx.MultiDiGraph()
        all_node_ids = set()

        for ev in graph.events:
            G.add_node(ev.id, type=ev.type)
            all_node_ids.add(ev.id)
        for act in graph.activities:
            G.add_node(act.id, type="activity")
            all_node_ids.add(act.id)
        for gw in graph.gateways:
            G.add_node(gw.id, type="gateway")
            all_node_ids.add(gw.id)

        for tr in graph.transitions:
            if tr.from_id in all_node_ids and tr.to_id in all_node_ids:
                G.add_edge(tr.from_id, tr.to_id, key=tr.id)

        # 1. Reachability from start
        for sid in graph.start_event_ids:
            if sid in G:
                reachable = nx.descendants(G, sid) | {sid}
                orphans = all_node_ids - reachable
                for orphan in orphans:
                    if orphan not in graph.start_event_ids:
                        if not any(d.proposition_id == orphan and d.defect_category == DefectCategory.STRUCTURALLY_UNRESOLVED for d in defects):
                            defects.append(DefectRecord(
                                proposition_id=orphan,
                                evidence_spans=[],
                                defect_category=DefectCategory.STRUCTURALLY_UNRESOLVED,
                                claimed_statement=f"Node '{orphan}' unreachable from START",
                                evidence_text="",
                                rationale=f"Post-compilation check: node not reachable from start event '{sid}'",
                                confidence=0.0
                            ))

        # 2. Dead-end activities (0 out-degree, not end events)
        for nid in all_node_ids:
            node_type = G.nodes[nid].get("type")
            if node_type not in ("end",) and G.out_degree(nid) == 0:
                if not any(d.proposition_id == nid and d.defect_category == DefectCategory.INVALID_TERMINAL_TOPOLOGY for d in defects):
                    defects.append(DefectRecord(
                        proposition_id=nid,
                        evidence_spans=[],
                        defect_category=DefectCategory.INVALID_TERMINAL_TOPOLOGY,
                        claimed_statement=f"Node '{nid}' is a dead-end with no outgoing transitions",
                        evidence_text="",
                        rationale="Post-compilation: non-terminal node has zero outgoing edges",
                        confidence=0.0
                    ))

        # 3. Gateway validation: out-degree check
        for gw in graph.gateways:
            out_degree = G.out_degree(gw.id)
            if out_degree < 2:
                if not any(d.proposition_id == gw.id and d.defect_category == DefectCategory.STRUCTURALLY_UNRESOLVED for d in defects):
                    defects.append(DefectRecord(
                        proposition_id=gw.id,
                        evidence_spans=gw.evidence,
                        defect_category=DefectCategory.STRUCTURALLY_UNRESOLVED,
                        claimed_statement=f"Gateway '{gw.id}' has only {out_degree} outgoing edge(s)",
                        evidence_text="",
                        rationale="Decision gateways should have at least 2 outgoing branches",
                        confidence=0.3
                    ))

    def _compile_from_propositions(
        self,
        document_name: str,
        process_name: str,
        objective: str,
        propositions: List[AtomicProposition],
        verdicts: Dict[str, LayaVerdict],
        span_registry: SpanRegistry
    ) -> DualOutputResult:
        """
        Backward-compatible compilation for unit tests passing mock propositions.
        """
        verified_props: List[AtomicProposition] = []
        defects: List[DefectRecord] = []

        for prop in propositions:
            verdict = verdicts.get(prop.id)
            if not verdict or not verdict.is_verified:
                cat = DefectCategory.LOW_CONFIDENCE if not verdict else (
                    DefectCategory.UNGROUNDED_ROLE if not verdict.actor_grounded else DefectCategory.ACTION_UNENTAILED
                )
                defects.append(DefectRecord(
                    proposition_id=prop.id,
                    evidence_spans=prop.evidence_spans,
                    defect_category=cat,
                    claimed_statement=f"{prop.actor_claim} {prop.action_verb} {prop.target_object}",
                    evidence_text="",
                    rationale="; ".join(verdict.rejection_reasons) if verdict and verdict.rejection_reasons else "Failed verification",
                    confidence=0.0,
                    actor_involved=prop.actor_claim
                ))
                continue
            verified_props.append(prop)

        # Assemble basic sequential AST
        actors_dict: Dict[str, ProcessActor] = {}
        activities: List[ProcessActivity] = []
        transitions: List[ProcessTransition] = []

        for idx, prop in enumerate(verified_props, 1):
            role_id = f"ACTOR_{re.sub(r'[^a-zA-Z0-9]', '_', prop.actor_claim.upper())}"
            if role_id not in actors_dict:
                actors_dict[role_id] = ProcessActor(id=role_id, name=prop.actor_claim, evidence=prop.evidence_spans)

            act_id = f"ACT_{idx:03d}"
            activities.append(ProcessActivity(
                id=act_id,
                actor_id=role_id,
                label=f"{prop.action_verb.capitalize()} {prop.target_object}",
                description=f"{prop.actor_claim} {prop.action_verb} {prop.target_object}",
                evidence=prop.evidence_spans,
                temporal_order=idx
            ))
            if idx > 1:
                transitions.append(ProcessTransition(from_id=activities[idx - 2].id, to_id=act_id))

        graph = GroundedProcessGraph(
            process_name=process_name,
            objective=objective,
            events=[ProcessEvent(id="START", type="start", label="Start", evidence=["S001"])],
            actors=list(actors_dict.values()),
            activities=activities,
            gateways=[],
            transitions=transitions
        )

        total_props = len(propositions)
        props_supp = sum(
            1 for p in propositions
            if verdicts.get(p.id) and verdicts[p.id].verdict == GroundingVerdict.SUPPORTED and verdicts[p.id].is_verified
        )
        props_unc = sum(
            1 for p in propositions
            if verdicts.get(p.id) and verdicts[p.id].verdict == GroundingVerdict.UNCERTAIN
        )
        props_unsupp = sum(
            1 for p in propositions
            if verdicts.get(p.id) and verdicts[p.id].verdict == GroundingVerdict.UNSUPPORTED
        )
        props_miss = total_props - (props_supp + props_unc + props_unsupp)

        return DualOutputResult(
            graph=graph,
            defect_register=AmbiguityRegister(
                document_name=document_name,
                total_propositions_extracted=total_props,
                propositions_supported=props_supp,
                propositions_uncertain=props_unc,
                propositions_unsupported=props_unsupp,
                propositions_missing=props_miss,
                total_nodes_generated=len(activities) + 1,
                total_nodes_verified=len(activities) + 1,
                total_nodes_quarantined=0,
                total_edges_generated=len(transitions),
                total_edges_verified=len(transitions),
                total_edges_quarantined=0,
                process_integrity_status="VERIFIED" if not defects else "STRUCTURALLY_DEGRADED",
                total_verified=len(verified_props),
                total_rejected=len(defects),
                defects=defects
            )
        )
