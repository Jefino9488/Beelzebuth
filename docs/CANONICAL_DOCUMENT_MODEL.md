# Beelzebuth — Canonical Document Model (CDM) Specification

> **The Two-Model Architecture: Document IR + Semantic Overlays**  
> *The central bridge between raw document packages, visual editing canvases, decision-making engines, and format-specific recompilers.*

---

## 1. Architectural Philosophy: Why Two Linked Models?

A common failure mode in document intelligence systems is attempting to represent an entire document as a single graph or flattening it into Markdown. 

Beelzebuth explicitly separates:
1. **What is physically in the source** (Document IR — Model A)
2. **The semantic meaning derived from it** (Semantic Overlays & Process Graph — Model B)

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                        BEELZEBUTH CANONICAL DOCUMENT MODEL                             │
├───────────────────────────────────────────┬────────────────────────────────────────────┤
│         MODEL A: DOCUMENT IR              │        MODEL B: SEMANTIC OVERLAYS          │
│    (Faithful Structural Source Form)      │    (Domain-Appropriate Semantic Meaning)   │
├───────────────────────────────────────────┼────────────────────────────────────────────┤
│ • Headings, paragraphs, tables, images    │ • Manuals: Procedures, steps, dependencies │
│ • Stable block IDs (`block-001`, `block-002`)│ • Resumes: Experience, skills, education   │
│ • DocumentType classification             │ • Contracts: Clauses, obligations, terms   │
│ • Block types: HEADING, PARAGRAPH, TABLE, │ • Reports: Chapters, executive summaries   │
│   LIST_ITEM, CALLOUT, FIGURE_CAPTION,     │ • Research Papers: Citations, equations    │
│   CITATION, EQUATION, CLAUSE              │ • Every semantic node maps to source blocks│
│ • Parent/child hierarchy & reading order  │ • Retains inference confidence & evidence  │
│ • Formatting metadata (styles, runs, XML) │ • Procedure scope bounded by parent blocks │
│ • Physical anchors (fingerprints, XPath)  │                                            │
└───────────────────────────────────────────┴────────────────────────────────────────────┘
                                    │
                                    ▼
                     ┌─────────────────────────────┐
                     │  Source & Provenance Index  │
                     │  Atomic Span IDs `[S001]`   │
                     └─────────────────────────────┘
```

### The Many-to-Many Relationship
- **One Semantic Step ➔ Multiple Source Blocks**: A single procedure step like *“Initialize RAID 10 Array”* may be derived from a paragraph on page 14, a specifications table on page 15, and a safety warning on page 18.
- **One Source Block ➔ Multiple Semantic Steps**: A dense paragraph like *“First turn on power, then press F2 to enter BIOS, and immediately disable Secure Boot”* contains three distinct procedural tasks.

Because the mapping is explicitly maintained, changing a node in the visual workspace knows exactly which source blocks in Model A are affected.

---

## 2. Model A — Document IR (Structural Representation)

Model A captures the physical and structural elements extracted from any source document format:

```python
from enum import Enum
from typing import List, Dict, Optional, Any
from pydantic import BaseModel, Field

class DocumentType(str, Enum):
    RESUME = "RESUME"                   # CV / Resume: experience, education, skills
    REPORT = "REPORT"                   # Business report, proposal, executive summary
    MANUAL = "MANUAL"                   # SOP, technical manual — procedural steps
    RESEARCH_PAPER = "RESEARCH_PAPER"   # Academic paper: citations, equations, figures
    CONTRACT = "CONTRACT"               # Legal document: clauses, obligations
    GENERIC = "GENERIC"                 # Default safe representation

class FormattingSnapshot(BaseModel):
    is_bold: bool = False
    is_italic: bool = False
    style_name: Optional[str] = None       # e.g., "Heading 2", "List Bullet"
    font_name: Optional[str] = None
    font_size_pt: Optional[float] = None
    is_heading: bool = False
    heading_level: Optional[int] = None
    list_num_id: Optional[str] = None      # OOXML w:numId
    list_ilvl: Optional[int] = None        # OOXML w:ilvl (nesting depth)
    is_table_row: bool = False
    table_index: Optional[int] = None
    row_index: Optional[int] = None
    col_index: Optional[int] = None

class SourceLocationRef(BaseModel):
    element_index: int                    # 0-indexed position among document elements
    xpath: str                            # e.g., "/w:document/w:body/w:p[12]"
    fingerprint_hash: str                 # SHA-256 of normalized text
    xml_signature_hash: str               # SHA-256 of structural tag pattern

class DocumentBlock(BaseModel):
    block_id: str                          # Stable ID: "block-001"
    block_type: str                        # HEADING | PARAGRAPH | LIST_ITEM | TABLE | CALLOUT |
                                           # FIGURE_CAPTION | CITATION | EQUATION | CLAUSE
    text_content: str
    parent_block_id: Optional[str] = None  # Hierarchical section parent
    sequence_index: int                    # Reading order position
    formatting: FormattingSnapshot
    location: SourceLocationRef
    span_ids: List[str] = Field(default_factory=list)
    table_data: Optional[List[List[str]]] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

class DocumentIR(BaseModel):
    document_id: str
    filename: str
    file_format: str = "DOCX"
    file_hash: str
    document_type: DocumentType = DocumentType.GENERIC
    total_blocks: int = 0
    blocks: Dict[str, DocumentBlock] = Field(default_factory=dict)
    structural_order: List[str] = Field(default_factory=list)
```

---

## 3. Model B — Domain Semantic Overlays

Rather than forcing every document into an SOP process graph, Beelzebuth activates the overlay appropriate to the `document_type`:

### A. Manuals & SOPs: Procedural Step Overlay
```python
class GroundedStep(BaseModel):
    step_id: str                          # e.g., "step-01"
    label: str
    instruction: str
    source_block_id: str                  # Reference to Model A block
    evidence_span_id: str                 # Reference to Span Registry "S001"
    sequence_index: int
    actor: Optional[str] = None
    procedure_parent_block_id: Optional[str] = None
    evidence_strength: EvidenceStrength = EvidenceStrength.STRONG

class StepDependency(BaseModel):
    dependency_id: str
    from_step_id: str                     # Prerequisite step
    to_step_id: str                       # Dependent step
    relationship: EdgeRelationship = EdgeRelationship.DEPENDS_ON
    rationale: str
```

### B. Resumes / CVs: Section & Experience Overlay
- Top-level sections: Summary, Experience, Education, Skills, Certifications.
- Experience items: Organization, Role, Date Range, Bullet Points linked to source paragraphs.
- Primary visual operation: Drag-and-drop section reordering (`REORDER_SECTION`) or bullet rewording (`EDIT_PARAGRAPH_TEXT`).

### C. Contracts: Clause & Obligation Overlay
- Numbered clauses: Section/Clause identifiers (`1.1`, `2.3(a)`).
- Obligation classification: Mandatory (`must`, `shall`), Permissive (`may`, `can`), Prohibitive (`shall not`).
- Primary visual operation: Clause reordering, condition updates, term reviews.

---

## 4. Decision-Making Engines & Interface Contracts

Beelzebuth assigns distinct responsibilities to **OpenJev** and **Laya**:

### A. OpenJev: Fast Path Router
- **Role**: Request classification and rapid dispatch to structured actions.
- **Input Contract**:
  ```python
  class OpenJevRouterInput(BaseModel):
      user_request: str                   # e.g., "Move skills section above education"
      document_type: DocumentType         # RESUME, MANUAL, CONTRACT, etc.
      active_sections: List[str]          # Known section labels / IDs in active document
      active_steps: List[str]             # Known step IDs (if manual)
  ```
- **Output Contract**:
  ```python
  class OpenJevRouterOutput(BaseModel):
      intent: str                         # "STRUCTURED_REORDER" | "DIRECT_EDIT" | "SEMANTIC_REWRITE"
      suggested_operation: Optional[ChangeOperationType]
      target_identifier: Optional[str]    # section or step ID
      anchor_identifier: Optional[str]    # target position before/after ID
      requires_semantic_analysis: bool    # True if generative rewriting or factual check needed
      confidence: float
  ```

### B. Laya: Semantic Analysis & Evidence Grounding Engine
- **Role**: Evaluates meaning preservation, intent, and factual consistency against cited source evidence spans.
- **Input Contract**:
  ```python
  class LayaSemanticInput(BaseModel):
      proposed_text: str                  # Rewritten bullet, revised instruction, or modified clause
      evidence_spans: List[str]           # Text of cited original spans [S001, S002]
      context_actor: Optional[str]        # Expected actor or entity
      context_action: Optional[str]       # Expected core action verb / target
  ```
- **Output Contract**:
  ```python
  class LayaSemanticVerdict(BaseModel):
      is_supported: bool                  # True if entailed by evidence
      action_entailment_score: float      # [0.0, 1.0]
      actor_grounding_score: float        # [0.0, 1.0]
      modality_preserved: bool            # True if obligation level unchanged
      evidence_strength: EvidenceStrength # STRONG | MODERATE | WEAK | NONE
      unsupported_claims: List[str]       # Specific phrases lacking evidence
  ```

---

## 5. The Typed Change-Command Layer & Approval Gate

All edits — whether from visual drag-and-drop, OpenJev fast-path routing, or Laya-evaluated proposals — are submitted through the deterministic Change Engine:

```python
class ChangeOperationType(str, Enum):
    # Procedural operations (Manuals, SOPs)
    MOVE_PROCEDURE_STEP = "MOVE_PROCEDURE_STEP"
    UPDATE_STEP_INSTRUCTION = "UPDATE_STEP_INSTRUCTION"
    INSERT_PROCEDURE_STEP = "INSERT_PROCEDURE_STEP"
    REMOVE_PROCEDURE_STEP = "REMOVE_PROCEDURE_STEP"

    # General document operations (Resumes, Reports, Contracts, Papers)
    REORDER_SECTION = "REORDER_SECTION"
    EDIT_PARAGRAPH_TEXT = "EDIT_PARAGRAPH_TEXT"

class TypedChangeCommand(BaseModel):
    command_id: str
    operation: ChangeOperationType
    target_step_id: Optional[str] = None
    target_block_id: Optional[str] = None
    before_step_id: Optional[str] = None
    source_block_ids: List[str] = Field(default_factory=list)
    new_values: Optional[Dict[str, Any]] = None
    expected_document_version: str
    procedure_parent_block_id: Optional[str] = None
    rationale: str = ""
    proposed_by: str = "user"
```

### Deterministic Change Engine Guarantees
1. **Target & Scope Resolution**: Maps target identifiers to physical blocks in `DocumentIR` and ensures moves do not violate procedure or section boundaries.
2. **Version Invariance**: Rejects commands targeting stale document versions.
3. **Cycle Prevention**: Depth-first search prevents circular dependencies.
4. **Approval Gate**: ChangeSet status must be `APPROVED` before compilation can occur.
5. **Pre-Mutation Checks**: Validates whole-procedure unsupported structures and re-hashes source files.
6. **Round-Trip Reconciliation**: Confirms all unmodified blocks and styles survive 100% intact via `matched_reopened_ids`.

---

## 6. Three Dimensions of Traceability

```
1. SOURCE GROUNDING
   Which original passage, table cell, image, or page supports a procedure or claim?
   [S042] ➔ Page 14 ➔ Chapter 3 ➔ "Format boot drive with NTFS filesystem"

2. SEMANTIC GROUNDING
   Why does a workflow node exist, and what evidence supports its edges?
   "Configure RAID" ➔ DEPENDS_ON ➔ "Load Storage Driver" [Evidence: Step 4.1 note]

3. CHANGE PROVENANCE
   What did the user or AI change, which source elements were affected, and what was added/removed?
   ChangeSet cs_091: Moved Step 4 before Step 2. Affected block-104. Verified: 0 conflicts.
```

---

## 7. The 4-Tier Validation Rule

| Level | Definition | Behavior in Visual Editor & Recompiler |
| :--- | :--- | :--- |
| `STRONG` | Direct, clear support in source. | Displayed with green verified badge; automatically eligible for compilation. |
| `MODERATE` | Reasonable support with interpretation. | Displayed with amber badge; user can inspect supporting excerpt. |
| `WEAK` | Indirect or ambiguous support. | Quarantined in Defect / Ambiguity Register; requires confirmation before export. |
| `NONE` | No original source support (new addition). | Clearly tagged as `[NEW CONTENT: USER PROPOSED]`; never falsely attributed to source manual. |
