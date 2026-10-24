from pathlib import Path
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

from injester.application.manager import manager

class IngestResult(BaseModel):
    doc_id: str
    name: str
    format: str
    chunk_count: int
    version: int
    file_size: int
    storage_path: str
    errors: List[str] = Field(default_factory=list)

class DocumentSummary(BaseModel):
    doc_id: str
    name: str
    versions_count: int
    chunk_count: int = 0
    created_at: str

class DocumentService:
    def __init__(self):
        self.mgr = manager

    def ingest(self, file_path: str | Path, filename: Optional[str] = None) -> IngestResult:
        """Ingests a document directly into the local workspace."""
        path = Path(file_path).resolve()
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")

        pipeline = self.mgr.get_pipeline()
        sec_ctx = self.mgr.sec_ctx()

        file_rec, ver_rec, chunks = pipeline.ingest_file(
            sec_ctx=sec_ctx,
            file_path=path,
            filename=filename or path.name,
        )

        return IngestResult(
            doc_id=file_rec.id,
            name=file_rec.name,
            format=path.suffix.lstrip(".").upper() or "FILE",
            chunk_count=len(chunks),
            version=ver_rec.version_number,
            file_size=ver_rec.file_size,
            storage_path=ver_rec.storage_path,
        )

    def list_documents(self) -> List[DocumentSummary]:
        """Lists all documents stored in the local workspace."""
        pipeline = self.mgr.get_pipeline()
        sec_ctx = self.mgr.sec_ctx()

        files = pipeline.repo.list_files(sec_ctx)
        # Also query vector store chunks to know indexed chunk counts
        tenant_id = sec_ctx.organisation_id or "local"
        all_chunks = pipeline.vector_store.get_chunks(tenant_id)
        chunk_map: Dict[str, int] = {}
        for c in all_chunks:
            chunk_map[c.document_id] = chunk_map.get(c.document_id, 0) + 1

        results = []
        for f in files:
            results.append(DocumentSummary(
                doc_id=f.id,
                name=f.name,
                versions_count=len(f.versions) if f.versions else 1,
                chunk_count=chunk_map.get(f.id, 0),
                created_at=str(f.created_at),
            ))
        return results

    def get_document(self, doc_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves details of a specific local document."""
        pipeline = self.mgr.get_pipeline()
        sec_ctx = self.mgr.sec_ctx()
        try:
            f = pipeline.repo.get_file(sec_ctx, doc_id)
        except Exception:
            return None

        tenant_id = sec_ctx.organisation_id or "local"
        doc_chunks = pipeline.vector_store.get_chunks(tenant_id, document_ids=[doc_id])

        return {
            "id": f.id,
            "name": f.name,
            "created_at": str(f.created_at),
            "versions": [
                {
                    "version_number": v.version_number,
                    "file_size": v.file_size,
                    "mime_type": v.mime_type,
                    "file_hash": v.file_hash,
                    "storage_path": v.storage_path,
                }
                for v in (f.versions or [])
            ],
            "chunks_count": len(doc_chunks),
            "chunks": [c.model_dump() for c in doc_chunks],
        }

    def delete_document(self, doc_id: str) -> bool:
        """Deletes a document from the local database and vector store."""
        pipeline = self.mgr.get_pipeline()
        sec_ctx = self.mgr.sec_ctx()
        tenant_id = sec_ctx.organisation_id or "local"

        pipeline.vector_store.delete_document(tenant_id, doc_id)
        f = pipeline.repo.get_file(sec_ctx, doc_id)
        if f:
            pipeline.session.delete(f)
            pipeline.session.commit()
            return True
        return False
