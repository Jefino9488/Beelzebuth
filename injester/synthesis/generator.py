import re
from typing import List, Dict, Optional, Tuple, Any
from injester.ingestion.schema import DocumentChunk
from injester.synthesis.schemas import (
    DigestOutline,
    DigestSection,
    DigestDocument,
    ClaimCitation,
    DigestClaim,
    VerifiedClaim,
    VerifiedClaimIR,
    CandidateClaimsResponse,
    DigestOutlineSection,
)
from injester.synthesis.spans import SpanRegistry
from injester.synthesis.knowledge_map import DocumentKnowledgeMap, extract_knowledge_map
from injester.synthesis.llm_client import get_instructor_client
from injester.synthesis.retriever import HybridRetriever
from injester.synthesis.validator import CitationValidator
from injester.synthesis.assembler import DigestAssembler
from injester.vectorstore.base import VectorStore


class DigestGenerator:
    """
    Claim-First, auditable document generator.
    Pipeline: Source Chunks -> Extract Candidate Claims -> Verify Claims -> VerifiedClaimIR -> Assemble Document.
    Enforces that every statement in the generated document is backed by an independently verified evidence span.
    """
    def __init__(self, vector_store: Optional[VectorStore] = None):
        self.vector_store = vector_store
        self.retriever = HybridRetriever(vector_store) if vector_store is not None else None
        self.client, self.model_name = get_instructor_client()
        self.last_kmap: Optional[DocumentKnowledgeMap] = None
        self.last_claim_ir: Optional[VerifiedClaimIR] = None

    def extract_candidate_claims(
        self,
        section_title: str,
        section_goal: str,
        evidence_chunks: List[DocumentChunk],
        span_registry: SpanRegistry
    ) -> List[DigestClaim]:
        """
        Extracts candidate operational rules, thresholds, exceptions, and steps from evidence spans.
        Each candidate claim MUST cite its source span ID.
        """
        evidence_blocks = [span_registry.format_chunk_with_spans(c) for c in evidence_chunks]
        evidence_text = "\n\n".join(evidence_blocks)

        system_instruction = (
            "You are an authoritative factual claim extractor for technical operational procedures.\n"
            "Extract candidate operational rules, steps, thresholds, exceptions, and roles directly from the evidence.\n"
            "CRITICAL RULES:\n"
            "1. Each claim MUST cite the exact [S###] span ID where it appears in brackets (e.g. span_id='S014').\n"
            "2. Do NOT invent or hallucinate span IDs.\n"
            "3. State facts cleanly and objectively without speculative extrapolation."
        )
        user_prompt = (
            f"Section: {section_title}\nGoal: {section_goal}\n\n"
            f"Evidence Spans:\n{evidence_text}\n\n"
            "Extract all substantive candidate claims with their exact span IDs."
        )

        candidates: List[DigestClaim] = []
        try:
            resp = self.client.chat.completions.create(
                model=self.model_name,
                response_model=CandidateClaimsResponse,
                messages=[
                    {"role": "system", "content": system_instruction},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.0,
            )
            candidates = resp.claims
        except Exception:
            candidates = []

        return candidates

    def verify_claims(
        self,
        candidates: List[DigestClaim],
        span_registry: SpanRegistry,
        validator: Optional[CitationValidator] = None
    ) -> List[VerifiedClaim]:
        """
        Audits candidate claims against immutable cited spans using independent entailment verification.
        Only supported/entailed claims pass into the VerifiedClaim set.
        """
        val = validator or CitationValidator()
        verified: List[VerifiedClaim] = []

        for idx, claim in enumerate(candidates, 1):
            target_span_id = claim.span_id or (getattr(claim.citation, 'span_id', '') if claim.citation else '')
            if not target_span_id:
                m = re.search(r'\[(S\d{3,4})\]', claim.claim_text)
                if m:
                    target_span_id = m.group(1)

            if not target_span_id:
                continue

            span = span_registry.get_span(target_span_id)
            if not span:
                continue

            # Independent deterministic / NLI entailment check
            verdict = val._verify_entailment(claim.claim_text, span.text)
            if verdict:
                claim_id = f"CLM_{idx:03d}"
                c_hash = VerifiedClaim.compute_hash(claim.claim_text, claim.claim_type, [target_span_id])
                verified.append(VerifiedClaim(
                    claim_id=claim_id,
                    claim_text=claim.claim_text,
                    claim_type=claim.claim_type,
                    evidence_spans=[target_span_id],
                    entailment_confidence=getattr(verdict, "confidence", 1.0),
                    verifier_provider=getattr(verdict, "provider", "exact_match"),
                    verifier_model=getattr(verdict, "model", None),
                    source_chunk_ids=[span.chunk_id],
                    claim_hash=c_hash
                ))

        return verified

    def assemble_section_from_verified_claims(
        self,
        section_title: str,
        section_goal: str,
        verified_claims: List[VerifiedClaim],
        span_registry: SpanRegistry
    ) -> DigestSection:
        """
        Deterministically compiles verified claims into an auditable document section.
        """
        if not verified_claims:
            content = f"No verified procedural claims established for {section_title}."
            return DigestSection(
                section_title=section_title,
                content=content,
                claims=[],
                citations=[]
            )

        steps = []
        digest_claims = []
        citations = []

        for c in verified_claims:
            clean_text = c.claim_text.rstrip(".")
            sid = c.evidence_spans[0]
            steps.append(f"- {clean_text}. [{sid}]")

            span = span_registry.get_span(sid)
            chunk_id = span.chunk_id if span else (c.source_chunk_ids[0] if c.source_chunk_ids else "")
            claim_cit = ClaimCitation(
                citation_tag=sid,
                chunk_id=chunk_id,
                span_id=sid
            )
            digest_claims.append(DigestClaim(
                claim_text=c.claim_text,
                claim_type=c.claim_type,
                span_id=sid,
                citation=claim_cit
            ))
            citations.append(claim_cit)

        content = "\n".join(steps)
        return DigestSection(
            section_title=section_title,
            content=content,
            claims=digest_claims,
            citations=citations
        )

    def generate_section(
        self,
        section_title: str,
        section_goal: str,
        evidence_chunks: List[DocumentChunk],
        span_registry: SpanRegistry,
        validator: Optional[CitationValidator] = None
    ) -> DigestSection:
        """
        Claim-first section generation: extract candidates -> verify -> assemble.
        """
        val = validator or CitationValidator()
        candidates = self.extract_candidate_claims(section_title, section_goal, evidence_chunks, span_registry)
        verified = self.verify_claims(candidates, span_registry, val)
        return self.assemble_section_from_verified_claims(section_title, section_goal, verified, span_registry)

    def generate_outline(
        self,
        topic_goal: str,
        kmap: DocumentKnowledgeMap
    ) -> DigestOutline:
        system_instruction = (
            "You are an enterprise document architect. Design an authoritative operational outline "
            "based strictly on the provided DocumentKnowledgeMap.\n"
            "STRICT SOURCE-DRIVEN TAXONOMY & CONTAINMENT RULES:\n"
            "1. You MUST generate outline sections corresponding EXACTLY to the Recommended Sections from the knowledge map. "
            "Do NOT invent phantom sections or extra topics (e.g. do NOT invent 'Absence Tracking', 'Leave Types', or 'Portal Usage').\n"
            "2. IF kmap.has_slas is False: Do NOT create an SLA section. Any escalation timeframe "
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
            f"Generate the concise, source-contained DigestOutline mirroring the Mandatory Outline Sections."
        )

        try:
            outline = self.client.chat.completions.create(
                model=self.model_name,
                response_model=DigestOutline,
                messages=[
                    {"role": "system", "content": system_instruction},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.0,
            )
            return outline
        except Exception:
            sections = [
                DigestOutlineSection(section_title=sec, section_goal=f"Operational requirements for {sec}", search_queries=[sec])
                for sec in (kmap.recommended_sections or ["Standard Procedure"])
            ]
            return DigestOutline(
                title=kmap.title or "Standard Operational Document",
                purpose=kmap.summary or topic_goal,
                target_audience="",
                sections=sections
            )

    def build_claim_ir(
        self,
        topic_goal: str,
        chunks: List[DocumentChunk],
        span_registry: Optional[SpanRegistry] = None,
    ) -> VerifiedClaimIR:
        """
        Constructs the VerifiedClaimIR by extracting and verifying candidate claims across sections.
        """
        if span_registry is None:
            span_registry = SpanRegistry.from_chunks(chunks)

        kmap = extract_knowledge_map(chunks, span_registry)
        self.last_kmap = kmap
        outline = self.generate_outline(topic_goal, kmap)

        all_verified: List[VerifiedClaim] = []
        val = CitationValidator()

        for outline_sec in outline.sections:
            query = f"{outline_sec.section_title} {' '.join(outline_sec.search_queries)}".strip()
            tenant = getattr(chunks[0].provenance, 'tenant_id', None) if chunks else "platform"
            if self.retriever and tenant:
                try:
                    evidence = self.retriever.retrieve(
                        tenant_id=tenant,
                        query=query,
                        all_tenant_chunks=chunks,
                        top_k=min(6, len(chunks))
                    )
                except Exception:
                    evidence = chunks[:6]
            elif len(chunks) <= 8:
                evidence = chunks
            else:
                tokens = query.lower().split()
                evidence = sorted(
                    chunks,
                    key=lambda c: sum(1 for t in tokens if t in c.text.lower()),
                    reverse=True
                )[:6]

            candidates = self.extract_candidate_claims(
                section_title=outline_sec.section_title,
                section_goal=outline_sec.section_goal,
                evidence_chunks=evidence,
                span_registry=span_registry
            )
            sec_verified = self.verify_claims(candidates, span_registry, val)
            all_verified.extend(sec_verified)

        claim_ir = VerifiedClaimIR(
            title=outline.title,
            purpose=outline.purpose,
            target_audience=outline.target_audience,
            claims=all_verified,
            sections=outline.sections
        )
        self.last_claim_ir = claim_ir
        return claim_ir

    def build_digest_from_chunks(
        self,
        topic_goal: str,
        chunks: List[DocumentChunk],
        span_registry: Optional[SpanRegistry] = None,
        flowchart_mermaid: Optional[str] = None
    ) -> Tuple[DigestDocument, Any, str]:
        """
        Claim-First document compilation pipeline.
        Source Chunks -> VerifiedClaimIR -> DigestDocument -> Markdown.
        """
        if span_registry is None:
            span_registry = SpanRegistry.from_chunks(chunks)

        claim_ir = self.build_claim_ir(topic_goal, chunks, span_registry)
        val = CitationValidator()

        generated_sections: List[DigestSection] = []
        for outline_sec in claim_ir.sections:
            if len(chunks) <= 8:
                evidence = chunks
            else:
                tokens = (outline_sec.section_title + " " + " ".join(outline_sec.search_queries)).lower().split()
                evidence = sorted(
                    chunks,
                    key=lambda c: sum(1 for t in tokens if t in c.text.lower()),
                    reverse=True
                )[:6]

            evidence_chunk_ids = {c.chunk_id for c in evidence}
            sec_claims = [c for c in claim_ir.claims if any(cid in evidence_chunk_ids for cid in c.source_chunk_ids)]
            if not sec_claims:
                candidates = self.extract_candidate_claims(outline_sec.section_title, outline_sec.section_goal, evidence, span_registry)
                sec_claims = self.verify_claims(candidates, span_registry, val)

            sec = self.assemble_section_from_verified_claims(
                section_title=outline_sec.section_title,
                section_goal=outline_sec.section_goal,
                verified_claims=sec_claims,
                span_registry=span_registry
            )
            generated_sections.append(sec)

        digest_doc = DigestDocument(
            title=claim_ir.title,
            purpose=claim_ir.purpose,
            target_audience=claim_ir.target_audience,
            sections=generated_sections,
        )

        report = val.validate_document(digest_doc, chunks, knowledge_map=getattr(self, 'last_kmap', None))
        assembler = DigestAssembler()
        markdown_digest = assembler.assemble_markdown(digest_doc, report)
        if flowchart_mermaid:
            toc_marker = "---\n\n"
            if toc_marker in markdown_digest:
                parts = markdown_digest.split(toc_marker, 1)
                diagram_block = f"## Process Workflow Diagram\n\n```mermaid\n{flowchart_mermaid.strip()}\n```\n\n---\n\n"
                markdown_digest = parts[0] + toc_marker + diagram_block + parts[1]

        return digest_doc, report, markdown_digest

    def build_digest(
        self,
        tenant_id: str,
        topic_goal: str,
        all_tenant_chunks: List[DocumentChunk]
    ) -> DigestDocument:
        span_registry = SpanRegistry.from_chunks(all_tenant_chunks)
        digest_doc, _, _ = self.build_digest_from_chunks(
            topic_goal=topic_goal,
            chunks=all_tenant_chunks,
            span_registry=span_registry
        )
        return digest_doc
