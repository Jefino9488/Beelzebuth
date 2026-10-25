# Beelzebuth Web Workbench (Visual Editing Workspace)

> **High-Performance React 19 Dual-Pane Document Workspace**  
> *Interacting with document meaning, structure, and procedures in real time.*

---

## 1. Overview

The **Beelzebuth Web Workbench** is a local-first single-page application built with **React 19**, **TypeScript**, **Vite**, **Tailwind CSS**, and modern web visual tools. It serves as the primary visual interface for Beelzebuth's Canonical Document Model, enabling users to understand and edit procedural content without reading hundreds of linear pages.

### Component Implementation Status & Roadmap

| Component | Technology | Target Phase | Implementation Status | Current Capabilities |
| :--- | :--- | :--- | :--- | :--- |
| **Workflow Studio Canvas** | React Flow (`@xyflow/react`) | Phase 1.5 | **In Development** | Interactive procedural step nodes with cited evidence badges `[S###]`, step selection, and status indicators. |
| **Graph Auto-Layout** | ELK.js (`elkjs`) | Phase 1.5 | **Planned / In Dev** | Algorithmic layout engine to calculate hierarchical node positions and orthogonal edge routing automatically. |
| **Source PDF View** | PDF.js (`pdfjs-dist`) | Phase 2 | **Planned** | Native in-browser PDF viewport with deep-linking to exact page and coordinate passages for citations. |
| **Knowledge Map** | Cytoscape.js | Phase 4 | **Planned** | Cross-document graph visualizer for actors, warning cascades, and procedural prerequisites. |
| **Formal BPMN Modeler** | bpmn-js | Phase 4 | **Planned** | Full enterprise BPMN 2.0 visual modeling with standard notation symbols and XML export. |
| **Source-Linked Editor** | Tiptap / ProseMirror | Phase 4 | **Planned** | Rich-text editing surface with live citation tracking, inline evidence badges, and undo/redo history. |

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│  Top: Devour Dropzone (Drag-and-Drop Ingestion · Progress Bar · Stop Devouring Button) │
├───────────────────────────────────┬────────────────────────────────────────────────────┤
│         LEFT PANE (50%)           │                 RIGHT PANE (50%)                   │
│    Source Evidence Grounding      │            Visual Editing Workspace                │
│                                   │                                                    │
│  • Raw immutable source text      │  [Digital .md] [Diagram] [Tree] [Table] [Schema]   │
│  • Sentence-level badges [S001]   │                                                    │
│  • Visual highlight sync          │  • Interactive Flowcharts (React Flow Studio)      │
│  • Page & coordinate tooltips     │  • Digital Markdown Tab & live citation links      │
│  • PDF.js passage nav (Planned P2)│  • Knowledge Map (Cytoscape.js - Planned P4)       │
│                                   │  • Tiptap rich editor (Planned P4)                 │
│                                   │  • Visual step reordering & direct node editing    │
│                                   │  • Before/after diff preview before recompile      │
├───────────────────────────────────┴────────────────────────────────────────────────────┤
│  Bottom: Inquisitor Bar (Claim validation against source evidence via System-1 NLI)    │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Multi-Representation Workspace Tabs

The workbench dynamically presents document content using domain-appropriate visual representations:

1. **Digital Markdown (`.md`) Tab (Active) & Tiptap Rich Editor (Planned Phase 4)**:
   - **Read Mode (Active)**: Clean GitHub-Flavored Markdown with clickable `[S###]` badges that instantly jump to and highlight corresponding source evidence.
   - **Edit Mode (Planned Phase 4)**: Monospace and rich-text editing surfaces for making quick textual adjustments with transactional history via Tiptap.
   - **One-Click Actions (Active)**: Download `.md` file, copy full text and citation index to clipboard.
2. **Diagram & Flowchart Studio Tab (React Flow In Development / ELK.js Planned)**:
   - Interactive process visualization powered by **React Flow (`@xyflow/react`)**.
   - Automatic graph layout and edge routing calculated by **ELK.js** (Planned Phase 1.5) to prevent visual clutter and edge crossings.
   - Renders steps as modular nodes displaying action verbs, actors, tools, and evidence links.
   - Direct manipulation: drag steps to reorder, add branches, and view execution sequences.
3. **Knowledge Map Tab (Cytoscape.js — Planned Phase 4)**:
   - Interactive network graph exploring cross-document relationships, actors, warnings, prerequisites, and system constraints.
4. **Decision Tree Tab**:
   - Visual branching trees optimized for troubleshooting guides and diagnostic manuals.
5. **Interactive Document Outline Tab**:
   - Hierarchical outline tree allowing whole-document restructuring, heading promotions, and section collapsing.
6. **Configuration Table Tab**:
   - Schema-validated grid editor for technical parameters, hardware pinouts, and specification tables.
7. **Source PDF View Tab (PDF.js — Planned Phase 2)**:
   - Render the original PDF directly in the browser and navigate straight to the page and passage associated with any selected workflow node.
8. **Schema & JSON Tab (Active)**:
   - Real-time JSON tree of the Canonical Document Model, node properties, and entailment confidence scores.

---

## 3. Architecture & State Management

- **Global Store (`src/store/useBeelzebuthStore.ts`)**:
  - Managed via **Zustand**.
  - Tracks active document, version lineage, selected evidence spans, active view tab, and pending ChangeSets.
- **Bidirectional Highlighting**:
  - Hovering or clicking a citation badge `[S042]` in the right pane automatically scrolls the left pane (or PDF.js canvas) to the exact sentence and highlights it with animated glowing borders.
- **Zero Synthetic Fallbacks**:
  - No dummy data or hardcoded mock files. Displays true ingested document data or clean empty state.
- **FastAPI Integration**:
  - Communicates directly with backend REST API at `/api/v1/`.
  - When compiled (`npm run build` or `bun run build`), production assets are bundled into `injester/_frontend_dist` and served automatically by FastAPI during `injester web`.

---

## 4. Development Workflow

### Prerequisites
- Node.js 18+
- Bun 1.3+ (recommended) or npm

### Commands
```bash
# Install dependencies
bun install # or npm install

# Start Vite dev server with Hot Module Replacement (HMR)
bun run dev # or npm run dev

# Run Oxlint / TypeScript linter
bun run lint # or npm run lint

# Build production bundle for FastAPI static serving
bun run build # or npm run build
```

During development with `bun run dev`, Vite runs on `http://localhost:5173` and proxies API requests to the backend server running at `http://127.0.0.1:8000`.
