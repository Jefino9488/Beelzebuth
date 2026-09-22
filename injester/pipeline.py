from pathlib import Path
from typing import List, Optional, Tuple
from sqlalchemy.orm import Session

from injester.config import settings
from injester.domain.auth import SecurityContext, AccessDeniedError
from injester.domain.models import File, FileVersion
from injester.infrastructure.db import SessionLocal, TenantRepository
from injester.ingestion.extractor import DocumentExtractor
from injester.ingestion.chunker import HierarchicalChunker
from injester.ingestion.schema import DocumentChunk
from injester.vectorstore.faiss_store import FaissVectorStore
from injester.sop.generator import SOPGenerator
from injester.sop.validator import CitationValidator, ValidationReport
from injester.sop.assembler import SOPAssembler

class InjesterPipeline:
    """
    End-to-End multi-tenant pipeline orchestrating:
    - Backend tenant permission validation
    - Document ingestion & hierarchical chunking
    - FAISS vector indexing per tenant
    - Citation-grounded SOP generation with Instructor
    - Claim validation and traceable Markdown output
    """
    def __init__(self, session: Optional[Session] = None):
        self._external_session = session is not None
        self.session = session or SessionLocal()
        self.repo = TenantRepository(self.session)
        self.extractor = DocumentExtractor()
        self.chunker = HierarchicalChunker()
        self.vector_store = FaissVectorStore()
        self.validator = CitationValidator()
        self.assembler = SOPAssembler()

    def close(self):
        if not self._external_session:
            self.session.close()

    def ingest_file(
        self,
        sec_ctx: SecurityContext,
        file_path: str | Path,
        filename: Optional[str] = None,
        folder_id: Optional[str] = None
    ) -> Tuple[File, FileVersion, List[DocumentChunk]]:
        """
        Ingests a document into the tenant workspace:
        1. Validates tenant scope and stores file in DB + isolated disk storage.
        2. Normalizes elements via Unstructured preserving section hierarchy.
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

        # 2. Extract with Unstructured
        normalized_elements = self.extractor.extract(
            file_path=version_record.storage_path,
            document_id=file_record.id,
            filename=doc_name,
            tenant_id=tenant_id,
        )

        # 3. Intelligent Hierarchical Chunking
        chunks = self.chunker.chunk_elements(normalized_elements)

        # 4. Index in Tenant Vector Store
        self.vector_store.add_documents(tenant_id, chunks)

        return file_record, version_record, chunks

    def generate_sop(
        self,
        sec_ctx: SecurityContext,
        topic_goal: str,
        file_ids: Optional[List[str]] = None
    ) -> Tuple[str, ValidationReport]:
        """
        Generates an auditable, citation-grounded SOP from tenant documents:
        1. Collects accessible files and all associated chunks for the tenant.
        2. Synthesizes outline + grounded sections with citations via Instructor.
        3. Validates citations and claim grounding.
        4. Compiles final traceable Markdown SOP with Citation Index.
        """
        tenant_id = sec_ctx.organisation_id
        if not tenant_id and not sec_ctx.is_super_admin:
            raise AccessDeniedError("Tenant organisation required to generate SOP.")

        # Load all tenant chunks from vector store metadata
        _, all_chunks = self.vector_store._load_tenant_index(tenant_id or "platform")

        if file_ids:
            # Filter chunks to selected document IDs
            target_ids = set(file_ids)
            chunks_to_use = [c for c in all_chunks if c.document_id in target_ids]
        else:
            chunks_to_use = all_chunks

        if not chunks_to_use:
            raise ValueError(f"No indexed documents found for tenant '{tenant_id}'. Please ingest files first.")

        # Build SOP using LLM + Instructor
        generator = SOPGenerator(self.vector_store)
        sop_doc = generator.build_sop(
            tenant_id=tenant_id or "platform",
            topic_goal=topic_goal,
            all_tenant_chunks=chunks_to_use
        )

        # Validate Citations & Claim Grounding
        validation_report = self.validator.validate_document(
            sop_doc, chunks_to_use, knowledge_map=getattr(generator, 'last_kmap', None)
        )

        # Assemble Markdown with Citation Index and Validator-derived Audit Badge
        markdown_sop = self.assembler.assemble_markdown(sop_doc, validation_report)

        # Record audit log
        self.repo._audit(
            sec_ctx,
            "GENERATE_SOP",
            f"Generated SOP '{sop_doc.title}' with {len(sop_doc.sections)} sections and {len(validation_report.verified_citation_index)} verified citations."
        )

        return markdown_sop, validation_report
