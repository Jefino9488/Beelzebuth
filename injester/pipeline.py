from pathlib import Path
import hashlib
import json
from typing import List, Optional, Tuple, Union
from sqlalchemy.orm import Session

from injester.config import settings
from injester.domain.auth import SecurityContext, AccessDeniedError
from injester.domain.models import File, FileVersion
from injester.infrastructure.db import SessionLocal, TenantRepository
from injester.ingestion.extractor import DocumentExtractor
from injester.ingestion.chunker import HierarchicalChunker
from injester.ingestion.schema import DocumentChunk
from injester.vectorstore.faiss_store import FaissVectorStore
from injester.synthesis.generator import DigestGenerator
from injester.synthesis.validator import CitationValidator, ValidationReport
from injester.synthesis.assembler import DigestAssembler
from injester.semantic.pipeline import EvidenceFirstSemanticPipeline
from injester.semantic.schemas import DualOutputResult
from injester.semantic.laya_adapter import LayaSystem1Verifier

class InjesterPipeline:
    """
    End-to-End multi-tenant pipeline orchestrating:
    - Backend tenant permission validation
    - Document ingestion & hierarchical chunking
    - FAISS vector indexing per tenant
    - Citation-grounded digital markdown synthesis with Instructor
    - Evidence-first Grounded Process Graph generation with local Laya System-1 verification
    - Claim validation and traceable Markdown output
    """
    def __init__(
        self,
        session: Optional[Session] = None,
        semantic_pipeline: Optional[EvidenceFirstSemanticPipeline] = None,
    ):
        self._external_session = session is not None
        self.session = session or SessionLocal()
        self.repo = TenantRepository(self.session)
        self.extractor = DocumentExtractor()
        self.chunker = HierarchicalChunker()
        self.vector_store = FaissVectorStore()
        self.validator = CitationValidator()
        self.assembler = DigestAssembler()
        self._semantic_pipeline = semantic_pipeline

    def close(self):
        if not self._external_session:
            self.session.close()

    def _compute_config_hash(self, run_type: str = "process_graph") -> str:
        cfg_manifest = {
            "model_name": getattr(settings, "MODEL_NAME", "default"),
            "verifier_provider": getattr(settings, "SYSTEM1_PROVIDER", "openjev"),
            "verifier_model": getattr(settings, "OPENJEV_MODEL_NAME", "system1-v1"),
            "validation_policy_version": "1.0",
            "schema_version": "1.0",
            "pipeline_version": "2.0.0",
            "run_type": run_type,
        }
        return hashlib.sha256(json.dumps(cfg_manifest, sort_keys=True).encode("utf-8")).hexdigest()

    def ingest_file(
        self,
        sec_ctx: SecurityContext,
        file_path: str | Path,
        filename: Optional[str] = None,
        folder_id: Optional[str] = None,
        backend: Optional[str] = None,
    ) -> Tuple[File, FileVersion, List[DocumentChunk]]:
        """
        Ingests a document into the tenant workspace:
        1. Validates tenant scope and stores file in DB + isolated disk storage.
        2. Normalizes elements via Unstructured or Docling preserving section hierarchy.
        3. Chunks text with provenance metadata.
        4. Indexes chunks into the tenant's FAISS vector store.
        """
        path = Path(file_path).resolve()
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")

        file_bytes = path.read_bytes()
        doc_name = filename or path.name

        # 1. Register file in database with versioning
        file_record, version_record = self.repo.upload_file(
            sec_ctx=sec_ctx,
            filename=doc_name,
            content_bytes=file_bytes,
            mime_type="application/octet-stream",
            folder_id=folder_id,
        )

        tenant_id = sec_ctx.organisation_id or "platform"

        # 2. Extract with Unstructured or Docling
        normalized_elements = self.extractor.extract(
            file_path=version_record.storage_path,
            document_id=file_record.id,
            filename=doc_name,
            tenant_id=tenant_id,
            file_version_id=version_record.id,
            file_hash=version_record.file_hash,
            backend=backend,
        )

        # 3. Intelligent Hierarchical Chunking
        chunks = self.chunker.chunk_elements(normalized_elements)

        # 4. Index in Tenant Vector Store
        self.vector_store.add_documents(tenant_id, chunks)

        return file_record, version_record, chunks

    def generate_digest(
        self,
        sec_ctx: SecurityContext,
        topic_goal: str,
        file_ids: Optional[List[str]] = None
    ) -> Tuple[str, ValidationReport]:
        """
        Generates an auditable, citation-grounded document digest from tenant documents:
        1. Collects accessible files and all associated chunks for the tenant.
        2. Synthesizes outline + grounded sections with citations via Instructor.
        3. Validates citations and claim grounding.
        4. Compiles final traceable Markdown digest with Citation Index.
        """
        tenant_id = sec_ctx.organisation_id
        if not tenant_id and not sec_ctx.is_super_admin:
            raise AccessDeniedError("Tenant organisation required to generate digest.")

        # Collect accessible files for this principal with resource-level ACL
        accessible_files = {f.id: f for f in self.repo.list_visible_files(sec_ctx)}
        if not accessible_files:
            raise AccessDeniedError("No accessible files found for this user in tenant organisation.")

        if file_ids:
            requested_ids = set(file_ids)
            inaccessible = requested_ids - set(accessible_files.keys())
            if inaccessible:
                raise AccessDeniedError(f"Inaccessible resources requested: {sorted(list(inaccessible))}")
            target_ids = requested_ids
        else:
            target_ids = set(accessible_files.keys())

        # Load all tenant chunks from vector store metadata
        _, all_chunks = self.vector_store._load_tenant_index(tenant_id or "platform")
        chunks_to_use = [c for c in all_chunks if c.document_id in target_ids]

        if not chunks_to_use:
            raise ValueError(f"No indexed documents found for tenant '{tenant_id}'. Please ingest files first.")

        # Build document digest using LLM + Instructor
        generator = DigestGenerator(self.vector_store)
        doc = generator.build_digest(
            tenant_id=tenant_id or "platform",
            topic_goal=topic_goal,
            all_tenant_chunks=chunks_to_use
        )

        # Validate Citations & Claim Grounding
        validation_report = self.validator.validate_document(
            doc, chunks_to_use, knowledge_map=getattr(generator, 'last_kmap', None)
        )

        # Assemble Markdown with Citation Index and Validator-derived Audit Badge
        markdown_doc = self.assembler.assemble_markdown(doc, validation_report)

        # Record GenerationRun lineage
        file_version_ids = []
        doc_hashes = {}
        for f in accessible_files.values():
            if f.id in target_ids and getattr(f, 'versions', None):
                latest = sorted(f.versions, key=lambda v: v.version_number)[-1]
                file_version_ids.append(latest.id)
                doc_hashes[f.id] = latest.file_hash

        cfg_hash = self._compute_config_hash(run_type="digest")
        self.repo.save_generation_run(
            sec_ctx=sec_ctx,
            run_type="digest",
            input_file_version_ids=file_version_ids,
            input_hashes=doc_hashes,
            config_hash=cfg_hash,
            output_document_id=doc.title,
        )

        # Record audit log
        self.repo._audit(
            sec_ctx,
            "GENERATE_DIGEST",
            f"Generated digest '{doc.title}' with {len(doc.sections)} sections and {len(validation_report.verified_citation_index)} verified citations."
        )

        return markdown_doc, validation_report

    def generate_process_graph(
        self,
        sec_ctx: SecurityContext,
        file_path_or_id: Union[str, Path],
        output_dir: Optional[Union[str, Path]] = None,
        verifier: Optional[LayaSystem1Verifier] = None,
    ) -> DualOutputResult:
        """
        Generates an auditable, evidence-grounded Process Graph with dual output:
        1. Validates tenant access to document (file_id resolved via repo.get_visible_file).
        2. Executes EvidenceFirstSemanticPipeline:
           - Ingestion & granular [S###] span construction
           - Atomic proposition extraction (actor, action, condition, modality, epistemic status, evidence)
           - Local Laya System-1 verification (ModernBERT weights) + deterministic token/span checks
           - Deterministic graph compilation into verified AST + Ambiguity/Defect Register
        3. Deterministically renders BPMN 2.0 XML, Mermaid projections, and DEFECT_REGISTER.md
        4. Logs audit entry in tenant repository and persists immutable ProcessGraphSnapshot & GenerationRun.
        """
        if isinstance(file_path_or_id, Path):
            # Internal worker Path object only (from verified multipart upload or internal tests)
            target_path = file_path_or_id.resolve()
            if not target_path.exists():
                raise FileNotFoundError(f"Internal file path does not exist: {target_path}")
            doc_id = target_path.stem
            filename = target_path.name
        else:
            # String input is strictly treated as an existing document UUID and checked against ACL
            file_record = self.repo.get_visible_file(sec_ctx, str(file_path_or_id))
            if not file_record.versions:
                raise ValueError(f"File '{file_record.id}' has no uploaded versions.")
            latest_version = sorted(file_record.versions, key=lambda v: v.version_number)[-1]
            target_path = Path(latest_version.storage_path).resolve()
            if not target_path.exists():
                raise FileNotFoundError(f"Storage path for file '{file_record.id}' does not exist: {target_path}")
            doc_id = file_record.id
            filename = file_record.name

        tenant_id = sec_ctx.organisation_id or "platform"
        out_dir = Path(output_dir).resolve() if output_dir else None

        # Collect file version info for lineage & snapshot
        f_version_ids = []
        s_hashes = []
        s_doc_hashes = {}

        if not isinstance(file_path_or_id, Path):
            f_version_ids = [latest_version.id]
            s_hashes = [latest_version.file_hash]
            s_doc_hashes = {file_record.id: latest_version.file_hash}
        else:
            file_hash = hashlib.sha256(target_path.read_bytes()).hexdigest() if target_path.exists() else "hash"
            f_version_ids = [f"{doc_id}_local"]
            s_hashes = [file_hash]
            s_doc_hashes = {doc_id: file_hash}

        pipeline = self._semantic_pipeline or EvidenceFirstSemanticPipeline(verifier=verifier)
        result = pipeline.process_document(
            file_path=target_path,
            output_dir=out_dir,
            document_id=doc_id,
            tenant_id=tenant_id,
            file_version_id=f_version_ids[0] if f_version_ids else None,
            file_hash=s_hashes[0] if s_hashes else None,
            synthesize_graph=True,
        )

        span_reg_hash = getattr(result, "span_registry_hash", None) or hashlib.sha256(
            "".join(sorted(t.id for t in result.graph.transitions) + [result.graph.process_name]).encode("utf-8")
        ).hexdigest()

        cfg_hash = self._compute_config_hash(run_type="process_graph")

        snapshot = self.repo.save_process_graph_snapshot(
            sec_ctx=sec_ctx,
            process_name=result.graph.process_name or filename,
            canonical_graph=result.graph.model_dump(),
            defect_register=result.defect_register.model_dump(),
            file_version_ids=f_version_ids,
            source_hashes=s_hashes,
            source_document_hashes=s_doc_hashes,
            span_registry_hash=span_reg_hash,
            reasoner_model=getattr(settings, "MODEL_NAME", "default"),
            laya_model_version="openjev-system1-v1",
            validation_policy_version="1.0",
            projections={
                "bpmn_xml": getattr(result, "bpmn_xml", "") or "",
                "mermaid": getattr(result, "mermaid_diagram", "") or "",
                "defect_md": getattr(result, "defect_markdown", "") or "",
                "digital_md": getattr(result, "digital_markdown", "") or "",
            }
        )
        result.snapshot_id = snapshot.id

        run = self.repo.save_generation_run(
            sec_ctx=sec_ctx,
            run_type="process_graph",
            input_file_version_ids=f_version_ids,
            input_hashes=s_doc_hashes,
            config_hash=cfg_hash,
            output_snapshot_id=snapshot.id,
        )
        result.generation_run_id = run.id

        try:
            self.repo._audit(
                sec_ctx,
                "GENERATE_PROCESS_GRAPH",
                f"Generated Process Graph for '{filename}' ({doc_id}): "
                f"{len(result.graph.activities)} verified activities, "
                f"{len(result.graph.gateways)} gateways, "
                f"{len(result.defect_register.defects)} quarantined defects."
            )
        except Exception:
            pass

        return result

