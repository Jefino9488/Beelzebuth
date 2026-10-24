"""
Grounded Semantic Schemas for the Evidence-First Process Pipeline.
Defines immutable atomic propositions, typed Laya verdicts, Defect Register, and Grounded Semantic IR.
"""

import re
from enum import Enum
from typing import List, Dict, Optional, Literal, Any, Union
from pydantic import BaseModel, Field, model_validator, field_validator, ConfigDict


def _normalize_span_list(v: Any) -> List[str]:
    """Normalizes evidence spans to a list of strings, handling dictionaries or scalars gracefully."""
    if isinstance(v, list):
        normalized = []
        for item in v:
            if isinstance(item, dict):
                val = item.get("span_id") or item.get("id") or item.get("span") or item.get("text") or ""
                if isinstance(val, str):
                    m = re.search(r"\bS\d+\b", val, re.IGNORECASE)
                    if m:
                        normalized.append(m.group(0).upper())
                    elif val.strip():
                        normalized.append(val.strip())
                    else:
                        normalized.append(str(item))
                else:
                    normalized.append(str(val))
            elif isinstance(item, str):
                m = re.search(r"\bS\d+\b", item, re.IGNORECASE)
                normalized.append(item.strip())
            elif item is not None:
                normalized.append(str(item))
        return normalized
    elif isinstance(v, str):
        return [v.strip()]
    elif v is None:
        return []
    return v



class ModalityType(str, Enum):
    MANDATORY = "mandatory"       # must, shall, required to, mandatory, strictly
    PERMISSIVE = "permissive"     # may, can, optional, at discretion, permitted to
    TYPICAL = "typical"           # normally, typically, usually, generally, standardly
    UNSTATED = "unstated"         # neutral action statement with no explicit modal operator


class EpistemicStatus(str, Enum):
    CONFIRMED = "confirmed"       # is, was, verified, proven, established
    TENTATIVE = "tentative"       # appears, seems, believed, alleged, presumed
    ABSENT_RECORD = "unrecorded"  # not recorded, unverified, does not state, no statement


class TemporalConnective(str, Enum):
    SEQUENTIAL = "sequential"     # then, after, subsequently, upon completion
    CONCURRENT = "concurrent"     # simultaneously, in parallel, while
    CONDITIONAL = "conditional"   # if, provided that, in case of, subject to
    LOOP_EXCEPTION = "loop_exception" # retry, return, re-evaluate, escalate, waiver
    UNSPECIFIED = "unspecified"   # standalone assertion without explicit connective


# =====================================================================
# 1. ATOMIC SEMANTIC PROPOSITIONS
# =====================================================================

class AtomicProposition(BaseModel):
    """
    Fine-grained semantic assertion extracted directly from source evidence spans.
    Represents an atomic procedural fact without forcing full macro-graph interpretation.
    """
    id: str = Field(description="Unique proposition ID, e.g. 'PROP_001'")
    evidence_spans: List[str] = Field(description="Exact span IDs cited as evidence, e.g. ['S002']")
    actor_claim: str = Field(default="", description="Actor verbatim or designated in text, e.g. 'AP' or 'Raj' or 'System'")
    action_verb: str = Field(default="", description="Core action predicate, e.g. 'verifies', 'approves', 'puts on hold'")
    target_object: str = Field(default="", description="Direct object or scope, e.g. 'three-way invoice match', 'payment'")
    condition: Optional[str] = Field(default=None, description="Explicit precondition, e.g. 'if invoice > 10000'")
    modality: ModalityType = Field(default=ModalityType.UNSTATED, description="Deontic modality asserted")
    epistemic_status: EpistemicStatus = Field(default=EpistemicStatus.CONFIRMED, description="Epistemic status")
    temporal_marker: Optional[str] = Field(default=None, description="Verbatim temporal text, e.g. 'after AP confirms'")
    connective: TemporalConnective = Field(default=TemporalConnective.UNSPECIFIED, description="Causal relationship")
    is_decision: bool = Field(default=False, description="True if proposition defines a branch point or choice")
    potential_outcomes: List[str] = Field(default_factory=list, description="Explicit stated outcomes if decision point")
    order_index: int = Field(default=0, description="Position index in source text sequence")

    @field_validator("actor_claim", "action_verb", "target_object", mode="before")
    @classmethod
    def validate_string_fields(cls, v: Any) -> str:
        if v is None:
            return ""
        return str(v)

    @field_validator("evidence_spans", mode="before")
    @classmethod
    def validate_spans(cls, v: Any) -> List[str]:
        return _normalize_span_list(v)


    @field_validator("condition", mode="before")
    @classmethod
    def validate_condition(cls, v: Any) -> Optional[str]:
        if isinstance(v, dict):
            return v.get("value") or v.get("text") or v.get("condition") or str(v)
        elif v is not None:
            return str(v)
        return None



class PropositionBatch(BaseModel):
    """Container for batch atomic proposition extraction from the strong LLM."""
    process_name: str = Field(default="Standard Operating Procedure", description="Name or title of the process")
    objective: str = Field(default="Operational process execution", description="High-level operational goal stated in the document")
    propositions: List[AtomicProposition] = Field(default_factory=list, description="Ordered list of extracted atomic propositions")


    @model_validator(mode="after")
    def validate_batch_size(self) -> "PropositionBatch":
        if len(self.propositions) < 3:
            raise ValueError(
                f"Extracted only {len(self.propositions)} propositions. "
                f"Please extract all procedural propositions thoroughly across all document sections."
            )
        return self


class GroundingVerdict(str, Enum):
    SUPPORTED = "SUPPORTED"
    UNCERTAIN = "UNCERTAIN"
    UNSUPPORTED = "UNSUPPORTED"


class ElementStatus(str, Enum):
    VERIFIED = "VERIFIED"          # Fully grounded in spans and structurally sound
    AMBIGUOUS = "AMBIGUOUS"        # Partially grounded or uncertain; retained with dependency note
    REJECTED = "REJECTED"          # Ungrounded, contradicting, or excluded from execution AST


# =====================================================================
# 2. SYSTEM-1 DECISION VERDICTS & RAW DECISIONS
# =====================================================================

class RawTypedDecisions(BaseModel):
    """
    Raw, unthresholded typed decisions returned by a System-1 model adapter
    (Laya, Jev, OpenJev). Keeps model adapters free of hard-coded policy logic.
    """
    actor_p: float = Field(default=0.5, ge=0.0, le=1.0, description="P(actor is grounded in evidence)")
    actor_confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    action_p: float = Field(default=0.5, ge=0.0, le=1.0, description="P(action is entailed by evidence)")
    action_confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    modality_choice: str = Field(default="unstated", description="Classified modality label")
    modality_confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    epistemic_choice: str = Field(default="confirmed", description="Classified epistemic label")
    epistemic_confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    outcomes_p: Optional[float] = Field(default=None, description="P(decision outcomes stated in evidence)")
    outcomes_confidence: Optional[float] = Field(default=None)
    raw_metadata: Dict[str, Any] = Field(default_factory=dict, description="Provider-specific raw response data")


class System1Verdict(BaseModel):
    """
    Typed, non-autoregressive verification verdict produced by a System-1 verifier (Jev, Laya, OpenJev).
    Carries explicit categorical grounding verdict and validation rationale per proposition.
    """
    proposition_id: str
    verdict: GroundingVerdict = Field(
        default=GroundingVerdict.UNSUPPORTED,
        description="Categorical grounding verdict: SUPPORTED, UNCERTAIN, UNSUPPORTED"
    )

    @model_validator(mode="before")
    @classmethod
    def set_default_verdict(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "verdict" not in data or data["verdict"] is None:
                if data.get("is_verified"):
                    data["verdict"] = GroundingVerdict.SUPPORTED
                else:
                    data["verdict"] = GroundingVerdict.UNSUPPORTED
        return data

    actor_grounded: bool = Field(description="Does the cited span support the claimed actor?")
    actor_confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    resolved_actor: Optional[str] = Field(default=None, description="Canonical resolved actor name")

    action_entailed: bool = Field(description="Is the claimed action-object pair asserted in the span?")
    action_confidence: float = Field(default=1.0, ge=0.0, le=1.0)

    modality_verified: ModalityType = Field(default=ModalityType.UNSTATED, description="Classified modality from evidence span")
    modality_confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    is_modality_escalated: bool = Field(default=False, description="True if claimed modality exceeds span evidence")

    epistemic_verified: EpistemicStatus = Field(default=EpistemicStatus.CONFIRMED, description="Classified epistemic certainty from span")
    epistemic_confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    is_epistemic_inverted: bool = Field(default=False, description="True if unrecorded fact is affirmed")

    outcome_stated: bool = Field(default=True, description="Are claimed decision outcomes explicitly in span?")
    outcome_confidence: float = Field(default=1.0, ge=0.0, le=1.0)

    is_verified: bool = Field(default=False, description="True if proposition satisfies configured policy threshold")
    rejection_reasons: List[str] = Field(default_factory=list, description="Exclusion rationales if rejected")
    provider: str = Field(default="system1", description="Provider identifier: jev, laya, openjev, structural")


# Backward-compatible alias for existing compiler, tests, and API code
LayaVerdict = System1Verdict


# =====================================================================
# 3. DEFECT & AMBIGUITY REGISTER (DUAL OUTPUT)
# =====================================================================

class DefectCategory(str, Enum):
    UNGROUNDED_ROLE = "UNGROUNDED_ROLE"
    AMBIGUOUS_ACTOR = "AMBIGUOUS_ACTOR"
    ACTION_UNENTAILED = "ACTION_UNENTAILED"
    UNGROUNDED_TRANSITION = "UNGROUNDED_TRANSITION"
    MODALITY_ESCALATION = "MODALITY_ESCALATION"
    NEGATIVE_RECORD_INVERSION = "NEGATIVE_RECORD_INVERSION"
    OUTCOME_HALLUCINATION = "OUTCOME_HALLUCINATION"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    NUMERICAL_DISCREPANCY = "NUMERICAL_DISCREPANCY"
    CONTRADICTION = "CONTRADICTION"
    UNVERIFIED_CLAIM = "UNVERIFIED_CLAIM"
    STRUCTURALLY_UNRESOLVED = "STRUCTURALLY_UNRESOLVED"
    DEPENDENCY_BLOCKED = "DEPENDENCY_BLOCKED"
    INVALID_TERMINAL_TOPOLOGY = "INVALID_TERMINAL_TOPOLOGY"


class ValidationPolicy(BaseModel):
    entailment_confidence_threshold: float = 0.70
    actor_confidence_threshold: float = 0.70
    ambiguity_floor: float = 0.50


class ProcessRelationType(str, Enum):
    PRECEDES = "PRECEDES"          # Direct sequential progression (source finishes, target begins)
    BRANCH_IF = "BRANCH_IF"        # Conditional path from a decision point
    DEFAULT_BRANCH = "DEFAULT_BRANCH"  # Default / else path from a decision point
    LOOP_BACK = "LOOP_BACK"        # Rework, retry, or iterative loop back to earlier activity
    ESCALATES_TO = "ESCALATES_TO"  # Escalation or exception handling path
    CONCURRENT = "CONCURRENT"      # Simultaneous / parallel path
    PARALLEL_SPLIT = "PARALLEL_SPLIT"  # Divergence to parallel paths
    PARALLEL_JOIN = "PARALLEL_JOIN"    # Convergence of parallel paths


class ActorResolution(BaseModel):
    """
    Contextual entity resolution of actor mentions within the document.
    Does not force equivalence when uncertain.
    """
    raw_mention: str = Field(description="Raw actor name/role mention from source text")
    canonical_actor: str = Field(description="Resolved canonical actor role in document context")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    is_ambiguous: bool = Field(default=False, description="True if evidence does not definitively equate raw mention with canonical role")
    possible_actors: List[str] = Field(default_factory=list, description="Alternative plausible actor interpretations if ambiguous")
    justification: Optional[str] = Field(default=None, description="Concise evidence justification grounded in text")
    evidence_spans: List[str] = Field(default_factory=list)

    @field_validator("evidence_spans", mode="before")
    @classmethod
    def validate_spans(cls, v: Any) -> List[str]:
        return _normalize_span_list(v)



class SemanticProcessEdge(BaseModel):
    """
    The sole semantic topology primitive.

    Every directed process relationship MUST be represented here.
    Gateways do not own branch topology. Branches are ordinary edges
    whose relation/condition expresses their semantics.
    """
    edge_id: str = Field(
        default="",
        description="Stable deterministic edge identifier, e.g. EDGE_01"
    )
    source_node_id: str = Field(description="Originating node ID (activity, decision gateway, or start event). NEVER use an end_event as source_node_id.")
    target_node_id: str = Field(description="Destination node ID (activity, gateway, or end event)")
    relation: ProcessRelationType = Field(default=ProcessRelationType.PRECEDES, description="Semantic nature of the transition")
    trigger_type: Optional[Literal["timeout", "error", "message", "signal", "condition"]] = Field(
        default=None,
        description="Explicit semantic trigger type when relation is ESCALATES_TO or conditional (e.g. timeout for SLA non-response)"
    )
    condition: Optional[str] = Field(
        default=None,
        description="Explicit guard condition. Required for BRANCH_IF. Never synthesized by validation or compilation."
    )
    evidence_spans: List[str] = Field(default_factory=list, description="Immutable span IDs supporting this transition")
    source_proposition_ids: List[str] = Field(default_factory=list, description="Candidate proposition IDs mapped to this transition")
    required_proposition_ids: List[str] = Field(default_factory=list, description="Mandatory proposition IDs required for verification")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    is_ambiguous: bool = Field(default=False)
    justification: Optional[str] = Field(default=None, description="Concise justification grounded in document evidence")
    status: ElementStatus = Field(default=ElementStatus.VERIFIED)

    @field_validator("evidence_spans", mode="before")
    @classmethod
    def validate_spans(cls, v: Any) -> List[str]:
        return _normalize_span_list(v)


    @model_validator(mode="after")
    def validate_edge_contract(self) -> "SemanticProcessEdge":
        if self.relation == ProcessRelationType.BRANCH_IF:
            if not self.condition or not self.condition.strip():
                raise ValueError(
                    f"Conditional edge '{self.edge_id}' requires an explicit condition (e.g. 'Approved', 'Rejected') grounded in evidence."
                )
        return self


class SemanticProcessNode(BaseModel):
    """
    Explicit, semantically interpreted process node.
    """
    node_id: str = Field(description="Deterministic node identifier, e.g. ACT_01, GW_01, START, END_APPROVED")
    node_type: Literal["activity", "decision", "start_event", "end_event", "intermediate_event"] = Field(
        description="Category of node. 'end_event' MUST have 0 outgoing edges (out-degree == 0). If a milestone has outgoing flows, use 'intermediate_event' or 'activity'."
    )
    actor: str = Field(default="", description="Resolved canonical actor responsible for node (or empty for events/unassigned)")
    label: str = Field(description="Concise verb-noun action, gateway question, or milestone label")
    description: str = Field(default="", description="Detailed factual description grounded in text")
    evidence_spans: List[str] = Field(default_factory=list, description="Span IDs [S###] providing evidence")
    source_proposition_ids: List[str] = Field(default_factory=list, description="Candidate proposition IDs mapped to this node")
    required_proposition_ids: List[str] = Field(default_factory=list, description="Mandatory proposition IDs required for verification")
    is_terminal: bool = Field(default=False, description="True if node represents an explicit terminal state/process exit (out-degree == 0)")
    potential_outcomes: List[str] = Field(
        default_factory=list,
        description=(
            "Optional descriptive list of branch conditions explicitly stated "
            "for this decision. This field is informational only; topology is "
            "represented exclusively by SemanticProcessEdge instances."
        )
    )
    is_independent: bool = Field(default=False, description="True if node represents an independently executable component")
    independence_evidence_spans: List[str] = Field(default_factory=list, description="Evidence spans justifying independent execution")
    status: ElementStatus = Field(default=ElementStatus.VERIFIED)

    @field_validator("evidence_spans", "independence_evidence_spans", mode="before")
    @classmethod
    def validate_node_spans(cls, v: Any) -> List[str]:
        return _normalize_span_list(v)


    @model_validator(mode="after")
    def validate_node_evidence(self) -> "SemanticProcessNode":
        if self.node_type == "end_event":
            self.is_terminal = True
        if self.node_type in ("activity", "decision") and not self.evidence_spans:
            raise ValueError(
                f"Node '{self.node_id}' ({self.label}) must cite at least one evidence span [S###]."
            )
        if self.is_independent and not self.independence_evidence_spans:
            raise ValueError(
                f"Node '{self.node_id}' is marked as independent but lacks independence_evidence_spans."
            )
        return self


class CanonicalProcessModel(BaseModel):
    """
    Contract between Semantic Process Reasoner and Deterministic Compiler/Renderers.
    Pure data schema without semantic inference or mutations.
    """
    schema_version: str = Field(default="1.0", description="Contract schema version for forward/backward compatibility")
    process_name: str = Field(default="Canonical Process Model")
    objective: str = Field(default="")
    nodes: List[SemanticProcessNode] = Field(default_factory=list)

    edges: List[SemanticProcessEdge] = Field(default_factory=list, description="All directed transitions and branches. Must contain edges connecting process nodes.")
    actor_resolutions: List[ActorResolution] = Field(default_factory=list)
    disconnected_node_ids: List[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_graph_invariants(self) -> "CanonicalProcessModel":
        # Disallow duplicate node IDs (reject instead of renaming)
        seen_nodes = set()
        for node in self.nodes:
            if node.node_id in seen_nodes:
                raise ValueError(f"Duplicate node_id '{node.node_id}' found in CanonicalProcessModel")
            seen_nodes.add(node.node_id)

        # Ensure edge IDs are populated and unique
        seen_edges = set()
        for edge in self.edges:
            if not edge.edge_id:
                raise ValueError(
                    f"Edge from '{edge.source_node_id}' to '{edge.target_node_id}' must have an explicit edge_id."
                )
            if edge.edge_id in seen_edges:
                raise ValueError(f"Duplicate edge_id '{edge.edge_id}' found in CanonicalProcessModel")
            seen_edges.add(edge.edge_id)

        # Strict referential integrity: no silent alias rewriting
        node_ids = {node.node_id for node in self.nodes}
        for edge in self.edges:
            if edge.source_node_id not in node_ids:
                raise ValueError(
                    f"Edge '{edge.edge_id}' references unknown source node '{edge.source_node_id}'. Valid nodes: {sorted(list(node_ids))}"
                )
            if edge.target_node_id not in node_ids:
                raise ValueError(
                    f"Edge '{edge.edge_id}' references unknown target node '{edge.target_node_id}'. Valid nodes: {sorted(list(node_ids))}"
                )

        end_nodes = {
            node.node_id
            for node in self.nodes
            if node.node_type == "end_event"
        }
        for edge in self.edges:
            if edge.source_node_id in end_nodes:
                raise ValueError(
                    f"End event '{edge.source_node_id}' cannot have outgoing transition or edges."
                )

        return self


class DefectRecord(BaseModel):
    """
    Record of an uncertain, conflicting, or ungrounded proposition captured
    in the Ambiguity Register rather than forced into workflow logic.
    """
    proposition_id: str
    evidence_spans: List[str]

    @field_validator("evidence_spans", mode="before")
    @classmethod
    def validate_spans(cls, v: Any) -> List[str]:
        return _normalize_span_list(v)

    defect_category: DefectCategory
    claimed_statement: str
    evidence_text: str
    rationale: str
    confidence: float
    actor_involved: Optional[str] = None


class AmbiguityRegister(BaseModel):
    """
    Dual-output companion artifact capturing all ungrounded or ambiguous claims.
    Ensures zero loss of information while keeping the execution graph authoritative.
    """
    document_name: str

    # 1. Proposition Grounding Metrics (Strict Partition of evaluated propositions)
    total_propositions_extracted: int = 0
    propositions_supported: int = 0
    propositions_uncertain: int = 0
    propositions_unsupported: int = 0
    propositions_missing: int = 0

    # 2. Graph AST Topology Metrics
    total_nodes_generated: int = 0
    total_nodes_verified: int = 0
    total_nodes_quarantined: int = 0

    total_edges_generated: int = 0
    total_edges_verified: int = 0
    total_edges_quarantined: int = 0

    # 3. Overall Process Integrity Status
    process_integrity_status: Literal["VERIFIED", "STRUCTURALLY_DEGRADED", "REJECTED"] = "VERIFIED"

    # Backward-compatible summary counts
    total_verified: int = 0
    total_rejected: int = 0

    defects: List[DefectRecord] = Field(default_factory=list)

    def to_markdown(self) -> str:
        md = [
            f"# Ambiguity & Defect Register: {self.document_name}\n\n",
            f"### 1. Proposition Grounding Accounting\n",
            f"- **Total Candidate Propositions Extracted**: {self.total_propositions_extracted}  \n",
            f"- **Propositions Supported**: {self.propositions_supported}  \n",
            f"- **Propositions Uncertain**: {self.propositions_uncertain}  \n",
            f"- **Propositions Unsupported**: {self.propositions_unsupported}  \n",
            f"- **Propositions Missing / Unverified**: {self.propositions_missing}  \n\n",
            f"### 2. Process Graph AST Topology Accounting\n",
            f"- **Synthesized Process Nodes**: {self.total_nodes_generated} (Verified: {self.total_nodes_verified}, Quarantined: {self.total_nodes_quarantined})  \n",
            f"- **Synthesized Directed Transitions**: {self.total_edges_generated} (Verified: {self.total_edges_verified}, Quarantined: {self.total_edges_quarantined})  \n",
            f"- **Process Structural Status**: `{self.process_integrity_status}`  \n\n",
            f"### 3. Summary\n",
            f"- **Total Extracted Propositions**: {self.total_propositions_extracted}  \n",
            f"- **Verified & Compiled into Graph**: {self.total_nodes_verified} nodes, {self.total_edges_verified} transitions  \n",
            f"- **Excluded / Logged in Register**: {len(self.defects)} defect items  \n\n",
            "---\n\n",
            "## Excluded / Ambiguous Statements Audit\n\n"
        ]
        if not self.defects:
            md.append("✅ **Zero defects or ungrounded propositions detected. 100% of claims satisfied verification policy.**\n")
        else:
            md.append("| # | Category | Proposition | Cited Span | Evidence Text | Verification Rationale | Confidence |\n")
            md.append("| :-: | :--- | :--- | :---: | :--- | :--- | :-: |\n")
            for idx, d in enumerate(self.defects, 1):
                spans = ", ".join(d.evidence_spans)
                snippet = (d.evidence_text[:60] + "...") if len(d.evidence_text) > 60 else d.evidence_text
                snippet = snippet.replace("|", "\\|").replace("\n", " ")
                stmt = d.claimed_statement.replace("|", "\\|").replace("\n", " ")
                rat = d.rationale.replace("|", "\\|").replace("\n", " ")
                md.append(f"| {idx} | `{d.defect_category.value}` | {stmt} | `{spans}` | *\"{snippet}\"* | {rat} | {d.confidence:.2f} |\n")
        return "".join(md)


# =====================================================================
# 4. CANONICAL PROCESS GRAPH AST (GROUNDED IR)
# =====================================================================

class ProcessActor(BaseModel):
    id: str
    name: str
    evidence: List[str] = Field(default_factory=list)


class ProcessActivity(BaseModel):
    id: str
    actor_id: str
    label: str
    description: str
    evidence: List[str] = Field(default_factory=list)
    modality: ModalityType = Field(default=ModalityType.UNSTATED)
    temporal_order: int = Field(default=0)


class ProcessGateway(BaseModel):
    id: str
    question: str
    gateway_type: Literal["exclusive", "parallel", "inclusive"] = "exclusive"
    evidence: List[str] = Field(default_factory=list)
    actor_id: Optional[str] = None

    @property
    def type(self) -> str:
        return self.gateway_type



class ProcessEvent(BaseModel):
    id: str
    type: Literal["start", "end", "intermediate"]
    label: str
    evidence: List[str]
    actor_id: Optional[str] = None


class ProcessTransition(BaseModel):
    """
    Deterministic execution edge produced from a verified SemanticProcessEdge.
    No semantic interpretation happens here.
    """
    id: str = Field(default="")
    from_id: str
    to_id: str
    relation: ProcessRelationType = ProcessRelationType.PRECEDES
    label: Optional[str] = None
    condition: Optional[str] = None
    trigger_type: Optional[
        Literal["timeout", "error", "message", "signal", "condition"]
    ] = None
    evidence: List[str] = Field(default_factory=list)
    source_proposition_ids: List[str] = Field(default_factory=list)
    is_loop: bool = False
    is_exception: bool = False

    @model_validator(mode="after")
    def ensure_id(self) -> "ProcessTransition":
        if not self.id:
            self.id = f"TRANS_{self.from_id}_{self.to_id}"
        return self


class StateTransition(BaseModel):
    from_state: str = Field(description="Source status, e.g. 'Submitted', 'Under Review'")
    to_state: str = Field(description="Target status, e.g. 'Approved', 'Disbursed'")
    trigger: str = Field(description="Cause of status change, e.g. 'Sanction letter issued'")
    evidence: List[str] = Field(default_factory=list, description="Immutable span IDs supporting state change")


class GroundedProcessGraph(BaseModel):
    """The authoritative, verified canonical process graph AST."""
    process_name: str
    objective: str
    events: List[ProcessEvent] = Field(default_factory=list)
    actors: List[ProcessActor] = Field(default_factory=list)
    activities: List[ProcessActivity] = Field(default_factory=list)
    gateways: List[ProcessGateway] = Field(default_factory=list)
    transitions: List[ProcessTransition] = Field(default_factory=list)
    state_transitions: List[StateTransition] = Field(default_factory=list)
    start_event_ids: List[str] = Field(default_factory=list)
    terminal_event_ids: List[str] = Field(default_factory=list)
    initial_states: List[str] = Field(default_factory=list)
    terminal_states: List[str] = Field(default_factory=list)


class GroundedSemanticIR(BaseModel):
    """
    Intermediate Representation of surviving propositions that have satisfied
    both Laya System-1 verification and deterministic evidence checks.
    """
    process_name: str
    objective: str
    verified_propositions: List[AtomicProposition]
    verdicts: Dict[str, LayaVerdict]
    canonical_actors: List[ProcessActor]


class DualOutputResult(BaseModel):
    """Container holding both the verified graph AST and the defect register."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    graph: GroundedProcessGraph
    defect_register: AmbiguityRegister
    sop_markdown: Optional[str] = Field(default=None, description="Generated traceable Markdown SOP procedure with citations")
    snapshot_id: Optional[str] = Field(default=None, description="Persisted ProcessGraphSnapshot ID")
    generation_run_id: Optional[str] = Field(default=None, description="Persisted GenerationRun ID")
    span_registry_hash: Optional[str] = Field(default=None, description="SHA-256 manifest hash of the underlying SpanRegistry")
    span_registry: Optional[Any] = Field(default=None, description="GranularSpanRegistry with verbatim spans")
    elements: Optional[List[Any]] = Field(default=None, description="Extracted NormalizedElements")
    extraction_latency_sec: float = 0.0
    laya_latency_sec: float = 0.0
    compilation_latency_sec: float = 0.0
    total_latency_sec: float = 0.0
