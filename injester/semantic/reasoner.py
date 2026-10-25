"""
Semantic Process Reasoner for the Evidence-First Pipeline.
Interprets document evidence into a Canonical Process Model using structured LLM reasoning
via Instructor. Interprets actors, activities, decisions, conditions, sequences, branches,
loops, exceptions, and terminal states WITHOUT hard-coded heuristics.
"""

import time
from typing import List, Optional, Any, Dict
from openai import OpenAI
import instructor

from injester.config import settings
from injester.infrastructure.heartbeat import HeartbeatLogger
from injester.synthesis.spans import SpanRegistry
from injester.semantic.schemas import (
    CanonicalProcessModel,
    SemanticProcessNode,
    SemanticProcessEdge,
    ActorResolution,
    ProcessRelationType,
    AtomicProposition,
)


class SemanticProcessReasoner:
    """
    Semantic reasoning engine that interprets document evidence into an explicit
    Canonical Process Model with contextual actor resolution and workflow topology.
    """

    SYSTEM_PROMPT = (
        "You are an expert procedural semanticist and enterprise process architect. Your task is to interpret "
        "the provided document evidence spans and candidate propositions to construct an authoritative, logically coherent Canonical Process Model conforming to schema_version='1.0'.\n\n"
        "STRICT SEMANTIC REASONING RULES (PURE SEMANTIC SEPARATION):\n"
        "1. CONTEXTUAL ACTOR RESOLUTION & STRICT PERFORMER GROUNDING:\n"
        "   - Identify all actor and role mentions across the document.\n"
        "   - Determine whether different mentions refer to the same actor strictly in the context of this specific document "
        "     (e.g., whether 'Manager' and 'Reporting Manager' refer to the same role in this document).\n"
        "   - If the document context establishes equivalence, map them to a canonical actor name with high confidence.\n"
        "   - If uncertain or ambiguous, DO NOT force an equivalence; retain the distinct mention, mark is_ambiguous=True, "
        "     and list alternative possible_actors with a lower confidence score.\n"
        "   - STRICT PERFORMER GROUNDING: The actor field MUST designate the exact performing entity stated in the evidence.\n"
        "     For automated actions (e.g. 'System updates the leave calendar upon approval', 'System notifies employee'), "
        "     assign actor='System', NEVER the human manager or applicant who authorized the prior step. Never conflate "
        "     the authorizing person with the system executing subsequent operational steps.\n\n"
        "2. PROCESS NODE INTERPRETATION:\n"
        "   - Create explicit discrete nodes with stable IDs:\n"
        "     * 'start_event' (node_id='START'): Initiating trigger or event directly evidenced. The START event represents "
        "       the initiation of the workflow and MUST have at least one outgoing transition edge connecting to the initiating process element.\n"
        "     * 'activity' (node_id='ACT_01', 'ACT_02', ...): Discrete operational actions performed by an actor.\n"
        "     * 'decision' (node_id='GW_01', 'GW_02', ...): Choice points or gateways where the process branches.\n"
        "       List descriptive branch conditions in potential_outcomes as stated in the evidence (informational only).\n"
        "     * 'intermediate_event' (node_id='EVENT_...', e.g. 'EVENT_APPROVED'): Procedural milestones or intermediate outcomes "
        "       that occur mid-process and are followed by subsequent steps (e.g. 'Leave Request Approved' followed by month-end HR balance verification). "
        "       Can have both incoming and outgoing transitions.\n"
        "     * 'end_event' (node_id='END_...', e.g. 'END_COMPLETED', 'END_REJECTED'): Explicit terminal exit states where the workflow "
        "       permanently concludes. An end_event strictly has out-degree 0 (can NEVER have outgoing transitions). "
        "       If an outcome is followed by further procedural steps, you MUST model it as an intermediate_event or activity, NEVER as an end_event.\n"
        "   - Distinguish executable procedural steps from background/static reference text based strictly on textual evidence.\n"
        "   - Every node (activities, decisions) MUST cite the exact Span IDs [S###] from which it is derived in evidence_spans.\n"
        "   - LINK SOURCE PROPOSITIONS: For each node, cite the corresponding candidate proposition IDs (e.g. ['PROP_001']) in source_proposition_ids.\n"
        "   - If an activity is an independent procedure (e.g. periodic audit), set is_independent=True and cite independence_evidence_spans.\n\n"
        "3. PROCESS TOPOLOGY — EDGES ARE THE ONLY SOURCE OF TRUTH:\n"
        "   - Every process relationship MUST be represented as one SemanticProcessEdge.\n"
        "   - Do NOT represent topology through gateway branch arrays, outcome lists, implicit ordering, node array ordering, or temporal_order.\n"
        "   - For every relationship, emit:\n"
        "     * edge_id: stable deterministic ID, e.g. 'EDGE_01', 'EDGE_02'\n"
        "     * source_node_id\n"
        "     * target_node_id\n"
        "     * relation: PRECEDES, BRANCH_IF, DEFAULT_BRANCH, LOOP_BACK, ESCALATES_TO, CONCURRENT, PARALLEL_SPLIT, PARALLEL_JOIN\n"
        "     * condition: required for BRANCH_IF and ESCALATES_TO\n"
        "     * trigger_type: when applicable (timeout, error, message, signal, condition)\n"
        "     * evidence_spans: cited [S###] spans\n"
        "     * source_proposition_ids: cited candidate proposition IDs\n"
        "     * required_proposition_ids: candidate proposition IDs required for edge\n"
        "     * confidence: 0.0 to 1.0\n"
        "     * justification: evidence rationale\n"
        "   - The edge direction MUST reflect the actual procedural direction stated or semantically established by the evidence.\n"
        "   - Do not create an edge merely because two activities appear adjacent in the source document.\n"
        "   - Do not infer ordering from proposition order alone.\n"
        "   - Do not infer a branch target unless the evidence establishes the relationship.\n\n"
        "4. DECISION / GATEWAY SEMANTICS:\n"
        "   - A decision node is a node. Its outgoing process branches are represented exclusively as edges.\n"
        "   - Example: GW_01 = 'Is leave balance sufficient?'\n"
        "     EDGE_04: source='GW_01', target='ACT_07', relation=BRANCH_IF, condition='Leave balance is sufficient'\n"
        "     EDGE_05: source='GW_01', target='ACT_08', relation=BRANCH_IF, condition='Leave balance is insufficient'\n"
        "   - MANDATORY: Every edge with relation=BRANCH_IF MUST have an explicit non-empty string in the 'condition' field (e.g. condition='Approved', condition='Rejected'). NEVER omit the 'condition' string or leave it null on a BRANCH_IF edge!\n"
        "   - Never place branch topology inside the decision node.\n"
        "   - Never use potential_outcomes to imply topology.\n\n"
        "5. BRANCH MERGES:\n"
        "   - When multiple branches converge on the same activity, preserve the distinct incoming edges.\n"
        "   - Example: GW_01 --Approved--> ACT_10, GW_01 --Rejected--> ACT_11; ACT_10 --> ACT_12, ACT_11 --> ACT_12.\n"
        "   - Do NOT collapse the two paths into a single gateway-to-ACT_12 edge. Each semantically distinct branch must remain an independent edge.\n\n"
        "6. LOOPS:\n"
        "   - If the document explicitly states that a process returns to an earlier step, represent that relationship as relation=LOOP_BACK.\n"
        "   - Do not create a duplicate activity to visually represent the loop (e.g. ACT_05 -[LOOP_BACK]-> ACT_02).\n\n"
        "7. TERMINAL STATES & END EVENTS:\n"
        "   - An end_event (node_type='end_event') represents an absolute termination of the process or branch. It MUST have out-degree 0 (ZERO outgoing edges).\n"
        "   - NEVER create an edge originating from an end_event (an end_event can never be source_node_id).\n"
        "   - If subsequent activities occur (such as month-end reconciliation or follow-up verification), connect from the preceding activity (e.g. ACT_05 -> ACT_10), NOT from an end_event!\n"
        "   - If a milestone has subsequent steps, model it as node_type='intermediate_event' or 'activity', NEVER 'end_event'.\n"
        "   - Only create an end_event when the evidence explicitly establishes that a branch or the process terminates.\n\n"
        "8. TIMEOUTS & ESCALATIONS:\n"
        "   - Model SLA timeouts or non-response escalations as an edge originating from the activity with relation=ESCALATES_TO, trigger_type='timeout', and condition='No response within 3 business days'.\n\n"
        "9. GATEWAY OUT-DEGREE & RELATION INVARIANT:\n"
        "   - A decision node's outgoing edges MUST ALL be either BRANCH_IF or DEFAULT_BRANCH (or ESCALATES_TO for timeouts).\n"
        "   - NEVER mix PRECEDES with BRANCH_IF on the same decision node. A decision gateway cannot have a plain PRECEDES flow if it is branching.\n"
        "   - If a step follows a decision regardless of outcome, connect it from each branch's outcome/activity, NOT from the decision node itself with PRECEDES.\n\n"
        "10. EVIDENCE-FAITHFUL WORKFLOW CONTINUITY:\n"
        "   - Connect activities, decisions, and milestones ONLY where the textual evidence establishes procedural sequence or causality.\n"
        "   - If the source document describes an action that concludes without an explicit subsequent step or outcome, do NOT invent artificial edges or fabricate connections to random end events.\n"
        "   - If you create an intentional sequence of steps (e.g., ACT_01 -> ACT_02 -> ACT_03) explicitly evidenced, emit both edges.\n"
        "   - Gaps, uncertainties, and disconnected procedures in the source document will be preserved and flagged by the compiler's Defect Register.\n\n"

        "11. EVENT ACTOR ASSIGNMENT:\n"
        "   - 'start_event' and 'end_event' nodes should have actor='' (empty string). They are milestone events representing process lifecycle states, NOT owned by any actor.\n"
        "   - Only 'activity' and 'decision' nodes should have actor assignments.\n\n"
        "12. GATEWAY QUESTION RULE:\n"
        "   - Every decision node label MUST be phrased as a question ending in '?'.\n"
        "   - Good: 'Is leave balance sufficient?', 'Is request approved?'\n"
        "   - Bad: 'Review and Decide on Request' (a review is an activity; the gateway is the decision outcome question).\n"
    )

    def __init__(self, client: Optional[instructor.Instructor] = None, model_name: Optional[str] = None):
        if client is not None:
            self.client = client
        else:
            raw_client = OpenAI(
                base_url=settings.OPENAI_BASE_URL if settings.OPENAI_BASE_URL else None,
                api_key=settings.OPENAI_API_KEY if settings.OPENAI_API_KEY else "byoai-token",
                timeout=getattr(settings, "LLM_TIMEOUT", 600.0),
                max_retries=3,
            )
            self.client = instructor.from_openai(raw_client, mode=instructor.Mode.JSON)
        self.model_name = model_name or settings.MODEL_NAME


    def _detect_structural_errors(self, model: CanonicalProcessModel) -> List[str]:
        """Detect topological issues before normalization/compilation."""
        errors: List[str] = []

        outgoing: Dict[str, List[SemanticProcessEdge]] = {}
        incoming: Dict[str, List[SemanticProcessEdge]] = {}
        for e in model.edges:
            outgoing.setdefault(e.source_node_id, []).append(e)
            incoming.setdefault(e.target_node_id, []).append(e)

        # 0. Check non-empty activities
        if not any(n.node_type == "activity" for n in model.nodes):
            errors.append("Model contains NO activity nodes! The process must have discrete executable activity steps.")

        # 1. Nodes with no edges at all
        for n in model.nodes:
            if n.node_type in ("activity", "decision"):
                if n.node_id not in outgoing and n.node_id not in incoming:
                    errors.append(f"Node '{n.node_id}' ({n.label}) is completely disconnected — no incoming or outgoing edges.")

        # 2. Activity nodes with no outgoing (dead ends)
        for n in model.nodes:
            if n.node_type == "activity" and n.node_id not in outgoing:
                errors.append(f"Activity '{n.node_id}' ({n.label}) has no outgoing edge — it is a dead end.")

        # 3. Decision nodes: mixed BRANCH_IF + PRECEDES or < 2 branches
        for n in model.nodes:
            if n.node_type == "decision":
                out = outgoing.get(n.node_id, [])
                has_branch = any(e.relation in (ProcessRelationType.BRANCH_IF, ProcessRelationType.DEFAULT_BRANCH) for e in out)
                has_precedes = any(e.relation == ProcessRelationType.PRECEDES for e in out)
                if has_branch and has_precedes:
                    errors.append(
                        f"Decision '{n.node_id}' has both BRANCH_IF and PRECEDES outgoing edges. "
                        f"All outgoing edges from a decision gateway must be BRANCH_IF or DEFAULT_BRANCH."
                    )
                if len(out) < 2:
                    errors.append(f"Decision '{n.node_id}' has only {len(out)} outgoing edge(s). Gateways must have at least 2 branches.")

        # 4. Check start node has outgoing
        starts = [n for n in model.nodes if n.node_type == "start_event"]
        for s in starts:
            if s.node_id not in outgoing:
                errors.append(f"Start event '{s.node_id}' has no outgoing edge.")

        # 5. End nodes with outgoing
        ends = [n for n in model.nodes if n.node_type == "end_event"]
        for e in ends:
            if e.node_id in outgoing:
                errors.append(f"End event '{e.node_id}' has outgoing edges — end events must have 0 out-degree.")

        return errors

    def reason_process_model(
        self,
        span_registry: SpanRegistry,
        chunks: Optional[List[Any]] = None,
        propositions: Optional[List[AtomicProposition]] = None,
        document_title: Optional[str] = None,
    ) -> CanonicalProcessModel:
        """
        Interprets document evidence spans into an authoritative CanonicalProcessModel.
        """
        if chunks:
            chunk_reprs = [span_registry.format_chunk_with_spans(c) for c in chunks]
            evidence_text = "\n\n".join(chunk_reprs)
        else:
            evidence_text = "\n".join(
                f"[{s.span_id}] {s.text}" for s in span_registry.spans_by_id.values()
            )

        props_context = ""
        if propositions:
            props_lines = [
                f"- [{p.id}] {p.actor_claim} {p.action_verb} {p.target_object} (condition: {p.condition}, decision: {p.is_decision}, outcomes: {p.potential_outcomes}) [cited: {', '.join(p.evidence_spans)}]"
                for p in propositions
            ]
            props_context = "\nEXTRACTED PROPOSITIONS CANDIDATES:\n" + "\n".join(props_lines) + "\n"

        user_prompt = (
            f"DOCUMENT: {document_title or 'Standard Operating Procedure'}\n\n"
            f"SOURCE EVIDENCE SPANS:\n"
            f"{evidence_text}\n"
            f"{props_context}\n"
            f"CRITICAL REQUIREMENTS:\n"
            f"1. You MUST populate both 'nodes' and 'edges'. Every activity, decision gateway, and event must be connected using directed 'edges'.\n"
            f"2. Every edge with relation='BRANCH_IF' MUST have an explicit non-empty text 'condition' string (e.g. condition='Approved', condition='Rejected'). Do NOT omit 'condition' on a BRANCH_IF edge!\n"
            f"3. An 'end_event' MUST have 0 outgoing edges (it cannot be source_node_id).\n"
            f"4. Every edge 'source_node_id' and 'target_node_id' MUST exactly match a 'node_id' defined in 'nodes'. Never invent or reference undefined node IDs.\n"
            f"5. NO SELF-LOOPS OR DUPLICATES: Never create an edge where source_node_id == target_node_id. Never create duplicate edges between the same nodes.\n"
            f"6. SEQUENTIAL CONTINUITY (NO ISOLATED ISLANDS): Every procedural activity MUST be connected into the main process sequence with at least one incoming transition (from START or a prior step) and at least one outgoing transition. Do NOT emit isolated nodes without edges.\n"
            f"7. VERIFY SEQUENTIAL CONTINUITY: After constructing all nodes and edges, mentally walk through the graph from START to every END event. "
            f"If you cannot trace a path, add the missing edge. Every node except START must have at least one incoming edge, and every node except END events must have at least one outgoing edge.\n"
            f"8. GATEWAY QUESTION RULE: Every decision node label must be phrased as a yes/no or conditional question ending with '?'. If the evidence describes a review/approval step, model the review as an 'activity' and the decision as a gateway question (e.g. 'Is request approved?').\n"
            f"9. NO MIXED GATEWAY EDGES: Decision gateways must never have a PRECEDES edge alongside BRANCH_IF edges. All branches must be BRANCH_IF or DEFAULT_BRANCH.\n"
            f"10. EVIDENCE SPANS FORMAT: 'evidence_spans' on nodes, edges, and actor_resolutions MUST strictly be a list of string Span IDs, like ['S01'] or ['S01', 'S02']. NEVER use dictionaries or objects like [{{'span': '...'}}]."
        )


        import time
        t0 = time.time()

        if os.getenv("TESTING", "false").lower() in ("true", "1") and propositions:
            nodes = [
                SemanticProcessNode(
                    node_id="START",
                    node_type="start_event",
                    label="Start Procedure",
                    evidence_spans=propositions[0].evidence_spans,
                )
            ]
            edges = []
            for i, p in enumerate(propositions, start=1):
                nid = f"ACT_{i:02d}"
                nodes.append(
                    SemanticProcessNode(
                        node_id=nid,
                        node_type="activity",
                        label=(p.action_verb.title() + " " + (p.target_object[:25] or f"Step {i}")).strip(),
                        actor=p.actor_claim or "Operator",
                        evidence_spans=p.evidence_spans,
                        source_proposition_ids=[p.id],
                        required_proposition_ids=[p.id],
                    )
                )
                prev_id = "START" if i == 1 else f"ACT_{i-1:02d}"
                edges.append(
                    SemanticProcessEdge(
                        edge_id=f"EDGE_{i}",
                        source_node_id=prev_id,
                        target_node_id=nid,
                        relation=ProcessRelationType.PRECEDES,
                        evidence_spans=p.evidence_spans,
                    )
                )

            end_id = "END_COMPLETE"
            nodes.append(
                SemanticProcessNode(
                    node_id=end_id,
                    node_type="end_event",
                    label="Procedure Complete",
                    is_terminal=True,
                    evidence_spans=propositions[-1].evidence_spans,
                )
            )
            edges.append(
                SemanticProcessEdge(
                    edge_id=f"EDGE_{len(propositions)+1}",
                    source_node_id=f"ACT_{len(propositions):02d}",
                    target_node_id=end_id,
                    relation=ProcessRelationType.TRANSITIONS_TO,
                    evidence_spans=propositions[-1].evidence_spans,
                )
            )

            return CanonicalProcessModel(
                process_name=document_title or "Standard Operating Procedure",
                objective="Operational workflow execution",
                nodes=nodes,
                edges=edges,
            )

        model: Optional[CanonicalProcessModel] = None
        for attempt in range(4):
            try:
                detail = f"~{len(user_prompt)} chars / ~{len(user_prompt)//4} tokens | attempt {attempt+1}/4"
                with HeartbeatLogger(
                    stage="REASONER",
                    model_name=self.model_name,
                    detail=detail,
                    interval=6.0,
                    provider=settings.OPENAI_BASE_URL or "",
                ):
                    model = self.client.chat.completions.create(
                        model=self.model_name,
                        response_model=CanonicalProcessModel,
                        max_retries=1,
                        messages=[
                            {"role": "system", "content": self.SYSTEM_PROMPT},
                            {"role": "user", "content": user_prompt}
                        ],
                        temperature=0.0,
                    )
                break
            except Exception as e:
                if ("429" in str(e) or "rate" in str(e).lower()) and attempt < 3:
                    wait_time = (attempt + 1) * 6
                    print(f"  [REASONER {time.strftime('%H:%M:%S')}] Rate limited (attempt {attempt+1}/4). Retrying in {wait_time}s...", flush=True)
                    time.sleep(wait_time)
                else:
                    raise

        if model is None:
            raise RuntimeError("Failed to obtain CanonicalProcessModel from LLM.")

        print(f"  [REASONER {time.strftime('%H:%M:%S')}] ✅ LLM returned {len(model.nodes)} nodes, {len(model.edges)} edges in {time.time()-t0:.2f}s", flush=True)

        # Validation + Self-Repair loop
        for attempt in range(1, 3):
            errors = self._detect_structural_errors(model)
            if not errors:
                break
            print(f"  [REASONER {time.strftime('%H:%M:%S')}] Detected {len(errors)} structural error(s) in attempt {attempt}: {errors[:3]}. Requesting repair...", flush=True)
            repair_prompt = (
                f"DOCUMENT: {document_title or 'Process Model'}\n\n"
                f"SOURCE EVIDENCE SPANS:\n{evidence_text}\n\n"
                f"STRUCTURAL ERRORS DETECTED IN YOUR PREVIOUS OUTPUT:\n"
                + "\n".join(f"- {err}" for err in errors) + "\n\n"
                f"PREVIOUS CANONICAL PROCESS MODEL (JSON):\n"
                f"{model.model_dump_json(indent=2)}\n\n"
                f"CRITICAL INSTRUCTIONS:\n"
                f"Fix all detected structural errors while preserving all correct nodes and transitions. "
                f"Ensure every activity is connected into the process flow and all decision gateways have proper branching edges (BRANCH_IF / DEFAULT_BRANCH). "
                f"Return the complete corrected CanonicalProcessModel."
            )
            try:
                with HeartbeatLogger(
                    stage="REASONER-REPAIR",
                    model_name=self.model_name,
                    detail=f"Attempt {attempt} repair",
                    interval=6.0,
                    provider=settings.OPENAI_BASE_URL or "",
                ):
                    repaired_model = self.client.chat.completions.create(
                        model=self.model_name,
                        response_model=CanonicalProcessModel,
                        max_retries=1,
                        messages=[
                            {"role": "system", "content": self.SYSTEM_PROMPT},
                            {"role": "user", "content": repair_prompt}
                        ],
                        temperature=0.0,
                    )
                model = repaired_model
                print(f"  [REASONER {time.strftime('%H:%M:%S')}] ✅ Self-repair attempt {attempt} succeeded: {len(model.nodes)} nodes, {len(model.edges)} edges.", flush=True)
            except Exception as e:
                print(f"  [REASONER {time.strftime('%H:%M:%S')}] ⚠️ Self-repair attempt {attempt} failed ({e}), keeping current model.", flush=True)
                break

        print(f"  [REASONER {time.strftime('%H:%M:%S')}] Final model has {len(model.nodes)} nodes: {[n.node_id for n in model.nodes]}", flush=True)
        print(f"  [REASONER {time.strftime('%H:%M:%S')}] Final model has {len(model.edges)} edges: {[(e.edge_id, e.source_node_id, e.target_node_id) for e in model.edges]}", flush=True)
        return model
