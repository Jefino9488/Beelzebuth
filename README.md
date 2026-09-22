# Project Injester

## Project Goal

For this standalone multi-format knowledge ingestion + SOP generation project, the final goal should be to build a pipeline that can ingest multiple heterogeneous sources—PDF, DOCX, PPTX, XLSX/CSV, TXT, Markdown, HTML, and eventually images/video—using Unstructured as the primary ingestion layer, normalize everything into a common element representation with strong provenance metadata such as document ID, filename, page/slide/sheet, section, element type, and source location, then intelligently chunk and index the content in a vector store such as FAISS (with the storage layer abstracted so it can later move to pgvector/Qdrant). From multiple documents, the system should build a global knowledge/section map, generate a structured SOP outline using Instructor + an LLM, retrieve relevant evidence across all source documents for each section, rerank the retrieved evidence, generate each section with structured citations, and then run a validation layer to detect unsupported claims, missing evidence, conflicting sources, or weak citations before assembling the final SOP. Jev can be added afterward as the decision/quality-control layer for chunk validation, retrieval sufficiency, conflict detection, and generation/citation validation. The end goal is therefore not merely an “Unstructured parser,” but a scalable ingestion-to-grounded-document-generation engine: ingest anything → normalize → understand → index → retrieve → generate → verify → produce a traceable SOP with citations back to the original sources.

> **Current Focus Note:** While the ultimate goal includes video/image ingestion and adding Jev as the decision/quality-control layer, our current immediate focus is on building out the core text/document ingestion pipeline, chunking, indexing, SOP generation, and basic citation validation. Video/image ingestion and Jev integration will be deferred to a later phase.

## Product Goal

We will **focus on the ingestion engine first, but implement the multi-tenant foundation alongside it**, because the ingestion system is the core product while tenant/file permissions are infrastructure that becomes painful to retrofit later. Architect it as a proper OOP/domain-driven system with four identities: **Developer/Super Admin → Client/Organisation → Employee/User → Files**. The Developer account should be a permanently privileged platform-level account, but **do not hard-code the actual password in source code**—bootstrap it through environment secrets and require secure password rotation. A Client such as **Indian Bank** is created through a controlled onboarding flow where the Developer approves the organisation, creates its tenant, and assigns its first Client Super Admin; that Client Super Admin can manage the organisation and access **all files belonging to that organisation and its employees**, while an Employee can access only files explicitly belonging to that employee. Every file should belong to an `organisation_id`, optionally a `user_id`, and a hierarchical `folder_id`, with a separate version model such as `File → FileVersion[]`, so you get folders, subfolders, version history, metadata, uploads, and audit trails without mixing tenant data. The architecture should enforce **tenant isolation at the backend/database layer**, not merely hide files in the frontend: every request resolves the authenticated user's organisation and authorization scope before querying anything. Your final system therefore becomes **Developer/Super Admin → approves and manages Clients → Client Admin manages organisation/employees → Employees manage/view their permitted files → Ingestion pipeline processes those files → normalized knowledge → retrieval → citation-grounded SOP generation**, giving you the ingestion engine you want while simultaneously establishing the enterprise-grade foundation needed to turn it into a real multi-tenant product.

## Overview
**Injester** is a standalone, modular pipeline designed to intelligently ingest multiple unstructured documents, preserve their hierarchical structure, and synthesize them into a unified, structured document. 

The core philosophy of this project is **Bring Your Own AI (BYOAI)** — you can plug in any LLM API (OpenAI, Anthropic, local models, etc.) to drive the reasoning engine.

## Core Objectives
1. **Intelligent Extraction:** Use the `unstructured` library to parse PDFs, Word docs, and other formats while preserving tables, titles, and section hierarchies.
2. **Structural Chunking:** Convert extracted elements into a rich JSON structure where every piece of text is tagged with strong provenance metadata (e.g., document ID, filename, page, section, element type).
3. **Synthesis & Combination:** Generate a unified SOP outline from multiple documents, retrieving and reranking relevant evidence across all source documents for each section.
4. **Structured Outputs & Citations:** Utilize the `instructor` library and `pydantic` to ensure the AI always outputs structurally perfect data with strict schemas, enforcing citation-based generation for every claim.
5. **Traceable Markdown Output:** The final synthesized document will be compiled and exported as clean, readable Markdown (`.md`), complete with a citation index ensuring full auditability back to the original source documents.

## Architecture & Pipeline Flow

The intended end-to-end flow is:
**Source documents → Unstructured → normalized elements + provenance → chunking → vector index → SOP outline → retrieve + rerank evidence → LLM generates each section with citations → citation/claim validation → final SOP.**

### Grounded & Traceable Generation
The final SOP isn't just AI-generated text; it is **grounded, traceable, and auditable back to the original documents**. Instructor will enforce structured citation output.

Each generated claim must be traceable back to its origin, for example:
> *"Employees must obtain manager approval before system access is provisioned."* **[C12]**

With an accompanying citation index:
```text
[C12]
Source: IT_Access_Policy.pdf
Page: 14
Section: Access Provisioning
Chunk ID: chunk_8f31
```
*(Later on, Jev will be added as a quality-control layer to validate whether these citations actually support the generated claims.)*

## Planned Architecture

### 1. `extractor.py` (The Reader)
- Uses `unstructured.partition.auto.partition` to read files.
- Loops through elements (like `Title`, `NarrativeText`).
- Maintains a running "current header" to tag all subsequent text elements, creating a hierarchical JSON representation of the file.

### 2. `combiner.py` (The Brain)
- Driven by `instructor` and Pydantic models.
- **Step 1 (Outline):** Takes the summaries of the selected input JSONs and asks the LLM to generate a combined `Outline` schema.
- **Step 2 (Drafting):** Iterates over the outline. For each section, retrieves relevant chunks from the source JSONs (using FAISS + reranking) and generates the section content.

### 3. `exporter.py` (The Writer)
- Takes the final Pydantic objects generated by the combiner and formats them into a clean Markdown file, complete with headers, bullet points, and source citations.

## Setup Instructions

1. Activate the virtual environment:
   ```bash
   source venv/bin/activate
   ```
2. Install the dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Create a `.env` file and supply your database and API keys (refer to `.env.example`).
4. Run the automated tests:
   ```bash
   pytest -v
   ```
5. Launch the FastAPI server:
   ```bash
   uvicorn injester.api.app:app --reload --port 8000
   ```
   Interactive Swagger documentation is available at `http://localhost:8000/docs`.
