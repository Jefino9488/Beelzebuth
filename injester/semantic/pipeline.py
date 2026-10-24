"""
Evidence-First Semantic Pipeline.
Coordinates Document Ingestion -> Atomic Extraction -> Batched Laya Verification ->
Deterministic Graph Compilation & Defect Register -> Multi-Target Projections.
"""

import time
import json
from pathlib import Path
from typing import Dict, Any, Optional

from injester.ingestion.extractor import DocumentExtractor
from injester.ingestion.chunker import HierarchicalChunker
from injester.sop.spans import SpanRegistry
from injester.semantic.schemas import (
    PropositionBatch,
    DualOutputResult,
    GroundedProcessGraph,
    AmbiguityRegister,
)
from injester.semantic.extractor import AtomicPropositionExtractor
from injester.semantic.reasoner import SemanticProcessReasoner
from injester.semantic.normalizer import ProcessNormalizer
from injester.semantic.verifiers import System1Verifier, get_system1_verifier
from injester.semantic.compiler import DeterministicGraphCompiler


class GranularSpanRegistry(SpanRegistry):
    """
    Granular SpanRegistry that deterministically splits in-line numbered items
    and procedural lists into atomic verifiable spans.
    """
    import re
    def _segment_text(self, text: str) -> list:
        import re
        initial_units = super()._segment_text(text)
        refined_units = []
        for unit in initial_units:
            parts = re.split(r'(?<=[.?!;:])\s+(?=(?:step\s+\d+|phase\s+\d+|\d+[\.)]|[a-zA-Z][\.)]|[•\-*])\s+)', unit, flags=re.IGNORECASE)
            for p in parts:
                p_str = p.strip()
                if p_str:
                    refined_units.append(p_str)
        return refined_units


class EvidenceFirstSemanticPipeline:
    """
    Complete end-to-end evidence-first procedural extraction pipeline.
    """

    def __init__(
        self,
        extractor: Optional[AtomicPropositionExtractor] = None,
        reasoner: Optional[SemanticProcessReasoner] = None,
        normalizer: Optional[ProcessNormalizer] = None,
        verifier: Optional[System1Verifier] = None,
        compiler: Optional[DeterministicGraphCompiler] = None,
    ):
        self.doc_extractor = DocumentExtractor()
        self.chunker = HierarchicalChunker()
        self.extractor = extractor or AtomicPropositionExtractor()
        self.reasoner = reasoner or SemanticProcessReasoner()
        self.normalizer = normalizer or ProcessNormalizer()
        self.verifier = verifier or get_system1_verifier()
        self.compiler = compiler or DeterministicGraphCompiler()

    def process_document(
        self,
        file_path: Path,
        output_dir: Optional[Path] = None,
        document_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
        file_version_id: Optional[str] = None,
        file_hash: Optional[str] = None,
        synthesize_graph: bool = False,
    ) -> DualOutputResult:
        """
        Executes the pipeline on a single document.
        Defaults to high-fidelity, deterministic digitization into Markdown (.md) in ~1-2 seconds.
        If synthesize_graph=True, runs semantic extraction and System-1 verification.
        """
        t_start = time.time()

        # 1. Ingestion & Granular Spans
        t0 = time.time()
        doc_id = document_id or file_path.stem
        effective_tenant = tenant_id or "platform"
        effective_ver_id = file_version_id or f"{doc_id}_v1"
        file_size = file_path.stat().st_size if file_path.exists() else 0
        print(f"[PIPELINE {time.strftime('%H:%M:%S')}] [1/5] Ingesting & segmenting '{file_path.name}' ({file_size} bytes)...", flush=True)
        elements = self.doc_extractor.extract(
            file_path=file_path,
            document_id=doc_id,
            filename=file_path.name,
            tenant_id=effective_tenant,
            file_version_id=effective_ver_id,
            file_hash=file_hash,
        )
        chunks = self.chunker.chunk_elements(elements)
        span_registry = GranularSpanRegistry.from_chunks(chunks)
        print(f"[PIPELINE {time.strftime('%H:%M:%S')}] [1/5] ✅ Chunking complete in {time.time()-t0:.2f}s: {len(elements)} elements, {len(chunks)} chunks, {len(span_registry.spans_by_id)} spans", flush=True)

        if not synthesize_graph:
            from injester.application.digitizer import reconstruct_digital_markdown
            annotated_md, clean_md, full_raw = reconstruct_digital_markdown(
                elements=elements,
                span_registry=span_registry,
                document_title=file_path.stem
            )
            total_latency = round(time.time() - t_start, 3)
            dual_result = DualOutputResult(
                graph=GroundedProcessGraph(
                    process_name=file_path.stem,
                    objective=f"Digitized Document: {file_path.stem}",
                    actors=[],
                    activities=[],
                    gateways=[],
                    events=[],
                    transitions=[],
                ),
                defect_register=AmbiguityRegister(document_name=file_path.name, defects=[]),
                extraction_latency_sec=0.0,
                laya_latency_sec=0.0,
                compilation_latency_sec=0.0,
                total_latency_sec=total_latency,
                span_registry_hash=span_registry.compute_manifest_hash(),
                span_registry=span_registry,
                elements=elements,
                sop_markdown=annotated_md,
            )
            print(
                f"[PIPELINE {time.strftime('%H:%M:%S')}] [COMPLETE] Devoured in {total_latency:.2f}s | "
                f"{len(elements)} elements, {len(chunks)} chunks, {len(span_registry.spans_by_id)} spans",
                flush=True
            )
            if output_dir:
                output_dir.mkdir(parents=True, exist_ok=True)
                (output_dir / f"{file_path.stem}.md").write_text(annotated_md, encoding="utf-8")
                (output_dir / "DOCUMENT.md").write_text(annotated_md, encoding="utf-8")
            return dual_result

        # 2. Atomic Proposition Extraction (Candidate assertions)
        t_ext = time.time()
        print(f"[PIPELINE {time.strftime('%H:%M:%S')}] [2/5] 🧠 Extracting atomic propositions with LLM ({self.extractor.model_name})...", flush=True)
        batch: PropositionBatch = self.extractor.extract_propositions(span_registry, chunks)
        extraction_latency = round(time.time() - t_ext, 3)
        print(f"[PIPELINE {time.strftime('%H:%M:%S')}] [2/5] ✅ Extraction complete in {extraction_latency:.2f}s: {len(batch.propositions)} propositions extracted", flush=True)

        # 3. Laya System-1 Batched Grounding Verification (Proposition level)
        t_laya = time.time()
        verifier_name = getattr(self.verifier, 'provider_name', 'system1').upper()
        device_str = "CUDA" if getattr(self.verifier, 'device', None) == "cuda" else "Local/API"
        print(f"[PIPELINE {time.strftime('%H:%M:%S')}] [3/5] 🛡️ Verifying {len(batch.propositions)} propositions with {verifier_name} on {device_str}...", flush=True)
        verdicts = self.verifier.verify_propositions(batch.propositions, span_registry)
        laya_latency = round(time.time() - t_laya, 3)
        supp_count = sum(1 for v in verdicts.values() if getattr(v.verdict, 'value', str(v.verdict)).upper() == 'SUPPORTED')
        print(f"[PIPELINE {time.strftime('%H:%M:%S')}] [3/5] ✅ Verification complete in {laya_latency:.2f}s: {supp_count}/{len(verdicts)} verified SUPPORTED", flush=True)

        # 4. Semantic Process Reasoning (Topology & Contextual Actor Resolution)
        t_reason = time.time()
        print(f"[PIPELINE {time.strftime('%H:%M:%S')}] [4/5] 🧩 Reasoning Canonical Process Model with LLM ({self.reasoner.model_name})...", flush=True)
        canonical_model = self.reasoner.reason_process_model(
            span_registry=span_registry,
            chunks=chunks,
            propositions=batch.propositions,
            document_title=file_path.stem
        )
        reasoning_latency = round(time.time() - t_reason, 3)
        print(f"[PIPELINE {time.strftime('%H:%M:%S')}] [4/5] ✅ Reasoning complete in {reasoning_latency:.2f}s: {len(canonical_model.nodes)} nodes, {len(canonical_model.edges)} edges", flush=True)

        # 4b. Deterministic Structural Normalization
        canonical_model = self.normalizer.normalize(canonical_model)

        # 5. Deterministic Compilation & Gating
        t_comp = time.time()
        print(f"[PIPELINE {time.strftime('%H:%M:%S')}] [5/5] ⚙️ Compiling GroundedProcessGraph AST & Defect Register...", flush=True)
        dual_result = self.compiler.compile(
            document_name=file_path.name,
            process_name=canonical_model.process_name or batch.process_name,
            objective=canonical_model.objective or batch.objective,
            span_registry=span_registry,
            canonical_model=canonical_model,
            propositions=batch.propositions,
            verdicts=verdicts
        )
        compilation_latency = round(time.time() - t_comp, 3)
        total_latency = round(time.time() - t_start, 3)

        dual_result.extraction_latency_sec = extraction_latency
        dual_result.laya_latency_sec = laya_latency
        dual_result.compilation_latency_sec = compilation_latency
        dual_result.total_latency_sec = total_latency
        dual_result.span_registry_hash = span_registry.compute_manifest_hash()
        dual_result.span_registry = span_registry
        dual_result.elements = elements

        # Generate heading-based, citation-grounded readable Markdown digest
        from injester.semantic.projections import render_sop_markdown
        dual_result.sop_markdown = render_sop_markdown(
            dual_result.graph,
            span_registry=span_registry,
            defect_register=dual_result.defect_register
        )

        print(
            f"[PIPELINE {time.strftime('%H:%M:%S')}] [COMPLETE] Total: {total_latency:.2f}s | "
            f"Activities: {len(dual_result.graph.activities)}, "
            f"Gateways: {len(dual_result.graph.gateways)}, "
            f"Transitions: {len(dual_result.graph.transitions)}, "
            f"Defects: {len(dual_result.defect_register.defects)}",
            flush=True
        )

        # 5. Persist Artifacts if output_dir provided
        if output_dir:
            output_dir.mkdir(parents=True, exist_ok=True)
            self._write_artifacts(dual_result, output_dir, span_registry=span_registry)

        return dual_result

    def _write_artifacts(self, result: DualOutputResult, out_dir: Path, span_registry: Optional[Any] = None):
        """
        Deterministically renders BPMN, Mermaid, Markdown Defect Register, and Citation-Grounded SOP.md.
        """
        from injester.semantic.projections import (
            render_flowchart_mermaid,
            render_swimlane_mermaid,
            render_state_machine_mermaid,
            render_bpmn_20_xml,
            render_sop_markdown,
        )

        # JSON representations
        (out_dir / "process_graph.json").write_text(result.graph.model_dump_json(indent=2), encoding="utf-8")
        (out_dir / "defect_register.json").write_text(result.defect_register.model_dump_json(indent=2), encoding="utf-8")

        # Markdown Defect Register
        (out_dir / "DEFECT_REGISTER.md").write_text(result.defect_register.to_markdown(), encoding="utf-8")

        # Citation-Grounded Document Markdown
        if not result.sop_markdown:
            result.sop_markdown = render_sop_markdown(
                result.graph,
                span_registry=span_registry,
                defect_register=result.defect_register
            )
        (out_dir / "DOCUMENT.md").write_text(result.sop_markdown, encoding="utf-8")
        (out_dir / "digest.md").write_text(result.sop_markdown, encoding="utf-8")

        # Deterministic AST Projections (Verified Graph Only)
        fc_md = render_flowchart_mermaid(result.graph)
        sw_md = render_swimlane_mermaid(result.graph)
        sm_md = render_state_machine_mermaid(result.graph) if getattr(result.graph, 'state_transitions', None) else None
        xml_str = render_bpmn_20_xml(result.graph)

        (out_dir / "flowchart.mmd").write_text(fc_md, encoding="utf-8")
        (out_dir / "swimlane.mmd").write_text(sw_md, encoding="utf-8")
        if sm_md:
            (out_dir / "state_machine.mmd").write_text(sm_md, encoding="utf-8")
        (out_dir / "bpmn_2_0.xml").write_text(xml_str, encoding="utf-8")
