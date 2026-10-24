from typing import List, Dict, Any
from pydantic import BaseModel

from injester.application.manager import manager
from injester.ingestion.schema import DocumentChunk

class SearchResult(BaseModel):
    document_id: str
    chunk_id: str
    text: str
    score: float
    section: str = ""
    location: str = ""
    metadata: Dict[str, Any] = {}

class RetrievalService:
    def __init__(self):
        self.mgr = manager

    def search(self, query: str, top_k: int = 5) -> List[SearchResult]:
        """Searches indexed evidence chunks across local documents."""
        pipeline = self.mgr.get_pipeline()
        sec_ctx = self.mgr.sec_ctx()
        tenant_id = sec_ctx.organisation_id or "local"

        raw_results = pipeline.vector_store.search(
            tenant_id=tenant_id,
            query=query,
            top_k=top_k,
        )

        results = []
        for chunk, score in raw_results:
            sec = " > ".join(chunk.section_hierarchy) if chunk.section_hierarchy else ""
            loc = getattr(chunk.provenance, "source_location", "") or (
                f"Page {chunk.page_numbers[0]}" if chunk.page_numbers else ""
            )
            results.append(SearchResult(
                document_id=chunk.document_id,
                chunk_id=chunk.chunk_id,
                text=chunk.text,
                score=round(float(score), 4),
                section=sec,
                location=loc,
                metadata=getattr(chunk.provenance, "extra", {}) or {},
            ))
        return results
