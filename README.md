# Beelzebuth (Injester Community)

> **Devour any document into high-fidelity Markdown (`.md`) and depict them in diagrams.**

Beelzebuth is an open-source, local-first document digitization and grounding engine. It devours heterogeneous files (`.pdf`, `.docx`, `.xlsx`, `.csv`, `.txt`, `.md`, images) into clean, editable, and structurally faithful **GitHub-Flavored Markdown (`.md`)** in under 2 seconds—complete with native tables, inline Mermaid diagrams, and granular sentence-level citations `[S###]` anchored to an auditable **Citation & Source Provenance Index**.

---

## Key Capabilities

- **Universal Document Digitization**: Converts any document format into high-fidelity, human-readable `.md` while preserving all original context, headings, paragraphs, and list hierarchies.
- **Native Table Transcription**: Detects tabular structures from PDFs, DOCX, and HTML layouts and converts them into standardized GitHub-Flavored Markdown tables.
- **Diagram & Flow Preservation**: Recognizes process flows, sequence progressions, and state transitions, transcribing them into native inline Mermaid blocks (````mermaid graph TD ... ````).
- **Granular Evidence Grounding**: Every sentence is tagged with an immutable citation badge `[S001]` mapped to an exact page, section path, and source excerpt in the **Citation & Source Provenance Index**.
- **Three Unified Interfaces**: Operate via terminal CLI, local interactive Web Workbench, or Model Context Protocol (MCP) server for AI assistants—all sharing a single core engine and local workspace.
- **Optional Diagram Depiction**: Synthesizes interactive document structure graphs, Mermaid flowcharts, swimlanes, and BPMN 2.0 XML.
- **Zero Hardcoded Data & Zero Synthetic Drift**: No fake fallbacks, mock documents, or procedural hallucinations. Displays only genuine evidence or a clean empty state.
- **Bring Your Own AI (BYOAI)**: Plug in any OpenAI-compatible provider (OpenRouter, Ollama, vLLM, OpenAI) or run offline on local hardware.

---

## The Three Unified Interfaces

```
                               ┌────────────────────────────────────────────────┐
                               │           Injester / Beelzebuth Core           │
                               │  Ingestion · Partitioning · Digitizer · Index  │
                               └──────────────────────┬─────────────────────────┘
                                                      │
                         ┌────────────────────────────┼───────────────────────────┐
                         ▼                            ▼                           ▼
                 ┌───────────────┐           ┌──────────────────┐         ┌───────────────┐
                 │  Terminal CLI │           │  Local Web SPA   │         │  MCP Server   │
                 │  `injester`   │           │  `injester web`  │         │ `injester mcp`│
                 └───────────────┘           └──────────────────┘         └───────────────┘
```

1. **Terminal CLI (`injester`)**: Fast local devouring, indexing, searching, and diagnostics directly from the command line.
2. **Local Web Workbench (`injester web`)**: A high-performance React 19 single-page application served by FastAPI. Features side-by-side evidence inspection, live Markdown editing, clickable citation badges, and diagram rendering.
3. **Model Context Protocol (`injester mcp`)**: Standard stdio JSON-RPC interface exposing document operations directly to AI tools like Claude Desktop, Cursor, and Windsurf.

---

## Command Reference

| Command | Description |
| :--- | :--- |
| `injester` | Display overview and available commands. |
| `injester init` | Initialize the local workspace directory (`injester.db` and vector store). |
| `injester md generate -f <file> -o <out.md>` | Devour a file directly into high-fidelity Markdown with tables and citations. |
| `injester ingest <file>` | Ingest and index a document into the local workspace. |
| `injester ingest <file> -o <out.md>` | Ingest, index, and save the digitized Markdown file. |
| `injester documents list` | List locally stored documents and indexed chunk counts. |
| `injester search "<query>"` | Semantic vector search across indexed evidence chunks. |
| `injester diagram generate -f <file>` | Depict diagrams (BPMN 2.0 XML, Mermaid flowcharts, swimlanes). |
| `injester web` | Start the local FastAPI server, serve the React workbench, and open the browser. |
| `injester web --port 8765 --no-browser` | Run web server on custom port without automatically opening browser. |
| `injester mcp` | Launch the local stdio MCP server for AI clients. |
| `injester doctor` | Diagnose configuration, dependencies, and local workspace health. |
| `injester config` | Inspect and configure active LLM, System-1 verifier, and storage settings. |

---

## Quickstart & Installation

### 1. Prerequisites
- Python 3.10+ (tested through Python 3.14)
- Node.js 18+ (only needed if building frontend from source)

### 2. Install Beelzebuth / Injester
```bash
# Clone repository
git clone https://github.com/Jefino9488/Beelzebuth.git
cd Beelzebuth

# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies and CLI
pip install -e .
```

### 3. Initialize Workspace & Check Health
```bash
injester init
injester doctor
```

### 4. Devour a Document from the Terminal
```bash
# Devour any PDF, Word document, or text file into Markdown
injester md generate -f sample_docs/Incident_and_Revocation_Procedure.md -o output.md
```

### 5. Launch the Web Workbench
```bash
injester web
```
The browser will automatically open to `http://127.0.0.1:8000`.

---

## Web Workbench Overview

The Beelzebuth Web Workbench (`injester web`) provides an intuitive dual-pane workspace:

- **Top Devour Dropzone**: Drag and drop any document (`.pdf`, `.docx`, `.xlsx`, `.csv`, `.txt`, `.md`). Ingestion completes in ~1-2 seconds. Includes an active **Stop Devouring** button to abort at any time.
- **Left Pane (Source Evidence Grounding)**: Displays the raw, immutable document text with sentence-level span IDs (`[S001]`). Hovering or clicking any span highlights the corresponding statement.
- **Right Pane (Transmutation Studio)**:
  - **Digital Markdown (.md)** *(Default Hero Tab)*:
    - **Read Mode**: Cleanly rendered Markdown with interactive, clickable `[S###]` badges.
    - **Edit Mode**: Built-in monospace Markdown editor for making instant modifications.
    - **Download .md**: One-click download of the complete digitized file.
    - **Copy Markdown**: Copies the full Markdown text and citation index to clipboard.
  - **Diagram View**: Renders structural flowcharts and interactive node graphs of the document.
  - **LLM Context**: Displays compression ratios, raw vs clean token counts, and chunk distributions.
  - **Schema (JSON)**: Programmatic key-value schema with entailment confidence scores.
- **Bottom Inquisitor Bar**: Type any candidate claim or hypothesis to run real System-1 NLI verification against source evidence.
- **Settings Modal**: Configure your LLM provider (OpenRouter, Ollama, OpenAI) and discover free models with live filtering.

---

## Model Context Protocol (MCP) Integration

Beelzebuth ships a local stdio MCP server. AI desktop clients can discover documents, run vector searches, and synthesize verified Markdown directly.

### Claude Desktop Configuration
Add to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "injester": {
      "command": "/absolute/path/to/venv/bin/injester",
      "args": ["mcp"]
    }
  }
}
```

### Available MCP Tools
- `list_documents`: Discover all locally ingested documents and chunk counts.
- `ingest_document(path)`: Ingest and index any local document file.
- `search_evidence(query, top_k)`: Semantic vector search across indexed chunks.
- `generate_digest(topic, document_ids)`: Synthesize a citation-audited Markdown document.
- `generate_diagram(document_id_or_path, output_dir)`: Generate Mermaid flowcharts and BPMN 2.0 XML.
- `export_artifact(snapshot_id, format, output_path)`: Export diagrams or Markdown to disk.

---

## Architecture

For an in-depth breakdown of the internal pipeline, data models, and span provenance engine, see the full architecture document:

📖 **[System Architecture Specification](docs/ARCHITECTURE.md)**

```
┌──────────────────┐     ┌──────────────────────┐     ┌────────────────────────┐
│  Input Document  │ ──> │ Document Partition   │ ──> │ Granular Span Registry │
│ (.pdf, .docx...) │     │ (unstructured)       │     │ (Atomic S001... spans) │
└──────────────────┘     └──────────────────────┘     └───────────┬────────────┘
                                                                  │
                                 ┌────────────────────────────────┴────────────────────────┐
                                 ▼                                                         ▼
                  ┌──────────────────────────────┐                         ┌──────────────────────────────┐
                  │   High-Fidelity Digitizer    │                         │  Diagram Projection Engine   │
                  │  • GFM Table Parser          │                         │  • Structural Flowcharts     │
                  │  • Inline Mermaid Diagrams   │                         │  • BPMN 2.0 XML AST          │
                  │  • Inline [S###] Citations   │                         │  • Swimlane Diagrams         │
                  │  • Provenance Index Table    │                         └──────────────────────────────┘
                  └──────────────┬───────────────┘
                                 │
                                 ▼
                  ┌──────────────────────────────┐
                  │     Digital Markdown (.md)   │
                  │   (Editable & Exportable)    │
                  └──────────────────────────────┘
```

---

## Running Tests

All core functionality is covered by automated unit and integration tests:

```bash
# Run all test suites
pytest

# Run interface & digitizer test suites
pytest tests/test_cli.py tests/test_web.py tests/test_mcp.py tests/test_semantic_pipeline.py
```

---

## License

Apache 2.0. Open-source core.
