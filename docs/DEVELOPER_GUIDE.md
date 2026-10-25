# Beelzebuth Developer & Agent Context Guide (Locked)

> **Core Operating Manual & Invariants for Beelzebuth Engineers & AI Agents**  
> *Read this document before writing, refactoring, or generating code in this repository.*

---

## 1. Project Mission & North Star

**Beelzebuth is a source-preserving document intelligence engine with a separate semantic process graph, visual editing layer, and format-specific recompilers.**  
Its purpose is to make complex, large documents (such as technical manuals, standard operating procedures, contracts, resumes, and research papers) editable through their **meaning and structure**, rather than only through their physical pages.

```
Traditional Flow:
  Open 200-page doc ➔ Manually hunt across pages ➔ Edit text ➔ Formatting breaks ➔ Save

Beelzebuth Flow:
  Ingest doc ➔ Build Dual Canonical Model (Doc IR + Process Graph) ➔ Edit procedure visually (React Flow / Cytoscape)
  ➔ Evaluate dependencies ➔ Validate claims (NLI) ➔ Explicit Approval Gate ➔ Recompile to original format with styles preserved
```

---

## 2. The 9 Non-Negotiable Invariants

When implementing features or refactoring code in this repository, you **must adhere to these 9 invariants**:

1. **The Canonical Document Model (CDM) is the Single Source of Truth**:
   - Maintain the **Two-Model Architecture**:
     - **Model A (`DocumentIR`)**: Faithful structural representation of the source (headings, paragraphs, lists, tables, callouts, captions, citations, equations, clauses, stable block IDs `block-001`, ordering, hierarchy, formatting snapshots, OpenXML styles).
     - **Model B (`SemanticProcessGraph`)**: Interpreted procedures, steps, decisions, actors, conditions, and dependencies.
   - All visual views are **projections** of the CDM. All user edits generate a `TypedChangeCommand` that mutates the CDM. Recompilers serialize from the CDM back into document files.

2. **Models Interpret and Assess; The Change Engine Controls and Verifies**:
   - **OpenJev** handles fast-path request classification and structured action dispatch (e.g., section moves, known typed commands).
   - **Laya** evaluates semantic entailment, factual consistency, and meaning preservation against cited evidence spans.
   - The deterministic **Change Engine** owns target resolution, version validation, structural integrity, the approval gate, and document recompilation.
   - **Neither model can bypass the Change Engine or directly mutate document binaries.**

3. **General Documents Are Never Forced into SOP Workflows**:
   - Resumes, contracts, reports, and research papers use their native structural units (sections, experience bullets, clauses, citations, paragraphs) rather than hallucinated procedural steps.
   - The detected `DocumentType` controls which semantic overlays and operations are active.

4. **Approval Gate & Cryptographic Integrity Boundary**:
   - Every document mutation requires an explicitly `APPROVED` ChangeSet (`COMPILABLE_STATUSES = {"APPROVED"}`).
   - `PROPOSED`, `REJECTED`, and already `APPLIED` ChangeSets must be rejected at the recompilation boundary.
   - **HMAC-SHA256 Payload Binding**: Approval generates an HMAC-SHA256 signature binding the exact document version, authenticated principal identity, and canonical command payload digest. Approved ChangeSets and TypedChangeCommands are deeply frozen (`is_frozen=True`, `FrozenDict`, `FrozenList`). Any mutation of fields, operations, or nested collections after approval invalidates compilation.
   - **Tiered Secret Provisioning**:
     - *Local / Single-User Mode*: Frictionless automatic initialization. The engine generates a cryptographically secure 256-bit key (`secrets.token_hex(32)`) on first launch, persists it to `~/.injester/.approval_signing_key` with restricted permissions (`0600`), and reuses it across restarts.
     - *Self-Hosted / Multi-User Mode*: Operators must configure `export APPROVAL_SIGNING_KEY="$(openssl rand -hex 32)"` via environment or secret manager. Reusing `JWT_SECRET` is strictly prohibited.
     - *Production Mode*: Fails startup fast if `APPROVAL_SIGNING_KEY` is absent, shorter than 32 characters, or identical to `JWT_SECRET`.
     - *Zero Embedded Secrets*: No default or fallback constant exists in the codebase.

5. **Zero Ungrounded Assertions & Zero Synthetic Drift**:
   - Every statement and procedural step must anchor to an immutable `SpanAnchor` with line, page, and excerpt evidence.
   - Unverified statements, missing steps, or proposed additions must be explicitly quarantined in the `Defect Register / Ambiguity Register`.
   - Never introduce fake mocks, dummy fallbacks, or placeholder text. If evidence does not exist, return an empty state.

6. **Procedure Scope & Dependency Preservation**:
   - Reordering operations are strictly scoped to their containing procedure parent block (`step_parent_map`). Moving steps across unrelated sections or procedures is rejected.
   - Moving a procedural step or updating a parameter must trigger an impact analysis query on the Dependency Graph. Dependency cycles are strictly detected and rejected.

7. **Style-Preserving Same-Format Recompilation**:
   - When editing a `.docx` file, update the document AST (`zipfile` + `lxml`) at the element level.
   - Never re-render the entire document from scratch if 95% of it was untouched. Preserve original fonts, margins, headers, footers, cover pages, tables, and styles.
   - Check the entire procedure scope for unsupported structures (tracked revisions, SDT, cross-paragraph bookmarks/comments) before applying any mutation.

8. **Stale-Source Protection & Verification**:
   - Source files are cryptographically re-hashed immediately prior to patching to prevent mutating stale files.
   - Recompiled artifacts are re-extracted and verified with one-to-one block reconciliation (`matched_reopened_ids`).

9. **Unified Interfaces Sharing 100% Core Services**:
   - CLI (`injester`), Web Workbench (`injester web`), and MCP Server (`injester mcp`) must call the exact same underlying application services in `injester/application/`. Never duplicate business logic in CLI or router layers.

---

## 3. The Open-Source Component Assembly Stack

Beelzebuth combines proven open-source modules:

| Subsystem | Library | Purpose |
| :--- | :--- | :--- |
| **Document Ingestion** | **Docling** (Primary) | Structured layout analysis, deep learning table recognition (TableFormer), provenance coordinates. |
| **Ingestion Fallback** | **Unstructured** | Rapid heuristic partitioning for heterogeneous documents. |
| **Fast Path Router** | **OpenJev** | Request classification and structured action dispatch. |
| **Semantic Verifier** | **Laya** | Non-autoregressive factual consistency and meaning preservation checks. |
| **Workflow Canvas** | **React Flow** (`@xyflow/react`) | Draggable procedure steps, custom nodes, connectors, minimaps. |
| **Auto Graph Layout** | **ELK.js** | Computes node positions and edge routing to minimize crossings. |
| **Knowledge Maps** | **Cytoscape.js** | Cross-document relationship exploration (roles, warnings, prerequisites). |
| **Formal BPMN** | **bpmn-js** | Formal BPMN 2.0 XML viewing and editing. |
| **Rich-Text Editor** | **Tiptap / ProseMirror** | Source-linked rich-text blocks and transactional history. |
| **PDF Viewing** | **PDF.js** | High-fidelity PDF rendering with source passage navigation. |
| **Word Recompiler** | **zipfile + lxml** | Element-level OpenXML AST patching for Word documents. |
| **Sheet Recompiler** | **openpyxl** | Spreadsheet modification preserving formulas and styles. |
| **Slides Recompiler**| **python-pptx** | Presentation slide and shape editor. |

---

## 4. Repository Architecture & Directory Structure

```
injester/
├── domain/                      # Domain entities, Document IR, and auth models
│   ├── auth.py                  # RBAC, user models, session tokens
│   ├── document_ir.py           # Model A: Document IR, DocumentType enum, extract_docx_ir()
│   └── models.py                # Core database entities (Files, Snapshots, Lineage)
├── infrastructure/              # Database, low-level patchers, and background jobs
│   ├── db.py                    # SQLAlchemy async engine & SQLite setup
│   ├── docx_patcher.py          # Surgical OOXML AST patcher (zipfile + lxml element surgery)
│   ├── heartbeat.py             # Server heartbeat & health diagnostics
│   └── jobs.py                  # Background ingestion and compilation tasks
├── ingestion/                   # Subsystem 1: Document Ingestion
│   ├── extractor.py             # Dual backend: Docling TableFormer + Unstructured
│   ├── chunker.py               # Hierarchical chunking preserving section paths
│   └── schema.py                # NormalizedElement and LayoutMetadata schemas
├── semantic/                    # Subsystem 2: Beelzebuth Analyzer & Change Engine
│   ├── change_engine.py         # Typed Change Engine: approval gate, cycle detection, scope
│   ├── schemas.py               # Canonical Document Model (Model A + Model B schemas)
│   ├── extractor.py             # Procedural entity extraction (verbs, actors, tools)
│   ├── normalizer.py            # Sentence-level text normalizer
│   ├── pipeline.py              # Semantic pipeline orchestrator
│   ├── projections.py           # CDM to BPMN, Mermaid, ReactFlow, Cytoscape projections
│   ├── reasoner.py              # Procedural AST reasoner
│   ├── validator.py             # Structural graph consistency checker
│   └── verifiers/               # Subsystem 5: Validation & Decision Engines
│       ├── factory.py           # Verifier factory
│       ├── openjev.py           # OpenJev adapter: fast-path classification & NLI
│       ├── laya.py              # Laya adapter: typed semantic consistency checks
│       └── policy.py            # Safety policy verifier
├── application/                 # Application Service Layer (Shared by CLI, Web, MCP)
│   ├── docx_pipeline.py         # DocxRoundTripPipeline & DocumentEditSession orchestrator
│   ├── manager.py               # WorkspaceManager (local directory bootstrap & locks)
│   ├── documents.py             # DocumentService (ingest, list, delete, version)
│   ├── digitizer.py             # High-Fidelity Digitizer (GFM tables, span registry)
│   ├── process_graph.py         # ProcessGraphService (visual projections & diffs)
│   └── retrieval.py             # RetrievalService (FAISS hybrid semantic search)
├── vectorstore/                 # Dense vector retrieval
│   ├── base.py                  # Vector store abstract interface
│   └── faiss_store.py           # FAISS index with sentence-transformers embeddings
├── api/                         # FastAPI REST Endpoints for Web Workbench
│   ├── app.py                   # FastAPI initialization & SPA static file mounting
│   ├── deps.py                  # Dependency injection for services and sessions
│   └── routers/                 # Modular endpoints
│       ├── beelzebuth.py        # Core CDM, procedures, and recompiler endpoints
│       ├── files.py             # File upload and download routes
│       └── process_graph.py     # Graph retrieval and visualization routes
├── mcp/                         # Subsystem: Model Context Protocol (MCP)
│   └── server.py                # Local stdio JSON-RPC MCP server
├── providers/                   # Bring Your Own AI (BYOAI) integrations
│   ├── base.py                  # Base LLM provider contract
│   ├── openai_compatible.py     # OpenRouter, Ollama, vLLM, OpenAI provider
│   ├── gemini.py                # Google Gemini provider
│   └── registry.py              # Active provider registry
├── synthesis/                   # Digest synthesis and span registry
│   └── spans.py                 # Granular sentence span segmentation (`[S001]...`)
├── cli.py                       # Python Typer + Rich Terminal CLI (`injester`)
└── config.py                    # Environment settings and workspace paths
```

---

## 5. Three Dimensions of Traceability & Evidence Scoring

Every procedure node and claim must maintain three-way traceability:
1. **Source Grounding**: Which exact passage, table cell, or page supports a claim?
2. **Semantic Grounding**: Why does a workflow node exist, and what evidence supports its relationships?
3. **Change Provenance**: What did the user or AI change, which source blocks were affected, and what was added/removed?

### The 4-Tier Validation Rule
- `STRONG`: Direct, explicit support in the source text.
- `MODERATE`: Reasonable support with interpretation.
- `WEAK`: Indirect or ambiguous support; quarantined in Defect Register.
- `NONE`: No source support (explicit user-added content).

---

## 6. How to Run & Verify the Environment

### 1. Verify Python Environment & Dependencies
```bash
# Check Python version (>= 3.10)
python3 --version

# Run workspace diagnostic
injester doctor

# Run full pytest suite (247 tests)
./venv/bin/pytest

# Run DOCX acceptance suite specifically (14 gates)
./venv/bin/pytest tests/test_docx_roundtrip_acceptance.py -v
```

### 2. Verify Frontend Assets
```bash
cd frontend
# Verify dependencies
bun install # or npm install

# Verify TypeScript compilation & Vite build
bun run build # or npm run build
cd ..
```

### 3. Launching Unified Interfaces
```bash
# Terminal CLI
injester md generate -f sample_docs/Workstation_Deployment_Guide.docx -o output.md

# Web Workbench (opens browser to http://127.0.0.1:8000)
injester web

# Model Context Protocol (MCP) stdio server
injester mcp
```
