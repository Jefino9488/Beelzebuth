from typing import List, Dict, Optional
from injester.ingestion.schema import DocumentChunk
from injester.sop.schemas import SOPOutline, SOPSection, SOPDocument, ClaimCitation, SOPClaim
from injester.sop.spans import SpanRegistry
from injester.sop.knowledge_map import DocumentKnowledgeMap, extract_knowledge_map
from injester.sop.llm_client import get_instructor_client
from injester.sop.retriever import HybridRetriever
from injester.vectorstore.base import VectorStore

class SOPGenerator:
    """
    Dynamic, auditable SOP generator driven by 100% document knowledge mapping
    and deterministic span-anchored citation binding.
    """
    def __init__(self, vector_store: VectorStore):
        self.vector_store = vector_store
        self.retriever = HybridRetriever(vector_store)
        self.client, self.model_name = get_instructor_client()

    def generate_outline(
        self,
        topic_goal: str,
        kmap: DocumentKnowledgeMap
    ) -> SOPOutline:
        system_instruction = (
            "You are an enterprise SOP architect. Design a Standard Operating Procedure outline "
            "based strictly on the provided DocumentKnowledgeMap.\n"
            "STRICT SOURCE-DRIVEN TAXONOMY & CONTAINMENT RULES:\n"
            "1. You MUST generate outline sections corresponding EXACTLY to the Recommended Sections from the knowledge map. "
            "Do NOT invent phantom sections or extra topics (e.g. do NOT invent 'Absence Tracking', 'Leave Types', or 'Portal Usage').\n"
            "2. IF kmap.has_slas is False: Do NOT create an SLA section. Any escalation timeframe (such as manager 3-day response in Test 1) "
            "belongs strictly inside the Exceptions section.\n"
            "3. IF kmap.has_slas is True: Ensure the SLA section from the source is included.\n"
            "4. Provide targeted search queries for each section to retrieve the relevant chunks."
        )

        user_prompt = (
            f"GOAL / TOPIC: {topic_goal}\n\n"
            f"DOCUMENT KNOWLEDGE MAP:\n"
            f"- Title: {kmap.title}\n"
            f"- Summary: {kmap.summary}\n"
            f"- Mandatory Outline Sections: {', '.join(kmap.recommended_sections)}\n"
            f"- Has Exceptions: {kmap.has_exceptions}\n"
            f"- Has SLAs: {kmap.has_slas}\n\n"
            f"Generate the concise, source-contained SOPOutline mirroring the Mandatory Outline Sections."
        )

        outline = self.client.chat.completions.create(
            model=self.model_name,
            response_model=SOPOutline,
            messages=[
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.0,
        )
        return outline

    def generate_section(
        self,
        section_title: str,
        section_goal: str,
        evidence_chunks: List[DocumentChunk],
        span_registry: SpanRegistry
    ) -> SOPSection:
        # Format evidence chunks with deterministic span IDs [S###]
        evidence_blocks = []
        for c in evidence_chunks:
            chunk_repr = span_registry.format_chunk_with_spans(c)
            evidence_blocks.append(chunk_repr)

        evidence_text = "\n\n".join(evidence_blocks)

        system_instruction = (
            "You are a meticulous technical documentation writer producing an auditable Standard Operating Procedure (SOP).\n"
            "Your output must include the procedure text and structured claims tied directly to immutable Span IDs.\n\n"
            "GLOBAL IMMUTABLE SPAN CITATION RULES:\n"
            "1. Every factual statement, requirement, threshold, exception, and timeframe MUST be followed immediately by its exact Span ID in brackets in the text, for example: [S014].\n"
            "2. For every asserted fact or procedural step in `claims`:\n"
            "   - claim_text: the factual statement or procedural step (clean statement without appending bracketed span IDs)\n"
            "   - claim_type: 'rule' | 'threshold' | 'exception' | 'sla' | 'role' | 'procedure' | 'descriptive' | 'instruction'\n"
            "   - span_id: the exact Span ID [S###] from the evidence (e.g. 'S014')\n"
            "3. NEVER invent or hallucinate span IDs. Only reference valid [S###] IDs present in the evidence spans.\n"
            "4. STRICT BAN ON [C1], [C2], ETC.: Do NOT use local [C1], [C2] tags anywhere. Use ONLY the immutable [S###] span IDs (e.g. [S001], [S014]) from the provided evidence spans.\n"
            "5. NO DUPLICATE HEADINGS: Do NOT begin the content with '# Section Title' or '## Section Title'. Start immediately with the section body.\n"
            "6. SECTION BOUNDARY ISOLATION: Focus strictly on the distinct objective of this specific section. Do NOT repeat or restate introductory sentences from prior sections (such as Purpose or Overview) even if they appear in the same retrieved chunk."
        )

        user_prompt = (
            f"Generate section: '{section_title}'\n"
            f"Section Objective: {section_goal}\n\n"
            f"AVAILABLE EVIDENCE SPANS:\n"
            f"{evidence_text}\n\n"
            f"Write a thorough, step-by-step procedure section with inline span citations [S###] and structured claims."
        )

        section = self.client.chat.completions.create(
            model=self.model_name,
            response_model=SOPSection,
            messages=[
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.0,
        )
        return section

    def build_sop(
        self,
        tenant_id: str,
        topic_goal: str,
        all_tenant_chunks: List[DocumentChunk]
    ) -> SOPDocument:
        # Step 0: Register deterministic spans across 100% of chunks
        span_registry = SpanRegistry.from_chunks(all_tenant_chunks)

        # Step 1: Extract Document Knowledge Map from 100% of chunks
        print("  Extracting Document Knowledge Map from 100% of chunks...")
        kmap = extract_knowledge_map(all_tenant_chunks, span_registry)
        self.last_kmap = kmap

        # Step 2: Generate Outline with Conditional Rules
        print(f"  Synthesizing dynamic outline (has_exceptions={kmap.has_exceptions}, has_slas={kmap.has_slas})...")
        outline = self.generate_outline(topic_goal, kmap)
        print(f"  Dynamic outline created with {len(outline.sections)} sections.")

        # Step 3: Generate each section with retrieved evidence and deterministic spans
        generated_sections: List[SOPSection] = []
        top_k = min(len(all_tenant_chunks), 7)

        for idx, outline_sec in enumerate(outline.sections, 1):
            print(f"  Generating section {idx}/{len(outline.sections)}: '{outline_sec.section_title}'...")
            query = f"{outline_sec.section_title} {' '.join(outline_sec.search_queries)}"
            evidence = self.retriever.retrieve(
                tenant_id=tenant_id,
                query=query,
                all_tenant_chunks=all_tenant_chunks,
                top_k=top_k
            )
            section = self.generate_section(
                section_title=outline_sec.section_title,
                section_goal=outline_sec.section_goal,
                evidence_chunks=evidence,
                span_registry=span_registry
            )
            generated_sections.append(section)

        sop_doc = SOPDocument(
            title=outline.title,
            purpose=outline.purpose,
            target_audience=outline.target_audience,
            sections=generated_sections,
        )
        return sop_doc
